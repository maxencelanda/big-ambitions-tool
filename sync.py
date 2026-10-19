"""Tient out/bigambitions.sqlite à jour avec la sauvegarde la plus récente (qui fait foi).

    python sync.py            # importe la sauvegarde la plus récente si elle a changé, puis s'arrête
    python sync.py --watch    # idem, puis surveille le dossier en continu (Ctrl+C pour arrêter)
    python sync.py --force    # ré-importe même si rien n'a changé

« La plus récente » = le .hsg modifié en dernier dans le dossier des sauvegardes. Il est importé
quand il change (nouveau fichier, ou date/taille différente), une fois que le jeu a fini de
l'écrire (taille et date stables pendant --settle secondes). Le serveur web (app.py) fait la même
chose en tâche de fond.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bigambitions.ingest import DEFAULT_DB, Ingestor
from bigambitions.save import SAVE_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--root", type=Path, default=SAVE_ROOT, help="dossier des sauvegardes")
    parser.add_argument("--watch", action="store_true", help="surveiller le dossier en continu")
    parser.add_argument("--force", action="store_true", help="ré-importer même si rien n'a changé")
    parser.add_argument("--interval", type=float, default=3.0, help="secondes entre deux scans")
    parser.add_argument("--settle", type=float, default=2.0, help="secondes de stabilité avant import")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not args.root.exists():
        sys.exit(f"dossier introuvable : {args.root}")
    ingestor = Ingestor(args.db, args.root, args.interval, args.settle)
    ingestor.log(f"base : {args.db}")
    ingestor.sync(force=args.force)
    if args.watch:
        try:
            ingestor.watch()
        except KeyboardInterrupt:
            ingestor.log("arrêt")


if __name__ == "__main__":
    main()
