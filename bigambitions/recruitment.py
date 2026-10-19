"""Recrutement et exigences des employés (mécaniques reconstituées depuis BigAmbitions.dll).

Salaire du marché (EmployeeHelper.CalculateHourlyWageForSkill) :
    salaire de base de la compétence × (1 + compétence^1,05 / 100) × multiplicateur de difficulté.
Les candidats demandent exactement ce salaire ; un employé de rival ou débauché, 25 % de plus.

Satisfaction (EmployeeInstance.UpdateSatisfaction) : elle tend, de 0,6 point par heure au plus, vers un
plafond fixé par la part d'exigences satisfaites : ≤ 34 % → 60, ≤ 67 % → 80, au-delà → 100.
Le service client vaut compétence × satisfaction : un employé dont les exigences ne sont pas tenues
« vaut » 60 ou 80 % de sa compétence.

Statut d'une exigence :
    met          satisfaite
    arrangeable  satisfiable en adaptant le planning (candidats uniquement)
    missing      il manque quelque chose : ``fix`` dit quoi
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

INSURANCE_LABEL = {0: "bronze", 1: "silver", 2: "gold"}
SHIFT_DEFAULT, SHIFT_CLEANING = 1, 0
WEEKDAY = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def market_wage(ref, skill_name: str, value: float, multiplier: float) -> float | None:
    skill = ref.skills.get(skill_name)
    if not skill:
        return None
    return skill["baseHourlyWage"] * (1 + value ** 1.05 / 100) * multiplier


def satisfaction_cap(met: int, total: int) -> int | None:
    """Plafond de satisfaction selon la part d'exigences satisfaites.

    Sans exigence, la satisfaction ne bouge plus (la somme des effets est nulle) : None.
    """
    if not total:
        return None
    share = met / total
    return 60 if share <= 0.34 else 80 if share <= 0.67 else 100


def building_cleanliness(registration: dict) -> int:
    """Propreté réelle du bâtiment à partir des taches (BuildingCleanliness.GetCleanliness)."""
    spots = registration.get("dirtSpots") or []
    if not spots:
        return 100
    total = sum(s.get("dirtiness") or 0 for s in spots)
    visible = sum(s.get("dirtiness") or 0 for s in spots if (s.get("dirtiness") or 0) >= 5)
    if visible == 0:
        return 100
    return max(0, int(100 - total / len(spots) - visible / len(spots)))


class BusinessContext:
    """Ce qu'il faut savoir d'un commerce pour juger les exigences : objets, horaires, mutuelles, propreté."""

    def __init__(self, registration: dict, ref, hr_plans: dict[str, dict], player_happiness: float):
        self.registration = registration
        self.ref = ref
        self.hr_plans = hr_plans
        self.player_happiness = player_happiness
        items = registration.get("itemInstances") or {}
        self.items = items
        self.item_names: set[str] = set()
        self.filled: set[str] = set()
        for item in items.values():
            for name in [item["itemName"]] + [c["childItemName"] for c in item.get("stackedItems") or []]:
                self.item_names.add(name)
            # « Rempli » (HasItemInBuilding) : rien à exposer, ou au moins un article dedans.
            data = ref.item(item["itemName"]) or {}
            if not data.get("itemsThatCanShowcase") or any(c.get("itemName") and c.get("amount", 0) > 0
                                                            for c in item.get("cargoInstances") or []):
                self.filled.add(item["itemName"])
        self.cleanliness = building_cleanliness(registration)
        self.open_hours: dict[int, set[int]] = {}
        self.shifts: dict[str, list[tuple[int, int, int, int, str]]] = defaultdict(list)  # employé -> (jour, début, fin, type, poste)
        for day in registration.get("scheduleDays") or []:
            if day.get("isOpen"):
                self.open_hours[day["day"]] = {h for s in day.get("openingHourSlots") or []
                                               for h in range(s["startingHour"], s["endingHour"])}
            for s in day.get("workShifts") or []:
                if s.get("employeeId"):
                    self.shifts[s["employeeId"]].append((day["day"], s["startingHour"], s["endingHour"], s.get("type"), s.get("itemInstanceId")))
        self.best_insurance = max((p["planType"] for p in hr_plans.values() if p.get("active")), default=None)

    def label(self, key: str) -> str:
        return self.ref.label(key) or key

    def items_label(self, names: list[str]) -> str:
        return " or ".join(dict.fromkeys(self.label(n) for n in names))

    def station_items(self, employee_id: str) -> set[str]:
        """Objets des postes où l'employé est planifié (poste, son support et ce qui y est posé)."""
        names = set()
        for _, _, _, _, item_id in self.shifts.get(employee_id, []):
            item = self.items.get(item_id)
            if not item:
                continue
            names.add(item["itemName"])
            parent = self.items.get(item.get("parentId") or "")
            for holder in (item, parent):
                if holder:
                    names.add(holder["itemName"])
                    names.update(c["childItemName"] for c in holder.get("stackedItems") or [])
        return names


def _hours_between(shifts, start: int, end: int) -> bool:
    return any(s_start < end and start < s_end for _, s_start, s_end, _, _ in shifts) if end > start else False


def evaluate(demand: dict, ctx: BusinessContext, employee: dict | None) -> tuple[str, str | None]:
    """Statut d'une exigence pour un employé en poste (``employee``) ou un candidat (``employee`` None)."""
    kind = demand["$script"]
    shifts = ctx.shifts.get(employee["id"], []) if employee else []
    if kind == "HoursWorkingPerWeek":
        low, high = demand["betweenHours"]["x"], demand["betweenHours"]["y"]
        if employee is None:
            possible = sum(len(h) for h in ctx.open_hours.values()) >= low
            return ("arrangeable", None) if possible else ("missing", f"open at least {low} h a week")
        hours = employee.get("assignedWeeklyHours") or 0
        return ("met", None) if low <= hours <= high else ("missing", f"schedule {low}–{high} h a week (now {hours} h)")
    if kind == "DaysWorkingPerWeek":
        n = demand["daysWorkingPerWeek"]
        if employee is None:
            return ("arrangeable", None) if len(ctx.open_hours) >= n else ("missing", f"open at least {n} days a week")
        days = len(employee.get("assignedWeeklyDays") or [])
        return ("met", None) if days == n else ("missing", f"exactly {n} working days a week (now {days})")
    if kind == "FreeOnDays":
        free = demand["freeDays"]
        names = "/".join(WEEKDAY[d] for d in free)
        if employee is None:
            return ("arrangeable", None) if set(ctx.open_hours) - set(free) else ("missing", f"open on days other than {names}")
        works = set(employee.get("assignedWeeklyDays") or []) & set(free)
        return ("met", None) if not works else ("missing", f"no shifts on {names}")
    if kind == "HasNoShiftBetweenHours":
        periods = [(demand["shiftPeriod"]["x"], demand["shiftPeriod"]["y"]),
                   (demand["nextShiftPeriod"]["x"], demand["nextShiftPeriod"]["y"])]
        span = " and ".join(f"{a}–{b} h" for a, b in periods if b > a)
        if employee is None:
            outside = any(h for hours in ctx.open_hours.values() for h in hours if not any(a <= h < b for a, b in periods))
            return ("arrangeable", None) if outside else ("missing", f"the business is only open {span}")
        clash = any(_hours_between(shifts, a, b) for a, b in periods)
        return ("met", None) if not clash else ("missing", f"no shifts between {span}")
    if kind == "NoSpecificShift":
        if employee is None:
            return ("arrangeable", None)
        clash = any(t in demand["workShiftTypes"] for _, _, _, t, _ in shifts)
        return ("met", None) if not clash else ("missing", "no cleaning shifts")
    if kind == "WorksOnItem":
        wanted = demand["itemNames"]
        if employee is not None:
            has = ctx.station_items(employee["id"]) & set(wanted)
            return ("met", None) if has else ("missing", f"put a {ctx.items_label(wanted)} at their workstation")
        return (("arrangeable", None) if ctx.item_names & set(wanted)
                else ("missing", f"buy a {ctx.items_label(wanted)} for their workstation"))
    if kind == "HasItemInBuilding":
        wanted = demand["itemNames"]
        if ctx.filled & set(wanted):
            return ("met", None)
        if ctx.item_names & set(wanted):
            return ("missing", f"refill the {ctx.items_label(wanted)}")
        return ("missing", f"place a {ctx.items_label(wanted)} in the building")
    if kind == "HasHealthInsurance":
        level = demand["healthInsurancePlan"]
        if employee is not None:
            plan = ctx.hr_plans.get(employee.get("assignedHrManagerPlanId") or "")
            ok = plan and plan.get("active") and plan["planType"] >= level
            return ("met", None) if ok else ("missing", f"{INSURANCE_LABEL[level]} health insurance (HR manager plan)")
        ok = ctx.best_insurance is not None and ctx.best_insurance >= level
        return ("arrangeable", None) if ok else ("missing", f"an HR manager plan with {INSURANCE_LABEL[level]} insurance")
    if kind == "CleanWorkplace":
        ok = ctx.cleanliness is not None and ctx.cleanliness >= demand["minimumCleanlinessPercentage"]
        return ("met", None) if ok else ("missing", f"cleanliness ≥ {demand['minimumCleanlinessPercentage']} % (now {ctx.cleanliness})")
    if kind == "MinimumPlayerHappiness":
        ok = ctx.player_happiness >= demand["minimumPlayerHappiness"]
        return ("met", None) if ok else ("missing", f"your own happiness ≥ {demand['minimumPlayerHappiness']}")
    return ("met", None)


def assess(demands: list[str], ctx: BusinessContext, employee: dict | None, catalog: dict[str, dict]) -> dict[str, Any]:
    """Évalue toutes les exigences ; ``arrangeable`` compte comme satisfait pour le plafond."""
    rows = []
    for name in demands:
        demand = catalog.get(name)
        if not demand:
            continue
        status, fix = evaluate(demand, ctx, employee)
        rows.append({"demand": name, "label": ctx.label(name), "status": status, "fix": fix})
    met = sum(1 for r in rows if r["status"] != "missing")
    return {"demands": rows, "met": met, "total": len(rows), "cap": satisfaction_cap(met, len(rows))}


def candidate_value(skill: float, cap: int | None, wage: float) -> dict[str, float]:
    effective = skill * (cap if cap is not None else 100) / 100
    return {"effectiveSkill": round(effective, 1),
            "wagePerEffectivePoint": round(wage / effective, 3) if effective else math.inf}
