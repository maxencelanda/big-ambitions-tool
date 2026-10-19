"""Compare biggerambitions.com au référentiel du jeu et enregistre les écarts.

    python check_biggerambitions.py            # utilise le cache (7 jours)
    python check_biggerambitions.py --refresh  # retélécharge les pages

Écrit la table check_biggerambitions dans out/bigambitions.sqlite (conservée entre les imports).
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from bigambitions import db as database
from bigambitions.biggerambitions import BiggerAmbitions, compare
from bigambitions.reference import Reference

DEFAULT_DB = Path(__file__).parent / "out" / "bigambitions.sqlite"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    rows = compare(BiggerAmbitions(), Reference.load(), refresh=args.refresh)
    db = database.connect(args.db)
    database.replace_table(db, "check_biggerambitions", rows)

    counts = Counter((r["field"], r["status"]) for r in rows)
    for (field, status), n in sorted(counts.items()):
        print(f"  {field:20} {status:12} {n:5}")
    worst = sorted((r for r in rows if r["status"] == "ecart"), key=lambda r: -abs(r["delta"] or 0))[:10]
    if worst:
        print("\nplus gros écarts (site - jeu) :")
        for r in worst:
            print(f"  {r['label'][:30]:30} {r['field']:18} {str(r['neighborhood'] or '')[16:]:16} site={r['site']} jeu={r['game']} ({r['delta']:+})")


if __name__ == "__main__":
    main()
