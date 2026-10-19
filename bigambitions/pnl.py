"""Compte de résultat (P&L) à partir de l'historique (hist_daily_finances, hist_daily_totals).

Structure (montants signés : + produit, − charge), conforme au calcul du jeu
(FinancialSummaryHelper.CalculateIncomeStatementTotalProfit) :

    Revenue − Cost of goods sold                           = Gross margin
    − Salaries − Rent − Marketing − Licensing − Theft      = Operating profit (centres de profit)
    + Headquarters + Logistics + Other (centres de coût)   = Business profit   (= totalBusinessProfit du jeu)
    + Health insurance + Headhunter fees + Unassigned wages
    − Housing + Real estate + Loans + Parking + Salary     = Net profit        (= totalProfit du jeu)

Centres de profit : segments retail et office. Centres de coût : siège, entrepôts, locaux vides et
commerces fermés sans ventes. Leur coût peut être réparti sur les centres de profit :
  - siège + coûts de personnel communs (assurance, chasseurs de têtes, salaires non affectés) :
    au prorata des effectifs ;
  - chaque entrepôt : au prorata du CA des commerces qu'il livre (objectifs des managers logistiques),
    à défaut de tous les commerces retail ;
  - autres (locaux vides, commerces fermés) : au prorata du CA.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

PROFIT_SEGMENTS = ("retail", "office")
GRANULARITIES = ("day", "week", "year")

BUSINESS_LINES = [
    ("revenue", "Revenue", "line"),
    ("cogs", "Cost of goods sold", "line"),
    ("grossMargin", "Gross margin", "subtotal"),
    ("salaries", "Salaries", "line"),
    ("rent", "Rent", "line"),
    ("marketing", "Marketing", "line"),
    ("licensingFees", "Licensing fees", "line"),
    ("theft", "Theft", "line"),
    ("operatingProfit", "Operating profit", "subtotal"),
]
OVERHEAD_LINES = [
    ("overheadHeadquarters", "Headquarters", "line"),
    ("overheadLogistics", "Warehouses & logistics", "line"),
    ("overheadOther", "Empty & closed buildings", "line"),
    ("businessProfit", "Business profit", "subtotal"),
]
GROUP_LINES = [
    ("healthInsurance", "Health insurance", "line"),
    ("headhunterFees", "Headhunter fees", "line"),
    ("unassignedWages", "Unassigned staff wages", "line"),
    ("housing", "Housing rent", "line"),
    ("realEstate", "Real estate income", "line"),
    ("loans", "Loans", "line"),
    ("parking", "Parking", "line"),
    ("salaryIncome", "Salary income", "line"),
    ("netProfit", "Net profit", "total"),
]
ALLOCATION_LINES = [
    ("allocatedHeadquarters", "Allocated headquarters & staff costs", "line"),
    ("allocatedLogistics", "Allocated warehouses", "line"),
    ("allocatedOther", "Allocated empty & closed buildings", "line"),
    ("profitAfterOverhead", "Businesses' profit after overhead", "total"),
]
GROUP_STAFF_KEYS = ("healthInsurance", "headhunterFees", "unassignedWages")


def _all(db: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cursor = db.execute(sql, params)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def days_per_year(db: sqlite3.Connection) -> int:
    try:
        row = db.execute("SELECT daysPerYear FROM source").fetchone()
        return int(row[0]) if row and row[0] else 60
    except sqlite3.OperationalError:
        return 60


def period_of(day: int, granularity: str, year_length: int) -> int:
    if granularity == "week":
        return (day - 1) // 7 + 1
    if granularity == "year":
        return (day - 1) // year_length + 1
    return day


def period_bounds(period: int, granularity: str, year_length: int) -> tuple[int, int]:
    if granularity == "week":
        return (period - 1) * 7 + 1, period * 7
    if granularity == "year":
        return (period - 1) * year_length + 1, period * year_length
    return period, period


def business_directory(db: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """address -> {name, segment, typeLabel, status} pour tous les commerces connus, actuels ou fermés."""
    tables = _tables(db)
    directory: dict[str, dict[str, Any]] = {}
    if "hist_businesses" in tables:
        for b in _all(db, """SELECT address, name, segment, typeLabel FROM hist_businesses h
                             WHERE day = (SELECT max(day) FROM hist_businesses WHERE address = h.address)"""):
            directory[b["address"]] = {**b, "status": "closed"}
    if "businesses" in tables:
        for b in _all(db, "SELECT address, name, segment, typeLabel, employees, creationDay FROM businesses"):
            directory[b["address"]] = {**b, "status": "active"}
    if "hist_daily_finances" in tables:
        for row in _all(db, """SELECT address, sum(sales) AS sales FROM hist_daily_finances GROUP BY address"""):
            if row["address"] not in directory:
                # Fermé avant le début du suivi : on ne connaît ni son nom ni son type.
                directory[row["address"]] = {
                    "address": row["address"], "name": None, "typeLabel": None, "status": "closed",
                    "segment": "retail" if (row["sales"] or 0) > 0 else "other",
                }
    return directory


def _business_amounts(row: dict[str, Any]) -> dict[str, float]:
    sales, resources = row["sales"] or 0, row["resources"] or 0
    salaries, rent, marketing = row["salaries"] or 0, row["rent"] or 0, row["marketing"] or 0
    licensing, theft = row["licensingFees"] or 0, row["theft"] or 0
    return {
        "revenue": sales, "cogs": -resources, "grossMargin": sales - resources,
        "salaries": -salaries, "rent": -rent, "marketing": -marketing,
        "licensingFees": -licensing, "theft": -theft, "operatingProfit": row["profit"] or 0,
    }


def _group_amounts(t: dict[str, Any]) -> dict[str, float]:
    return {
        "healthInsurance": t["totalHealthInsuranceExpenses"] or 0,
        "headhunterFees": t["totalHeadhunterReplacementFees"] or 0,
        "unassignedWages": t["totalUnassignedStaffWages"] or 0,
        "housing": -(t["totalResidentialExpenses"] or 0),
        "realEstate": t["totalRealEstate"] or 0,
        "loans": t["totalLoanExpenses"] or 0,
        "parking": t["parkingFees"] or 0,
        "salaryIncome": t["salaryIncome"] or 0,
        "gameTotalProfit": t["totalProfit"] or 0,
        "gameBusinessProfit": t["totalBusinessProfit"] or 0,
    }


def _warehouse_destinations(db: sqlite3.Connection) -> dict[str, set[str]]:
    if "logistics_targets" not in _tables(db):
        return {}
    out: dict[str, set[str]] = defaultdict(set)
    for r in _all(db, "SELECT DISTINCT sourceAddress, destinationAddress FROM logistics_targets"):
        if r["sourceAddress"] and r["destinationAddress"]:
            out[r["sourceAddress"]].add(r["destinationAddress"])
    return out


def _share(amount: float, weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if not weights or total <= 0:
        return {}
    return {k: amount * w / total for k, w in weights.items()}


def allocate(per_business: dict[str, dict[str, float]], group: dict[str, float],
             directory: dict[str, dict[str, Any]], destinations: dict[str, set[str]]) -> dict[str, dict[str, float]]:
    """Répartit les centres de coût d'une période sur les centres de profit (voir docstring du module)."""
    profit_centers = [a for a, info in directory.items()
                      if info["segment"] in PROFIT_SEGMENTS and info["status"] == "active"]
    revenue = {a: per_business.get(a, {}).get("revenue", 0) for a in profit_centers}
    headcount = {a: directory[a].get("employees") or 0 for a in profit_centers}
    retail_revenue = {a: v for a, v in revenue.items() if directory[a]["segment"] == "retail"}
    result: dict[str, dict[str, float]] = {a: defaultdict(float) for a in profit_centers}

    def spread(line: str, amount: float, weights: dict[str, float]) -> None:
        for a, part in _share(amount, weights).items():
            result[a][line] += part

    for address, amounts in per_business.items():
        info = directory.get(address, {"segment": "other", "status": "closed"})
        if info["segment"] in PROFIT_SEGMENTS and info["status"] == "active":
            continue
        cost = amounts.get("operatingProfit", 0)
        if info["segment"] == "headquarters":
            spread("allocatedHeadquarters", cost, headcount)
        elif info["segment"] == "logistics":
            served = {a: revenue[a] for a in destinations.get(address, set()) if a in revenue}
            spread("allocatedLogistics", cost, served if sum(served.values()) > 0 else retail_revenue or revenue)
        else:
            spread("allocatedOther", cost, revenue)
    spread("allocatedHeadquarters", sum(group.get(k, 0) for k in GROUP_STAFF_KEYS), headcount)
    return result


def _overhead_line(info: dict[str, Any]) -> str:
    if info["segment"] == "headquarters":
        return "overheadHeadquarters"
    if info["segment"] == "logistics":
        return "overheadLogistics"
    return "overheadOther"


def statement(db: sqlite3.Connection, granularity: str = "week", periods: int = 8,
              scope: str = "group", allocate_overhead: bool = True) -> dict[str, Any]:
    """P&L par période. scope : "group", "segment:<retail|office|...>" ou "business:<adresse>"."""
    if granularity not in GRANULARITIES:
        raise ValueError(f"granularity must be one of {GRANULARITIES}")
    tables = _tables(db)
    if "hist_daily_finances" not in tables:
        return {"empty": True}
    year_length = days_per_year(db)
    directory = business_directory(db)
    destinations = _warehouse_destinations(db)

    last_day = db.execute("SELECT max(day) FROM hist_daily_finances").fetchone()[0]
    first_day = db.execute("SELECT min(day) FROM hist_daily_finances").fetchone()[0]
    last_period = period_of(last_day, granularity, year_length)
    first_period = max(period_of(first_day, granularity, year_length), last_period - periods + 1)
    keys = list(range(first_period, last_period + 1))
    start_day = period_bounds(first_period, granularity, year_length)[0]

    by_period_business: dict[int, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for row in _all(db, "SELECT * FROM hist_daily_finances WHERE day >= ?", (start_day,)):
        p = period_of(row["day"], granularity, year_length)
        for k, v in _business_amounts(row).items():
            by_period_business[p][row["address"]][k] += v
    by_period_group: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    days_covered: dict[int, set[int]] = defaultdict(set)
    for t in _all(db, "SELECT * FROM hist_daily_totals WHERE day >= ?", (start_day,)):
        p = period_of(t["day"], granularity, year_length)
        days_covered[p].add(t["day"])
        for k, v in _group_amounts(t).items():
            by_period_group[p][k] += v

    if scope == "group":
        selected = None
    elif scope.startswith("segment:"):
        segment = scope.split(":", 1)[1]
        selected = {a for a, info in directory.items() if info["segment"] == segment}
    elif scope.startswith("business:"):
        selected = {scope.split(":", 1)[1]}
    else:
        raise ValueError("scope must be group, segment:<name> or business:<address>")
    profit_scope = selected is None or all(directory.get(a, {}).get("segment") in PROFIT_SEGMENTS for a in selected)

    values: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(keys))
    gaps = []
    for i, p in enumerate(keys):
        businesses = by_period_business.get(p, {})
        group = by_period_group.get(p, {})
        allocation = allocate(businesses, group, directory, destinations) if allocate_overhead else {}
        for address, amounts in businesses.items():
            info = directory.get(address, {"segment": "other", "status": "closed"})
            is_profit_center = info["segment"] in PROFIT_SEGMENTS
            if selected is not None and address not in selected:
                continue
            if is_profit_center or selected is not None:
                for k, v in amounts.items():
                    values[k][i] += v
            else:
                values[_overhead_line(info)][i] += amounts["operatingProfit"]
            for k, v in allocation.get(address, {}).items():
                values[k][i] += v
        if selected is None:
            overhead = sum(values[k][i] for k, _, _ in OVERHEAD_LINES[:3])
            values["businessProfit"][i] = values["operatingProfit"][i] + overhead
            for k, _, _ in GROUP_LINES[:-1]:
                values[k][i] = group.get(k, 0)
            values["netProfit"][i] = values["businessProfit"][i] + sum(group.get(k, 0) for k, _, _ in GROUP_LINES[:-1])
            gaps.append(abs(values["netProfit"][i] - group.get("gameTotalProfit", 0)))
        if profit_scope and allocate_overhead:
            values["profitAfterOverhead"][i] = values["operatingProfit"][i] + sum(
                values[k][i] for k in ("allocatedHeadquarters", "allocatedLogistics", "allocatedOther"))

    layout = list(BUSINESS_LINES)
    if selected is None:
        layout += OVERHEAD_LINES + GROUP_LINES
    if profit_scope and allocate_overhead:
        layout += ALLOCATION_LINES
    lines = [
        {"key": k, "label": label, "kind": kind,
         "values": [round(v, 2) for v in values[k]], "total": round(sum(values[k]), 2)}
        for k, label, kind in layout
    ]
    return {
        "granularity": granularity,
        "scope": scope,
        "allocated": allocate_overhead,
        "periods": [
            {"key": p, "label": f"{granularity.capitalize()} {p}", "firstDay": period_bounds(p, granularity, year_length)[0],
             "lastDay": period_bounds(p, granularity, year_length)[1], "daysCovered": len(days_covered.get(p, ())),
             "complete": len(days_covered.get(p, ())) == period_bounds(p, granularity, year_length)[1] - period_bounds(p, granularity, year_length)[0] + 1}
            for p in keys
        ],
        "lines": lines,
        "reconciliationGap": round(max(gaps), 2) if gaps else None,
        "dataFrom": first_day,
        "dataTo": last_day,
    }


def by_business(db: sqlite3.Connection, first_day: int, last_day: int, allocate_overhead: bool = True) -> list[dict[str, Any]]:
    """P&L de chaque commerce sur [first_day, last_day], avec répartition des frais de structure."""
    directory = business_directory(db)
    destinations = _warehouse_destinations(db)
    per_business: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in _all(db, "SELECT * FROM hist_daily_finances WHERE day BETWEEN ? AND ?", (first_day, last_day)):
        for k, v in _business_amounts(row).items():
            per_business[row["address"]][k] += v
    group: dict[str, float] = defaultdict(float)
    for t in _all(db, "SELECT * FROM hist_daily_totals WHERE day BETWEEN ? AND ?", (first_day, last_day)):
        for k, v in _group_amounts(t).items():
            group[k] += v
    allocation = allocate(per_business, group, directory, destinations) if allocate_overhead else {}
    days = max(1, last_day - first_day + 1)
    total_revenue = sum(a.get("revenue", 0) for a in per_business.values())

    rows = []
    for address in set(per_business) | {a for a, i in directory.items() if i["status"] == "active"}:
        info = directory.get(address, {"name": None, "segment": "other", "typeLabel": None, "status": "closed"})
        amounts = per_business.get(address, {})
        allocated = allocation.get(address, {})
        overhead = sum(allocated.values())
        revenue = amounts.get("revenue", 0)
        operating = amounts.get("operatingProfit", 0)
        rows.append({
            "address": address, "name": info.get("name"), "typeLabel": info.get("typeLabel"),
            "segment": info["segment"], "status": info["status"],
            "costCenter": info["segment"] not in PROFIT_SEGMENTS,
            **{k: round(amounts.get(k, 0), 2) for k, _, _ in BUSINESS_LINES},
            "otherCosts": round(amounts.get("licensingFees", 0) + amounts.get("theft", 0), 2),
            "margin": round(operating / revenue, 4) if revenue else None,
            "grossMarginRate": round(amounts.get("grossMargin", 0) / revenue, 4) if revenue else None,
            "payrollRatio": round(-amounts.get("salaries", 0) / revenue, 4) if revenue else None,
            "revenueShare": round(revenue / total_revenue, 4) if total_revenue else None,
            "allocatedOverhead": round(overhead, 2) if allocated else None,
            "allocatedDetail": {k: round(v, 2) for k, v in allocated.items()} or None,
            "profitAfterOverhead": round(operating + overhead, 2) if allocated else None,
            "profitPerDay": round(operating / days, 2),
        })
    return sorted(rows, key=lambda r: (r["costCenter"], -(r["operatingProfit"] or 0)))
