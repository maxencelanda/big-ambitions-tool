"""Formules de prix du jeu (reconstituées depuis BigAmbitions.dll, voir PLAN.md).

Le jeu calcule en float32 et tronque au centime ; ``f32`` reproduit cet arrondi pour retomber
exactement sur les plafonds affichés en jeu et appliqués par les managers de prix.
"""

from __future__ import annotations

import math
import struct
from typing import Any

from .reference import Reference

GLOBAL_NEIGHBORHOOD = "ba:neighborhood_global"

# Types d'événements de marché (Entities.MarketEventType).
EVENT_TYPES = {0: "business_opened", 1: "business_closed", 2: "hype", 3: "shortage", 4: "backorder",
               5: "large_player_purchase", 6: "max_providers_exceeded"}
# Multiplicateurs du prix d'achat pendant une pénurie / rupture fournisseur. Ils viennent d'un
# ScriptableObject non extrait (ProductMarketSettings) : valeurs reprises de biggerambitions.com.
PURCHASE_EVENT_MULTIPLIER = {"shortage": 1.25, "backorder": 1.5}


def f32(x: float) -> float:
    return struct.unpack("f", struct.pack("f", x))[0]


MONOPOLY_BONUS = f32(0.29999998)
# Indice de prix maximal accepté par classe sociale (120 / 140 / 170 % du prix de référence).
SOCIAL_CLASS_INDEX = {
    "working": f32(120 * f32(0.01)),
    "middle": f32(140 * f32(0.01)),
    "upper": f32(170 * f32(0.01)),
}
_CLASS_WEIGHTS = (f32(1.1999999), f32(1.4), f32(1.6999999))


def neighborhood_price_index(neighborhood: dict) -> float:
    """Moyenne des indices de classe pondérée par la population du quartier."""
    shares = (neighborhood["workingClassPercentage"], neighborhood["middleClassPercentage"],
              neighborhood["upperClassClassPercentage"])
    total = f32(0.0)
    for weight, share in zip(_CLASS_WEIGHTS, shares):
        total = f32(total + f32(weight * share))
    return f32(total / f32(sum(shares)))


def floor_cents(price: float) -> float:
    return int(price * 100.0) / 100


class Pricing:
    """Prix de marché d'une partie : prix le plus bas par quartier, monopoles, plafonds."""

    def __init__(self, game: dict[str, Any], ref: Reference):
        self.ref = ref
        self.index = {key: neighborhood_price_index(n) for key, n in ref.neighborhoods.items()}
        self.monopoly: dict[tuple[str, str], bool] = {}
        self.demand: dict[tuple[str, str], dict] = {}
        for entry in game.get("productMarketEntries", []):
            for d in entry.get("demandValues", []):
                self.monopoly[(entry["itemName"], d["neighborhood"])] = bool(d.get("hasPlayerMonopoly"))
                self.demand[(entry["itemName"], d["neighborhood"])] = d
        self.day = game.get("Day") or 0
        # Événements actifs (même règle que MarketEvent.IsActive) par (produit, quartier) ; quartier None = toute la ville.
        self.events: dict[tuple[str, str | None], list[dict]] = {}
        for e in game.get("marketEvents", []):
            if e.get("itemName") and not e.get("stopped") and e["startDay"] <= self.day < e["startDay"] + e["durationInDays"]:
                self.events.setdefault((e["itemName"], e.get("neighbourhood") or None), []).append(e)
        self.import_price_index = {e["itemName"]: e.get("importPriceIndex") for e in game.get("productMarketEntries", [])}
        self.market_price_multiplier = (game.get("gameVariables") or {}).get("marketPriceMultiplier") or 1.0
        # (produit, quartier) -> offres [(prix, registration)] des commerces qui comptent pour le marché
        self.offers: dict[tuple[str, str], list[tuple[float, dict]]] = {}
        for reg in game.get("BuildingRegistrations", []):
            if reg.get("temporarilyClosed") or not reg.get("BusinessName"):
                continue
            neighborhood = ref.neighborhood_of(reg.get("StreetName"), reg.get("StreetNumber"))
            if not neighborhood:
                continue
            # Les commerces IA ne comptent que s'ils ont le produit en rayon : le jeu teste le
            # remplissage des étagères, on s'appuie sur la liste des produits disponibles.
            available = set(reg.get("cachedAvailableProducts") or [])
            for rp in reg.get("retailPrices") or []:
                if rp["price"] > 0 and (reg.get("RentedByPlayer") or rp["itemName"] in available):
                    self.offers.setdefault((rp["itemName"], neighborhood), []).append((rp["price"], reg))

    # --- formules du jeu ----------------------------------------------------

    def default_price(self, item_name: str) -> float:
        item = self.ref.item(item_name)
        return item["defaultMarketPrice"] if item else 0.0

    def has_monopoly(self, item_name: str, neighborhood: str) -> bool:
        return self.monopoly.get((item_name, neighborhood), False)

    def can_have_demand(self, item_name: str, neighborhood: str) -> bool:
        item = self.ref.item(item_name) or {}
        limited = item.get("limitDemandToNeighbourhoods") or []
        return bool(item.get("isADemandedProduct")) and (not limited or neighborhood in limited)

    def optimal_price(self, item_name: str, neighborhood: str, monopoly: bool | None = None) -> float:
        index = self.index[neighborhood]
        if self.has_monopoly(item_name, neighborhood) if monopoly is None else monopoly:
            index = f32(index + MONOPOLY_BONUS)
        return f32(self.default_price(item_name) * index)

    def lowest_market_price(self, item_name: str, neighborhood: str) -> float:
        offers = self.offers.get((item_name, neighborhood))
        if offers:
            return min(price for price, _ in offers)
        return self.optimal_price(item_name, neighborhood)

    def reference_price(self, item_name: str, neighborhood: str) -> float:
        return min(self.default_price(item_name), self.lowest_market_price(item_name, neighborhood))

    def max_acceptable_price(self, item_name: str, neighborhood: str, social_class: str | None = None) -> float:
        """Prix maximum accepté par un client du quartier (classe la plus exigeante si non précisée)."""
        classes = [social_class] if social_class else list(SOCIAL_CLASS_INDEX)
        bonus = MONOPOLY_BONUS if self.can_have_demand(item_name, neighborhood) and self.has_monopoly(item_name, neighborhood) else 0.0
        reference = self.reference_price(item_name, neighborhood)
        return min(
            f32(reference * f32(max(SOCIAL_CLASS_INDEX[c], self.index[neighborhood]) + bonus))
            for c in classes
        )

    def ceiling(self, item_name: str, neighborhood: str) -> float:
        """Plafond en centimes entiers, tel qu'appliqué par le manager de prix."""
        return floor_cents(min(self.max_acceptable_price(item_name, neighborhood), 10000.0))

    def active_events(self, item_name: str, neighborhood: str | None = None) -> list[dict]:
        return self.events.get((item_name, None), []) + (self.events.get((item_name, neighborhood), []) if neighborhood else [])

    def purchase_event_multiplier(self, item_name: str, neighborhood: str | None = None) -> float:
        kinds = {EVENT_TYPES.get(e["type"]) for e in self.active_events(item_name, neighborhood)}
        for kind in ("shortage", "backorder"):  # même priorité que le jeu
            if kind in kinds:
                return PURCHASE_EVENT_MULTIPLIER[kind]
        return 1.0

    def purchase_price_estimate(self, item_name: str, neighborhood: str | None = None) -> float | None:
        """Coût d'achat chez un grossiste : prix de gros × indice d'import × difficulté × pénurie éventuelle."""
        item = self.ref.item(item_name)
        if not item or not item.get("wholesalePrice"):
            return None
        return (item["wholesalePrice"] * (self.import_price_index.get(item_name) or 1.0) * self.market_price_multiplier
                * self.purchase_event_multiplier(item_name, neighborhood))

    def optimal_providers(self, item_name: str) -> int:
        """Nombre de fournisseurs qu'un quartier absorbe avant que la demande baisse (Item.GetOptimalProviders)."""
        default = self.default_price(item_name)
        return min(math.ceil(math.sqrt(1300 / default)), 7) if default else 7

    def rival_sellers(self, item_name: str, neighborhood: str) -> list[tuple[float, dict]]:
        """Commerces d'un rival qui ont le produit en rayon : ce sont eux qui empêchent le monopole."""
        return [o for o in self.offers.get((item_name, neighborhood), [])
                if not o[1].get("RentedByPlayer") and o[1].get("businessOwnerRivalId")]

    # --- concurrence --------------------------------------------------------

    def lowest_competitor(self, item_name: str, neighborhood: str) -> tuple[float, dict] | None:
        competitors = [o for o in self.offers.get((item_name, neighborhood), []) if not o[1].get("RentedByPlayer")]
        return min(competitors, key=lambda o: o[0]) if competitors else None

    def sellers(self, item_name: str, neighborhood: str) -> list[tuple[float, dict]]:
        return self.offers.get((item_name, neighborhood), [])
