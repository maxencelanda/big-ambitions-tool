"""Plan idéal d'un commerce : campagnes marketing, horaires d'ouverture et postes occupés à chaque heure.

Les trois se décident ensemble : le marketing fixe les clients de chaque heure (marketing.Context), les clients
fixent les postes utiles, et une heure d'ouverture coûte les salaires des postes occupés. Pour chacune des
64 combinaisons de campagnes :

1. clients attendus à chaque heure de la semaine si le commerce était ouvert. Le jeu arrondit au client supérieur :
   une heure creuse (multiplicateur 0,1) amène encore 1 client, qui peut payer un poste. En détail, même calage
   sur les clients observés que l'analyse marketing ;
2. postes à occuper = ⌈clients / débit d'un poste⌉, dans la limite des postes installés ;
3. profit de l'heure = clients servis × marge par client − salaires des postes occupés ;
4. chaque jour, on ouvre la plage d'heures consécutives la plus rentable (aucune si elle perd de l'argent).

La combinaison retenue maximise le profit de la semaine, coût des campagnes compris. Le plan actuel est évalué
avec le même modèle, ce qui rend la comparaison cohérente.

Non modélisés : ménage, exigences des employés (jours, horaires) et effet des horaires sur la satisfaction.
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import Any

from .marketing import CAMPAIGNS, Context, _label
from .staffing import RETAIL_BOTTLENECKS, WORK_SHIFT_DEFAULT, _station_kind

MAX_HOURS_PER_DAY = 12  # ScheduleAutoFiller.MaxEmployeeHoursPerDay
DEFAULT_WEEKLY_HOURS = 40
DAY_LABELS = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def _best_window(profits: list[float]) -> tuple[int, int, float] | None:
    """Plage d'heures consécutives [début, fin) au profit maximal (Kadane) ; None si aucune n'est rentable."""
    best, start, total, best_range = 0.0, 0, 0.0, None
    for h, p in enumerate(profits):
        if total <= 0:
            start, total = h, 0.0
        total += p
        if total > best + 1e-9:
            best, best_range = total, (start, h + 1)
    return (best_range[0], best_range[1], best) if best_range else None


def _shifts(stations: dict[int, int]) -> list[dict[str, int]]:
    """Découpe un profil de postes par heure en créneaux : la k-ième couche couvre les heures à ≥ k postes."""
    layers: dict[tuple[int, int], int] = {}
    for k in range(1, max(stations.values(), default=0) + 1):
        hours = sorted(h for h, n in stations.items() if n >= k)
        run_start = prev = None
        for h in hours + [None]:
            if h is not None and prev is not None and h == prev + 1:
                prev = h
                continue
            if run_start is not None:
                layers[(run_start, prev + 1)] = layers.get((run_start, prev + 1), 0) + 1
            run_start = prev = h
    return [{"start": s, "end": e, "stations": n} for (s, e), n in sorted(layers.items())]


class _Business:
    def __init__(self, reg: dict, ref, segment: str, wages: dict[str, float]):
        items = reg.get("itemInstances") or {}
        stations: dict[str, list[float]] = {}
        for item in items.values():
            data = ref.item(item["itemName"]) or {}
            kind = _station_kind(item["itemName"], segment)
            capacity = data.get("addedCustomersPerHour") or 0
            # Seuls les postes « assignables » sont tenus par un employé (un frigo a aussi une capacité de 20).
            if kind and capacity > 0 and data.get("assignable"):
                stations.setdefault(kind, []).append(capacity)
        self.kind = "desk" if segment == "office" else next((k for k in RETAIL_BOTTLENECKS if k in stations), None)
        capacities = stations.get(self.kind) or []
        self.installed = len(capacities)
        self.per_station = max(capacities) if capacities else 0
        # Postes occupés aujourd'hui et salaire des employés qui les tiennent.
        self.now: dict[tuple[int, int], list[float]] = {}
        self.open_now: set[tuple[int, int]] = set()
        weekly: dict[str, int] = {}
        for day in reg.get("scheduleDays") or []:
            if day.get("isOpen"):
                for slot in day.get("openingHourSlots") or []:
                    self.open_now.update((day["day"], h) for h in range(slot["startingHour"], slot["endingHour"]))
            for shift in day.get("workShifts") or []:
                item = items.get(shift.get("itemInstanceId"))
                if (not item or shift.get("type") != WORK_SHIFT_DEFAULT or shift.get("employeeId") not in wages
                        or _station_kind(item["itemName"], segment) != self.kind):
                    continue
                weekly[shift["employeeId"]] = weekly.get(shift["employeeId"], 0) + shift["endingHour"] - shift["startingHour"]
                for h in range(shift["startingHour"], shift["endingHour"]):
                    self.now.setdefault((day["day"], h), []).append(wages[shift["employeeId"]])
        on_station = [wages[e] for e in weekly]
        self.wage = sum(on_station) / len(on_station) if on_station else None
        self.weekly_hours = sum(weekly.values()) / len(weekly) if weekly else DEFAULT_WEEKLY_HOURS


def _hour(ctx: Context, biz: _Business, promotion: int, day: int, hour: int, calibration: float,
          value: float, limit: int) -> dict[str, float]:
    customers = ctx.wanted(promotion, day, hour)[0] * calibration
    stations = min(math.ceil(customers / biz.per_station - 1e-9), limit) if customers > 0 else 0
    served = min(customers, stations * biz.per_station)
    return {"customers": customers, "stations": stations, "served": served,
            "profit": served * value - stations * biz.wage}


def _plan(ctx: Context, biz: _Business, combo: tuple[int, ...], calibration: float, value: float,
          limit: int) -> dict[str, Any]:
    promotion = ctx.promotion(sum(CAMPAIGNS[i][2] for i in combo))
    cost = sum(CAMPAIGNS[i][1] for i in combo)
    days, hours, profit = [], {}, -cost * 7
    for day in range(1, 8):
        cells = [_hour(ctx, biz, promotion, day, h, calibration, value, limit) for h in range(24)]
        window = _best_window([c["profit"] for c in cells])
        if window:
            profit += window[2]
            for h in range(window[0], window[1]):
                hours[(day, h)] = cells[h]
        days.append({"day": day, "open": [window[0], window[1]] if window else None})
    return {"combo": combo, "label": _label(combo), "cost": cost, "promotion": promotion,
            "profitPerWeek": profit, "days": days, "hours": hours}


def _current(ctx: Context, biz: _Business, combo: tuple[int, ...], calibration: float, value: float) -> dict[str, Any]:
    promotion = ctx.promotion(sum(CAMPAIGNS[i][2] for i in combo))
    cost = sum(CAMPAIGNS[i][1] for i in combo)
    profit, customers, station_hours = -cost * 7, 0.0, 0
    for day, h in biz.open_now:
        staffed = biz.now.get((day, h), [])
        wanted = ctx.wanted(promotion, day, h)[0] * calibration
        served = min(wanted, len(staffed) * biz.per_station)
        profit += served * value - sum(staffed)
        customers += served
        station_hours += len(staffed)
    # Postes tenus hors des heures d'ouverture : payés sans client.
    profit -= sum(sum(w) for key, w in biz.now.items() if key not in biz.open_now)
    station_hours += sum(len(w) for key, w in biz.now.items() if key not in biz.open_now)
    return {"label": _label(combo), "cost": cost, "promotion": promotion, "profitPerWeek": profit,
            "customersPerWeek": customers, "stationHoursPerWeek": station_hours}


def analyse(reg: dict, ref, segment: str, game: dict, demand: float | None, mk: dict[str, Any] | None,
            wages: dict[str, float]) -> dict[str, Any] | None:
    """Plan idéal ; None sans analyse marketing (marge par client), sans poste de service ou sans salaire connu."""
    if not mk or mk.get("valuePerCustomer") is None:
        return None
    biz = _Business(reg, ref, segment, wages)
    if not biz.installed or not biz.per_station or biz.wage is None:
        return None
    ctx = Context(reg, ref, segment, game, demand)
    value = mk["valuePerCustomer"]
    # Bureaux : le modèle du jeu est exact (à ±1 client/jour), le calage ne ferait qu'ajouter des fractions de client
    # et des postes en trop. Détail : une partie des clients entrés n'achète rien, on garde le calage.
    calibration = 1.0 if segment == "office" else mk["calibration"]
    combos = [c for n in range(len(CAMPAIGNS) + 1) for c in combinations(range(len(CAMPAIGNS)), n)]
    best = max((_plan(ctx, biz, c, calibration, value, biz.installed) for c in combos),
               key=lambda p: (round(p["profitPerWeek"], 2), -p["cost"]))
    # Avec des postes en plus (même campagnes) : le gain dit s'il vaut la peine d'en installer.
    unlimited = _plan(ctx, biz, best["combo"], calibration, value, 10 ** 6)
    current = _current(ctx, biz, tuple(mk["current"]["combo"]), calibration, value)

    hours = []
    for day in range(1, 8):
        for h in range(24):
            cell = best["hours"].get((day, h))
            now = len(biz.now.get((day, h), []))
            if cell or now or (day, h) in biz.open_now:
                hours.append({"day": day, "hour": h, "open": cell is not None, "openNow": (day, h) in biz.open_now,
                              "customers": round(cell["customers"], 2) if cell else 0.0,
                              "stations": cell["stations"] if cell else 0, "stationsNow": now})
    days = []
    for d in best["days"]:
        profile = {h: c["stations"] for (day, h), c in best["hours"].items() if day == d["day"]}
        days.append({**d, "label": DAY_LABELS[d["day"]], "shifts": _shifts(profile),
                     "customers": round(sum(c["served"] for (day, _), c in best["hours"].items() if day == d["day"]), 1),
                     "stationHours": sum(profile.values()), "peakStations": max(profile.values(), default=0)})
    station_hours = sum(d["stationHours"] for d in days)
    peak = max((d["peakStations"] for d in days), default=0)
    longest = max((d["open"][1] - d["open"][0] for d in days if d["open"]), default=0)
    # Assez de monde pour les heures de la semaine, pour le pic, et pour les journées de plus de 12 h.
    employees = max(math.ceil(station_hours / biz.weekly_hours), math.ceil(peak * longest / MAX_HOURS_PER_DAY))
    more = unlimited["profitPerWeek"] - best["profitPerWeek"]
    unlimited_peak = max((c["stations"] for c in unlimited["hours"].values()), default=0)
    return {
        "stationKind": biz.kind, "stationsInstalled": biz.installed, "customersPerStationHour": biz.per_station,
        "stationWage": round(biz.wage, 2), "valuePerCustomer": round(value, 2), "calibration": round(calibration, 3),
        "weeklyHoursPerEmployee": round(biz.weekly_hours, 1),
        "campaigns": best["label"], "marketingCost": best["cost"], "promotion": best["promotion"],
        "profitPerDay": round(best["profitPerWeek"] / 7, 2),
        "customersPerDay": round(sum(c["served"] for c in best["hours"].values()) / 7, 1),
        "stationHoursPerWeek": station_hours, "peakStations": peak, "employees": employees,
        "current": {**current, "profitPerDay": round(current["profitPerWeek"] / 7, 2),
                    "customersPerDay": round(current["customersPerWeek"] / 7, 1)},
        "gainPerDay": round((best["profitPerWeek"] - current["profitPerWeek"]) / 7, 2),
        "moreStations": {"peakStations": unlimited_peak, "extra": unlimited_peak - biz.installed,
                         "gainPerDay": round(more / 7, 2)} if more > 7 else None,
        "days": days, "hours": hours,
    }
