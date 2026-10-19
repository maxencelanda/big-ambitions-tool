"""Référentiel du jeu (source de vérité), construit à partir de out/gamedata (extract_gamedata.py).

    ref = Reference.load()
    ref.item("ba:itemname_burger")["defaultMarketPrice"]   # 12.5
    ref.building("ba:street_fifthavenue", 32)["Neighbourhood"]
    ref.label("ba:itemname_burger")                        # "Burger" (textes anglais du jeu)
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "out" / "gamedata"

# Segments d'analyse : un commerce n'est comparé qu'aux commerces de son segment.
SEGMENT_HEADQUARTERS = "headquarters"
SEGMENT_LOGISTICS = "logistics"
SEGMENT_RETAIL = "retail"
SEGMENT_OFFICE = "office"
SEGMENT_HOME = "home"
SEGMENT_OTHER = "other"


class ReferenceMissing(FileNotFoundError):
    pass


class Reference:
    def __init__(self, directory: Path = DEFAULT_DIR):
        self.directory = Path(directory)
        if not (self.directory / "items.json").exists():
            raise ReferenceMissing(
                f"référentiel absent ({self.directory}) : lancer .venv/Scripts/python extract_gamedata.py"
            )

    @classmethod
    def load(cls, directory: Path = DEFAULT_DIR) -> "Reference":
        return cls(directory)

    def _read(self, name: str) -> Any:
        return json.loads((self.directory / f"{name}.json").read_text(encoding="utf-8"))

    def _objects(self, bundle: str, script: str) -> list[dict]:
        return [o for o in self._read(bundle) if o.get("$script") == script]

    # --- tables indexées ----------------------------------------------------

    @cached_property
    def items(self) -> dict[str, dict]:
        return {i["itemName"]: i for i in self._objects("items", "Item") if i.get("itemName")}

    @cached_property
    def neighborhoods(self) -> dict[str, dict]:
        return {n["neighbourhood"]: n for n in self._objects("neighborhoods", "NeighborhoodData")}

    @cached_property
    def buildings(self) -> dict[tuple[str, int], dict]:
        return {(b["StreetName"], b["StreetNumber"]): b for b in self._objects("buildings", "Building")}

    @cached_property
    def business_types(self) -> dict[str, dict]:
        return {b["businessTypeName"]: b for b in self._objects("businesstypes", "BusinessType")}

    @cached_property
    def building_sizes(self) -> dict[str, dict]:
        return {s["buildingSize"]: s for s in self._objects("buildingsizes", "BuildingSizeData")}

    @cached_property
    def building_types(self) -> dict[str, dict]:
        return {t["buildingType"]: t for t in self._objects("buildingtypes", "BuildingTypeData")}

    def daily_rent(self, building: dict) -> int | None:
        """Loyer journalier du marché (Building.GetBuildingDailyMarketRent).

        Le jeu fixe le loyer au moment de la location : utile pour estimer celui d'un local libre.
        """
        neighborhood = self.neighborhoods.get(building.get("Neighbourhood"))
        building_type = self.building_types.get(building.get("BuildingType"))
        size = self.building_sizes.get(building.get("BuildingSize"))
        if not neighborhood or not building_type or not size:
            return None
        price = neighborhood["baseBuildingPricePerSqm"] * building_type["buildingPriceMultiplier"] * neighborhood["realEstateMultiplier"]
        traffic = building.get("trafficIndex") or 0
        if "ba:buildingtypetag_lowerrentforhightraffic" in building_type.get("tags", []):
            price -= price * min(traffic - 30, 0) / 100
        else:
            price *= 1.3 - (100 - traffic) / 100
        per_sqm = price * neighborhood["rentMultiplierPerSqmPrice"]
        return math.ceil(size["squareMeters"] * per_sqm * building_type["buildingPriceMultiplierForRent"])

    @cached_property
    def skills(self) -> dict[str, dict]:
        return {s["skillName"]: s for s in self._objects("skills", "SkillData")}

    @cached_property
    def importers(self) -> list[dict]:
        """Importateurs (quais) et leurs produits, via Building → SpecialService → ImportExportSettings."""
        objects = self._read("buildings")
        by_path = {o.get("$pathId"): o for o in objects}
        out = []
        for building in (o for o in objects if o.get("$script") == "Building"):
            service = by_path.get((building.get("SpecialService") or {}).get("m_PathID"))
            settings = by_path.get(((service or {}).get("settings") or {}).get("m_PathID"))
            if settings and settings.get("$script") == "ImportExportSettings":
                out.append({
                    "name": service.get("businessName"), "streetName": building["StreetName"],
                    "streetNumber": building["StreetNumber"], "neighborhood": building.get("Neighbourhood"),
                    "items": settings.get("itemsAvailable") or [],
                    # Disponibles seulement avec l'option de partie « allProductsAvailableFromImporters ».
                    "extraItems": settings.get("additionalItemsAvailableIfGameSettingEnabled") or [],
                })
        return out

    @cached_property
    def recipes(self) -> dict[str, dict]:
        """Recettes d'usine par produit fabriqué (bundle factories/recipes, absent des vieilles extractions)."""
        if not (self.directory / "factories_recipes.json").exists():
            return {}
        return {r["output"]["item"]: r for r in self._objects("factories_recipes", "Recipe") if r.get("output")}

    @cached_property
    def job_demands(self) -> dict[str, dict]:
        """Exigences d'emploi par nom (``$script`` donne la règle : WorksOnItem, FreeOnDays…)."""
        return {d["demandName"]: d for d in self._read("jobdemands") if d.get("demandName")}

    @cached_property
    def special_rivals(self) -> dict[str, dict]:
        return {r["rivalData"]["id"]: r for r in self._objects("rivals", "SpecialRival")}

    @cached_property
    def ai_business_defaults(self) -> list[dict]:
        return self._objects("aibusinessdefaults", "AiBusinessDefault")

    @cached_property
    def locale(self) -> dict[str, str]:
        path = self.directory / "locale_en.json"
        return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}

    @cached_property
    def version(self) -> dict[str, Any]:
        path = self.directory / "version.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    # --- accès --------------------------------------------------------------

    def item(self, item_name: str) -> dict | None:
        return self.items.get(item_name)

    def building(self, street_name: str, street_number: int) -> dict | None:
        return self.buildings.get((street_name, street_number))

    def neighborhood_of(self, street_name: str | None, street_number: int | None) -> str | None:
        b = self.building(street_name, street_number) if street_name else None
        return b["Neighbourhood"] if b else None

    def label(self, key: str | None) -> str | None:
        """Nom affiché dans le jeu (anglais) ; à défaut, la clé simplifiée."""
        if not key:
            return key
        text = self.locale.get(key)
        if text:
            return text
        return key[3:].split("_", 1)[-1] if key.startswith("ba:") else key

    def segment(self, business_type_name: str | None, building: dict | None = None) -> str:
        """Segment d'analyse ; ``building`` (référentiel) permet de reconnaître un logement."""
        if building and building.get("BuildingType") == "ba:buildingtype_residential":
            return SEGMENT_HOME
        if business_type_name == "ba:businesstype_headquarters":
            return SEGMENT_HEADQUARTERS
        data = self.business_types.get(business_type_name or "")
        if not data:
            return SEGMENT_OTHER
        building_type = data.get("suitableBuildingType")
        if building_type == "ba:buildingtype_warehouse":
            return SEGMENT_LOGISTICS
        if "ba:businesstag_generatesrevenue" not in data.get("tags", []):
            return SEGMENT_OTHER
        return SEGMENT_OFFICE if building_type == "ba:buildingtype_office" else SEGMENT_RETAIL

    def skill_base_wage(self, skill_name: str) -> float | None:
        skill = self.skills.get(skill_name)
        return skill.get("baseHourlyWage") if skill else None

    def rival_name(self, rival_id: str | None) -> str | None:
        """Nom des rivaux spéciaux ; les autres ont un nom généré par le jeu, non reproduit ici."""
        if not rival_id:
            return None
        special = self.special_rivals.get(rival_id)
        return special["rivalData"]["rivalName"] if special else f"Rival {rival_id[:6]}"

    # --- fraîcheur ----------------------------------------------------------

    def is_stale(self) -> bool | None:
        """True si le jeu a été mis à jour depuis l'extraction (None si on ne peut pas le savoir)."""
        game_path = self.version.get("gamePath")
        extracted = self.version.get("bigAmbitionsDllModified")
        if not game_path or not extracted:
            return None
        dll = Path(game_path) / "Big Ambitions_Data/Managed/BigAmbitions.dll"
        if not dll.exists():
            return None
        return datetime.fromtimestamp(dll.stat().st_mtime).isoformat(timespec="seconds") != extracted

    # --- tables pour la base -------------------------------------------------

    def tables(self) -> dict[str, list[dict]]:
        from .model import clean
        from .pricing import neighborhood_price_index

        items = [
            {
                "itemName": i["itemName"], "label": self.label(i["itemName"]),
                "isProduct": bool(i.get("isADemandedProduct")),
                "defaultMarketPrice": i.get("defaultMarketPrice"), "wholesalePrice": i.get("wholesalePrice"),
                "boxSize": i.get("boxSize"), "productSalesRatio": i.get("productSalesRatio"),
                "maxWholesaleOrderAmount": i.get("maxWholesaleOrderAmount"),
                "maxOrderAmountPerImporter": i.get("maxOrderAmountPerImporter"),
                "limitDemandToNeighbourhoods": ", ".join(i.get("limitDemandToNeighbourhoods") or []) or None,
            }
            for i in self.items.values()
            if i.get("defaultMarketPrice") or i.get("wholesalePrice") or i.get("isADemandedProduct")
        ]
        neighborhoods = [
            {
                "neighborhood": n["neighbourhood"], "label": n.get("m_Name"),
                "priceIndex": round(neighborhood_price_index(n), 4),
                "workingClassPct": n.get("workingClassPercentage"), "middleClassPct": n.get("middleClassPercentage"),
                "upperClassPct": n.get("upperClassClassPercentage"),
                "realEstateMultiplier": n.get("realEstateMultiplier"), "marketingStrength": n.get("marketingStrength"),
                "customerDemandsWeight": n.get("customerDemandsWeight"),
                "maxDailyIncomeToShutDownBusiness": n.get("maxDailyIncomeToShutDownBusiness"),
            }
            for n in self.neighborhoods.values()
        ]
        buildings = [
            {
                "address": f"{b['StreetNumber']} {clean(b['StreetName'])}",
                "streetName": b["StreetName"], "streetNumber": b["StreetNumber"],
                "neighborhood": b.get("Neighbourhood"), "buildingType": b.get("BuildingType"),
                "buildingSize": b.get("BuildingSize"), "sqm": b.get("totalSqm"), "trafficIndex": b.get("trafficIndex"),
            }
            for b in self.buildings.values()
        ]
        business_types = [
            {
                "businessType": t["businessTypeName"], "label": self.label(t["businessTypeName"]),
                "segment": self.segment(t["businessTypeName"]), "buildingType": t.get("suitableBuildingType"),
                "products": ", ".join(p["itemName"] for p in t.get("businessProducts") or []),
                "primarySkills": ", ".join(t.get("employeePrimarySkills") or []),
                "playerCanCreate": "ba:businesstag_allowplayercreation" in t.get("tags", []),
            }
            for t in self.business_types.values()
        ]
        skills = [
            {"skill": s["skillName"], "label": self.label(s["skillName"]), "baseHourlyWage": s.get("baseHourlyWage"),
             "secondarySkill": s.get("secondarySkill") or None}
            for s in self.skills.values()
        ]
        return {
            "ref_items": items, "ref_neighborhoods": neighborhoods, "ref_buildings": buildings,
            "ref_business_types": business_types, "ref_skills": skills,
        }
