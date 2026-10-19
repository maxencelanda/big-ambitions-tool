"""Exporte une sauvegarde en données exploitables.

    python export.py                    # sauvegarde la plus récente
    python export.py "chemin/vers.hsg"  # une sauvegarde précise

Produit dans out/<nom de la sauvegarde>/ :
    raw.json        arbre complet décodé (tout le contenu du .hsg)
    summary.json    vue d'ensemble du joueur + liste des commerces
    save.sqlite     une table par vue (businesses, employees, inventory, ...)
    csv/*.csv       les mêmes tables en CSV
"""

import argparse
import csv
import json
from pathlib import Path

from bigambitions import find_latest_save, load
from bigambitions.db import columns_of, write_tables
from bigambitions.model import Save
from bigambitions.reference import Reference, ReferenceMissing


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns_of(rows), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("save", nargs="?", type=Path, help="fichier .hsg (défaut : le plus récent)")
    parser.add_argument("-o", "--output", type=Path, help="dossier de sortie")
    args = parser.parse_args()

    path = args.save or find_latest_save()
    out = args.output or Path("out") / path.stem
    (out / "csv").mkdir(parents=True, exist_ok=True)

    data = load(path)
    try:
        ref = Reference.load()
    except ReferenceMissing as e:
        print(f"{e} : export sans prix ni quartiers")
        ref = None
    save = Save(data, ref)
    tables = save.tables()

    (out / "raw.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {"source": str(path), "player": save.player(), "businesses": tables["businesses"]}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, rows in tables.items():
        write_csv(out / "csv" / f"{name}.csv", rows)
    write_tables(out / "save.sqlite", tables)

    print(f"{path}\n -> {out}")
    for name, rows in tables.items():
        print(f"    {name:20} {len(rows):>6} lignes")


if __name__ == "__main__":
    main()
