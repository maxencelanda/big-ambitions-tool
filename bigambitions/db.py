"""Écriture des tables dans SQLite.

Base centrale (sync.py) : reflète la sauvegarde la plus récente, qui fait foi.

    source     une ligne : le fichier .hsg dont viennent les données
    snapshots  historique : une ligne par import, jamais effacée (les sauvegardes auto
               étant réécrites en boucle, c'est la seule trace de l'évolution de la partie)
    hist_*     historique cumulé par jour de jeu (voir history.py), conservé entre les imports
    check_*    rapports de contrôle (ex. écarts avec biggerambitions), conservés entre les imports
    ref_*      référentiel du jeu (reference.py), recréé à chaque import
    <tables>   les vues de model.Save.tables(), recréées à chaque import
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from . import history
from .model import Save

SOURCE_COLUMNS = ["save", "characterId", "name", "path", "mtimeNs", "size", "importedAt",
                  "day", "time", "money", "businesses", "employees", "daysPerYear", "codeVersion"]


def _hash_package() -> str:
    digest = hashlib.sha1()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


# Calculée au chargement : un processus démarré avant une modification du code tamponne la base avec
# la version qu'il exécute vraiment, et le prochain processus (nouveau code) la réimportera.
_CODE_VERSION = _hash_package()


def code_version() -> str:
    """Empreinte du code d'import : si elle change, la base doit être reconstruite depuis la sauvegarde."""
    return _CODE_VERSION
SNAPSHOT_COLUMNS = ["save", "importedAt", "mtimeNs", "day", "time", "money", "energy", "happiness",
                    "businesses", "employees", "investmentBalance", "lastWeeklyIncome", "lastDayProfit"]
_SYSTEM_TABLES = ("source", "snapshots")
_PRESERVED_PREFIXES = ("hist_", "check_", "user_")


def _is_preserved(name: str) -> bool:
    return name in _SYSTEM_TABLES or name.startswith(_PRESERVED_PREFIXES) or name.startswith("sqlite_")


def columns_of(rows: list[dict]) -> list[str]:
    columns: dict[str, None] = {}
    for row in rows:
        columns.update(dict.fromkeys(row))
    return list(columns)


def _sql_value(value: Any) -> Any:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value


def _create_table(db: sqlite3.Connection, name: str, columns: list[str]) -> None:
    quoted = ", ".join(f'"{c}"' for c in columns)
    db.execute(f'CREATE TABLE IF NOT EXISTS "{name}" ({quoted})')
    # Table créée par une version précédente de l'outil : on ajoute les colonnes manquantes.
    existing = {r[1] for r in db.execute(f'PRAGMA table_info("{name}")')}
    for column in columns:
        if column not in existing:
            db.execute(f'ALTER TABLE "{name}" ADD COLUMN "{column}"')


def _insert(db: sqlite3.Connection, name: str, rows: list[dict], columns: list[str]) -> None:
    if not rows:
        return
    names = ", ".join(f'"{c}"' for c in columns)
    db.executemany(
        f'INSERT INTO "{name}" ({names}) VALUES ({", ".join("?" * len(columns))})',
        [[_sql_value(r.get(c)) for c in columns] for r in rows],
    )


def _write_data_tables(db: sqlite3.Connection, tables: dict[str, list[dict]]) -> None:
    for name, rows in tables.items():
        if rows:
            columns = columns_of(rows)
            _create_table(db, name, columns)
            _insert(db, name, rows, columns)


def write_tables(path: Path, tables: dict[str, list[dict]]) -> None:
    """Base autonome pour une seule sauvegarde (export.py)."""
    path.unlink(missing_ok=True)
    with sqlite3.connect(path) as db:
        _write_data_tables(db, tables)


# --- base centrale ------------------------------------------------------------

def save_key(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Mode autocommit : les transactions sont ouvertes explicitement, DDL compris.
    db = sqlite3.connect(path, isolation_level=None, timeout=30)
    # WAL : le serveur web lit pendant qu'un import écrit, chacun voyant un état cohérent.
    db.execute("PRAGMA journal_mode=WAL")
    _create_table(db, "source", SOURCE_COLUMNS)
    _create_table(db, "snapshots", SNAPSHOT_COLUMNS)
    return db


def replace_table(db: sqlite3.Connection, name: str, rows: list[dict]) -> None:
    """Remplace entièrement une table (rapports check_*), en une transaction."""
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(f'DROP TABLE IF EXISTS "{name}"')
        if rows:
            _create_table(db, name, columns_of(rows))
            _insert(db, name, rows, columns_of(rows))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def set_dismissed(db: sqlite3.Connection, key: str, dismissed: bool) -> None:
    """Recommandation écartée par l'utilisateur (table user_dismissals, conservée entre les imports)."""
    _create_table(db, "user_dismissals", ["key", "dismissedAt"])
    db.execute("DELETE FROM user_dismissals WHERE key = ?", (key,))
    if dismissed:
        db.execute("INSERT INTO user_dismissals VALUES (?, ?)", (key, datetime.now().isoformat(timespec="seconds")))


def current_source(db: sqlite3.Connection) -> tuple[str, int, int] | None:
    """(chemin, mtimeNs, taille) de la sauvegarde actuellement en base.

    None si la base a été construite par une autre version du code : elle doit alors être réimportée.
    """
    row = db.execute("SELECT path, mtimeNs, size, codeVersion FROM source").fetchone()
    if not row or row[3] != code_version():
        return None
    return tuple(row[:3])


def replace_all(db: sqlite3.Connection, path: Path, mtime_ns: int, size: int,
                save: Save, tables: dict[str, list[dict]]) -> None:
    """Remplace tout le contenu de la base par cette sauvegarde, en une seule transaction."""
    now = datetime.now().isoformat(timespec="seconds")
    player = save.player()
    key = save_key(path)
    db.execute("BEGIN IMMEDIATE")
    try:
        existing = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for name in existing:
            if not _is_preserved(name):
                db.execute(f'DROP TABLE "{name}"')
        _write_data_tables(db, tables)
        if save.ref is not None:
            _write_data_tables(db, save.ref.tables())
        history.merge(db, tables, player["day"], _insert)

        db.execute("DELETE FROM source")
        _insert(db, "source", [{
            "save": key, "characterId": path.parent.name, "name": path.stem, "path": str(path),
            "mtimeNs": mtime_ns, "size": size, "importedAt": now,
            "day": player["day"], "time": player["time"], "money": player["money"],
            "businesses": player["businesses"], "employees": player["employees"],
            "daysPerYear": player["gameVariables"].get("daysPerYear") or 60,
            "codeVersion": code_version(),
        }], SOURCE_COLUMNS)

        totals = tables.get("daily_totals") or []
        weekly = player["weeklyIncomeHistory"]
        _insert(db, "snapshots", [{
            "save": key, "importedAt": now, "mtimeNs": mtime_ns,
            "day": player["day"], "time": player["time"], "money": player["money"],
            "energy": player["energy"], "happiness": player["happiness"],
            "businesses": player["businesses"], "employees": player["employees"],
            "investmentBalance": sum(f["balance"] or 0 for f in player["investmentFunds"]),
            "lastWeeklyIncome": weekly[-1][1] if weekly else None,
            "lastDayProfit": totals[-1]["totalProfit"] if totals else None,
        }], SNAPSHOT_COLUMNS)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
