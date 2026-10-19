"""Lance l'outil d'analytics : serveur local + surveillance des sauvegardes.

    .venv/Scripts/python app.py                 # http://127.0.0.1:8765 (ouvre le navigateur)
    .venv/Scripts/python app.py --no-watch      # sans surveillance automatique
    .venv/Scripts/python app.py --port 9000 --no-browser

L'interface doit avoir été construite une fois : cd web && npm install && npm run build
"""

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from bigambitions.ingest import DEFAULT_DB
from bigambitions.save import SAVE_ROOT
from bigambitions.server import WEB_DIST, create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--root", type=Path, default=SAVE_ROOT, help="dossier des sauvegardes")
    parser.add_argument("--no-watch", action="store_true", help="ne pas surveiller les sauvegardes")
    parser.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not WEB_DIST.exists():
        print("interface absente : cd web && npm install && npm run build (l'API reste disponible)")
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, (url,)).start()
    print(f"Big Ambitions Analytics : {url}")
    # Écoute locale uniquement (127.0.0.1) : l'outil n'est pas exposé sur le réseau.
    uvicorn.run(create_app(args.db, args.root, watch=not args.no_watch), host="127.0.0.1", port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
