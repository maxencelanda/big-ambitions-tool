"""Recommandations : actions concrètes, chiffrées en $ par jour de jeu, classées par gain × confiance.

Chaque recommandation :
    key         identifiant stable (pour l'écarter)
    category    pricing | staffing | employees | markets | stock | competition | expansion | profitability
    business / address
    title, steps (liste d'actions), why (explication chiffrée)
    gainPerDay  gain estimé ($/jour) ; None si non chiffrable
    confidence  high (formule du jeu, peu d'hypothèses) | medium | low (hypothèses fortes)
    effort      low | medium | high
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from typing import Any

from . import insights, market, pnl

CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}
WEEKDAY = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
SAFETY_MARGIN = 1.2  # comme staffing.py


def _all(db: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cursor = db.execute(sql, params)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _reco(key, category, business, title, steps, why, gain, confidence, effort, **evidence) -> dict[str, Any]:
    return {"key": key, "category": category, "address": business.get("address"),
            "business": business.get("name") or business.get("address"), "title": title, "steps": steps, "why": why,
            "gainPerDay": round(gain, 2) if gain is not None else None, "confidence": confidence, "effort": effort,
            "evidence": evidence}


class Data:
    def __init__(self, db: sqlite3.Connection, window: int):
        tables = _tables(db)
        self.db = db
        self.ok = {"businesses", "hist_daily_finances"} <= tables
        if not self.ok:
            return
        last = db.execute("SELECT max(day) FROM hist_daily_finances").fetchone()[0]
        self.window = window
        self.first_day, self.last_day = last - window + 1, last
        self.businesses = {b["address"]: b for b in _all(db, "SELECT * FROM businesses")}
        self.pnl = {r["address"]: r for r in pnl.by_business(db, self.first_day, self.last_day)}
        self.prices = _all(db, "SELECT * FROM prices") if "prices" in tables else []
        self.staffing = {s["address"]: s for s in _all(db, "SELECT * FROM staffing")} if "staffing" in tables else {}
        self.staffing_hours = _all(db, "SELECT * FROM staffing_hours ORDER BY day, hour") if "staffing_hours" in tables else []
        self.marketing = _all(db, "SELECT * FROM marketing") if "marketing" in tables else []
        self.employees = _all(db, "SELECT * FROM employees WHERE status = 'active'") if "employees" in tables else []
        self.demands = _all(db, "SELECT * FROM employee_demands WHERE status = 'missing'") if "employee_demands" in tables else []
        self.market = {(r["item"], r["neighborhood"]): r for r in _all(db, "SELECT * FROM market_prices")} if "market_prices" in tables else {}
        self.sales = market._sales_per_day(db, window) if "hist_sales" in tables else {}
        days = db.execute("SELECT count(DISTINCT day) FROM hist_sales WHERE day >= ?", (self.first_day,)).fetchone()[0] \
            if "hist_sales" in tables else 0
        self.customers = {r["address"]: r["c"] / max(days, 1) for r in _all(db, """
            SELECT address, sum(customers) AS c FROM (SELECT address, day, max(customers) AS customers
            FROM hist_sales WHERE day >= ? GROUP BY address, day) GROUP BY address""", (self.first_day,))} if days else {}

    def per_day(self, address: str, field: str) -> float:
        return (self.pnl.get(address, {}).get(field) or 0) / self.window


# --- prix ----------------------------------------------------------------------

def price_raises(d: Data) -> list[dict]:
    out = []
    for p in d.prices:
        units = d.sales.get((p["address"], p["item"]), {}).get("units", 0)
        if (p["headroom"] or 0) >= 0.01 and units > 0:
            b = {"address": p["address"], "name": p["business"]}
            out.append(_reco(f"price|{p['address']}|{p['item']}", "pricing", b, f"Raise {p['itemLabel']} to ${p['ceiling']:.2f}",
                             [f"Set {p['itemLabel']} at {p['business']} to ${p['ceiling']:.2f} (now ${p['price']:.2f})."],
                             f"Every customer of {p['neighborhood']} accepts up to ${p['ceiling']:.2f} (game formula). "
                             f"{units:.0f} sold per day × ${p['headroom']:.2f}.",
                             p["headroom"] * units, "high", "low", unitsPerDay=round(units, 1)))
    return out


# --- personnel -------------------------------------------------------------------

def _ranges(hours: list[dict]) -> list[str]:
    """« Mon 12–15 h: −2 » pour les heures consécutives avec le même nombre de postes inutiles."""
    out = []
    by_day = defaultdict(list)
    for h in hours:
        if h["idleStations"] > 0:
            by_day[h["day"]].append(h)
    for day, rows in sorted(by_day.items()):
        start = prev = rows[0]
        for h in rows[1:] + [None]:
            if h is None or h["hour"] != prev["hour"] + 1 or h["idleStations"] != start["idleStations"]:
                out.append(f"{WEEKDAY[day]} {start['hour']}–{prev['hour'] + 1} h: {start['idleStations']} fewer")
                start = h
            prev = h or prev
    return out


def idle_shifts(d: Data) -> list[dict]:
    out = []
    by_address = defaultdict(list)
    for h in d.staffing_hours:
        by_address[h["address"]].append(h)
    for address, s in d.staffing.items():
        if (s["idleWagesPerWeek"] or 0) < 200:
            continue
        b = d.businesses.get(address, {"address": address, "name": s["business"]})
        ranges = _ranges(by_address[address])
        label = {"desk": "desks", "hairdresserchair": "hairdresser chairs", "checkoutcounter": "checkouts",
                 "cashregister": "cash registers"}.get(s["stationKind"], "stations")
        steps = [f"Unstaff these {label} (still keeps a 20 % margin over expected customers):"] + ranges[:14]
        if len(ranges) > 14:
            steps.append(f"…and {len(ranges) - 14} more slots (Staffing card on the business page).")
        steps.append("Then let go of the employees who end up with no shifts, or move them where desks are short.")
        out.append(_reco(f"idle|{address}", "staffing", b, f"Cut {s['idleStationHoursPerWeek']} idle {label}-hours a week",
                         steps,
                         f"About {s['avgCustomersPerDay']:.0f} customers a day, each {label[:-1]} serves {s['customersPerStationHour']}/h: "
                         f"{s['idleStationHoursPerWeek']} of {s['staffedStationHoursPerWeek']} staffed hours a week are not needed.",
                         s["idleWagesPerWeek"] / 7, "high", "medium", idleShare=s["idleShare"]))
    return out


# --- marketing -------------------------------------------------------------------

def marketing_mix(d: Data) -> list[dict]:
    """Combinaison de campagnes la plus rentable (marketing.py). Sûr quand la promotion ne baisse pas."""
    out = []
    for m in d.marketing:
        gain = m["gainPerDay"] or 0
        if gain < 25 or m["bestCampaigns"] == m["currentCampaigns"]:
            continue
        b = d.businesses.get(m["address"], {"address": m["address"], "name": m["business"]})
        keeps = m["bestPromotion"] >= m["currentPromotion"]
        steps = [f"Replace “{m['currentCampaigns']}” (${m['currentCost']:,.0f}/day) by “{m['bestCampaigns']}” (${m['bestCost']:,.0f}/day)."]
        if keeps:
            steps.append(f"Promotion stays at {m['bestPromotion']} (now {m['currentPromotion']}): same customers.")
        else:
            steps.append(f"Promotion goes from {m['currentPromotion']} to {m['bestPromotion']}: about "
                         f"{m['currentCustomersPerDay'] - m['bestCustomersPerDay']:.1f} fewer customers a day, worth less than the saving.")
        if m["samePromotionCampaigns"] and m["samePromotionCampaigns"] != m["bestCampaigns"]:
            steps.append(f"Without losing any promotion: “{m['samePromotionCampaigns']}” (${m['samePromotionCost']:,.0f}/day).")
        cap = "staffed desks" if b.get("segment") == "office" else "the customer capacity and service stations"
        why = (f"Promotion = traffic {m['trafficIndex']} + marketing reach × {m['marketingStrength']:g} (neighborhood), capped at 100; "
               f"reach = campaign m² / building m² ({m['sqm']} m²). Customers per hour are then capped by {cap}: "
               f"beyond promotion {m['saturationPromotion']}, extra marketing brings nobody. "
               f"A customer is worth ${m['valuePerCustomer']:,.0f} of gross margin here.")
        out.append(_reco(f"marketing|{m['address']}", "marketing", b,
                         f"Marketing: switch to {m['bestCampaigns'].lower()}" if m["bestCost"] else "Stop marketing",
                         steps, why, gain, "high" if keeps and m["bestCost"] <= m["currentCost"] else "medium", "low",
                         promotion=m["bestPromotion"], cost=m["bestCost"]))
    return out


def demand_fixes(d: Data) -> list[dict]:
    """Exigences non tenues : gain via le service client (compétence × satisfaction) et la satisfaction globale."""
    out = []
    staff_by_address = defaultdict(list)
    for e in d.employees:
        staff_by_address[e["address"]].append(e)
    fixes = defaultdict(list)
    for row in d.demands:
        fixes[row["address"]].append(row)
    for address, rows in fixes.items():
        b = d.businesses.get(address, {"address": address, "name": rows[0]["business"]})
        facing = b.get("segment") in pnl.PROFIT_SEGMENTS
        employees = {r["employeeId"] for r in rows}
        gain = None
        why = "Satisfaction settles at 60 / 80 / 100 depending on the share of demands met."
        if facing and b.get("satisfaction") is not None:
            service = [e for e in staff_by_address[address] if e["mainSkill"] != "cleaning"]
            capped = [e for e in service if e["id"] in employees and e["satisfactionCap"]]
            if service and capped:
                # Hausse moyenne du service client si ces employés montent à 100 de satisfaction.
                delta_service = sum((100 - e["satisfactionCap"]) * (e["mainSkillValue"] or 0) / 100 for e in capped) / len(service)
                delta_overall = delta_service / 4
                multiplier = 1 + (b["satisfaction"] - 50) / 100
                revenue = d.per_day(address, "revenue")
                gain = revenue * (delta_overall / 100) / multiplier
                why += (f" Customer service would gain ≈{delta_service:.1f} points, overall satisfaction ≈{delta_overall:.1f}; "
                        f"the game scales customers (office) or items bought (retail) by 1 + (satisfaction − 50) / 100.")
        steps = [f"{r['employee']}: {r['fix']}." for r in rows]
        out.append(_reco(f"demands|{address}", "employees", b, f"Meet {len(rows)} unmet job demand(s)", steps, why,
                         gain, "medium", "low", employees=sorted({r["employee"] for r in rows})))
    return out


# --- nombre de commerces par marché ---------------------------------------------------

def provider_counts(d: Data) -> list[dict]:
    """Commerces de bureau du même type dans un quartier : leurs clients suivent la demande, qui baisse avec
    chaque fournisseur. Compare la demande cumulée n·d(n) à n − 1 et n + 1."""
    out = []
    groups = defaultdict(list)
    for b in d.businesses.values():
        if b.get("segment") == "office":
            groups[(b["type"], b["neighborhood"])].append(b)
    opportunities = {(o["businessType"], o["neighborhood"]): o for o in market.opportunities(d.db)}
    for (business_type, neighborhood), own in groups.items():
        product = next((p["item"] for p in d.prices if p["address"] == own[0]["address"]), None)
        m = d.market.get((product, neighborhood))
        if not m:
            continue
        n, optimal, impact = len(own), m["optimalProviders"], m["eventDemandImpact"] or 0
        rivals = max(0, (m["providers"] or n) - n)

        def total(k: int) -> float:
            return k * market.demand_with(k + rivals, optimal, impact) if k > 0 else 0.0

        revenue = sum(d.per_day(b["address"], "revenue") for b in own)
        customers = sum(d.customers.get(b["address"], 0) for b in own)
        if not revenue or not customers:
            continue
        revenue_per_customer = revenue / customers
        label = own[0]["typeLabel"]
        staff = [e for e in d.employees if e["address"] in {b["address"] for b in own}]
        desk_staff = [e for e in staff if e["mainSkill"] != "cleaning"]
        desk_wage = sum(e["hourlyWage"] for e in desk_staff) / max(1, len(desk_staff))
        # Coûts fixes d'un commerce de plus, calqués sur les existants : marketing et ménage (par commerce).
        marketing = sum(-d.per_day(b["address"], "marketing") for b in own) / n
        cleaning = sum(e["hourlyWage"] * (e["weeklyHours"] or 0) / 7 for e in staff if e["mainSkill"] == "cleaning") / n

        # Fermer le moins rentable après frais de structure.
        if n >= 2:
            closed = min(own, key=lambda b: d.pnl.get(b["address"], {}).get("profitAfterOverhead") or 0)
            kept = [b for b in own if b is not closed]
            ratio = total(n - 1) / total(n)
            customers_after = customers * ratio
            capacity = sum((d.staffing.get(b["address"], {}).get("staffedStationHoursPerWeek") or 0) / 7 for b in kept)
            extra_hours = max(0.0, customers_after * SAFETY_MARGIN - capacity)
            saved = d.per_day(closed["address"], "salaries") * -1 + d.per_day(closed["address"], "rent") * -1
            lost = revenue * (1 - ratio)
            gain = saved - extra_hours * desk_wage - lost
            if gain > 0:
                out.append(_reco(
                    f"close|{closed['address']}", "markets", closed,
                    f"Run {n - 1} {label}(s) instead of {n} in {neighborhood}",
                    [f"Close {closed['name']} ({closed['address']}).",
                     f"Move ≈{math.ceil(extra_hours / 8)} of its staff to {', '.join(b['name'] for b in kept)} "
                     f"to add ≈{extra_hours:.0f} desk-hours a day." if extra_hours else "The remaining desks can absorb its customers.",
                     "Re-check in a few days: customers should move to the remaining business(es)."],
                    f"Optimal providers {optimal}, rivals {rivals}. Combined demand {total(n):.0f} with {n} vs "
                    f"{total(n - 1):.0f} with {n - 1}: office customers follow demand, so the market keeps "
                    f"{ratio:.0%} of its customers ({customers:.0f} → {customers_after:.0f}/day). Saves "
                    f"${saved:,.0f}/day of rent and salaries, minus ${extra_hours * desk_wage:,.0f} of extra desk hours"
                    + (f" and ${lost:,.0f} of lost revenue." if lost >= 1 else "."),
                    gain, "medium", "high", demandNow=total(n), demandAfter=total(n - 1)))

        # Ouvrir un commerce de plus (avec le même marketing et le même ménage que les existants).
        ratio_up = total(n + 1) / total(n)
        if ratio_up > 1.05:
            extra_customers = customers * (ratio_up - 1)
            opp = opportunities.get((business_type, neighborhood), {})
            space = (opp.get("bestSpaces") or [None])[0]
            rent = (space or {}).get("rent") or 0
            staff_cost = extra_customers * SAFETY_MARGIN * desk_wage
            costs = staff_cost + rent + marketing + cleaning
            gain = extra_customers * revenue_per_customer - costs
            if gain > 0:
                note = (f" With {n} you are at the worst point: {n - 1} or {n + 1} both do better."
                        if n >= 2 and total(n - 1) >= total(n) else "")
                out.append(_reco(
                    f"open|{business_type}|{neighborhood}", "markets", {"address": None, "name": f"New {label} in {neighborhood}"},
                    f"Open one more {label} in {neighborhood}",
                    [f"Rent {space['address']} (traffic {space['traffic']}, ≈${rent:,.0f}/day)." if space
                     else "No free building of the right type right now: watch the Market page.",
                     f"Staff ≈{math.ceil(extra_customers * SAFETY_MARGIN / 8)} desks for ≈{extra_customers:.0f} extra customers a day.",
                     f"Run the same marketing as your other {label}s (≈${marketing:,.0f}/day) so its promotion matches.",
                     "Furniture and setup are one-off costs not counted here."],
                    f"Office customers = building × promotion × satisfaction × demand, with no shared pool. With {n + 1} businesses "
                    f"the combined demand goes from {total(n):.0f} to {total(n + 1):.0f} (demand never falls below ≈30 per business): "
                    f"≈{extra_customers:.0f} more customers a day at ${revenue_per_customer:,.0f} each, minus desks "
                    f"(${staff_cost:,.0f}), rent (${rent:,.0f}), marketing (${marketing:,.0f}) and cleaning (${cleaning:,.0f}).{note}",
                    gain, "low", "high", demandNow=total(n), demandAfter=total(n + 1)))
    return out


# --- monopoles -------------------------------------------------------------------------

def monopoly_targets(d: Data) -> list[dict]:
    """Produits où 1 ou 2 commerces de rivaux empêchent le monopole (+30 % du prix de base au plafond)."""
    out = []
    rivals = defaultdict(list)
    for c in _all(d.db, "SELECT * FROM competitor_prices WHERE rivalId IS NOT NULL"):
        rivals[(c["item"], c["neighborhood"])].append(c)
    by_business = defaultdict(list)
    for p in d.prices:
        units = d.sales.get((p["address"], p["item"]), {}).get("units", 0)
        shops = rivals.get((p["item"], p["neighborhood"]), [])
        if not p["monopoly"] and units > 0 and 0 < len(shops) <= 2:
            by_business[p["address"]].append((p, units, shops))
    for address, products in by_business.items():
        b = d.businesses.get(address, {"address": address, "name": products[0][0]["business"]})
        gain = sum(p["defaultPrice"] * 0.3 * units for p, units, _ in products)
        targets: dict[str, dict] = {}
        for p, _, shops in products:
            for s in shops:
                t = targets.setdefault(s["competitorAddress"], {"shop": s, "items": []})
                t["items"].append(f"{p['itemLabel']} at ${s['competitorPrice']:.2f}")
        steps = [f"{t['shop']['competitor']} ({t['shop']['rival']}, {address_}) sells {', '.join(t['items'])}."
                 for address_, t in targets.items()]
        steps.append("Each of these shops must stop selling the product in the neighborhood: buy the business out, "
                     "or beat its owner (rival app).")
        out.append(_reco(f"monopoly|{address}", "competition", b,
                         f"Win a monopoly on {len(products)} product(s)", steps,
                         "A monopoly needs no rival-owned shop stocking the product in the neighborhood; independent shops "
                         "do not count. It adds 30 % of the base price to the ceiling: "
                         + ", ".join(f"{p['itemLabel']} +${p['defaultPrice'] * 0.3:.2f} × {units:.0f}/day" for p, units, _ in products[:5]) + ".",
                         gain, "low", "high", targets=list(targets)))

    # Par rival : ce que rapporterait sa défaite, sur les produits où il est le seul obstacle.
    by_rival: dict[str, dict] = {}
    for address, products in by_business.items():
        for p, units, shops in products:
            owners = {s["rivalId"] for s in shops}
            if len(owners) == 1:
                rival = by_rival.setdefault(shops[0]["rivalId"], {"name": shops[0]["rival"], "gain": 0.0, "lines": []})
                rival["gain"] += p["defaultPrice"] * 0.3 * units
                rival["lines"].append(f"{p['itemLabel']} at {p['business']} (+${p['defaultPrice'] * 0.3 * units:,.0f}/day)")
    for rival_id, r in by_rival.items():
        if len(r["lines"]) < 2:
            continue
        out.append(_reco(f"rival|{rival_id}", "competition", {"address": None, "name": r["name"]},
                         f"Defeating {r['name']} would unlock {len(r['lines'])} monopolies",
                         [f"{line}" for line in r["lines"][:8]] + ["See Market → Rival activity for this rival's businesses."],
                         f"On these products every blocking shop belongs to {r['name']}: once their shops stop selling them, "
                         "you get the monopoly bonus (+30 % of the base price on the ceiling).",
                         r["gain"], "low", "high", rivalId=rival_id))
    return out


# --- reprises des points d'attention ------------------------------------------------

INSIGHT_CATEGORIES = {
    "stock": ("stock", "medium", "low"),
    "competition": ("competition", "low", "high"),
}


def from_insights(db: sqlite3.Connection, window: int) -> list[dict]:
    out = []
    for i in insights.compute(db, window):
        within_reach = i["title"].startswith("Monopoly within reach")  # traité par monopoly_targets
        if i["category"] == "stock" or (i["category"] == "competition" and i["severity"] in ("info", "medium")
                                        and i["impactPerDay"] and not within_reach):
            category, confidence, effort = INSIGHT_CATEGORIES[i["category"]]
            b = {"address": i["address"], "name": i["business"]}
            out.append(_reco(f"insight|{i['category']}|{i['address']}|{i['title']}", category, b, i["title"],
                             [i["action"]] if i["action"] else [], i["detail"], i["impactPerDay"], confidence, effort))
        elif i["category"] == "profitability" and i["title"] in ("Losing money", "Does not cover its share of overhead"):
            b = {"address": i["address"], "name": i["business"]}
            out.append(_reco(f"insight|loss|{i['address']}", "profitability", b, f"{i['business']}: {i['title'].lower()}",
                             [i["action"]] if i["action"] else [], i["detail"], i["impactPerDay"], "medium", "high"))
    return out


def expansion(db: sqlite3.Connection, limit: int = 3) -> list[dict]:
    out = []
    for o in [o for o in market.opportunities(db) if o["freeBuildings"] and not o["playerBusinesses"]][:limit]:
        space = o["bestSpaces"][0]
        out.append(_reco(f"expand|{o['businessType']}|{o['neighborhood']}", "expansion",
                         {"address": None, "name": f"{o['label']} in {o['neighborhoodLabel']}"},
                         f"Consider a {o['label']} in {o['neighborhoodLabel']} (score {o['score']:.0f})",
                         [f"Best space: {space['address']} (traffic {space['traffic']}, ≈${space['rent'] or 0:,.0f}/day).",
                          "See Market → Opportunities for the full breakdown."],
                         "Strengths: " + "; ".join(o["pros"]) + (". Watch: " + "; ".join(o["cons"]) if o["cons"] else "."),
                         None, "low", "high", score=o["score"]))
    return out


def compute(db: sqlite3.Connection, window: int = 7, dismissed: set[str] | None = None) -> list[dict[str, Any]]:
    d = Data(db, window)
    if not d.ok:
        return []
    items = (price_raises(d) + idle_shifts(d) + marketing_mix(d) + demand_fixes(d) + provider_counts(d) + monopoly_targets(d)
             + from_insights(db, window) + expansion(db))
    for r in items:
        r["dismissed"] = r["key"] in (dismissed or set())
        r["rank"] = (r["gainPerDay"] or 0) * CONFIDENCE_WEIGHT[r["confidence"]]
    return sorted(items, key=lambda r: (r["gainPerDay"] is None, -r["rank"]))
