"""Marketing : clients obtenus par chaque combinaison de campagnes, et la combinaison la plus rentable.

Mécanique du jeu (BuildingRegistration.GetMarketingEfficiency, BusinessHelper.UpdatePromotion,
CustomerEntriesCalculator*) :

- portée marketing = min(Σ portée des campagnes actives × multiplicateur du type de bâtiment / m² du bâtiment, 1) × 100,
  où les m² sont ceux de la taille de bâtiment (BuildingSizeData.squareMeters), pas la surface totale ;
- promotion = min(arrondi(trafic + portée × force marketing du quartier), 100) ;
- clients par heure = capacité du bâtiment × (base + 0,75 × promotion / 100) × multiplicateurs jour et heure ;
  - détail : plafonné à la capacité clients du commerce, heure par heure ;
  - bureau : × satisfaction × demande du marché, plafonné par les bureaux occupés (1 client / bureau / heure).

Une même campagne ne s'achète qu'une fois par commerce : on évalue les 64 combinaisons des 6 campagnes.
La valeur d'un client est la marge brute moyenne par client observée (CA − achats) ; au-delà des plafonds,
la promotion ne rapporte plus rien.
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import Any

from .pricing import f32

# MarketingTypeSettings : (nom affiché, $ par jour, m² couverts), dans l'ordre de l'enum MarketingTypeName.
CAMPAIGNS = [
    ("Small internet", 100.0, 20),
    ("Medium internet", 250.0, 40),
    ("Large internet", 500.0, 60),
    ("Small billboard", 500.0, 100),
    ("Medium billboard", 2500.0, 250),
    ("Large billboard", 6000.0, 600),
]
VALUE_WINDOW = 7  # jours d'historique pour la marge par client


def _round(x: float) -> int:
    """Mathf.RoundToInt : arrondi au pair le plus proche, comme round() en Python."""
    return round(x)


def _multiplier(entries: list[dict], key: str, value: int) -> float:
    for e in entries or []:
        if key == "hour" and e["startingHour"] <= value < e["endingHour"]:
            return e["multiplier"]
        if key == "day" and e["dayOfWeekOrdered"] == value:
            return e["multiplier"]
    return 0.0


class Context:
    """Ce dont dépend la promotion d'un commerce, hors campagnes."""

    def __init__(self, reg: dict, ref, segment: str, game: dict, demand: float | None):
        building = ref.building(reg["StreetName"], reg["StreetNumber"]) or {}
        size = ref.building_sizes.get(building.get("BuildingSize")) or {}
        building_type = building.get("BuildingType")
        self.sqm = size.get("squareMeters") or 0
        capacities = size.get("customerCapacities") or []
        # BuildingSizeData.GetCustomerCapacity : par type de bâtiment (les entrées sont en version 0).
        same_type = [c for c in capacities if c.get("buildingType") == building_type]
        self.initial = next((c["amount"] for c in same_type if c.get("buildingVersion", 0) == building.get("BuildingVersion", 0)),
                            same_type[0]["amount"] if same_type else 0)
        self.reach_multiplier = (ref.building_types.get(building_type) or {}).get("marketingReachMultiplier") or 1.0
        self.strength = (ref.neighborhoods.get(building.get("Neighbourhood")) or {}).get("marketingStrength") or 1.0
        self.traffic = building.get("trafficIndex") or (reg.get("promotion") or {}).get("trafficIndex") or 0
        self.base = (game.get("gameVariables") or {}).get("baseCustomerPromotionMultiplier") or 0.55
        self.segment = segment
        self.demand = demand
        self.satisfaction = ((reg.get("satisfaction") or {}).get("overall") or 50)
        self.cap = reg.get("customerCapacity") or self.initial
        business_type = ref.business_types.get(reg.get("businessTypeName")) or {}
        self.hours_mult = business_type.get("hourlyFactorMultipliers") or []
        self.days_mult = business_type.get("dayFactorMultipliers") or []
        self.schedule = reg.get("scheduleDays") or []
        items = reg.get("itemInstances") or {}
        # Bureaux occupés par heure (CustomerEntriesCalculatorOffice.GetAvailableWorkersOnHourAndDay).
        self.desks: dict[tuple[int, int], int] = {}
        for day in self.schedule:
            for shift in day.get("workShifts") or []:
                item = items.get(shift.get("itemInstanceId"))
                if not shift.get("employeeId") or not item:
                    continue
                per_hour = (ref.item(item["itemName"]) or {}).get("addedCustomersPerHour") or 0
                for h in range(shift["startingHour"], shift["endingHour"]):
                    self.desks[(day["day"], h)] = self.desks.get((day["day"], h), 0) + per_hour

    def marketing_points(self, reach: float) -> int:
        if not self.sqm:
            return 0
        return _round(f32(min(f32(f32(reach * self.reach_multiplier) / self.sqm), 1.0) * 100))

    def promotion(self, reach: float) -> int:
        # Calcul en float32 comme le jeu : 13 + 95 × 0,7f donne 79,5 tout rond, arrondi à 80.
        return min(_round(f32(self.traffic + f32(self.marketing_points(reach) * self.strength))), 100)

    def weekly_customers(self, promotion: int) -> dict[str, float]:
        """Clients sur une semaine type ; ``uncapped`` : sans le plafond des bureaux occupés."""
        m = self.base + 0.75 * promotion / 100
        served = uncapped = 0.0
        for day in self.schedule:
            if not day.get("isOpen"):
                continue
            dm = _multiplier(self.days_mult, "day", day["day"])
            hours = {h for slot in day.get("openingHourSlots") or [] for h in range(slot["startingHour"], slot["endingHour"])}
            for h in hours:
                base = self.initial * m * dm * _multiplier(self.hours_mult, "hour", h)
                if self.segment == "office":
                    sat = (self.satisfaction - 50) / 100 + 1
                    wanted = max(0, math.ceil(base * sat * (self.demand or 0) - 0.2))
                    served += min(wanted, self.desks.get((day["day"], h), 0))
                    uncapped += wanted
                else:
                    c = math.ceil(min(base, self.cap))
                    # Postes de service (fauteuils, caisses) : au-delà de leur débit, les clients ne sont pas servis.
                    if self.desks:
                        c = min(c, self.desks.get((day["day"], h), 0))
                    served += c
                    uncapped += math.ceil(base)
        return {"served": served, "uncapped": uncapped}


def _label(combo: tuple[int, ...]) -> str:
    return " + ".join(CAMPAIGNS[i][0] for i in combo) or "No marketing"


def analyse(reg: dict, ref, segment: str, game: dict, demand: float | None) -> dict[str, Any] | None:
    """Campagnes actuelles, toutes les combinaisons utiles et la plus rentable ; None si le commerce n'a pas de ventes."""
    today = game.get("Day") or 0
    # Jours complets seulement : le jour en cours n'est pas terminé.
    history = sorted((h for h in reg.get("orderHistory") or [] if h["dayNumber"] < today),
                     key=lambda h: h["dayNumber"])[-VALUE_WINDOW:]
    customers = sum(h.get("totalCustomers") or 0 for h in history)
    if not customers:
        return None
    revenue = sum(s["totalPrice"] for h in history for s in h.get("itemSales") or [])
    cogs = sum(s["totalWholesalePrice"] for h in history for s in h.get("itemSales") or [])
    ctx = Context(reg, ref, segment, game, demand)
    active = tuple(sorted({c["marketingTypeName"] for c in reg.get("marketingCampaigns") or [] if c.get("enabled")}))

    def evaluate(combo: tuple[int, ...]) -> dict[str, Any]:
        reach = sum(CAMPAIGNS[i][2] for i in combo)
        promo = ctx.promotion(reach)
        week = ctx.weekly_customers(promo)
        return {"campaigns": [CAMPAIGNS[i][0] for i in combo], "label": _label(combo), "combo": list(combo),
                "cost": sum(CAMPAIGNS[i][1] for i in combo), "marketingPoints": ctx.marketing_points(reach),
                "promotion": promo, "customersPerDay": week["served"] / 7, "potentialPerDay": week["uncapped"] / 7}

    options = [evaluate(c) for n in range(len(CAMPAIGNS) + 1) for c in combinations(range(len(CAMPAIGNS)), n)]
    current = next(o for o in options if tuple(o["combo"]) == active)
    observed = customers / len(history)
    # Calage sur les clients observés : en boutique, une partie des clients entrés n'achète rien.
    calibration = min(max(observed / current["customersPerDay"], 0.3), 1.5) if current["customersPerDay"] else 1.0
    for o in options:
        o["customersPerDay"] *= calibration
        o["potentialPerDay"] *= calibration
    # Valeur d'un client : marge brute observée, ramenée aux clients que le modèle prévoit aujourd'hui.
    value = (revenue - cogs) / customers if revenue else None
    for o in options:
        o["profitPerDay"] = (o["customersPerDay"] * value - o["cost"]) if value is not None else None
    best = max(options, key=lambda o: (round(o["profitPerDay"] or 0, 2), -o["cost"]))
    # Même promotion (donc mêmes clients, au client près) pour moins cher : économie sûre.
    same = min((o for o in options if o["promotion"] >= current["promotion"]), key=lambda o: o["cost"])
    # Pour l'affichage : la combinaison la moins chère pour chaque niveau de promotion.
    frontier: dict[int, dict] = {}
    for o in sorted(options, key=lambda o: o["cost"]):
        frontier.setdefault(o["promotion"], o)
    return {
        "sqm": ctx.sqm, "trafficIndex": ctx.traffic, "marketingStrength": ctx.strength,
        "reachMultiplier": ctx.reach_multiplier, "initialCustomers": ctx.initial, "customerCapacity": ctx.cap,
        "valuePerCustomer": value, "observedCustomersPerDay": observed, "calibration": calibration,
        "savedPromotion": (reg.get("promotion") or {}).get("total"),
        "current": current, "best": best, "samePromotionCheaper": same if same["cost"] < current["cost"] else None,
        "gainPerDay": (best["profitPerDay"] - current["profitPerDay"]) if value is not None else None,
        # Promotion au-delà de laquelle plus aucun client n'arrive (plafonds atteints à toutes les heures).
        "saturationPromotion": next((o["promotion"] for o in sorted(frontier.values(), key=lambda o: o["promotion"])
                                     if o["customersPerDay"] >= max(x["customersPerDay"] for x in options) - 1e-9), None),
        "options": sorted(frontier.values(), key=lambda o: o["promotion"]),
    }
