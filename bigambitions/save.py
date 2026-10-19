"""Chargement des sauvegardes Big Ambitions (.hsg = gzip + Odin binaire, .hsg.meta = JSON)."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Any

from . import odin

SAVE_ROOT = Path(os.environ.get("USERPROFILE", "~")).expanduser() / (
    "AppData/LocalLow/Hovgaard Games/Big Ambitions/SaveGames/Big Ambitions"
)


def find_latest_save(root: Path = SAVE_ROOT) -> Path:
    saves = list(Path(root).rglob("*.hsg"))
    if not saves:
        raise FileNotFoundError(f"aucun .hsg sous {root}")
    return max(saves, key=lambda p: p.stat().st_mtime)


def load_raw(path: Path) -> bytes:
    data = Path(path).read_bytes()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def load_meta(path: Path) -> dict[str, Any] | None:
    meta = Path(str(path) + ".meta")
    return json.loads(meta.read_text(encoding="utf-8-sig")) if meta.exists() else None


def load(path: Path) -> dict[str, Any]:
    """Retourne {"meta": ..., "game": ...} pour un fichier .hsg."""
    game, _ = odin.loads(load_raw(path))
    return {"meta": load_meta(path), "game": game}
