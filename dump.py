"""Convertit une sauvegarde .hsg en JSON.

    python dump.py                      # sauvegarde la plus récente -> out/<nom>.json
    python dump.py "chemin/vers.hsg" -o save.json
"""

import argparse
import json
from pathlib import Path

from bigambitions import find_latest_save, load


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("save", nargs="?", type=Path, help="fichier .hsg (défaut : le plus récent)")
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()

    path = args.save or find_latest_save()
    output = args.output or Path("out") / f"{path.stem}.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    data = load(path)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{path} -> {output}")


if __name__ == "__main__":
    main()
