"""Points d'attention : règles qui croisent finances, prix, concurrence, stock, satisfaction et personnel.

Chaque point est un dict :
    severity    high | medium | low | info | positive
    category    profitability | costs | pricing | competition | stock | satisfaction | staff
    title       constat court ; detail : explication avec les chiffres
    action      ce qu'il faudrait faire
    impactPerDay  gain (ou perte évitée) estimé en $ par jour de jeu, si on sait l'estimer
    evidence    les valeurs qui justifient le point
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from statistics import median
from typing import Any

from . import pnl

PROFIT_SEGMENTS = pnl.PROFIT_SEGMENTS
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3, "positive": 4}

PAYROLL_MEDIUM, PAYROLL_HIGH = 0.5, 0.8
PROFIT_DROP = 0.25
SATISFACTION_TARGET = 90
STOCK_DAYS_HIGH, STOCK_DAYS_MEDIUM = 1.0, 2.0
HEADROOM_MIN = 0.02
REFUSAL_RATE, REFUSAL_MIN_ORDERS = 0.10, 10
EMPLOYEE_SATISFACTION_HIGH, EMPLOYEE_SATISFACTION_MEDIUM = 60, 75
# Compétence qui alimente la satisfaction « service client » selon le type de commerce.
SERVICE_SKILL_FALLBACK = "customerservice"


def _all(db: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cursor = db.execute(sql, params)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _skills(text: str | None) -> dict[str, float]:
    out = {}
    for part in (text or "").split(", "):
        if "=" in part:
            name, value = part.split("=", 1)
            out[name] = float(value)
    return out


def _insight(severity, category, business, title, detail, action=None, impact=None, **evidence) -> dict[str, Any]:
    return {
        "severity": severity, "category": category,
        "address": business.get("address"), "business": business.get("name") or business.get("address"),
        "title": title, "detail": detail, "action": action,
        "impactPerDay": round(impact, 2) if impact is not None else None,
        "evidence": evidence,
    }


class Context:
    """Données chargées une fois pour toutes les règles."""

    def __init__(self, db: sqlite3.Connection, window: int):
        tables = _tables(db)
        self.ready = {"businesses", "hist_daily_finances"} <= tables
        if not self.ready:
            return
        self.source = _all(db, "SELECT * FROM source")[0]
        self.last_day = db.execute("SELECT max(day) FROM hist_daily_finances").fetchone()[0]
        self.first_day = self.last_day - window + 1
        self.window = window
        self.businesses = _all(db, "SELECT * FROM businesses")
        current = {r["address"]: r for r in pnl.by_business(db, self.first_day, self.last_day)}
        previous = {r["address"]: r for r in pnl.by_business(db, self.first_day - window, self.first_day - 1)}
        self.pnl, self.previous = current, previous
        self.prices = _all(db, "SELECT * FROM prices") if "prices" in tables else []
        everyone = _all(db, "SELECT * FROM employees") if "employees" in tables else []
        # Les employés débauchés restent dans la sauvegarde le temps d'être remplacés : on les met à part.
        self.employees = [e for e in everyone if e.get("status", "active") == "active"]
        self.departed = [e for e in everyone if e.get("status", "active") != "active"]
        self.inventory = _all(db, "SELECT * FROM inventory") if "inventory" in tables else []
        self.imports = _all(db, "SELECT * FROM import_partnerships") if "import_partnerships" in tables else []
        self.staffing = _all(db, "SELECT * FROM staffing") if "staffing" in tables else []
        self.unmet_demands = _all(db, """SELECT d.*, e.satisfaction, e.satisfactionCap, e.mainSkill
                                         FROM employee_demands d JOIN employees e ON e.id = d.employeeId
                                         WHERE d.status = 'missing'""") \
            if {"employee_demands", "employees"} <= tables else []
        self.market = {(r["item"], r["neighborhood"]): r for r in _all(db, "SELECT * FROM market_prices")} if "market_prices" in tables else {}
        self.events = _all(db, "SELECT * FROM market_events WHERE active") if "market_events" in tables else []
        self.competitors = _all(db, """SELECT c.*, b.creationDay FROM competitor_prices c
                                       LEFT JOIN city_buildings b ON b.address = c.competitorAddress""") \
            if {"competitor_prices", "city_buildings"} <= tables else []
        self.monopoly_before: dict[tuple[str, str], int] = {}
        if "hist_market" in tables:
            days = [r[0] for r in db.execute("SELECT DISTINCT day FROM hist_market ORDER BY day DESC LIMIT 2")]
            if len(days) == 2:
                self.monopoly_before = {(r["item"], r["neighborhood"]): r["monopoly"] for r in _all(
                    db, "SELECT item, neighborhood, monopoly FROM hist_market WHERE day = ?", (days[1],))}
        items = _all(db, "SELECT itemName, label, wholesalePrice FROM ref_items") if "ref_items" in tables else []
        self.physical = {i["itemName"][3:].split("_", 1)[-1] for i in items if (i["wholesalePrice"] or 0) > 0}
        self.item_label = {i["itemName"][3:].split("_", 1)[-1]: i["label"] for i in items}
        self.business_types = {t["label"]: t for t in _all(db, "SELECT * FROM ref_business_types")} if "ref_business_types" in tables else {}
        self.targets = _all(db, "SELECT * FROM logistics_targets") if "logistics_targets" in tables else []
        # Ventes moyennes par jour (commerce, produit) sur la fenêtre
        self.daily_sales: dict[tuple[str, str], dict[str, float]] = {}
        if "hist_sales" in tables:
            days = db.execute("SELECT count(DISTINCT day) FROM hist_sales WHERE day >= ?", (self.first_day,)).fetchone()[0] or 1
            for r in _all(db, """SELECT address, item, sum(amountSold) AS units, sum(revenue) AS revenue
                                 FROM hist_sales WHERE day >= ? GROUP BY address, item""", (self.first_day,)):
                self.daily_sales[(r["address"], r["item"])] = {"units": r["units"] / days, "revenue": r["revenue"] / days}

    def label(self, item: str) -> str:
        return self.item_label.get(item, item)


# --- règles ------------------------------------------------------------------

def profitability(ctx: Context) -> list[dict]:
    out = []
    payrolls = [r["payrollRatio"] for r in ctx.pnl.values() if r["segment"] in PROFIT_SEGMENTS and r["payrollRatio"]]
    payroll_median = median(payrolls) if payrolls else None
    for b in ctx.businesses:
        if b["segment"] not in PROFIT_SEGMENTS:
            continue
        cur, prev = ctx.pnl.get(b["address"]), ctx.previous.get(b["address"])
        if not cur or not cur["revenue"]:
            continue
        is_new = b["creationDay"] is not None and b["creationDay"] > ctx.first_day - ctx.window
        per_day = cur["operatingProfit"] / ctx.window
        if cur["operatingProfit"] < 0:
            out.append(_insight("high", "profitability", b, "Losing money",
                                f"Operating loss of {cur['operatingProfit']:,.0f} $ over the last {ctx.window} days "
                                f"({per_day:,.0f} $/day) on {cur['revenue']:,.0f} $ of revenue.",
                                "Check payroll and prices below; consider shorter opening hours or closing.",
                                -per_day, operatingProfit=cur["operatingProfit"], revenue=cur["revenue"]))
        elif cur["profitAfterOverhead"] is not None and cur["profitAfterOverhead"] < 0:
            out.append(_insight("medium", "profitability", b, "Does not cover its share of overhead",
                                f"Operating profit {cur['operatingProfit']:,.0f} $ but {cur['allocatedOverhead']:,.0f} $ of "
                                f"headquarters/warehouse costs are allocated to it.",
                                "Grow revenue or reduce the overhead it consumes (staff managed by HQ, deliveries).",
                                -cur["profitAfterOverhead"] / ctx.window,
                                operatingProfit=cur["operatingProfit"], allocatedOverhead=cur["allocatedOverhead"]))
        if not is_new and prev and prev["operatingProfit"] > 0 and cur["operatingProfit"] < prev["operatingProfit"] * (1 - PROFIT_DROP):
            drop = cur["operatingProfit"] - prev["operatingProfit"]
            out.append(_insight("medium", "profitability", b, f"Profit down {-drop / prev['operatingProfit']:.0%}",
                                f"{cur['operatingProfit']:,.0f} $ over the last {ctx.window} days vs {prev['operatingProfit']:,.0f} $ before "
                                f"(revenue {cur['revenue']:,.0f} $ vs {prev['revenue']:,.0f} $).",
                                "Look at competition, stock-outs and price refusals for this business.",
                                -drop / ctx.window, current=cur["operatingProfit"], previous=prev["operatingProfit"]))
        ratio = cur["payrollRatio"]
        if ratio and ratio > PAYROLL_MEDIUM:
            out.append(_insight("high" if ratio > PAYROLL_HIGH else "medium", "costs", b, f"Salaries are {ratio:.0%} of revenue",
                                f"{-cur['salaries']:,.0f} $ of salaries for {cur['revenue']:,.0f} $ of revenue"
                                + (f" (median of your businesses: {payroll_median:.0%})." if payroll_median else "."),
                                f"Reduce hours or headcount ({b['employees']} employees), or raise revenue per employee.",
                                None, payrollRatio=ratio, medianPayrollRatio=payroll_median, employees=b["employees"]))
        if is_new:
            out.append(_insight("info", "profitability", b, "New business, still ramping up",
                                f"Opened on day {b['creationDay']}; comparisons with the previous period are not meaningful yet.",
                                None, None, creationDay=b["creationDay"]))
    return out


def satisfaction(ctx: Context) -> list[dict]:
    out = []
    by_address = defaultdict(list)
    for e in ctx.employees:
        by_address[e["address"]].append(e)
    for b in ctx.businesses:
        if b["segment"] not in PROFIT_SEGMENTS or b["satisfaction"] is None:
            continue
        parts = {"customer service": b["satCustomerService"], "pricing": b["satPricing"],
                 "cleanliness": b["satCleanliness"], "facility": b["satFacility"]}
        for part, value in parts.items():
            if value is None or value >= SATISFACTION_TARGET:
                continue
            severity = "medium" if value < 80 else "low"
            staff = by_address.get(b["address"], [])
            if part == "customer service":
                # Le jeu note chaque client servi : compétence de l'employé × (sa satisfaction / 100).
                skill_name = (ctx.business_types.get(b["typeLabel"], {}).get("primarySkills") or "").split(", ")[0]
                skill = skill_name[3:].split("_", 1)[-1] if skill_name else SERVICE_SKILL_FALLBACK
                scored = sorted(
                    ((e["name"], _skills(e["skills"])[skill], e["satisfaction"] or 0) for e in staff
                     if skill in _skills(e["skills"])),
                    key=lambda x: x[1] * x[2] / 100)[:3]
                detail = (f"Customer service is {value}. Each served customer scores the employee's {skill} skill × "
                          "their satisfaction"
                          + (": lowest are " + ", ".join(f"{n} ({s:.0f} skill × {sat:.0f}% = {s * sat / 100:.0f})"
                                                         for n, s, sat in scored) + "." if scored else "."))
                # Compétence déjà élevée : c'est la satisfaction des employés qui limite la note.
                satisfaction_bound = bool(scored) and all(s >= 90 for _, s, _ in scored)
                action = ("Their skill is already high: raise their satisfaction (job demands, bonus, health insurance)."
                          if satisfaction_bound else "Train the weakest employees (HR manager training target) or replace them.")
                out.append(_insight(severity, "satisfaction", b, f"Customer service at {value}", detail, action, None,
                                    value=value, skill=skill,
                                    weakest=[{"name": n, "skill": s, "satisfaction": sat} for n, s, sat in scored]))
            elif part == "cleanliness":
                cleaners = [e["name"] for e in staff if "cleaning" in _skills(e["skills"]) and e["mainSkill"] == "cleaning"]
                out.append(_insight(severity, "satisfaction", b, f"Cleanliness at {value}",
                                    f"Cleanliness is {value}; {len(cleaners)} dedicated cleaner(s) assigned.",
                                    "Add cleaning shifts or a better cleaner.", None, value=value, cleaners=cleaners))
            elif part == "facility":
                out.append(_insight(severity, "satisfaction", b, f"Facility score at {value}",
                                    f"Facility is {value}: some customer demands (music, decoration, seating, toilet…) are not met.",
                                    "Check the business type's customer demands and add the missing furniture.", None, value=value))
            else:
                out.append(_insight(severity, "satisfaction", b, f"Price satisfaction at {value}",
                                    f"Only {value}% of yesterday's items were sold at a price customers accepted.",
                                    "See the price refusal points for this business.", None, value=value))
    return out


def pricing(ctx: Context) -> list[dict]:
    out = []
    for p in ctx.prices:
        b = {"address": p["address"], "name": p["business"]}
        sales = ctx.daily_sales.get((p["address"], p["item"]), {"units": 0, "revenue": 0})
        units = sales["units"]
        label = p["itemLabel"]
        if p["headroom"] is not None and p["headroom"] < -0.005:
            out.append(_insight("high", "pricing", b, f"{label} priced above the ceiling",
                                f"{p['price']} $ while customers accept at most {p['ceiling']} $ in {p['neighborhood']}.",
                                f"Lower {label} to {p['ceiling']} $.", sales["revenue"] * (p["refusalRate"] or 0.5),
                                price=p["price"], ceiling=p["ceiling"]))
        elif p["ceiling"] and units > 0 and p["headroom"] > p["ceiling"] * HEADROOM_MIN:
            gain = p["headroom"] * units
            out.append(_insight("medium" if gain >= 100 else "low", "pricing", b, f"{label} could cost {p['headroom']:.2f} $ more",
                                f"Sold at {p['price']} $ ({units:.0f}/day) but the acceptance ceiling is {p['ceiling']} $"
                                + (" — the pricing manager is not capturing it all." if p["pricingManager"] else "."),
                                f"Raise {label} to {p['ceiling']} $.", gain,
                                price=p["price"], ceiling=p["ceiling"], unitsPerDay=round(units, 1)))
        if p["refusalRate"] is not None and p["refusalRate"] >= REFUSAL_RATE and p["ordersSampled"] >= REFUSAL_MIN_ORDERS:
            out.append(_insight("medium", "pricing", b, f"{p['refusalRate']:.0%} refuse the price of {label}",
                                f"{p['priceRefused']} of {p['ordersSampled']} recent orders refused {label} at {p['price']} $. "
                                "Customers judge prices against the ceiling of their home neighborhood, which can be lower than this one.",
                                f"Test a lower price for {label}, or accept the refusals if the margin is better.",
                                None, refusalRate=p["refusalRate"], orders=p["ordersSampled"]))
        default_ceiling = p["optimal"]
        if (not p["monopoly"] and p["lowestCompetitorPrice"] is not None and p["lowestCompetitorPrice"] < p["defaultPrice"]
                and units > 0 and default_ceiling > p["ceiling"] + 0.01):
            gain = (default_ceiling - p["ceiling"]) * units
            out.append(_insight("medium" if gain >= 200 else "low", "competition", b, f"{p['lowestCompetitor']} caps your {label} price",
                                f"They sell {label} at {p['lowestCompetitorPrice']} $ (below the {p['defaultPrice']} $ base price), "
                                f"which lowers the whole neighborhood's ceiling to {p['ceiling']} $ instead of {default_ceiling} $.",
                                "Out-compete them (monopoly gives +30 % on top) or move this product's focus elsewhere.", gain,
                                competitor=p["lowestCompetitor"], competitorPrice=p["lowestCompetitorPrice"],
                                ceiling=p["ceiling"], ceilingWithoutCompetitor=default_ceiling, unitsPerDay=round(units, 1)))
        if p["monopoly"] and units > 0:
            uplift = p["defaultPrice"] * 0.3 * units
            out.append(_insight("positive", "competition", b, f"Monopoly on {label}",
                                f"Monopoly in {p['neighborhood']} raises the ceiling by 30 % of the base price "
                                f"(+{p['defaultPrice'] * 0.3:.2f} $/unit, about {uplift:,.0f} $/day).",
                                "Keep at least the current supply so rivals cannot come back.", uplift,
                                uplift=uplift, unitsPerDay=round(units, 1)))
    return out


def stock(ctx: Context) -> list[dict]:
    """Ruptures de stock, à deux niveaux.

    Un magasin livré par un manager logistique est réapprovisionné jusqu'à son objectif : son risque
    n'est pas son stock du moment, mais un objectif inférieur à une journée de ventes, ou un entrepôt
    qui n'a plus de quoi livrer (compte tenu des imports déjà prévus). Un magasin sans manager
    logistique est jugé sur son propre stock.
    """
    out = []
    held = defaultdict(float)
    for row in ctx.inventory:
        held[(row["address"], row["item"])] += row["amount"] or 0
    names = {b["address"]: b for b in ctx.businesses}
    targets = {(t["destinationAddress"], t["item"]): t for t in ctx.targets}
    # Demande servie par chaque entrepôt : somme des ventes des magasins qu'il livre.
    warehouse_demand: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"units": 0.0, "revenue": 0.0})
    warehouse_clients: dict[tuple[str, str], list[str]] = defaultdict(list)

    for (address, item), sales in ctx.daily_sales.items():
        b = names.get(address)
        if not b or b["segment"] not in PROFIT_SEGMENTS or item not in ctx.physical or sales["units"] <= 0:
            continue
        label = ctx.label(item)
        amount = held.get((address, item), 0)
        target = targets.get((address, item))
        if target:
            key = (target["sourceAddress"], item)
            warehouse_demand[key]["units"] += sales["units"]
            warehouse_demand[key]["revenue"] += sales["revenue"]
            warehouse_clients[key].append(b["name"] or address)
            if target["targetAmount"] < sales["units"]:
                short = 1 - target["targetAmount"] / sales["units"]
                out.append(_insight("medium", "stock", b, f"{label}: logistics target below one day of sales",
                                    f"The logistics target is {target['targetAmount']} but {sales['units']:.0f} are sold per day: "
                                    f"the shelves run empty between deliveries ({amount:.0f} in store now).",
                                    f"Raise the {label} target to at least {sales['units'] * 1.5:.0f}.",
                                    sales["revenue"] * short, target=target["targetAmount"], unitsPerDay=round(sales["units"], 1)))
            continue
        cover = amount / sales["units"]
        if cover >= STOCK_DAYS_MEDIUM:
            continue
        out.append(_insight("high" if cover < STOCK_DAYS_HIGH else "medium", "stock", b,
                            f"{label}: {'out of stock' if amount == 0 else f'{cover:.1f} days of stock'}",
                            f"{amount:.0f} in stock for {sales['units']:.0f} sold per day; no logistics manager delivers it.",
                            f"Order {label} or add it to a logistics manager plan.",
                            sales["revenue"] if amount == 0 else sales["revenue"] * max(0.0, 1 - cover),
                            stock=amount, unitsPerDay=round(sales["units"], 1), daysOfCover=round(cover, 2)))

    for (warehouse, item), demand in warehouse_demand.items():
        stock_left = held.get((warehouse, item), 0)
        cover = stock_left / demand["units"]
        incoming = [i for i in ctx.imports if i["warehouse"] == warehouse and i["item"] == item and (i["amountPerDelivery"] or 0) > 0]
        arrives_in = min((i["nextDeliveryDay"] - ctx.source["day"] for i in incoming), default=None)
        if cover >= STOCK_DAYS_MEDIUM or (arrives_in is not None and arrives_in <= cover):
            continue
        label = ctx.label(item)
        w = names.get(warehouse, {"address": warehouse, "name": warehouse})
        clients = ", ".join(warehouse_clients[(warehouse, item)])
        detail = (f"{stock_left:.0f} {label} left for {demand['units']:.0f} delivered per day to {clients} ({cover:.1f} days).")
        if incoming:
            detail += f" Next import of {sum(i['amountPerDelivery'] for i in incoming):.0f} arrives in {arrives_in} day(s): too late."
        out.append(_insight("high" if cover < STOCK_DAYS_HIGH else "medium", "stock", w, f"Warehouse low on {label}",
                            detail, "Bring the next import forward, raise the import quantity or buy at a wholesaler.",
                            demand["revenue"] * max(0.0, 1 - cover / max(arrives_in or 1, 1)),
                            stock=stock_left, unitsPerDay=round(demand["units"], 1), daysOfCover=round(cover, 2)))
    return out


def staff(ctx: Context) -> list[dict]:
    out = []
    by_address = defaultdict(list)
    for e in ctx.employees:
        if e["address"]:
            by_address[e["address"]].append(e)
    names = {b["address"]: b for b in ctx.businesses}
    for address, employees in by_address.items():
        b = names.get(address, {"address": address, "name": address})
        unhappy = sorted((e for e in employees if (e["satisfaction"] or 100) < EMPLOYEE_SATISFACTION_MEDIUM or e["isComplaining"]),
                         key=lambda e: e["satisfaction"] or 0)
        if unhappy:
            worst = unhappy[0]["satisfaction"] or 0
            out.append(_insight("high" if worst < EMPLOYEE_SATISFACTION_HIGH else "medium", "staff", b,
                                f"{len(unhappy)} unhappy employee(s)",
                                "; ".join(f"{e['name']} ({e['satisfaction']:.0f}{', complaining' if e['isComplaining'] else ''}"
                                          + (f"; wants: {e['demands']}" if e["demands"] else "") + ")"
                                          for e in unhappy[:4])
                                + (". Unhappy employees also lower customer service (skill × satisfaction)."
                                   if b.get("segment") in PROFIT_SEGMENTS else "."),
                                "Fulfil their job demands (hours, days, equipment, health insurance) or give a bonus before they quit.",
                                None, employees=[e["name"] for e in unhappy]))
        absent = [e["name"] for e in employees if e["isAbsent"]]
        if absent:
            out.append(_insight("low", "staff", b, f"{len(absent)} employee(s) absent", ", ".join(absent),
                                "Check that absences are covered (HR manager replacement).", None, employees=absent))
    for e in ctx.departed:
        b = names.get(e["address"], {"address": e["address"], "name": e["address"] or "Unassigned staff"})
        out.append(_insight("low" if e.get("beingReplaced") else "medium", "staff", b, f"{e['name']} was poached by a rival",
                            f"{e['name']} ({e['mainSkill']} {e['mainSkillValue']:.0f}) left on day {e['lastWorkedDay']}"
                            + ("; the headhunter is replacing them." if e.get("beingReplaced") else "."),
                            None if e.get("beingReplaced") else "Hire a replacement: their shifts are uncovered.",
                            None, employee=e["name"]))
    return out


def job_demands(ctx: Context) -> list[dict]:
    """Exigences d'emploi non tenues, regroupées par commerce et par correction.

    La satisfaction tend vers 60 / 80 / 100 selon la part d'exigences tenues, et le service client
    vaut compétence × satisfaction : chaque exigence corrigée peut rendre jusqu'à 20 points.
    """
    out = []
    names = {b["address"]: b for b in ctx.businesses}
    by_business: dict[str, list[dict]] = defaultdict(list)
    for d in ctx.unmet_demands:
        by_business[d["address"]].append(d)
    for address_, rows in by_business.items():
        b = names.get(address_, {"address": address_, "name": rows[0]["business"], "segment": None})
        facing = b.get("segment") in PROFIT_SEGMENTS
        employees = sorted({r["employee"] for r in rows})
        fixes = "; ".join(f"{r['employee']} ({r['satisfactionCap']}): {r['fix']}" for r in rows[:6])
        out.append(_insight(
            "medium" if facing else "low", "staff", b,
            f"{len(employees)} employee(s) held below 100 satisfaction by unmet demands",
            f"{fixes}{'…' if len(rows) > 6 else ''}. Satisfaction settles at 60, 80 or 100 depending on the share "
            "of demands met" + (", and customer service counts skill × satisfaction." if facing else "."),
            "Apply these fixes (Recruitment page lists them all).", None, employees=employees))
    return out


IDLE_SHARE_MIN, IDLE_SHARE_HIGH = 0.25, 0.5
IDLE_WAGES_MIN, IDLE_WAGES_MEDIUM = 1000, 3000  # $ par semaine
STATION_LABEL = {"desk": "desks", "hairdresserchair": "hairdresser chairs", "checkoutcounter": "checkouts",
                 "cashregister": "cash registers"}


def overstaffing(ctx: Context) -> list[dict]:
    """Postes de service planifiés que les clients ne remplissent pas (voir staffing.py)."""
    out = []
    names = {b["address"]: b for b in ctx.businesses}
    for s in ctx.staffing:
        b = names.get(s["address"], {"address": s["address"], "name": s["business"]})
        stations = STATION_LABEL.get(s["stationKind"], "stations")
        office = s["stationKind"] == "desk"
        if (s["idleShare"] or 0) >= IDLE_SHARE_MIN and s["idleWagesPerWeek"] >= IDLE_WAGES_MIN:
            severity = ("high" if s["idleShare"] >= IDLE_SHARE_HIGH else
                        "medium" if s["idleWagesPerWeek"] >= IDLE_WAGES_MEDIUM else "low")
            out.append(_insight(
                severity, "costs", b, f"Too many staff: {s['idleShare']:.0%} of staffed {stations} sit idle",
                f"About {s['avgCustomersPerDay']:.0f} customers a day; each of the {stations} serves "
                f"{s['customersPerStationHour']} per hour. Of {s['staffedStationHoursPerWeek']} staffed hours a week, "
                f"{s['idleStationHoursPerWeek']} are not needed even with a 20 % margin "
                f"(peak need {s['peakNeeded']} vs {s['peakStaffed']} staffed)"
                + (". Office customers follow neighborhood demand, not staff count." if office else ".")
                + " See the Staffing card for the hour-by-hour detail.",
                "Cut the idle shifts (or employees) shown on the business page.",
                s["idleWagesPerWeek"] / 7, idleShare=s["idleShare"], idleWagesPerWeek=s["idleWagesPerWeek"]))
        if office and s["understaffedHours"] >= 5:
            out.append(_insight(
                "low", "staff", b, f"Desks short at {s['understaffedHours']} opening hours a week",
                f"At those hours more customers are expected than staffed desks can serve "
                f"(peak need {s['peakNeeded']} vs {s['peakStaffed']} staffed): office customers above desk capacity are lost.",
                "Move shifts towards the busy hours shown on the business page.", None,
                understaffedHours=s["understaffedHours"]))
    return out


def market(ctx: Context) -> list[dict]:
    """Concurrence et événements de marché sur les produits que le joueur vend."""
    out = []
    names = {b["address"]: b for b in ctx.businesses}
    within_reach: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    for p in ctx.prices:
        b = {"address": p["address"], "name": p["business"]}
        key = (p["item"], p["neighborhood"])
        m = ctx.market.get(key, {})
        units = ctx.daily_sales.get((p["address"], p["item"]), {"units": 0})["units"]
        label = p["itemLabel"]
        before = ctx.monopoly_before.get(key)
        if before is not None and before and not p["monopoly"]:
            out.append(_insight("high", "competition", b, f"Monopoly on {label} lost",
                                f"A rival business now stocks {label} in {p['neighborhood']}: the ceiling lost 30 % of the base price.",
                                "Find which rival shop sells it (Prices page) and out-compete it.",
                                p["defaultPrice"] * 0.3 * units, unitsPerDay=round(units, 1)))
        elif before is not None and not before and p["monopoly"]:
            out.append(_insight("positive", "competition", b, f"Monopoly on {label} gained",
                                f"No rival business sells {label} in {p['neighborhood']} any more: +30 % of the base price on the ceiling.",
                                None, p["defaultPrice"] * 0.3 * units))
        rivals = m.get("rivalSellers")
        if not p["monopoly"] and rivals and rivals <= 2 and units > 0:
            within_reach[p["address"]].append((label, rivals, p["defaultPrice"] * 0.3 * units))
    # Un point par commerce : les produits dont un monopole est à 1 ou 2 commerces rivaux près.
    for address_, products in within_reach.items():
        products.sort(key=lambda x: -x[2])
        b = names.get(address_, {"address": address_, "name": address_})
        out.append(_insight("info", "competition", b, f"Monopoly within reach on {len(products)} product(s)",
                            "Only 1–2 rival shops stock: " + ", ".join(f"{label} ({n} rival{'s' if n > 1 else ''}, "
                                                                       f"+{gain:,.0f} $/day)" for label, n, gain in products[:6])
                            + ". A monopoly adds 30 % of the base price to the ceiling.",
                            "Out-compete or buy out those shops (see Prices for who they are).",
                            sum(g for _, _, g in products), products=[label for label, _, _ in products]))
    # Nouveaux concurrents sur les produits du joueur (commerces créés dans la fenêtre).
    seen = set()
    for c in ctx.competitors:
        if c["creationDay"] is None or c["creationDay"] < ctx.first_day or (c["competitorAddress"], c["playerAddress"]) in seen:
            continue
        seen.add((c["competitorAddress"], c["playerAddress"]))
        b = names.get(c["playerAddress"], {"address": c["playerAddress"], "name": c["playerBusiness"]})
        products = sorted({x["itemLabel"] for x in ctx.competitors
                           if x["competitorAddress"] == c["competitorAddress"] and x["playerAddress"] == c["playerAddress"]})
        out.append(_insight("medium", "competition", b, f"New competitor: {c['competitor']}",
                            f"{c['competitor']} ({c['rival'] or 'independent'}) opened at {c['competitorAddress']} on day "
                            f"{c['creationDay']} and sells {', '.join(products[:5])}{'…' if len(products) > 5 else ''}.",
                            "Watch its prices: a cheaper competitor lowers your ceiling and ends monopolies.", None,
                            competitor=c["competitor"], rival=c["rival"], products=products))
    # Événements actifs sur les produits vendus.
    sold = defaultdict(list)
    for p in ctx.prices:
        sold[p["item"]].append(p)
    for e in ctx.events:
        for p in sold.get(e["item"], []):
            if e["neighborhood"] and e["neighborhood"] != p["neighborhood"]:
                continue
            b = {"address": p["address"], "name": p["business"]}
            if e["kind"] == "hype":
                out.append(_insight("positive", "competition", b, f"Hype on {p['itemLabel']} until day {e['endDay']}",
                                    f"Demand +{e['demandImpact']} in {e['neighborhood'] or 'the whole city'}.",
                                    "Make sure stock and logistics targets can follow the extra sales.", None))
            elif e["kind"] in ("shortage", "backorder"):
                out.append(_insight("low", "costs", b, f"{e['kind'].capitalize()} on {p['itemLabel']} until day {e['endDay']}",
                                    f"Purchase price is {'+25' if e['kind'] == 'shortage' else '+50'} % at wholesalers/importers "
                                    f"({e['neighborhood'] or 'whole city'}).",
                                    "Avoid large purchases until it ends if stock allows.", None))
    return out


RULES = (profitability, satisfaction, pricing, stock, staff, job_demands, overstaffing, market)


def compute(db: sqlite3.Connection, window: int = 7, address: str | None = None) -> list[dict[str, Any]]:
    ctx = Context(db, window)
    if not ctx.ready:
        return []
    found = [i for rule in RULES for i in rule(ctx)]
    if address:
        found = [i for i in found if i["address"] == address]
    return sorted(found, key=lambda i: (SEVERITY_RANK[i["severity"]], -(i["impactPerDay"] or 0)))
