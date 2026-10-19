"""Historique cumulé, par jour de jeu (tables hist_*), au-delà de ce que la sauvegarde conserve.

Deux sortes de tables :
  - « journal » : la sauvegarde contient déjà plusieurs jours (P&L, ventes, transactions) ;
  - « photo »   : état au jour de la sauvegarde (prix, marché, commerces, employés).

À chaque import du jour D :
  1. on efface tout ce qui est daté de D ou après dans les tables photo, et après D partout
     (si une ancienne partie a été rechargée, la ligne de temps abandonnée disparaît) ;
  2. on remplace les jours présents dans la sauvegarde par sa version, qui fait foi. Pour les
     sources à fenêtre glissante, le jour le plus ancien est souvent incomplet : il n'est réécrit
     que s'il n'est pas encore dans l'historique.
"""

from __future__ import annotations

import sqlite3
from typing import Any

# table historique -> (table source, fenêtre glissante dont le 1er jour peut être partiel)
JOURNALS = {
    "hist_daily_finances": ("daily_finances", False),
    "hist_daily_totals": ("daily_totals", False),
    "hist_sales": ("sales_history", False),
    "hist_transactions": ("transactions", True),
}
SNAPSHOTS = {
    "hist_prices": "prices",
    "hist_market": "market_prices",
    "hist_businesses": "businesses",
    "hist_employees": "employees",
    "hist_competitor_prices": "competitor_prices",
}
HISTORY_TABLES = tuple(JOURNALS) + tuple(SNAPSHOTS)


def _columns(db: sqlite3.Connection, name: str) -> list[str]:
    return [r[1] for r in db.execute(f'PRAGMA table_info("{name}")')]


def _ensure(db: sqlite3.Connection, name: str, columns: list[str]) -> None:
    existing = _columns(db, name)
    if not existing:
        quoted = ", ".join(f'"{c}"' for c in columns)
        db.execute(f'CREATE TABLE "{name}" ({quoted})')
        db.execute(f'CREATE INDEX "ix_{name}_day" ON "{name}" ("day")')
        return
    for column in columns:
        if column not in existing:
            db.execute(f'ALTER TABLE "{name}" ADD COLUMN "{column}"')


def _days(db: sqlite3.Connection, name: str) -> set[int]:
    return {r[0] for r in db.execute(f'SELECT DISTINCT day FROM "{name}"')}


def merge(db: sqlite3.Connection, tables: dict[str, list[dict]], day: int, insert) -> dict[str, int]:
    """Fusionne les tables courantes dans l'historique. ``insert(db, name, rows, columns)`` écrit les lignes.

    Doit être appelé à l'intérieur d'une transaction. Renvoie le nombre de lignes écrites par table.
    """
    from .db import columns_of

    written = {}
    for name in HISTORY_TABLES:
        if _columns(db, name):
            db.execute(f'DELETE FROM "{name}" WHERE day > ?', (day,))

    for name, (source, sliding) in JOURNALS.items():
        rows = [r for r in tables.get(source, []) if r.get("day") is not None]
        if not rows:
            continue
        _ensure(db, name, columns_of(rows))
        days = {r["day"] for r in rows}
        if sliding and min(days) in _days(db, name):
            days.discard(min(days))
            rows = [r for r in rows if r["day"] in days]
        db.executemany(f'DELETE FROM "{name}" WHERE day = ?', [(d,) for d in days])
        insert(db, name, rows, _columns(db, name))
        written[name] = len(rows)

    for name, source in SNAPSHOTS.items():
        rows = [{"day": day, **r} for r in tables.get(source, [])]
        if not rows:
            continue
        _ensure(db, name, columns_of(rows))
        db.execute(f'DELETE FROM "{name}" WHERE day = ?', (day,))
        insert(db, name, rows, _columns(db, name))
        written[name] = len(rows)
    return written


def summary(db: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for name in HISTORY_TABLES:
        if _columns(db, name):
            first, last, count = db.execute(f'SELECT min(day), max(day), count(*) FROM "{name}"').fetchone()
            out.append({"table": name, "firstDay": first, "lastDay": last, "rows": count})
    return out
