"""Prix et marché : vue d'ensemble des prix, historique, opportunités et activité des rivaux."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

PROFIT_SEGMENTS = ("retail", "office")


def _all(db: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cursor = db.execute(sql, params)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _clean(key: str | None) -> str | None:
    return key[3:].split("_", 1)[-1] if key and key.startswith("ba:") else key


def _day(db: sqlite3.Connection) -> int:
    return db.execute("SELECT day FROM source").fetchone()[0]


def _sales_per_day(db: sqlite3.Connection, window: int) -> dict[tuple[str, str], dict[str, float]]:
    last = db.execute("SELECT max(day) FROM hist_sales").fetchone()[0] or 0
    first = last - window + 1
    days = db.execute("SELECT count(DISTINCT day) FROM hist_sales WHERE day >= ?", (first,)).fetchone()[0] or 1
    return {
        (r["address"], r["item"]): {"units": r["units"] / days, "revenue": r["revenue"] / days, "avgPrice": r["avgPrice"]}
        for r in _all(db, """SELECT address, item, sum(amountSold) AS units, sum(revenue) AS revenue,
                                    sum(revenue) / max(sum(amountSold), 1) AS avgPrice
                             FROM hist_sales WHERE day >= ? GROUP BY address, item""", (first,))
    }


def prices_overview(db: sqlite3.Connection, window: int = 7) -> dict[str, Any]:
    """Chaque prix du joueur, avec ventes, gain possible et concurrence."""
    tables = _tables(db)
    if "prices" not in tables:
        return {"prices": []}
    sales = _sales_per_day(db, window) if "hist_sales" in tables else {}
    competitors = defaultdict(int)
    if "competitor_prices" in tables:
        for r in _all(db, "SELECT item, neighborhood, count(*) AS n FROM competitor_prices GROUP BY item, neighborhood"):
            competitors[(r["item"], r["neighborhood"])] = r["n"]
    market = {}
    if "market_prices" in tables:
        market = {(r["item"], r["neighborhood"]): r for r in _all(db, "SELECT * FROM market_prices")}
    rows = []
    for p in _all(db, "SELECT * FROM prices"):
        s = sales.get((p["address"], p["item"]), {"units": 0, "revenue": 0, "avgPrice": None})
        m = market.get((p["item"], p["neighborhood"]), {})
        gain = max(0.0, p["headroom"] or 0) * s["units"]
        rows.append({
            **p,
            "unitsPerDay": round(s["units"], 1), "revenuePerDay": round(s["revenue"], 2),
            "avgSoldPrice": round(s["avgPrice"], 2) if s["avgPrice"] else None,
            "gainPerDay": round(gain, 2),
            "competitors": competitors.get((p["item"], p["neighborhood"]), 0),
            "rivalSellers": m.get("rivalSellers"), "demand": m.get("demand"), "providers": m.get("providers"),
            "optimalProviders": m.get("optimalProviders"), "activeEvents": m.get("activeEvents"),
            # Plafond abaissé par un concurrent moins cher que le prix de base.
            "cappedByCompetitor": bool(p["lowestCompetitorPrice"] is not None and p["lowestCompetitorPrice"] < p["defaultPrice"]
                                       and not p["monopoly"]),
        })
    rows.sort(key=lambda r: -r["revenuePerDay"])
    return {
        "prices": rows,
        "summary": {
            "products": len(rows),
            "atCeiling": sum(1 for r in rows if abs(r["headroom"] or 0) < 0.01),
            "belowCeiling": sum(1 for r in rows if (r["headroom"] or 0) >= 0.01),
            "aboveCeiling": sum(1 for r in rows if (r["headroom"] or 0) <= -0.01),
            "monopolies": sum(1 for r in rows if r["monopoly"]),
            "cappedByCompetitor": sum(1 for r in rows if r["cappedByCompetitor"]),
            "gainPerDay": round(sum(r["gainPerDay"] for r in rows), 2),
        },
    }


def price_history(db: sqlite3.Connection, address: str, item: str) -> dict[str, Any]:
    """Historique d'un produit dans un commerce : prix vendu (ventes), plafond et concurrence (photos du jour)."""
    tables = _tables(db)
    series: dict[int, dict[str, Any]] = defaultdict(dict)
    if "hist_sales" in tables:
        for r in _all(db, "SELECT day, amountSold, revenue, avgPrice FROM hist_sales WHERE address = ? AND item = ?", (address, item)):
            series[r["day"]].update({"day": r["day"], "units": r["amountSold"], "revenue": r["revenue"], "soldPrice": r["avgPrice"]})
    neighborhood = None
    if "hist_prices" in tables:
        for r in _all(db, """SELECT day, price, ceiling, optimal, lowestCompetitorPrice, monopoly, neighborhood
                             FROM hist_prices WHERE address = ? AND item = ?""", (address, item)):
            neighborhood = r.pop("neighborhood")
            series[r["day"]].update(r)
    if "hist_competitor_prices" in tables and neighborhood:
        for r in _all(db, """SELECT day, min(competitorPrice) AS minCompetitor, count(*) AS competitors
                             FROM hist_competitor_prices WHERE item = ? AND neighborhood = ? GROUP BY day""", (item, neighborhood)):
            series[r["day"]].update(r)
    label = None
    if "prices" in tables:
        row = db.execute("SELECT itemLabel, business FROM prices WHERE address = ? AND item = ?", (address, item)).fetchone()
        label = row[0] if row else None
    return {"address": address, "item": item, "label": label, "neighborhood": neighborhood,
            "series": [dict(day=d, **{k: v for k, v in s.items() if k != "day"}) for d, s in sorted(series.items())]}


def market_table(db: sqlite3.Connection, neighborhood: str | None = None) -> list[dict[str, Any]]:
    tables = _tables(db)
    if "market_prices" not in tables:
        return []
    if neighborhood:
        rows = _all(db, "SELECT * FROM market_prices WHERE neighborhood = ? ORDER BY demand DESC", (neighborhood,))
    else:
        rows = _all(db, "SELECT * FROM market_prices ORDER BY demand DESC")
    if "suppliers" in tables:
        where: dict[str, list[str]] = defaultdict(list)
        for s in _all(db, "SELECT item, supplier, kind FROM suppliers WHERE available ORDER BY kind, supplier"):
            where[s["item"]].append(f"{s['supplier']}{' (import)' if s['kind'] == 'importer' else ''}")
        for r in rows:
            r["suppliers"] = ", ".join(where.get(r["item"], [])) or None
    return rows


def suppliers(db: sqlite3.Connection, item: str | None = None) -> list[dict[str, Any]]:
    """Où acheter : un produit précis, ou tout le catalogue des importateurs et grossistes."""
    if "suppliers" not in _tables(db):
        return []
    if item:
        return _all(db, "SELECT * FROM suppliers WHERE item = ? ORDER BY available DESC, purchasePriceEstimate", (item,))
    return _all(db, "SELECT * FROM suppliers ORDER BY itemLabel, kind, supplier")


# Score d'opportunité (0–100) : heuristique transparente, chaque composant vaut entre 0 et 1.
SCORE_WEIGHTS = {"demand": 0.35, "room": 0.20, "monopoly": 0.15, "location": 0.20, "margin": 0.10}
CANNIBALIZATION_POINTS = 20  # points retirés si l'ouverture prenait 100 % de la demande de tes commerces
RENT_REFERENCE = 500.0       # $/jour : loyer pour lequel l'accessibilité vaut 0,5
DEMAND_FLOOR = 31.5          # le jeu tire 29–34 quand la formule passe sous 30


def demand_with(providers: int, optimal: int, event_impact: int = 0) -> float:
    """Demande d'un produit dans un quartier pour un nombre de fournisseurs (ProductMarketHelper.CalculateDemand)."""
    base = 100 - providers * 100 / optimal
    base = DEMAND_FLOOR if base < 30 else min(base, 100.0)
    return min(100.0, base + (event_impact or 0))


def _space_score(space: dict[str, Any]) -> float:
    """Trafic du local (60 %) et poids de son loyer (40 %)."""
    affordability = 1 / (1 + (space["estimatedRent"] or 0) / RENT_REFERENCE)
    return 0.6 * (space["trafficIndex"] or 0) / 100 + 0.4 * affordability


def _score(rows_for: list[dict[str, Any]], best_space: dict[str, Any] | None,
           cannibalization: float) -> tuple[float, dict[str, float]]:
    """``rows_for`` porte ``demandAfter`` : la demande une fois le nouveau commerce ouvert."""
    n = len(rows_for)
    margins = []
    for r in rows_for:
        if r["unitMarginAtOptimal"] is not None and r["optimal"]:
            margins.append(max(0.0, r["unitMarginAtOptimal"] / r["optimal"]))
        elif r["optimal"]:
            margins.append(1.0)  # service : pas de coût d'achat
    components = {
        "demand": sum(r["demandAfter"] for r in rows_for) / n / 100,
        "room": sum(max(0.0, min(1.0, r["roomForProviders"] / r["optimalProviders"])) for r in rows_for) / n,
        "monopoly": sum(1 for r in rows_for if r["monopolyPossible"]) / n,
        "location": _space_score(best_space) if best_space else 0.0,
        "margin": sum(margins) / len(margins) if margins else 0.0,
    }
    score = 100 * sum(SCORE_WEIGHTS[k] * v for k, v in components.items()) - CANNIBALIZATION_POINTS * cannibalization
    return round(max(score, 0.0), 1), {k: round(v, 3) for k, v in components.items()}


def _reasons(components: dict[str, float], row: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Points forts et points faibles, en clair."""
    pros, cons = [], []
    demand = row["demandAfter"]
    (pros if demand >= 40 else cons).append(
        f"demand {demand:.0f}/100 once you open" if demand >= 40 else f"weak demand once you open ({demand:.0f}/100)")
    if components["room"] >= 0.4:
        pros.append("few providers yet")
    elif components["room"] <= 0.05:
        cons.append("market already saturated")
    if row["monopolyPossibleProducts"] == row["productsWithDemand"]:
        pros.append("no rival sells its products: monopoly possible")
    elif row["monopolyPossibleProducts"]:
        pros.append(f"monopoly possible on {row['monopolyPossibleProducts']}/{row['productsWithDemand']} products")
    else:
        cons.append(f"rival shops on every product (up to {row['rivalSellers']})")
    space = row["bestSpaces"][0] if row["bestSpaces"] else None
    if not space:
        cons.append("no free building of the right type")
    else:
        rent = space["rent"] or 0
        (pros if space["traffic"] >= 50 else cons).append(f"best space: traffic {space['traffic']}")
        if rent >= 1000:
            cons.append(f"expensive rent ({rent:,.0f} $/day)")
    if row["cannibalizedPerDay"] >= 1:
        cons.append(f"takes ≈{row['cannibalizedPerDay']:,.0f} $/day from your {row['affectedBusinesses']}")
    elif row["affectedBusinesses"]:
        pros.append(f"no loss for your {row['affectedBusinesses']}: demand is already at its floor")
    return pros, cons


def opportunities(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Pour chaque type de commerce créable et chaque quartier : demande de ses produits, concurrence,
    monopole atteignable, marge unitaire, locaux libres adaptés, et un score d'opportunité."""
    tables = _tables(db)
    if not {"ref_business_types", "market_prices", "city_buildings", "ref_buildings"} <= tables:
        return []
    market = defaultdict(dict)
    for r in _all(db, "SELECT * FROM market_prices"):
        market[r["neighborhood"]][r["item"]] = r
    building_types = {b["address"]: b["buildingType"] for b in _all(db, "SELECT address, buildingType FROM ref_buildings")}
    free = defaultdict(list)
    competitors = defaultdict(int)
    player = defaultdict(list)
    for b in _all(db, "SELECT * FROM city_buildings"):
        if b["availableForRent"]:
            free[(b["neighborhood"], building_types.get(b["address"]))].append(b)
        elif b["rentedByPlayer"]:
            player[(b["neighborhood"], b["type"])].append(b["businessName"])
        elif b["businessName"]:
            competitors[(b["neighborhood"], b["type"])] += 1
    # CA par jour de tes commerces, par (quartier, produit) : base de la cannibalisation.
    my_sales: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    if {"prices", "hist_sales"} <= tables:
        sales = _sales_per_day(db, 7)
        for p in _all(db, "SELECT address, business, item, neighborhood FROM prices"):
            revenue = sales.get((p["address"], p["item"]), {}).get("revenue", 0)
            my_sales[(p["neighborhood"], p["item"])].append((p["business"], revenue))
    neighborhoods = [n["neighborhood"] for n in _all(db, "SELECT neighborhood FROM ref_neighborhoods")
                     if n["neighborhood"] != "ba:neighborhood_global"]
    labels = {n["neighborhood"]: n["label"] for n in _all(db, "SELECT neighborhood, label FROM ref_neighborhoods")}

    rows = []
    for bt in _all(db, "SELECT * FROM ref_business_types WHERE playerCanCreate AND segment IN ('retail', 'office')"):
        products = [_clean(p) for p in (bt["products"] or "").split(", ") if p]
        type_key = _clean(bt["businessType"])
        for nb_key in neighborhoods:
            nb = _clean(nb_key)
            rows_for = [dict(market[nb][p]) for p in products if p in market[nb]]
            if not rows_for:
                continue
            # Ouvrir ajoute un fournisseur à chacun de ses produits : la demande baisse pour tout le monde,
            # y compris pour tes commerces du quartier qui vendent les mêmes produits.
            affected: dict[str, float] = defaultdict(float)
            for r in rows_for:
                r["demandAfter"] = demand_with((r["providers"] or 0) + 1, r["optimalProviders"], r["eventDemandImpact"] or 0)
                loss = max(0.0, (r["demand"] - r["demandAfter"]) / r["demand"]) if r["demand"] else 0.0
                for business, revenue in my_sales.get((nb, r["item"]), []):
                    affected[business] += revenue * loss
            my_revenue = sum(rev for r in rows_for for _, rev in my_sales.get((nb, r["item"]), []))
            cannibalized = sum(affected.values())
            share = cannibalized / my_revenue if my_revenue else 0.0
            # Meilleurs locaux : trafic élevé et loyer raisonnable.
            spaces = sorted(free.get((nb, bt["buildingType"]), []), key=lambda b: -_space_score(b))
            margins = [r["unitMarginAtOptimal"] for r in rows_for if r["unitMarginAtOptimal"] is not None]
            score, components = _score(rows_for, spaces[0] if spaces else None, share)
            rows.append({
                "score": score, "components": components,
                "demandAfter": round(sum(r["demandAfter"] for r in rows_for) / len(rows_for), 1),
                "cannibalizedPerDay": round(cannibalized, 2),
                "cannibalizationShare": round(share, 3),
                "affectedBusinesses": ", ".join(sorted({b for r in rows_for for b, _ in my_sales.get((nb, r["item"]), [])})) or None,
                "businessType": type_key, "label": bt["label"], "segment": bt["segment"],
                "neighborhood": nb, "neighborhoodLabel": labels.get(nb_key, nb),
                "products": len(products), "productsWithDemand": len(rows_for),
                "avgDemand": round(sum(r["demand"] or 0 for r in rows_for) / len(rows_for), 1),
                "maxDemand": max(r["demand"] or 0 for r in rows_for),
                # Moyenne : un produit secondaire très concurrencé (ex. pop-corn) ne doit pas masquer les autres.
                "roomForProviders": round(sum(r["roomForProviders"] for r in rows_for) / len(rows_for), 1),
                "rivalSellers": max(r["rivalSellers"] for r in rows_for),
                "monopolyPossibleProducts": sum(1 for r in rows_for if r["monopolyPossible"]),
                "avgUnitMargin": round(sum(margins) / len(margins), 2) if margins else None,
                "sameTypeCompetitors": competitors.get((nb, type_key), 0),
                "playerBusinesses": ", ".join(player.get((nb, type_key), [])) or None,
                "freeBuildings": len(spaces),
                "cheapestRent": min((s["estimatedRent"] for s in spaces if s["estimatedRent"] is not None), default=None),
                "bestTraffic": spaces[0]["trafficIndex"] if spaces else None,
                "bestSpaces": [{"address": s["address"], "rent": s["estimatedRent"], "sqm": s["sqm"], "traffic": s["trafficIndex"]}
                               for s in spaces[:3]],
                "activeEvents": ", ".join(sorted({e for r in rows_for for e in (r["activeEvents"] or "").split(", ") if e})) or None,
                "saturation": round(sum((r["providers"] or 0) / r["optimalProviders"] for r in rows_for) / len(rows_for), 2),
                "avgPrice": round(sum(r["optimal"] or 0 for r in rows_for) / len(rows_for), 2),
            })
            rows[-1]["pros"], rows[-1]["cons"] = _reasons(components, rows[-1])
    rows.sort(key=lambda r: -r["score"])
    return rows


def rival_activity(db: sqlite3.Connection, days: int = 30) -> dict[str, Any]:
    """Ouvertures et fermetures de commerces, événements de marché et changements de monopole qui touchent le joueur."""
    tables = _tables(db)
    today = _day(db)
    player = _all(db, "SELECT address, name, type, neighborhood FROM businesses WHERE segment IN ('retail', 'office')")
    player_types = {(b["neighborhood"], b["type"]) for b in player}
    player_neighborhoods = {b["neighborhood"] for b in player}
    sold = defaultdict(set)
    if "prices" in tables:
        for p in _all(db, "SELECT item, neighborhood FROM prices"):
            sold[p["neighborhood"]].add(p["item"])

    events = []
    for e in _all(db, "SELECT * FROM market_events WHERE startDay >= ? ORDER BY startDay DESC", (today - days,)):
        if e["kind"] in ("business_opened", "business_closed"):
            relevance = ("direct" if (e["neighborhood"], e["businessType"]) in player_types
                         else "neighborhood" if e["neighborhood"] in player_neighborhoods else "city")
        else:
            relevance = ("direct" if e["item"] in sold.get(e["neighborhood"], set())
                         or (e["neighborhood"] is None and any(e["item"] in s for s in sold.values()))
                         else "city")
        events.append({**e, "relevance": relevance})

    monopoly_changes = []
    if "hist_market" in tables:
        snapshots = [r[0] for r in db.execute("SELECT DISTINCT day FROM hist_market ORDER BY day DESC LIMIT 2")]
        if len(snapshots) == 2:
            now, before = snapshots
            for r in _all(db, """SELECT a.itemLabel, a.neighborhood, a.monopoly AS now, b.monopoly AS before, a.playerSells,
                                        a.rivalSellers, b.rivalSellers AS rivalSellersBefore
                                 FROM hist_market a JOIN hist_market b
                                   ON a.item = b.item AND a.neighborhood = b.neighborhood AND b.day = ?
                                 WHERE a.day = ? AND a.monopoly != b.monopoly""", (before, now)):
                monopoly_changes.append({**r, "fromDay": before, "toDay": now,
                                         "change": "gained" if r["now"] else "lost"})
    rivals = _all(db, "SELECT * FROM rivals ORDER BY businessesInCity DESC") if "rivals" in tables else []
    # Commerces de chaque rival dans les quartiers du joueur.
    if "city_buildings" in tables:
        nearby = defaultdict(int)
        for b in _all(db, "SELECT businessOwnerRivalId, neighborhood FROM city_buildings WHERE businessOwnerRivalId IS NOT NULL"):
            if b["neighborhood"] in player_neighborhoods:
                nearby[b["businessOwnerRivalId"]] += 1
        for r in rivals:
            r["inYourNeighborhoods"] = nearby.get(r["rivalId"], 0)
    return {"today": today, "days": days, "events": events, "monopolyChanges": monopoly_changes, "rivals": rivals}
