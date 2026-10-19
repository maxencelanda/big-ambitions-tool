"""Effectifs : postes de service planifiés comparés aux clients réellement servis, heure par heure.

Chaque poste de service a une capacité en clients par heure (Item.addedCustomersPerHour : bureau 1,
fauteuil de coiffure 5, caisse 20, caisse de supermarché 30…). Pour un commerce de bureau, le jeu plafonne
les clients à la capacité des postes occupés (CustomerEntriesCalculatorOffice) ; pour le détail, c'est le
débit de service des caisses / fauteuils.

Les clients attendus à chaque heure sont les clients observés ce jour de la semaine (historique des ventes),
répartis sur les heures d'ouverture selon les multiplicateurs horaires du type de commerce.
Un poste est jugé nécessaire avec 20 % de marge : besoin = ⌈1,2 × clients attendus / capacité du poste⌉.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

SAFETY_MARGIN = 1.2
WORK_SHIFT_DEFAULT = 1  # WorkShiftType.Default (0 = ménage)
# Poste qui limite le service pour les commerces de détail, par ordre de priorité.
RETAIL_BOTTLENECKS = ("hairdresserchair", "checkoutcounter", "cashregister")


def _multiplier(entries: list[dict], key: str, value: int) -> float:
    for e in entries or []:
        if key == "hour" and e["startingHour"] <= value < e["endingHour"]:
            return e["multiplier"]
        if key == "day" and e["dayOfWeekOrdered"] == value:
            return e["multiplier"]
    return 0.0


def weekday(day_number: int) -> int:
    """Jour de la semaine du jeu, 1 = lundi (TimeHelper.GetDayOfWeek)."""
    return (day_number - 1) % 7 + 1


def _station_kind(item_name: str, segment: str) -> str | None:
    short = item_name[12:] if item_name.startswith("ba:itemname_") else item_name
    if segment == "office":
        return "desk"
    for kind in RETAIL_BOTTLENECKS:
        if short.startswith(kind):
            return kind
    return None


def analyse(registration: dict, ref, segment: str, wages: dict[str, float]) -> dict[str, Any] | None:
    """Analyse d'un commerce du joueur ; None si aucun poste de service pertinent.

    ``wages`` : salaire horaire des employés actifs. Un créneau tenu par quelqu'un d'absent de ce
    dictionnaire (employé débauché encore au planning) n'est pas compté.
    """
    business_type = ref.business_types.get(registration.get("businessTypeName")) or {}
    items = registration.get("itemInstances") or {}
    hours_mult = business_type.get("hourlyFactorMultipliers") or []
    days_mult = business_type.get("dayFactorMultipliers") or []

    # Clients observés par jour de la semaine (moyenne sur l'historique conservé par le jeu).
    by_weekday: dict[int, list[int]] = defaultdict(list)
    for h in registration.get("orderHistory") or []:
        by_weekday[weekday(h["dayNumber"])].append(h.get("totalCustomers") or 0)
    all_days = [c for values in by_weekday.values() for c in values]
    if not all_days:
        return None
    mean_customers = sum(all_days) / len(all_days)
    mean_day_mult = sum(_multiplier(days_mult, "day", d) for d in range(1, 8)) / 7 or 1.0

    hours = []
    capacity_per_station = None
    for schedule in registration.get("scheduleDays") or []:
        if not schedule.get("isOpen"):
            continue
        day = schedule["day"]
        open_hours = sorted({h for slot in schedule.get("openingHourSlots") or []
                             for h in range(slot["startingHour"], slot["endingHour"])})
        if not open_hours:
            continue
        customers = (sum(by_weekday[day]) / len(by_weekday[day]) if by_weekday.get(day)
                     else mean_customers * _multiplier(days_mult, "day", day) / mean_day_mult)
        weights = {h: _multiplier(hours_mult, "hour", h) for h in open_hours}
        total_weight = sum(weights.values()) or len(open_hours)
        staffed: dict[int, list[float]] = defaultdict(list)  # heure -> salaires horaires des postes occupés
        for shift in schedule.get("workShifts") or []:
            item = items.get(shift.get("itemInstanceId"))
            if not item or shift.get("type") != WORK_SHIFT_DEFAULT or shift.get("employeeId") not in wages:
                continue
            kind = _station_kind(item["itemName"], segment)
            capacity = (ref.item(item["itemName"]) or {}).get("addedCustomersPerHour") or 0
            if not kind or capacity <= 0:
                continue
            capacity_per_station = capacity
            for h in range(shift["startingHour"], shift["endingHour"]):
                if h in weights:
                    staffed[h].append(wages.get(shift["employeeId"], 0.0))
        for h in open_hours:
            expected = customers * (weights[h] or 1) / total_weight
            needed = math.ceil(SAFETY_MARGIN * expected / capacity_per_station) if capacity_per_station else 0
            on_duty = sorted(staffed.get(h, []), reverse=True)
            idle = max(0, len(on_duty) - needed)
            hours.append({
                "day": day, "hour": h, "expectedCustomers": round(expected, 2), "staffedStations": len(on_duty),
                "neededStations": needed, "idleStations": idle,
                # Sans marge : les clients attendus dépassent ce que les postes peuvent servir.
                "short": expected > len(on_duty) * capacity_per_station if capacity_per_station else False,
                # On retirerait d'abord les postes les plus chers.
                "idleWages": round(sum(on_duty[:idle]), 2),
            })
    if not capacity_per_station or not any(h["staffedStations"] for h in hours):
        return None
    staffed_hours = sum(h["staffedStations"] for h in hours)
    idle_hours = sum(h["idleStations"] for h in hours)
    return {
        "stationKind": "desk" if segment == "office" else next(
            (k for k in RETAIL_BOTTLENECKS if any(_station_kind(i["itemName"], segment) == k for i in items.values())), None),
        "customersPerStationHour": capacity_per_station,
        "avgCustomersPerDay": round(mean_customers, 1),
        "staffedStationHoursPerWeek": staffed_hours,
        "neededStationHoursPerWeek": sum(min(h["neededStations"], h["staffedStations"]) for h in hours),
        "idleStationHoursPerWeek": idle_hours,
        "idleShare": round(idle_hours / staffed_hours, 3) if staffed_hours else None,
        "idleWagesPerWeek": round(sum(h["idleWages"] for h in hours), 2),
        "peakStaffed": max(h["staffedStations"] for h in hours),
        "peakNeeded": max(h["neededStations"] for h in hours),
        "understaffedHours": sum(1 for h in hours if h["short"]),
        "hours": hours,
    }
