"""Import des sauvegardes dans la base centrale, utilisé par sync.py (CLI) et par le serveur web.

La sauvegarde la plus récente (le .hsg modifié en dernier) fait foi. Elle est importée quand elle
change, une fois que le jeu a fini de l'écrire (taille et date stables pendant ``settle`` secondes).
Un seul import à la fois (verrou) ; chaque opération ouvre sa propre connexion SQLite, ce qui permet
de l'appeler depuis n'importe quel thread.
"""

from __future__ import annotations

import gzip
import struct
import threading
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import db as database
from . import odin
from .model import Save
from .reference import DEFAULT_DIR, Reference, ReferenceMissing
from .save import SAVE_ROOT, load_meta

DEFAULT_DB = Path(__file__).resolve().parent.parent / "out" / "bigambitions.sqlite"
# Erreurs typiques d'un fichier encore en cours d'écriture.
READ_ERRORS = (OSError, EOFError, gzip.BadGzipFile, zlib.error, struct.error, odin.OdinError, IndexError, ValueError)

Signature = tuple[str, int, int]  # (chemin, mtimeNs, taille)
EventHandler = Callable[[str, dict[str, Any]], None]


def latest(root: Path) -> Signature | None:
    newest = None
    for path in Path(root).rglob("*.hsg"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if newest is None or stat.st_mtime_ns > newest[1]:
            newest = (str(path), stat.st_mtime_ns, stat.st_size)
    return newest


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Ingestor:
    def __init__(self, db_path: Path = DEFAULT_DB, root: Path = SAVE_ROOT, interval: float = 3.0,
                 settle: float = 2.0, on_event: EventHandler | None = None, log: Callable[[str], None] | None = None):
        self.db_path = Path(db_path)
        self.root = Path(root)
        self.interval = interval
        self.settle = settle
        self.on_event = on_event or (lambda kind, payload: None)
        self.log = log or (lambda message: print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True))
        self._lock = threading.Lock()
        self._reference: tuple[float, Reference | None] | None = None
        self._watch_thread: threading.Thread | None = None
        self._watch_stop = threading.Event()
        self.busy = False
        self.last_import: dict[str, Any] | None = None
        self.last_error: dict[str, Any] | None = None
        self.pending: str | None = None
        database.connect(self.db_path).close()  # crée la base et les tables système si besoin

    # --- événements ---------------------------------------------------------

    def _emit(self, kind: str, **payload: Any) -> None:
        payload.setdefault("at", _now())
        try:
            self.on_event(kind, payload)
        except Exception as e:  # un abonné défaillant ne doit pas casser l'import
            self.log(f"  erreur d'abonné ({kind}) : {e}")

    # --- référentiel --------------------------------------------------------

    def reference(self) -> Reference | None:
        """Référentiel du jeu, rechargé si out/gamedata a été ré-extrait. None s'il manque."""
        marker = DEFAULT_DIR / "version.json"
        stamp = marker.stat().st_mtime if marker.exists() else 0.0
        if self._reference is None or self._reference[0] != stamp:
            try:
                ref = Reference.load()
                if ref.is_stale():
                    self.log("  attention : le jeu a été mis à jour depuis l'extraction, relancer extract_gamedata.py")
            except ReferenceMissing as e:
                self.log(f"  {e} (prix, quartiers et segments indisponibles)")
                ref = None
            self._reference = (stamp, ref)
        return self._reference[1]

    # --- import -------------------------------------------------------------

    def import_save(self, path: Path) -> bool:
        """Lit et importe un .hsg. Renvoie False si le fichier a bougé pendant la lecture ou est illisible."""
        path = Path(path)
        key = database.save_key(path)
        with self._lock:
            self.busy = True
            self._emit("import_started", save=key)
            started = time.perf_counter()
            try:
                before = path.stat()
                raw = path.read_bytes()
                after = path.stat()
                if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                    self._emit("import_retry", save=key, reason="fichier en cours d'écriture")
                    return False
                game, _ = odin.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
                save = Save({"meta": load_meta(path), "game": game}, self.reference())
                tables = save.tables()
                db = database.connect(self.db_path)
                try:
                    database.replace_all(db, path, after.st_mtime_ns, after.st_size, save, tables)
                finally:
                    db.close()
            except READ_ERRORS as e:
                self.log(f"  lecture impossible pour l'instant ({type(e).__name__}: {e})")
                self.last_error = {"save": key, "error": f"{type(e).__name__}: {e}", "at": _now()}
                self._emit("import_retry", save=key, reason=self.last_error["error"])
                return False
            except Exception as e:
                self.last_error = {"save": key, "error": f"{type(e).__name__}: {e}", "at": _now()}
                self._emit("import_failed", **self.last_error)
                raise
            finally:
                self.busy = False
            player = save.player()
            self.last_import = {
                "save": key, "day": player["day"], "time": player["time"], "money": player["money"],
                "rows": sum(map(len, tables.values())), "seconds": round(time.perf_counter() - started, 1),
                "at": _now(),
            }
            self.last_error = None
            self.log(f"importé {key} : jour {player['day']} {player['time']}, {player['money']:,.0f} $, "
                     f"{self.last_import['rows']} lignes ({self.last_import['seconds']}s)")
            self._emit("import_done", **self.last_import)
            return True

    def current_source(self) -> Signature | None:
        db = database.connect(self.db_path)
        try:
            return database.current_source(db)
        finally:
            db.close()

    def sync(self, force: bool = False) -> dict[str, Any]:
        """Importe la sauvegarde la plus récente si elle a changé (ou toujours, avec ``force``)."""
        newest = latest(self.root)
        if newest is None:
            self.log(f"aucune sauvegarde dans {self.root}")
            return {"status": "nosave"}
        key = database.save_key(Path(newest[0]))
        if not force and newest == self.current_source():
            self.log(f"déjà à jour : {key}")
            return {"status": "uptodate", "save": key}
        ok = self.import_save(Path(newest[0]))
        return {"status": "imported" if ok else "retry", "save": key}

    # --- surveillance -------------------------------------------------------

    @property
    def watching(self) -> bool:
        return self._watch_thread is not None and self._watch_thread.is_alive()

    def start_watch(self) -> None:
        if self.watching:
            return
        self._watch_stop.clear()
        self._watch_thread = threading.Thread(target=self.watch, name="save-watcher", daemon=True)
        self._watch_thread.start()
        self._emit("watch_changed", watching=True)

    def stop_watch(self) -> None:
        self._watch_stop.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=self.interval + 5)
        self._watch_thread = None
        self._emit("watch_changed", watching=False)

    def watch(self) -> None:
        """Boucle de surveillance (bloquante) ; s'arrête quand stop_watch() est appelé."""
        self.log(f"surveillance de {self.root} (toutes les {self.interval:g}s)")
        pending: tuple[Signature, float] | None = None  # (signature, vue depuis)
        failed: Signature | None = None
        while not self._watch_stop.is_set():
            try:
                newest = latest(self.root)
                now = time.monotonic()
                if newest is None or newest == self.current_source() or newest == failed:
                    pending = None
                elif pending is None or pending[0] != newest:
                    if pending is None or pending[0][0] != newest[0]:
                        key = database.save_key(Path(newest[0]))
                        self.log(f"changement détecté : {key}")
                        self._emit("change_detected", save=key)
                    pending = (newest, now)
                elif now - pending[1] >= self.settle:
                    if self.import_save(Path(newest[0])):
                        pending, failed = None, None
                    elif now - pending[1] > self.settle + 60:
                        # Fichier stable mais illisible depuis une minute : on attend une nouvelle version.
                        self.log(f"  abandon pour {database.save_key(Path(newest[0]))} jusqu'à sa prochaine modification")
                        pending, failed = None, newest
                self.pending = database.save_key(Path(pending[0][0])) if pending else None
            except Exception as e:
                self.log(f"  erreur de surveillance : {type(e).__name__}: {e}")
            self._watch_stop.wait(self.interval)
        self.log("surveillance arrêtée")
