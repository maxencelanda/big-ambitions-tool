"""Client pour biggerambitions.com (site de fans, sans API) et comparaison avec le référentiel du jeu.

Le site ne sert que de contrôle : la source de vérité reste le référentiel extrait du jeu.
Les pages sont mises en cache sur disque (7 jours par défaut) pour ne pas solliciter le site.

    client = BiggerAmbitions()
    client.sell_prices()       # [{itemName, label, boxSize, lowestUnitPrice, prices: {neighborhood: prix}}]
    client.purchase_prices()   # [{itemName, label, boxSize, wholesalePrice}]
    compare(client, Reference.load())  # lignes d'écart
"""

from __future__ import annotations

import re
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from .pricing import neighborhood_price_index
from .reference import Reference

BASE_URL = "https://www.biggerambitions.com"
CACHE_DIR = Path(__file__).resolve().parent.parent / "out" / "cache" / "biggerambitions"
USER_AGENT = "big-ambitions-tool/0.1 (outil personnel d'analyse de sauvegarde; cache 7 jours)"
NEIGHBORHOOD_COLUMNS = {
    "Garment District": "ba:neighborhood_garmentdistrict",
    "Hells Kitchen": "ba:neighborhood_hellskitchen",
    "Murray Hill": "ba:neighborhood_murrayhill",
    "Midtown": "ba:neighborhood_midtown",
    "Lower Manhattan": "ba:neighborhood_lowermanhattan",
    "Industry City": "ba:neighborhood_industrycity",
    "Hamptons": "ba:neighborhood_thehamptons",
}
_ICON = re.compile(r"goods/(itemname_[a-z0-9_]+)\.png", re.I)


class _TableParser(HTMLParser):
    """Extrait les lignes d'un tableau : texte des cellules, icône produit, attributs de <tr>."""

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []
        self._row: dict | None = None
        self._cell: list[str] | None = None
        self._in_tbody = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tbody":
            self._in_tbody = True
        elif tag == "tr" and self._in_tbody:
            self._row = {"cells": [], "icon": None, "attrs": attrs}
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif tag == "img" and self._row is not None and not self._row["icon"]:
            match = _ICON.search(attrs.get("src") or "")
            if match:
                self._row["icon"] = "ba:" + match.group(1).lower()

    def handle_endtag(self, tag):
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row["cells"].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "tbody":
            self._in_tbody = False

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except (AttributeError, ValueError):
        return None


class BiggerAmbitions:
    def __init__(self, cache_dir: Path = CACHE_DIR, max_age_days: float = 7, delay: float = 1.0):
        self.cache_dir = Path(cache_dir)
        self.max_age = max_age_days * 86400
        self.delay = delay
        self._last_request = 0.0

    def fetch(self, page: str, refresh: bool = False) -> str:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached = self.cache_dir / f"{page}.html"
        if not refresh and cached.exists() and time.time() - cached.stat().st_mtime < self.max_age:
            return cached.read_text(encoding="utf-8")
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(f"{BASE_URL}/{page}.php", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8", errors="replace")
        self._last_request = time.monotonic()
        cached.write_text(html, encoding="utf-8")
        return html

    def fetched_at(self, page: str) -> str | None:
        cached = self.cache_dir / f"{page}.html"
        return datetime.fromtimestamp(cached.stat().st_mtime).isoformat(timespec="seconds") if cached.exists() else None

    @staticmethod
    def _rows(html: str) -> list[dict]:
        parser = _TableParser()
        parser.feed(html)
        return [r for r in parser.rows if r["icon"]]

    def sell_prices(self, refresh: bool = False) -> list[dict]:
        """Page « prices-of-goods » : prix de marché le plus bas et prix par quartier."""
        rows = []
        for r in self._rows(self.fetch("prices-of-goods", refresh)):
            cells = r["cells"]
            if len(cells) < 12:
                continue
            rows.append({
                "itemName": r["icon"], "label": cells[1], "boxSize": _number(cells[2]),
                "lowestUnitPrice": _number(cells[3]),
                "prices": {nb: _number(v) for nb, v in zip(NEIGHBORHOOD_COLUMNS.values(), cells[5:12])},
            })
        return rows

    def purchase_prices(self, refresh: bool = False) -> list[dict]:
        """Page « purchase-prices » : prix de gros de base (attribut data-wholesale-price)."""
        rows = []
        for r in self._rows(self.fetch("purchase-prices", refresh)):
            cells = r["cells"]
            rows.append({
                "itemName": r["icon"], "label": cells[1] if len(cells) > 1 else None,
                "boxSize": _number(cells[3]) if len(cells) > 3 else None,
                "wholesalePrice": _number(r["attrs"].get("data-wholesale-price")),
            })
        return rows


def _status(site: float | None, game: float | None, tolerance_abs: float, tolerance_pct: float) -> str:
    if site is None:
        return "absent_site"
    if game is None:
        return "absent_jeu"
    delta = abs(site - game)
    return "ok" if delta <= tolerance_abs or (game and delta / abs(game) <= tolerance_pct) else "ecart"


def compare(client: BiggerAmbitions, ref: Reference, refresh: bool = False) -> list[dict]:
    """Compare le site au référentiel du jeu. Une ligne par (produit, mesure, quartier)."""
    index = {key: neighborhood_price_index(n) for key, n in ref.neighborhoods.items()}
    checked_at = datetime.now().isoformat(timespec="seconds")
    rows = []

    def add(page, item_name, label, field, neighborhood, site, game, tolerance_abs, tolerance_pct=0.01):
        both = site is not None and game is not None
        rows.append({
            "checkedAt": checked_at, "page": page, "item": item_name, "label": label, "field": field,
            "neighborhood": neighborhood, "site": site, "game": round(game, 4) if game is not None else None,
            "delta": round(site - game, 4) if both else None,
            "deltaPct": round((site - game) / game, 5) if both and game else None,
            "status": _status(site, game, tolerance_abs, tolerance_pct),
        })

    for r in client.sell_prices(refresh):
        item = ref.item(r["itemName"])
        default = item.get("defaultMarketPrice") if item else None
        add("prices-of-goods", r["itemName"], r["label"], "defaultMarketPrice", None, r["lowestUnitPrice"], default, 0.005)
        add("prices-of-goods", r["itemName"], r["label"], "boxSize", None, r["boxSize"], item.get("boxSize") if item else None, 0, 0)
        for neighborhood, site in r["prices"].items():
            game = default * index[neighborhood] if default is not None and neighborhood in index else None
            # Le site tronque au dixième : on compare à la valeur du jeu tronquée de la même façon,
            # avec 0,2 % de marge (au-delà, le site utilise un autre indice de quartier).
            truncated = int(game * 10 + 1e-6) / 10 if game is not None else None
            add("prices-of-goods", r["itemName"], r["label"], "optimalPrice", neighborhood, site, truncated, 0.05, 0.002)

    # Indice de quartier implicite du site (médiane de prix site / prix par défaut), comparé au nôtre.
    implied: dict[str, list[float]] = {}
    for r in client.sell_prices():
        item = ref.item(r["itemName"])
        default = item.get("defaultMarketPrice") if item else None
        if default and default >= 50:  # produits chers : l'arrondi du site devient négligeable
            for neighborhood, site in r["prices"].items():
                if site:
                    implied.setdefault(neighborhood, []).append(site / default)
    for neighborhood, ratios in implied.items():
        ratios.sort()
        add("prices-of-goods", None, ref.neighborhoods[neighborhood].get("m_Name"), "neighborhoodIndex",
            neighborhood, round(ratios[len(ratios) // 2], 4), index[neighborhood], 0.0005, 0)

    for r in client.purchase_prices(refresh):
        item = ref.item(r["itemName"])
        add("purchase-prices", r["itemName"], r["label"], "wholesalePrice", None, r["wholesalePrice"],
            item.get("wholesalePrice") if item else None, 0.005)
    return rows
