"""Portefeuille : ce que rapporte chaque commerce, ce qu'il pourrait rapporter, et les produits à ajouter ou retirer.

Ventes d'un produit (CustomerEntriesCalculatorRetail) : clients × productSalesRatio × demande / 100
× (1 + (satisfaction − 50) / 100) × impact × quantité. On cale ce modèle sur les ventes réelles de chaque commerce
(médiane du rapport réel / prédit sur ses produits actuels), puis on l'applique aux produits qu'il ne vend pas.
Chaque produit est tiré indépendamment : un ajout ne retire pas de ventes aux autres, un retrait ne fait que perdre
sa propre marge.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from statistics import median
from typing import Any

from . import recommendations
from .recommendations import Data, _all, _tables

LIKELY = ("high", "medium")
LOW_EARNER = 0.25  # part du profit médian sous laquelle un commerce rapporte peu
DROP_SHARE = 0.03  # part de la marge du commerce sous laquelle un produit pèse peu
MIN_ADD_GAIN = 20  # $/jour : en dessous, un ajout ne vaut pas une étagère de plus
CALIBRATION = (0.5, 2.0)


def _sat_multiplier(satisfaction: float | None) -> float:
    return (satisfaction or 50) / 100 + 0.5


def _model_units(o: dict[str, Any], customers: float, satisfaction: float | None) -> float:
    return (customers * o["salesRatio"] * (o["demand"] or 0) / 100 * _sat_multiplier(satisfaction)
            * o["impact"] * o["amountFactor"])


def _best_cost(o: dict[str, Any]) -> tuple[float | None, str | None]:
    options = [(o["importCost"], "import"), (o["wholesaleCost"], "wholesaler")]
    options = [x for x in options if x[0] is not None]
    if options:
        return min(options)
    if o["kind"] != "product":
        return 0.0, None
    return o["costEstimate"], "factory" if o["fromFactory"] else None


def products(d: Data) -> dict[str, list[dict[str, Any]]]:
    """Produits actuels et candidats par commerce de détail."""
    if "product_options" not in _tables(d.db):
        return {}
    options = defaultdict(list)
    for o in _all(d.db, "SELECT * FROM product_options"):
        options[o["address"]].append(o)
    unit_costs = {(r["address"], r["item"]): r["c"] for r in _all(d.db, """
        SELECT address, item, sum(wholesaleCost) / max(sum(amountSold), 1) AS c FROM hist_sales
        WHERE day >= ? AND amountSold > 0 GROUP BY address, item""", (d.first_day,))}
    # Produits déjà sous contrat d'import : leur coût suit l'indice du marché, pas de gain à attendre.
    imported = {r["item"] for r in _all(d.db, "SELECT item FROM import_partnerships WHERE amountPerDelivery > 0")}         if "import_partnerships" in _tables(d.db) else set()
    out = {}
    for address, rows in options.items():
        b = d.businesses.get(address) or {}
        customers = d.customers.get(address, 0)
        sat = b.get("satisfaction")
        # Calage : rapport ventes réelles / modèle sur les produits vendus (hors droits d'entrée, comptés à part).
        ratios = []
        for o in rows:
            units = d.sales.get((address, o["item"]), {}).get("units", 0)
            model = _model_units(o, customers, sat)
            if o["selling"] and o["kind"] == "product" and units > 0 and model > 0:
                ratios.append(units / model)
        k = min(max(median(ratios), CALIBRATION[0]), CALIBRATION[1]) if ratios else 1.0
        current, candidates = [], []
        for o in rows:
            cost, source = _best_cost(o)
            if o["selling"]:
                s = d.sales.get((address, o["item"]), {"units": 0, "revenue": 0, "avgPrice": None})
                unit_cost = unit_costs.get((address, o["item"]))
                margin = s["revenue"] - s["units"] * (unit_cost or 0)
                saving = None
                if o["item"] not in imported and o["importCost"] is not None and unit_cost and unit_cost > o["importCost"] * 1.03:
                    saving = s["units"] * (unit_cost - o["importCost"])
                # Revenu par unité très inférieur au prix : le produit est surtout consommé par les services.
                consumed = o["kind"] == "product" and s["units"] > 0 and s["revenue"] / s["units"] < 0.5 * o["price"]
                current.append({**_base(o), "unitsPerDay": round(s["units"], 1), "revenuePerDay": round(s["revenue"], 2),
                                "marginPerDay": round(margin, 2), "unitCost": round(unit_cost, 3) if unit_cost else None,
                                "price": round(s["avgPrice"], 2) if s["avgPrice"] else o["price"],
                                "importCost": o["importCost"], "importSavingPerDay": round(saving, 2) if saving else None,
                                "manualRestock": o["kind"] == "product" and not o["logistics"], "consumed": consumed,
                                "imported": o["item"] in imported})
            elif o["kind"] == "product" and cost is not None and source is not None:
                units = _model_units(o, customers, sat) * k
                unit_margin = o["price"] - cost
                candidates.append({**_base(o), "unitsPerDay": round(units, 1), "price": o["price"], "unitCost": round(cost, 3),
                                   "source": source, "unitMargin": round(unit_margin, 2),
                                   "equipmentOwned": o["equipmentOwned"], "equipment": o["equipment"],
                                   "equipmentCost": o["equipmentCost"],
                                   "marginPerDay": round(units * unit_margin, 2)})
        total = sum(max(c["marginPerDay"], 0) for c in current)
        for c in current:
            c["share"] = round(c["marginPerDay"] / total, 4) if total else None
            c["verdict"], c["reason"] = _product_verdict(c)
        candidates = [c for c in candidates if c["marginPerDay"] >= MIN_ADD_GAIN]
        out[address] = {"calibration": round(k, 2), "customersPerDay": round(customers, 1),
                        "current": sorted(current, key=lambda c: -c["marginPerDay"]),
                        "candidates": sorted(candidates, key=lambda c: -c["marginPerDay"])}
    return out


def _base(o: dict[str, Any]) -> dict[str, Any]:
    return {k: o[k] for k in ("item", "itemLabel", "kind", "primary", "impact", "demand", "importable", "atWholesaler",
                              "fromFactory", "logistics")}


def _product_verdict(c: dict[str, Any]) -> tuple[str, str]:
    if c["kind"] != "product":
        return "keep", "Service or entrance fee: no stock to manage."
    if c["consumed"]:
        return "keep", "Mostly used up by the services (only part is sold to customers): a cost of the services, not a product to drop."
    if c["marginPerDay"] <= 0:
        return "drop", "Sells at a loss."
    if (c["share"] or 0) < DROP_SHARE and c["manualRestock"]:
        return "drop", f"{(c['share'] or 0) * 100:.1f} % of the shop's margin, and restocked by hand."
    if (c["share"] or 0) < DROP_SHARE:
        return "review", f"Only {(c['share'] or 0) * 100:.1f} % of the shop's margin: keep only if the shelf space is free."
    if c["importSavingPerDay"]:
        return "import", f"Importing would save ${c['importSavingPerDay']:.0f}/day."
    if c["manualRestock"]:
        return "automate", "Add it to a logistics manager plan so you stop restocking it."
    return "keep", ""


def compute(db: sqlite3.Connection, window: int = 14) -> dict[str, Any]:
    d = Data(db, window)
    if not d.ok:
        return {"empty": True}
    recos = recommendations.compute(db, window)
    potential = defaultdict(lambda: {"likely": 0.0, "possible": 0.0, "items": []})
    for r in recos:
        if not r.get("address") or not r["gainPerDay"] or r["category"] in ("markets", "expansion"):
            continue
        p = potential[r["address"]]
        p["likely" if r["confidence"] in LIKELY else "possible"] += r["gainPerDay"]
        p["items"].append({"title": r["title"], "gainPerDay": round(r["gainPerDay"], 2), "confidence": r["confidence"]})
    prods = products(d)

    rows = []
    for address, b in d.businesses.items():
        if b["segment"] not in ("retail", "office") or not b.get("name"):
            continue
        pnl = d.pnl.get(address, {})
        days = max(d.days.get(address, window), 1)
        revenue = (pnl.get("revenue") or 0) / days
        profit = (pnl.get("operatingProfit") or 0) / days
        after = pnl.get("profitAfterOverhead")
        capital = b.get("furnitureValue") or 0
        pr = prods.get(address, {})
        adds = sum(c["marginPerDay"] for c in pr.get("candidates", [])[:3])
        imports = sum(c["importSavingPerDay"] or 0 for c in pr.get("current", []))
        manual = sum(1 for c in pr.get("current", []) if c["manualRestock"])
        pot = potential.get(address, {"likely": 0.0, "possible": 0.0, "items": []})
        rows.append({
            "address": address, "name": b["name"], "typeLabel": b["typeLabel"], "segment": b["segment"],
            "neighborhood": b["neighborhood"], "creationDay": b["creationDay"], "daysOpen": days,
            "revenuePerDay": round(revenue, 2), "profitPerDay": round(profit, 2),
            "profitAfterOverheadPerDay": round(after / days, 2) if after is not None else None,
            "margin": round(profit / revenue, 4) if revenue else None,
            "capital": round(capital, 2), "paybackDays": round(capital / profit, 1) if profit > 0 else None,
            "employees": b["employees"], "profitPerEmployee": round(profit / b["employees"], 2) if b["employees"] else None,
            "likelyGainPerDay": round(pot["likely"], 2), "possibleGainPerDay": round(pot["possible"], 2),
            "productGainPerDay": round(adds + imports, 2), "manualRestock": manual,
            "levers": sorted(pot["items"], key=lambda x: -x["gainPerDay"])[:4],
        })
    profits = [r["profitPerDay"] for r in rows if r["profitPerDay"] > 0]
    typical = median(profits) if profits else 0
    for r in rows:
        r["verdict"], r["reason"] = _verdict(r, typical)
    total = sum(r["profitPerDay"] for r in rows)
    return {
        "window": window, "firstDay": d.first_day, "lastDay": d.last_day, "typicalProfitPerDay": round(typical, 2),
        "businesses": sorted(rows, key=lambda r: -r["profitPerDay"]),
        "products": prods,
        "summary": {
            "profitPerDay": round(total, 2),
            "likelyGainPerDay": round(sum(r["likelyGainPerDay"] for r in rows), 2),
            "productGainPerDay": round(sum(r["productGainPerDay"] for r in rows), 2),
            "capital": round(sum(r["capital"] for r in rows), 2),
            "toReview": sum(1 for r in rows if r["verdict"] in ("close", "drop-effort")),
        },
    }


def _verdict(r: dict[str, Any], typical: float) -> tuple[str, str]:
    profit = r["profitPerDay"]
    upside = r["likelyGainPerDay"] + r["productGainPerDay"]
    if profit <= 0:
        return "close", "Loses money over the window: fix it fast or sell it."
    low = typical and profit < LOW_EARNER * typical
    if low and r["manualRestock"]:
        return "drop-effort", (f"Earns ${profit:,.0f}/day ({profit / typical * 100:.0f} % of a typical business) and "
                               f"{r['manualRestock']} product(s) are restocked by hand: automate it or sell it.")
    if upside > 0.25 * profit:
        return "optimize", f"About +${upside:,.0f}/day within reach ({upside / profit * 100:.0f} % more)."
    if low:
        return "low", f"Earns only {profit / typical * 100:.0f} % of a typical business: the money is better elsewhere."
    if r["possibleGainPerDay"] > 0.25 * profit:
        return "keep", f"No reliable gain found; up to +${r['possibleGainPerDay']:,.0f}/day in uncertain ideas (see Recommendations)."
    return "keep", "Runs close to its potential."
