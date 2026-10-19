"""Lectures pour l'API : chaque fonction prend une connexion SQLite et renvoie des données JSON-compatibles."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import history, insights, pnl

PROFIT_SEGMENTS = pnl.PROFIT_SEGMENTS


def connect_readonly(path) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _all(db: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in db.execute(sql, params)]


def _one(db: sqlite3.Connection, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    row = db.execute(sql, params).fetchone()
    return dict(row) if row else None


def _window(db: sqlite3.Connection, window: int) -> tuple[int, int]:
    last_day = db.execute("SELECT max(day) FROM hist_daily_finances").fetchone()[0]
    return last_day - window + 1, last_day


def _ready(db: sqlite3.Connection) -> dict[str, Any] | None:
    """La source si la base contient des données exploitables, sinon None."""
    tables = _tables(db)
    if "source" not in tables or "hist_daily_finances" not in tables:
        return None
    return _one(db, "SELECT * FROM source")


def status(db: sqlite3.Connection) -> dict[str, Any]:
    tables = _tables(db)
    checks = None
    if "check_biggerambitions" in tables:
        checks = {
            "checkedAt": (_one(db, "SELECT max(checkedAt) AS at FROM check_biggerambitions") or {}).get("at"),
            "byStatus": {r["status"]: r["n"] for r in _all(
                db, "SELECT status, count(*) AS n FROM check_biggerambitions GROUP BY status")},
        }
    return {
        "source": _one(db, "SELECT * FROM source") if "source" in tables else None,
        "history": history.summary(db),
        "checks": checks,
        "hasReference": "ref_items" in tables,
    }


def _business_rows(db: sqlite3.Connection, first_day: int, last_day: int, window: int) -> list[dict[str, Any]]:
    """P&L par commerce sur la fenêtre, avec la période précédente et les infos courantes."""
    current = pnl.by_business(db, first_day, last_day)
    previous = {r["address"]: r for r in pnl.by_business(db, first_day - window, first_day - 1)}
    info = {b["address"]: b for b in _all(db, "SELECT * FROM businesses")}
    rows = []
    for r in current:
        b = info.get(r["address"], {})
        if b.get("segment") == "home":
            continue
        prev = previous.get(r["address"])
        rows.append({
            **r,
            "neighborhood": b.get("neighborhood"),
            "employees": b.get("employees"),
            "satisfaction": b.get("satisfaction") if r["segment"] in PROFIT_SEGMENTS else None,
            "creationDay": b.get("creationDay"),
            "previousOperatingProfit": prev["operatingProfit"] if prev else None,
            "isNew": b.get("creationDay") is not None and b["creationDay"] > first_day - window,
        })
    return rows


def dashboard(db: sqlite3.Connection, window: int = 7) -> dict[str, Any]:
    source = _ready(db)
    if not source:
        return {"source": source, "empty": True}
    first_day, last_day = _window(db, window)
    snapshot = _one(db, "SELECT * FROM snapshots ORDER BY importedAt DESC LIMIT 1") or {}
    totals = _all(db, "SELECT day, totalProfit, totalBusinessProfit FROM hist_daily_totals ORDER BY day")
    current = sum(t["totalProfit"] for t in totals if t["day"] >= first_day)
    previous = sum(t["totalProfit"] for t in totals if first_day - window <= t["day"] < first_day)

    rows = _business_rows(db, first_day, last_day, window)
    profit_centers = [r for r in rows if not r["costCenter"] and r["status"] == "active"]
    cost_centers = [r for r in rows if r["costCenter"] and r["status"] == "active"]
    operating = sum(r["operatingProfit"] for r in profit_centers)
    overhead = sum(r["operatingProfit"] for r in rows if r["costCenter"])

    found = insights.compute(db, window)
    return {
        "source": source,
        "window": {"days": window, "firstDay": first_day, "lastDay": last_day},
        "kpis": {
            "money": source["money"],
            "investments": snapshot.get("investmentBalance"),
            "netLiquid": (source["money"] or 0) + (snapshot.get("investmentBalance") or 0),
            "profitWindow": round(current, 2),
            "profitPreviousWindow": round(previous, 2),
            "operatingProfit": round(operating, 2),
            "overhead": round(overhead, 2),
            "lastDayProfit": totals[-1]["totalProfit"] if totals else None,
            "businesses": len(profit_centers),
            "costCenters": len(cost_centers),
            "employees": source["employees"],
        },
        "dailyProfit": totals,
        "businesses": profit_centers,
        "costCenters": cost_centers,
        "insights": found,  # tous, du plus grave au moins grave : la carte du tableau de bord défile
        "insightCounts": {s: sum(1 for i in found if i["severity"] == s) for s in insights.SEVERITY_RANK},
    }


def business_list(db: sqlite3.Connection, window: int = 7) -> dict[str, Any]:
    source = _ready(db)
    if not source:
        return {"empty": True}
    first_day, last_day = _window(db, window)
    rows = [r for r in _business_rows(db, first_day, last_day, window) if r["status"] == "active"]
    counts: dict[str, dict[str, int]] = {}
    for i in insights.compute(db, window):
        counts.setdefault(i["address"], {}).setdefault(i["severity"], 0)
        counts[i["address"]][i["severity"]] += 1
    for r in rows:
        r["insights"] = counts.get(r["address"], {})
    return {"window": {"days": window, "firstDay": first_day, "lastDay": last_day}, "businesses": rows}


def business_detail(db: sqlite3.Connection, address: str, window: int = 7) -> dict[str, Any] | None:
    source = _ready(db)
    if not source:
        return None
    tables = _tables(db)
    business = _one(db, "SELECT * FROM businesses WHERE address = ?", (address,))
    directory = pnl.business_directory(db)
    if not business and address not in directory:
        return None
    first_day, last_day = _window(db, window)
    rows = {r["address"]: r for r in _business_rows(db, first_day, last_day, window)}
    building = _one(db, "SELECT * FROM ref_buildings WHERE address = ?", (address,)) if "ref_buildings" in tables else None

    daily = _all(db, """SELECT f.day, f.sales, f.resources, f.salaries, f.rent, f.marketing, f.profit,
                               (SELECT max(customers) FROM hist_sales s WHERE s.address = f.address AND s.day = f.day) AS customers
                        FROM hist_daily_finances f WHERE f.address = ? ORDER BY f.day""", (address,))

    days_with_sales = db.execute("SELECT count(DISTINCT day) FROM hist_sales WHERE address = ? AND day >= ?",
                                 (address, first_day)).fetchone()[0] or 1
    products = _all(db, """SELECT item, sum(amountSold) AS units, sum(revenue) AS revenue, sum(wholesaleCost) AS cogs,
                                  sum(margin) AS margin
                           FROM hist_sales WHERE address = ? AND day >= ? GROUP BY item ORDER BY revenue DESC""",
                    (address, first_day))
    prices = {p["item"]: p for p in _all(db, "SELECT * FROM prices WHERE address = ?", (address,))} if "prices" in tables else {}
    stock = {}
    if "inventory" in tables:
        for s in _all(db, "SELECT item, sum(amount) AS amount, sum(stockValue) AS value FROM inventory WHERE address = ? GROUP BY item", (address,)):
            stock[s["item"]] = s
    labels = {}
    if "ref_items" in tables:
        labels = {r["itemName"][3:].split("_", 1)[-1]: r["label"] for r in _all(db, "SELECT itemName, label FROM ref_items")}
    for p in products:
        p["label"] = labels.get(p["item"], p["item"])
        p["unitsPerDay"] = round(p["units"] / days_with_sales, 1)
        p["avgPrice"] = round(p["revenue"] / p["units"], 2) if p["units"] else None
        p["marginRate"] = round(p["margin"] / p["revenue"], 4) if p["revenue"] else None
        price = prices.get(p["item"], {})
        p.update({k: price.get(k) for k in ("price", "ceiling", "headroom", "optimal", "monopoly",
                                            "lowestCompetitor", "lowestCompetitorPrice", "refusalRate", "pricingManager")})
        held = stock.get(p["item"])
        p["stock"] = held["amount"] if held else None
        p["daysOfCover"] = round(held["amount"] / (p["units"] / days_with_sales), 1) if held and p["units"] else None
    sold = {p["item"] for p in products}
    for item, price in prices.items():
        if item not in sold:
            products.append({"item": item, "label": price["itemLabel"], "units": 0, "revenue": 0, "unitsPerDay": 0,
                             "price": price["price"], "ceiling": price["ceiling"], "headroom": price["headroom"],
                             "monopoly": price["monopoly"], "lowestCompetitor": price["lowestCompetitor"],
                             "lowestCompetitorPrice": price["lowestCompetitorPrice"],
                             "stock": stock.get(item, {}).get("amount")})

    staffing = _one(db, "SELECT * FROM staffing WHERE address = ?", (address,)) if "staffing" in tables else None
    staffing_hours = _all(db, "SELECT day, hour, expectedCustomers, staffedStations, neededStations, idleStations, idleWages, short "
                              "FROM staffing_hours WHERE address = ? ORDER BY day, hour", (address,)) if "staffing_hours" in tables else []
    employees = _all(db, "SELECT * FROM employees WHERE address = ? ORDER BY mainSkillValue DESC", (address,)) if "employees" in tables else []
    marketing = _one(db, "SELECT * FROM marketing WHERE address = ?", (address,)) if "marketing" in tables else None
    marketing_options = _all(db, "SELECT * FROM marketing_options WHERE address = ? ORDER BY promotion",
                             (address,)) if "marketing_options" in tables else []
    satisfaction = _all(db, """SELECT day, satisfaction, satCustomerService, satPricing, satCleanliness, satFacility
                               FROM hist_businesses WHERE address = ? ORDER BY day""", (address,)) if "hist_businesses" in tables else []
    suppliers = _all(db, "SELECT * FROM logistics_targets WHERE destinationAddress = ?", (address,)) if "logistics_targets" in tables else []
    served = _all(db, "SELECT * FROM logistics_targets WHERE sourceAddress = ?", (address,)) if "logistics_targets" in tables else []

    return {
        "address": address,
        "business": business or directory.get(address),
        "building": building,
        "window": {"days": window, "firstDay": first_day, "lastDay": last_day},
        "pnl": rows.get(address),
        "daily": daily,
        "products": products,
        "employees": employees,
        "staffing": staffing,
        "staffingHours": staffing_hours,
        "marketing": marketing,
        "marketingOptions": marketing_options,
        "satisfactionHistory": satisfaction,
        "suppliers": suppliers,
        "serves": served,
        "insights": insights.compute(db, window, address),
    }


def pnl_statement(db: sqlite3.Connection, granularity: str, periods: int, scope: str, allocate: bool) -> dict[str, Any]:
    if not _ready(db):
        return {"empty": True}
    return pnl.statement(db, granularity, periods, scope, allocate)


def pnl_by_business(db: sqlite3.Connection, first_day: int | None, last_day: int | None, window: int) -> dict[str, Any]:
    if not _ready(db):
        return {"empty": True}
    if first_day is None or last_day is None:
        first_day, last_day = _window(db, window)
    rows = [r for r in pnl.by_business(db, first_day, last_day) if r["segment"] != "home"]
    return {"firstDay": first_day, "lastDay": last_day, "businesses": rows}


def customers(db: sqlite3.Connection, days: int = 60) -> dict[str, Any]:
    """Clients et CA par jour pour chaque centre de profit actif (historique des ventes)."""
    if not _ready(db) or "hist_sales" not in _tables(db):
        return {"empty": True}
    last = db.execute("SELECT max(day) FROM hist_sales").fetchone()[0]
    first = last - days + 1
    businesses = _all(db, "SELECT address, name, typeLabel, segment, customerCapacity FROM businesses "
                          "WHERE segment IN ('retail', 'office') ORDER BY name")
    rows = _all(db, """SELECT address, day, max(customers) AS customers, sum(revenue) AS revenue
                       FROM hist_sales WHERE day >= ? GROUP BY address, day ORDER BY day""", (first,))
    series: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        series.setdefault(r["address"], []).append(
            {"day": r["day"], "customers": r["customers"], "revenue": round(r["revenue"], 2),
             "revenuePerCustomer": round(r["revenue"] / r["customers"], 2) if r["customers"] else None})
    out = []
    for b in businesses:
        points = series.get(b["address"], [])
        recent = [p["customers"] for p in points[-7:]]
        before = [p["customers"] for p in points[-14:-7]]
        out.append({**b, "series": points,
                    "avg7": round(sum(recent) / len(recent), 1) if recent else None,
                    "avgPrev7": round(sum(before) / len(before), 1) if before else None})
    totals: dict[int, int] = {}
    for r in rows:
        totals[r["day"]] = totals.get(r["day"], 0) + (r["customers"] or 0)
    return {"firstDay": first, "lastDay": last, "businesses": out,
            "total": [{"day": d, "customers": c} for d, c in sorted(totals.items())]}


def recruitment(db: sqlite3.Connection) -> dict[str, Any]:
    """Candidats classés, exigences à corriger chez les employés, salaires comparés au marché, postes à pourvoir."""
    tables = _tables(db)
    if not _ready(db) or "candidates" not in tables:
        return {"empty": True}
    candidates = _all(db, "SELECT * FROM candidates ORDER BY effectiveSkill DESC, wagePerEffectivePoint")
    fits = _all(db, "SELECT * FROM candidate_fits ORDER BY effectiveSkill DESC") if "candidate_fits" in tables else []
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for f in fits:
        by_candidate.setdefault(f["candidateId"], []).append(f)
    for c in candidates:
        c["fitsDetail"] = by_candidate.get(c["id"], [])

    employees = _all(db, """SELECT e.*, b.segment FROM employees e LEFT JOIN businesses b ON b.address = e.address
                            WHERE e.status = 'active'""")
    fixes: dict[tuple[str, str], dict[str, Any]] = {}
    if "employee_demands" in tables:
        for d in _all(db, """SELECT d.*, e.satisfaction, e.satisfactionCap FROM employee_demands d
                             JOIN employees e ON e.id = d.employeeId WHERE d.status = 'missing'"""):
            key = (d["address"], d["fix"])
            entry = fixes.setdefault(key, {"address": d["address"], "business": d["business"], "demand": d["label"],
                                           "fix": d["fix"], "employees": []})
            entry["employees"].append({"name": d["employee"], "satisfaction": d["satisfaction"], "cap": d["satisfactionCap"]})

    openings = []
    for e in _all(db, "SELECT name, business, address, mainSkill, mainSkillValue, beingReplaced FROM employees WHERE status != 'active'"):
        openings.append({"kind": "poached", "business": e["business"], "address": e["address"], "skill": e["mainSkill"],
                         "detail": f"{e['name']} ({e['mainSkill']} {e['mainSkillValue']:.0f}) was poached"
                                   + (" — the headhunter is replacing them" if e["beingReplaced"] else "")})
    if "staffing" in tables:
        for s in _all(db, "SELECT * FROM staffing WHERE understaffedHours >= 5"):
            openings.append({"kind": "understaffed", "business": s["business"], "address": s["address"], "skill": None,
                             "detail": f"{s['understaffedHours']} opening hours a week with more customers than staffed {s['stationKind']}s"})

    expiring = sum(1 for c in candidates if (c["hoursUntilExpiring"] or 999) <= 24)
    return {
        "summary": {
            "candidates": len(candidates), "expiringWithin24h": expiring,
            "employees": len(employees),
            "cappedEmployees": sum(1 for e in employees if (e["satisfactionCap"] or 100) < 100),
            "overpaid": sum(1 for e in employees if (e["wageRatio"] or 1) > 1.05),
            "underpaid": sum(1 for e in employees if (e["wageRatio"] or 1) < 0.85),
        },
        "openings": openings,
        "fixes": sorted(fixes.values(), key=lambda f: -len(f["employees"])),
        "employees": employees,
        "candidates": candidates,
    }


def recommendation_list(db: sqlite3.Connection, window: int = 7) -> dict[str, Any]:
    from . import recommendations

    if not _ready(db):
        return {"empty": True}
    dismissed = {r["key"] for r in _all(db, "SELECT key FROM user_dismissals")} if "user_dismissals" in _tables(db) else set()
    items = recommendations.compute(db, window, dismissed)
    active = [r for r in items if not r["dismissed"]]
    return {
        "window": window,
        "summary": {
            "count": len(active),
            "dismissed": len(items) - len(active),
            "gainHigh": round(sum(r["gainPerDay"] or 0 for r in active if r["confidence"] == "high"), 2),
            "gainMedium": round(sum(r["gainPerDay"] or 0 for r in active if r["confidence"] == "medium"), 2),
            "gainLow": round(sum(r["gainPerDay"] or 0 for r in active if r["confidence"] == "low"), 2),
        },
        "items": items,
    }


def insight_list(db: sqlite3.Connection, window: int = 7) -> list[dict[str, Any]]:
    return insights.compute(db, window) if _ready(db) else []
