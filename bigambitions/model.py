"""Vues « à plat » d'une sauvegarde : chaque fonction renvoie une liste de lignes (dict).

Les identifiants du jeu sont de la forme "ba:<catégorie>_<nom>" (ex. "ba:itemname_burger") ;
``clean`` les réduit à "<nom>". Une adresse est rendue sous la forme "32 fifthavenue".
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from .reference import Reference

Row = dict[str, Any]
GLOBAL = "ba:neighborhood_global"


def clean(key: str | None) -> str | None:
    if not isinstance(key, str) or not key.startswith("ba:"):
        return key
    rest = key[3:]
    return rest.split("_", 1)[1] if "_" in rest else rest


def address(addr: dict | None) -> str | None:
    if not addr or not addr.get("streetName"):
        return None
    return f"{addr.get('streetNumber')} {clean(addr['streetName'])}"


def _building_address(b: dict) -> str:
    return f"{b['StreetNumber']} {clean(b['StreetName'])}"


def _timestamp(ts: dict | None) -> tuple[Any, Any, Any]:
    if not ts:
        return None, None, None
    return ts.get("Day"), ts.get("Hour"), round(ts.get("Minute") or 0, 2)


def _tuples(items: Iterable[dict]) -> list[tuple]:
    return [(t["m_Item1"], t["m_Item2"]) for t in items]


class Save:
    """Vues d'une sauvegarde. Avec un référentiel (``ref``), les vues sont enrichies
    (quartier, segment, noms du jeu) et les tables de prix sont disponibles."""

    def __init__(self, data: dict[str, Any], ref: "Reference | None" = None):
        self.meta = data.get("meta") or {}
        self.game = data["game"]
        self.ref = ref
        self.buildings = self.game.get("BuildingRegistrations", [])
        self.player_buildings = [b for b in self.buildings if b.get("RentedByPlayer")]
        self.business_by_address = {
            _building_address(b): b.get("BusinessName") or clean(b.get("businessTypeName"))
            for b in self.player_buildings
        }
        self.employees = self.game.get("EmployeeInstances", [])
        self.employee_by_id = {e["id"]: e for e in self.employees}
        self.pricing = None
        if ref is not None:
            from .pricing import Pricing
            self.pricing = Pricing(self.game, ref)

    def business_name(self, addr: str | None) -> str | None:
        return self.business_by_address.get(addr) if addr else None

    def _neighborhood(self, b: dict) -> str | None:
        return self.ref.neighborhood_of(b.get("StreetName"), b.get("StreetNumber")) if self.ref else None

    def _segment(self, b: dict) -> str | None:
        if not self.ref:
            return None
        return self.ref.segment(b.get("businessTypeName"), self.ref.building(b.get("StreetName"), b.get("StreetNumber")))

    def _label(self, key: str | None) -> str | None:
        return self.ref.label(key) if self.ref else clean(key)

    # --- vue d'ensemble -----------------------------------------------------

    def player(self) -> Row:
        g = self.game
        variables = g.get("gameVariables") or {}
        character = (g.get("charactersData") or [{}])[0]
        days_per_year = variables.get("daysPerYear") or 60
        funds = [
            {
                "name": clean(f["name"]),
                "balance": (f.get("developmentHistory") or [{}])[-1].get("newBalance"),
                "totalInvested": f.get("initialDeposit", 0) + f.get("additionalInvestment", 0),
                "withdrawn": f.get("withdrawal"),
                "interestEarned": f.get("interestPayment"),
            }
            for f in g.get("investmentFunds", [])
        ]
        return {
            "saveName": g.get("SaveGameName"),
            "name": character.get("name") or self.meta.get("characterData", {}).get("name"),
            "ageYears": round(character.get("ageInDays", 0) / days_per_year, 1),
            "day": g.get("Day"),
            "time": f"{g.get('Hour', 0):02d}:{int(g.get('Minute') or 0):02d}",
            "money": round(g.get("Money", 0), 2),
            "energy": round(g.get("Energy", 0), 1),
            "hunger": round(g.get("Hunger", 0), 1),
            "happiness": round(g.get("Happiness", 0), 1),
            "location": f"{g.get('CurrentStreetNumber')} {clean(g.get('CurrentStreetName'))}",
            "businesses": len(self.player_buildings),
            "employees": sum(1 for e in self.employees if not e.get("poached")),
            "vehicles": len(g.get("VehicleInstances", [])),
            "loans": g.get("Loans", []),
            "investmentFunds": funds,
            "weeklyIncomeHistory": _tuples(g.get("playerWeeklyIncomeHistory", [])),
            "midnightBankBalances": g.get("midnightBankBalances", []),
            "diplomas": [d["name"] for d in g.get("PlayerDiplomas", []) if d.get("completed")],
            "completedPersonalGoals": g.get("completedPersonalGoals", []),
            "achievements": {k: v for k, v in (g.get("achievementsData") or {}).items() if not k.startswith("$")},
            "gameVariables": {k: v for k, v in variables.items() if not k.startswith("$")},
            "buildNumber": g.get("buildNumberAtLastSave"),
        }

    # --- tables -------------------------------------------------------------

    def businesses(self) -> list[Row]:
        staff = defaultdict(list)
        for e in self.employees:
            if not e.get("poached"):
                staff[address(e.get("assignedAddress"))].append(e)
        rows = []
        for b in self.player_buildings:
            addr = _building_address(b)
            sat = b.get("satisfaction") or {}
            history = sorted(b.get("orderHistory") or [], key=lambda h: h["dayNumber"])
            last = history[-1] if history else None
            open_days = [d for d in b.get("scheduleDays", []) if d.get("isOpen")]
            building = self.ref.building(b["StreetName"], b["StreetNumber"]) if self.ref else None
            rows.append({
                "address": addr,
                "name": b.get("BusinessName"),
                "type": clean(b.get("businessTypeName")),
                "typeLabel": self._label(b.get("businessTypeName")),
                "segment": self._segment(b),
                "neighborhood": clean(self._neighborhood(b)),
                "sqm": building.get("totalSqm") if building else None,
                "rentPerDay": b.get("RentPerDay"),
                "creationDay": b.get("creationDay"),
                "customerCapacity": b.get("customerCapacity"),
                "employees": len(staff[addr]),
                "dailyWages": round(sum(e["hourlyWage"] * e.get("assignedWeeklyHours", 0) for e in staff[addr]) / 7, 2),
                "openDaysPerWeek": len(open_days),
                "openHours": ", ".join(
                    f"{s['startingHour']}-{s['endingHour']}" for s in (open_days[0]["openingHourSlots"] if open_days else [])
                ),
                "satisfaction": sat.get("overall"),
                "satCustomerService": sat.get("customerService"),
                "satPricing": sat.get("pricing"),
                "satCleanliness": sat.get("cleanliness"),
                "satFacility": sat.get("facility"),
                "promotion": (b.get("promotion") or {}).get("total"),
                "trafficIndex": (b.get("promotion") or {}).get("trafficIndex"),
                "marketingCampaigns": len(b.get("marketingCampaigns") or []),
                "lastSalesDay": last["dayNumber"] if last else None,
                "lastDayCustomers": last["totalCustomers"] if last else None,
                "lastDayRevenue": round(sum(i["totalPrice"] for i in last["itemSales"]), 2) if last else None,
                "furnitureValue": round(sum(i.get("priceOnPurchase") or 0 for i in self._items(b)), 2),
                "temporarilyClosed": b.get("temporarilyClosed"),
                "products": ", ".join(clean(p) for p in b.get("cachedAvailableProducts") or []),
            })
        return rows

    @staticmethod
    def _items(b: dict) -> list[dict]:
        items = b.get("itemInstances") or {}
        return list(items.values()) if isinstance(items, dict) else list(items)

    def _employee_row(self, e: dict) -> Row:
        c = e.get("characterData") or {}
        skills = {clean(s["name"]): round(s["value"], 1) for s in c.get("skills", [])}
        addr = address(e.get("assignedAddress"))
        return {
            "id": e["id"],
            "name": c.get("name"),
            "gender": c.get("gender"),
            "ageInDays": c.get("ageInDays"),
            "business": self.business_name(addr),
            "address": addr,
            "hourlyWage": round(e.get("hourlyWage", 0), 2),
            "weeklyHours": e.get("assignedWeeklyHours"),
            "weeklyDays": len(e.get("assignedWeeklyDays") or []),
            "satisfaction": round(e.get("satisfaction", 0), 1),
            "dayHired": e.get("dayHired"),
            "lastWorkedDay": e.get("lastWorkedDay"),
            "isAbsent": e.get("isAbsent"),
            "isComplaining": (e.get("complaintData") or {}).get("isComplaining"),
            # Débauché par un rival : le jeu garde la fiche le temps que le chasseur de têtes le remplace.
            "status": "poached" if e.get("poached") else "active",
            "beingReplaced": e.get("isBeingReplaced"),
            "poachedByRivalId": e.get("poachedByRivalId"),
            "demands": ", ".join(clean(d) for d in e.get("demands") or []),
            "skills": ", ".join(f"{k}={v}" for k, v in skills.items()),
            "mainSkill": max(skills, key=skills.get) if skills else None,
            "mainSkillValue": max(skills.values()) if skills else None,
        }

    def employee_name(self, employee_id: str | None) -> str | None:
        e = self.employee_by_id.get(employee_id)
        return (e.get("characterData") or {}).get("name") if e else None

    # --- recrutement et exigences (voir recruitment.py) -------------------------

    def _contexts(self) -> dict[str, Any]:
        """Contexte d'évaluation des exigences pour chaque commerce du joueur, calculé une fois."""
        if hasattr(self, "_contexts_cache"):
            return self._contexts_cache
        from .recruitment import BusinessContext

        contexts = {}
        if self.ref:
            hr_plans = {}
            for plan in self.game.get("hrManagerPlans", []):
                insurance = plan.get("healthInsurancePlan") or {}
                hr_plans[plan["id"]] = {"planType": insurance.get("planType"),
                                        "active": bool(insurance.get("pricePerDayAndEmployee"))}
            happiness = self.game.get("Happiness") or 0
            for b in self.player_buildings:
                contexts[_building_address(b)] = BusinessContext(b, self.ref, hr_plans, happiness)
        self._contexts_cache = contexts
        return contexts

    def _market_wage(self, skill_name: str | None, value: float | None) -> float | None:
        from .recruitment import market_wage

        if not self.ref or not skill_name or value is None:
            return None
        multiplier = (self.game.get("gameVariables") or {}).get("employeeHourlySalaryMultiplier") or 1.0
        return market_wage(self.ref, skill_name, value, multiplier)

    def _assess_employee(self, e: dict) -> dict | None:
        from .recruitment import assess

        ctx = self._contexts().get(address(e.get("assignedAddress")))
        return assess(e.get("demands") or [], ctx, e, self.ref.job_demands) if ctx else None

    def employees_table(self) -> list[Row]:
        rows = []
        for e in self.employees:
            row = self._employee_row(e)
            skills = (e.get("characterData") or {}).get("skills") or []
            main = max(skills, key=lambda s: s["value"]) if skills else None
            wage = self._market_wage(main["name"], main["value"]) if main else None
            assessment = self._assess_employee(e) if self.ref and not e.get("poached") else None
            row.update({
                "marketWage": round(wage, 2) if wage else None,
                # > 1 : payé plus que le marché pour sa compétence actuelle.
                "wageRatio": round(e.get("hourlyWage", 0) / wage, 3) if wage else None,
                "demandsMet": assessment["met"] if assessment else None,
                "demandsTotal": assessment["total"] if assessment else None,
                "satisfactionCap": assessment["cap"] if assessment else None,
                "unmetDemands": "; ".join(f"{d['label']}: {d['fix']}" for d in assessment["demands"]
                                          if d["status"] == "missing") or None if assessment else None,
            })
            rows.append(row)
        return rows

    def employee_demands(self) -> list[Row]:
        rows = []
        for e in self.employees:
            if e.get("poached") or not self.ref:
                continue
            assessment = self._assess_employee(e)
            if not assessment:
                continue
            addr = address(e.get("assignedAddress"))
            for d in assessment["demands"]:
                rows.append({"employeeId": e["id"], "employee": (e.get("characterData") or {}).get("name"),
                             "address": addr, "business": self.business_name(addr), **d})
        return rows

    def _skills_wanted(self, b: dict) -> set[str]:
        """Compétences qu'un commerce emploie : celles de son type, et le ménage s'il a des postes de nettoyage."""
        data = self.ref.business_types.get(b.get("businessTypeName")) or {}
        wanted = set(data.get("employeePrimarySkills") or [])
        if any(i["itemName"] == "ba:itemname_cleaningstation" for i in self._items(b)):
            wanted.add("ba:skill_cleaning")
        return wanted

    def candidates(self) -> list[Row]:
        fits = defaultdict(list)
        for f in self.candidate_fits():
            fits[f["candidateId"]].append(f)
        rows = []
        for e in self.game.get("CandidateEmployeeInstances", []):
            info = e.get("candidateInfo") or {}
            row = self._employee_row(e)
            for key in ("business", "address", "weeklyHours", "weeklyDays", "satisfaction", "dayHired",
                        "lastWorkedDay", "isAbsent", "isComplaining", "status", "beingReplaced", "poachedByRivalId"):
                row.pop(key)
            source = address(info.get("sourceAddress"))
            best = max(fits.get(e["id"], []), key=lambda f: (f["effectiveSkill"], -len(f["missing"] or "")), default=None)
            row.update({
                "sourceAddress": source,
                "sourceBusiness": self.business_name(source),
                "fromJobBoard": info.get("fromJobBoard"),
                "sourceHeadhunterId": info.get("sourceHeadhunterId"),
                "hoursUntilExpiring": info.get("hoursUntilExpiring"),
                "fits": len(fits.get(e["id"], [])),
                "bestBusiness": best["business"] if best else None,
                "bestAddress": best["address"] if best else None,
                "bestCap": best["cap"] if best else None,
                "effectiveSkill": best["effectiveSkill"] if best else None,
                "wagePerEffectivePoint": best["wagePerEffectivePoint"] if best else None,
                "missingAtBest": best["missing"] if best else None,
            })
            rows.append(row)
        return rows

    def candidate_fits(self) -> list[Row]:
        """Chaque candidat face à chaque commerce qui emploie sa compétence principale."""
        if hasattr(self, "_fits_cache"):
            return self._fits_cache
        from .recruitment import assess, candidate_value

        rows = []
        if self.ref:
            wanted = {_building_address(b): self._skills_wanted(b) for b in self.player_buildings}
            for e in self.game.get("CandidateEmployeeInstances", []):
                skills = (e.get("characterData") or {}).get("skills") or []
                if not skills:
                    continue
                main = max(skills, key=lambda s: s["value"])
                for addr, ctx in self._contexts().items():
                    if main["name"] not in wanted.get(addr, ()):
                        continue
                    a = assess(e.get("demands") or [], ctx, None, self.ref.job_demands)
                    value = candidate_value(main["value"], a["cap"], e.get("hourlyWage", 0))
                    rows.append({
                        "candidateId": e["id"], "name": (e.get("characterData") or {}).get("name"),
                        "skill": clean(main["name"]), "skillValue": round(main["value"], 1),
                        "hourlyWage": round(e.get("hourlyWage", 0), 2),
                        "address": addr, "business": self.business_name(addr),
                        "demandsMet": a["met"], "demandsTotal": a["total"], "cap": a["cap"],
                        "arrangeable": sum(1 for d in a["demands"] if d["status"] == "arrangeable"),
                        "missing": "; ".join(f"{d['label']}: {d['fix']}" for d in a["demands"] if d["status"] == "missing") or None,
                        **value,
                    })
        self._fits_cache = rows
        return rows

    def salary_negotiations(self) -> list[Row]:
        return [
            {
                "id": n.get("id"),
                "employeeId": (n.get("employeeInstance") or {}).get("id"),
                "name": ((n.get("employeeInstance") or {}).get("characterData") or {}).get("name"),
                "hourlyWage": round(n.get("hourlyWage") or 0, 2),
                "signingBonus": n.get("signingBonus"),
                "offers": len(n.get("offers") or []),
                "completed": n.get("completed"),
                "accepted": n.get("accepted"),
                "mood": n.get("mood"),
                "isRival": n.get("isRival"),
                "isPoached": n.get("isPoached"),
            }
            for n in self.game.get("candidateSalaryNegotiations", [])
        ]

    def contacts(self) -> list[Row]:
        rows = []
        for c in self.game.get("Contacts", []):
            messages = c.get("messagesQueue") or []
            days = [m["timestamp"]["Day"] for m in messages if m.get("timestamp")]
            rows.append({
                "id": c["id"],
                "name": self.employee_name(c["id"]),
                "description": clean(c.get("description")),
                "category": c.get("category"),
                "address": f"{c['streetNumber']} {clean(c['streetName'])}" if c.get("streetName") else None,
                "messages": len(messages),
                "unread": sum(1 for m in messages if not m.get("read")),
                "lastMessageDay": max(days) if days else None,
            })
        return rows

    def messages(self) -> list[Row]:
        rows = []
        for c in self.game.get("Contacts", []):
            for m in c.get("messagesQueue") or []:
                day, hour, minute = _timestamp(m.get("timestamp"))
                rows.append({
                    "contactId": c["id"],
                    "contactDescription": clean(c.get("description")),
                    "day": day, "hour": hour, "minute": minute,
                    "message": clean(m.get("messageKey")),
                    "read": m.get("read"),
                    "fromPlayer": m.get("isFromPlayer"),
                    "special": m.get("isSpecialMessage"),
                    "data": m.get("messageData") or None,
                })
        return sorted(rows, key=lambda r: (r["day"] or 0, r["hour"] or 0, r["minute"] or 0))

    def manager_plans(self) -> list[Row]:
        """Plans des managers du siège : RH, logistique, prix, chasseurs de têtes."""
        g = self.game
        rows = []

        def base(kind: str, p: dict) -> Row:
            return {
                "kind": kind, "id": p["id"],
                "managerId": p.get("assignedEmployeeId"),
                "managerName": self.employee_name(p.get("assignedEmployeeId")),
                "headquarters": address(p.get("headquartersAddress")),
            }

        for p in g.get("hrManagerPlans", []):
            insurance = p.get("healthInsurancePlan") or {}
            rows.append({**base("hr", p),
                         "assignedEmployees": len(p.get("assignedEmployees") or []),
                         "replaceAbsentEmployees": p.get("replaceAbsentEmployees"),
                         "trainingTarget": p.get("trainingTarget"),
                         "insurancePlanType": insurance.get("planType"),
                         "insurancePricePerDayAndEmployee": insurance.get("pricePerDayAndEmployee")})
        for p in g.get("logisticsManagerPlans", []):
            source = address(p.get("targetAddress"))
            rows.append({**base("logistics", p),
                         "sourceAddress": source, "sourceBusiness": self.business_name(source),
                         "isFactory": p.get("isFactory"),
                         "destinations": len(p.get("destinations") or [])})
        for p in g.get("pricingManagerPlans", []):
            rows.append({**base("pricing", p),
                         "neighborhood": clean(p.get("supervisedNeighborhood")),
                         "appliedPrices": len(p.get("appliedPrices") or []),
                         "manuallyPricedItems": len(p.get("manuallyPricedItems") or []),
                         "nextUpdateDay": p.get("nextUpdateDay")})
        for p in g.get("headhunterPlans", []):
            day, hour, _ = _timestamp(p.get("nextRecruit"))
            rows.append({**base("headhunter", p),
                         "isRecruiting": p.get("isRecruiting"),
                         "skill": clean(p.get("skillRecruiting")),
                         "skillTarget": p.get("skillValueTarget"),
                         "dealBreakers": ", ".join(clean(d) for d in p.get("dealBreakerTypes") or []),
                         "nextRecruitDay": day, "nextRecruitHour": hour,
                         "assignedHrPlans": len(p.get("assignedHrPlans") or [])})
        return rows

    def logistics_targets(self) -> list[Row]:
        """Objectifs de stock des managers logistiques : entrepôt source -> commerce, produit, quantité."""
        rows = []
        for p in self.game.get("logisticsManagerPlans", []):
            source = address(p.get("targetAddress"))
            for d in p.get("destinations") or []:
                dest = address(d.get("deliveryTargetAddress"))
                for t in d.get("stockTargets") or []:
                    rows.append({
                        "planId": p["id"],
                        "sourceAddress": source, "sourceBusiness": self.business_name(source),
                        "destinationAddress": dest, "destinationBusiness": self.business_name(dest),
                        "item": clean(t["itemName"]), "targetAmount": t.get("targetAmount"),
                    })
        return rows

    def pricing_plan_prices(self) -> list[Row]:
        """Prix appliqués par les managers de prix, par quartier."""
        return [
            {"planId": p["id"], "neighborhood": clean(p.get("supervisedNeighborhood")),
             "item": clean(r["itemName"]), "price": round(r["price"], 2)}
            for p in self.game.get("pricingManagerPlans", [])
            for r in p.get("appliedPrices") or []
        ]

    def quests(self) -> list[Row]:
        g = self.game
        sources = [
            ("main", "completed", g.get("CompletedQuestEntries", [])),
            ("side", "completed", g.get("completedSideQuestEntries", [])),
            ("side", "active", g.get("activeSideQuestEntries", [])),
            ("personalGoal", "completed", g.get("completedPersonalGoals", [])),
        ]
        return [
            {"kind": kind, "status": status, "key": entry if isinstance(entry, str) else json.dumps(entry, ensure_ascii=False)}
            for kind, status, entries in sources
            for entry in entries
        ]

    def notifications(self) -> list[Row]:
        rows = []
        for n in self.game.get("notifications", []):
            day, hour, minute = _timestamp(n.get("date"))
            rows.append({"day": day, "hour": hour, "minute": minute, "type": n.get("type"),
                         "key": n.get("key"), "data": n.get("notificationData") or None})
        return rows

    def inventory(self) -> list[Row]:
        """Stock par commerce et par produit (somme sur tous les meubles/étagères)."""
        totals: dict[tuple, list[float]] = defaultdict(lambda: [0, 0.0])

        def add(addr: str, holder: str, cargo: list[dict]) -> None:
            for c in cargo or []:
                t = totals[(addr, clean(c["itemName"]), holder)]
                t[0] += c.get("amount", 0)
                t[1] += c.get("amount", 0) * (c.get("pricePerUnit") or 0)
                add(addr, holder, c.get("nestedCargoInstances"))

        for b in self.player_buildings:
            addr = _building_address(b)
            for item in self._items(b):
                add(addr, "building", item.get("cargoInstances"))
        for v in self.game.get("VehicleInstances", []):
            add(f"vehicle {clean(v['vehicleTypeName'])} ({v['id'][:6]})", "vehicle", v.get("cargoInstances"))

        return [
            {
                "address": addr,
                "business": self.business_name(addr),
                "holder": holder,
                "item": item,
                "amount": amount,
                "stockValue": round(value, 2),
            }
            for (addr, item, holder), (amount, value) in sorted(totals.items())
        ]

    def retail_prices(self) -> list[Row]:
        return [
            {"address": _building_address(b), "business": b.get("BusinessName"),
             "item": clean(p["itemName"]), "price": round(p["price"], 2)}
            for b in self.player_buildings for p in b.get("retailPrices") or []
        ]

    def sales_history(self) -> list[Row]:
        rows = []
        for b in self.player_buildings:
            for h in b.get("orderHistory") or []:
                for s in h.get("itemSales", []):
                    rows.append({
                        "day": h["dayNumber"],
                        "address": _building_address(b),
                        "business": b.get("BusinessName"),
                        "customers": h.get("totalCustomers"),
                        "item": clean(s["itemName"]),
                        "amountSold": s["amountSold"],
                        "revenue": round(s["totalPrice"], 2),
                        "wholesaleCost": round(s["totalWholesalePrice"], 2),
                        "margin": round(s["totalPrice"] - s["totalWholesalePrice"], 2),
                        "avgPrice": round(s["totalPrice"] / s["amountSold"], 2) if s["amountSold"] else None,
                        "unitCost": round(s["totalWholesalePrice"] / s["amountSold"], 4) if s["amountSold"] else None,
                    })
        return sorted(rows, key=lambda r: (r["day"], r["address"], r["item"]))

    def daily_finances(self) -> list[Row]:
        """Compte de résultat journalier par commerce (financialSummaries)."""
        rows = []
        for f in self.game.get("financialSummaries", []):
            for s in f.get("businessIncomeStatements", []):
                addr = address(s.get("Address"))
                rows.append({
                    "day": f["dayNumber"],
                    "address": addr,
                    "business": self.business_name(addr),
                    "sales": round(s.get("TotalSales", 0), 2),
                    "resources": round(s.get("TotalResources", 0), 2),
                    "salaries": round(s.get("SalaryExpenses", 0), 2),
                    "rent": round(s.get("RentExpenses", 0), 2),
                    "marketing": round(s.get("MarketingExpenses", 0), 2),
                    "theft": round(s.get("Theft", 0), 2),
                    "licensingFees": round(s.get("LicensingFees", 0), 2),
                    "profit": round(s.get("TotalProfit", 0), 2),
                })
        return rows

    def daily_totals(self) -> list[Row]:
        keys = ["totalBusinessProfit", "totalLoanExpenses", "totalHealthInsuranceExpenses",
                "totalHeadhunterReplacementFees", "totalRealEstate", "totalResidentialExpenses",
                "totalUnassignedStaffWages", "parkingFees", "salaryIncome", "totalProfit"]
        return [
            {"day": f["dayNumber"], **{k: round(f.get(k) or 0, 2) for k in keys}}
            for f in self.game.get("financialSummaries", [])
        ]

    def transactions(self) -> list[Row]:
        rows = []
        for t in self.game.get("Transactions", []):
            day, hour, minute = _timestamp(t.get("timestamp"))
            addr = address(t.get("address"))
            rows.append({
                "day": day, "hour": hour, "minute": minute,
                "type": clean(t.get("transactionType")),
                "categories": ", ".join(clean(c) for c in t.get("transactionCategories") or []),
                "amount": round(t.get("amount", 0), 2),
                "balance": round(t.get("balance", 0), 2),
                "address": addr,
                "business": self.business_name(addr),
                "taxDeductible": t.get("isTaxDeductible"),
            })
        return rows

    def vehicles(self) -> list[Row]:
        return [
            {
                "id": v["id"], "type": clean(v["vehicleTypeName"]), "color": v.get("vehicleColorName"),
                "parkedAt": f"{v['streetNumber']} {clean(v['streetName'])}" if v.get("streetName") else None,
                "fuel": round(v.get("fuel", 0), 1), "damage": round(v.get("damage", 0), 3),
                "dirtiness": round(v.get("dirtiness", 0), 3),
                "cargoUnits": sum(c.get("amount", 0) for c in v.get("cargoInstances") or []),
                "unpaidParking": v.get("unpaidParkingAmount"),
            }
            for v in self.game.get("VehicleInstances", [])
        ]

    def market(self) -> list[Row]:
        """Demande par produit et par quartier."""
        return [
            {
                "item": clean(p["itemName"]),
                "importPriceIndex": round(p.get("importPriceIndex", 0), 3),
                "neighborhood": clean(d["neighborhood"]),
                "demand": d.get("demand"),
                "providers": d.get("providers"),
                "lastDaySold": d.get("lastDaySold"),
                "playerMonopoly": d.get("hasPlayerMonopoly"),
            }
            for p in self.game.get("productMarketEntries", [])
            for d in p.get("demandValues", [])
        ]

    def market_events(self) -> list[Row]:
        from .pricing import EVENT_TYPES

        day = self.game.get("Day") or 0
        rows = []
        for e in self.game.get("marketEvents", []):
            end = e["startDay"] + (e.get("durationInDays") or 0)
            rows.append({
                "type": e.get("type"), "kind": EVENT_TYPES.get(e.get("type"), "unknown"),
                "item": clean(e.get("itemName")), "itemLabel": self._label(e.get("itemName")) if e.get("itemName") else None,
                "neighborhood": clean(e.get("neighbourhood")), "startDay": e.get("startDay"),
                "durationInDays": e.get("durationInDays"), "endDay": end if e.get("durationInDays") else None,
                "active": not e.get("stopped") and e["startDay"] <= day < end,
                "demandImpact": e.get("demandImpact"), "stopped": e.get("stopped"),
                "businessType": clean(e.get("businessTypeName")),
                "businessTypeLabel": self._label(e.get("businessTypeName")) if e.get("businessTypeName") else None,
                "businessName": e.get("businessName"), "rivalName": e.get("rivalName"),
                "address": address(e.get("address")) if isinstance(e.get("address"), dict) else e.get("address"),
            })
        return rows

    @property
    def rival_names(self) -> dict[str, str]:
        """Noms des rivaux : rivaux spéciaux (référentiel) + ouvertures de commerces (événements de marché),
        rattachées au rival qui possède encore le commerce ouvert."""
        if hasattr(self, "_rival_names"):
            return self._rival_names
        names: dict[str, str] = {}
        by_address = {_building_address(b): b for b in self.buildings}
        for e in self.game.get("marketEvents", []):
            if e.get("type") != 0 or not e.get("rivalName") or not isinstance(e.get("address"), dict):
                continue
            reg = by_address.get(address(e["address"]))
            if reg and reg.get("businessOwnerRivalId") and reg.get("BusinessName") == e.get("businessName"):
                names[reg["businessOwnerRivalId"]] = e["rivalName"]
        if self.ref:
            for rival_id, special in self.ref.special_rivals.items():
                names[rival_id] = special["rivalData"]["rivalName"]
        self._rival_names = names
        return names

    def rival_name(self, rival_id: str | None) -> str | None:
        if not rival_id:
            return None
        return self.rival_names.get(rival_id) or f"Rival {rival_id[:6]}"

    def city_buildings(self) -> list[Row]:
        """Tous les bâtiments de la ville (commerces rivaux, locaux libres, ceux du joueur)."""
        rows = []
        for b in self.buildings:
            building = self.ref.building(b["StreetName"], b["StreetNumber"]) if self.ref else None
            rows.append({
                "address": _building_address(b),
                "businessName": b.get("BusinessName"),
                "type": clean(b.get("businessTypeName")),
                "neighborhood": clean(self._neighborhood(b)),
                "segment": self._segment(b),
                "buildingType": clean(building.get("BuildingType")) if building else None,
                "sqm": building.get("totalSqm") if building else None,
                "trafficIndex": building.get("trafficIndex") if building else None,
                "rentedByPlayer": b.get("RentedByPlayer"),
                "availableForRent": b.get("AvailableForRent"),
                "rentPerDay": b.get("RentPerDay"),
                # Le loyer d'un local libre n'est fixé qu'à la location : on applique la formule du jeu.
                "estimatedRent": self.ref.daily_rent(building) if building else None,
                "customerCapacity": b.get("customerCapacity"),
                "satisfaction": (b.get("satisfaction") or {}).get("overall"),
                "promotion": (b.get("promotion") or {}).get("total"),
                "buildingOwnerRivalId": b.get("buildingOwnerRivalId") or None,
                "businessOwnerRivalId": b.get("businessOwnerRivalId") or None,
                "businessOwner": self.rival_name(b.get("businessOwnerRivalId")) if b.get("businessOwnerRivalId") else None,
                "creationDay": b.get("creationDay"),
            })
        return rows

    def buildings_for_sale(self) -> list[Row]:
        return [
            {"address": address(b.get("address")), "price": b.get("buildingPrice"),
             "squareMeters": b.get("squareMeters"), "acceptOfferRate": round(b.get("acceptOfferRate", 0), 3)}
            for b in self.game.get("buildingsForSale", [])
        ]

    def rivals(self) -> list[Row]:
        owned = defaultdict(int)
        for b in self.buildings:
            if b.get("businessOwnerRivalId"):
                owned[b["businessOwnerRivalId"]] += 1
        special = {s["rivalId"]: s for s in self.game.get("specialRivalStates", [])}
        importers = set(self.game.get("importRivalIds", []))
        wholesalers = set(self.game.get("wholesaleRivalIds", []))
        rows = []
        for r in self.game.get("rivalStates", []):
            income = _tuples(r.get("weeklyIncomeHistory", []))
            count = _tuples(r.get("numberOfBusinessesHistory", []))
            rid = r["rivalId"]
            rows.append({
                "rivalId": rid,
                "name": self.rival_name(rid),
                "lastWeeklyIncome": round(income[-1][1], 2) if income else None,
                "businesses": count[-1][1] if count else None,
                "businessesInCity": owned.get(rid, 0),
                "isImporter": rid in importers,
                "isWholesaler": rid in wholesalers,
                "special": rid in special,
                "specialActive": special.get(rid, {}).get("isActive"),
                "specialDefeated": special.get(rid, {}).get("isDefeated"),
            })
        return rows

    def import_partnerships(self) -> list[Row]:
        return [
            {
                "importer": address(p.get("importAddress")),
                "nextDeliveryDay": p.get("nextDeliveryDay"),
                "item": clean(i["itemName"]),
                "amountPerDelivery": i.get("amount"),
                "orderedLastWeek": i.get("amountOrderedLastWeek"),
                "warehouse": address(i.get("assignedWarehouse")),
            }
            for p in self.game.get("importPartnerships", [])
            for i in p.get("products", [])
        ]

    # --- prix (nécessitent le référentiel) -------------------------------------

    def _seller_label(self, reg: dict) -> str:
        if reg.get("RentedByPlayer"):
            return f"{reg.get('BusinessName')} (joueur)"
        rival = self.rival_name(reg.get("businessOwnerRivalId"))
        return f"{reg.get('BusinessName')} ({rival})" if rival else reg.get("BusinessName")

    def prices(self) -> list[Row]:
        """Pour chaque produit vendu par le joueur : prix, plafond du jeu, prix optimal, concurrence, refus."""
        if not self.pricing:
            return []
        p = self.pricing
        managed = {plan.get("supervisedNeighborhood") for plan in self.game.get("pricingManagerPlans", [])
                   if plan.get("assignedEmployeeId")}
        rows = []
        for b in self.player_buildings:
            neighborhood = self._neighborhood(b)
            if not neighborhood or not b.get("retailPrices"):
                continue
            refusals = defaultdict(lambda: [0, 0])
            for order in b.get("unprocessedCompletedOrders") or []:
                for e in order.get("entries", []):
                    stats = refusals[e["itemName"]]
                    stats[1] += 1
                    stats[0] += 0 if e.get("priceAccceptable") else 1
            costs = {}
            for h in sorted(b.get("orderHistory") or [], key=lambda h: h["dayNumber"]):
                for s in h.get("itemSales", []):
                    if s["amountSold"]:
                        costs[s["itemName"]] = s["totalWholesalePrice"] / s["amountSold"]
            for rp in b["retailPrices"]:
                item = rp["itemName"]
                if rp["price"] <= 0 or not self.ref.item(item):
                    continue
                ceiling = p.ceiling(item, neighborhood)
                competitor = p.lowest_competitor(item, neighborhood)
                refused, ordered = refusals.get(item, (0, 0))
                unit_cost = costs.get(item, p.purchase_price_estimate(item))
                rows.append({
                    "address": _building_address(b),
                    "business": b.get("BusinessName"),
                    "neighborhood": clean(neighborhood),
                    "item": clean(item),
                    "itemLabel": self.ref.label(item),
                    "price": round(rp["price"], 2),
                    "ceiling": ceiling,
                    "headroom": round(ceiling - rp["price"], 2),
                    "priceVsCeiling": round(rp["price"] / ceiling, 4) if ceiling else None,
                    "optimal": round(p.optimal_price(item, neighborhood), 2),
                    "defaultPrice": p.default_price(item),
                    "referencePrice": round(p.reference_price(item, neighborhood), 2),
                    "lowestMarketPrice": round(p.lowest_market_price(item, neighborhood), 2),
                    "lowestCompetitorPrice": round(competitor[0], 2) if competitor else None,
                    "lowestCompetitor": self._seller_label(competitor[1]) if competitor else None,
                    "monopoly": p.has_monopoly(item, neighborhood),
                    "pricingManager": neighborhood in managed,
                    "unitCost": round(unit_cost, 4) if unit_cost is not None else None,
                    "unitMargin": round(rp["price"] - unit_cost, 2) if unit_cost is not None else None,
                    "ordersSampled": ordered,
                    "priceRefused": refused,
                    "refusalRate": round(refused / ordered, 3) if ordered else None,
                })
        return rows

    def market_prices(self) -> list[Row]:
        """Pour chaque produit demandé et chaque quartier : demande, offre, prix bas, plafond, coût d'achat."""
        from .pricing import EVENT_TYPES

        if not self.pricing:
            return []
        p = self.pricing
        player_prices = defaultdict(list)
        for b in self.player_buildings:
            neighborhood = self._neighborhood(b)
            for rp in b.get("retailPrices") or []:
                if rp["price"] > 0:
                    player_prices[(rp["itemName"], neighborhood)].append(rp["price"])
        rows = []
        for (item, neighborhood), demand in sorted(p.demand.items()):
            if neighborhood == GLOBAL or neighborhood not in p.index or not self.ref.item(item):
                continue
            sellers = p.sellers(item, neighborhood)
            competitor = p.lowest_competitor(item, neighborhood)
            purchase = p.purchase_price_estimate(item, neighborhood)
            optimal = p.optimal_price(item, neighborhood)
            optimal_providers = p.optimal_providers(item)
            rivals = p.rival_sellers(item, neighborhood)
            events = p.active_events(item, neighborhood)
            rows.append({
                "item": clean(item),
                "itemLabel": self.ref.label(item),
                "neighborhood": clean(neighborhood),
                "demand": demand.get("demand"),
                "providers": demand.get("providers"),
                "sellersInSave": len(sellers),
                "lastDaySold": demand.get("lastDaySold"),
                "monopoly": bool(demand.get("hasPlayerMonopoly")),
                "playerSells": bool(player_prices.get((item, neighborhood))),
                "playerPrice": round(min(player_prices[(item, neighborhood)]), 2) if player_prices.get((item, neighborhood)) else None,
                "defaultPrice": p.default_price(item),
                "optimal": round(optimal, 2),
                "ceiling": p.ceiling(item, neighborhood),
                "lowestMarketPrice": round(p.lowest_market_price(item, neighborhood), 2),
                "lowestCompetitorPrice": round(competitor[0], 2) if competitor else None,
                "lowestCompetitor": self._seller_label(competitor[1]) if competitor else None,
                "avgCompetitorPrice": round(sum(s[0] for s in sellers if not s[1].get("RentedByPlayer"))
                                            / max(1, sum(1 for s in sellers if not s[1].get("RentedByPlayer"))), 2)
                if any(not s[1].get("RentedByPlayer") for s in sellers) else None,
                "importPriceIndex": round(p.import_price_index.get(item) or 0, 3),
                "purchasePriceEstimate": round(purchase, 4) if purchase is not None else None,
                "unitMarginAtOptimal": round(optimal - purchase, 2) if purchase is not None else None,
                "optimalProviders": optimal_providers,
                "roomForProviders": optimal_providers - (demand.get("providers") or 0),
                "rivalSellers": len(rivals),
                # Monopole : le joueur vend le produit et aucun commerce d'un rival ne l'a en rayon.
                "monopolyPossible": not rivals,
                "activeEvents": ", ".join(sorted({EVENT_TYPES.get(e["type"], "?") for e in events})) or None,
                "eventDemandImpact": sum(e.get("demandImpact") or 0 for e in events) or None,
                "purchaseMultiplier": p.purchase_event_multiplier(item, neighborhood),
            })
        return rows

    def _staffing(self) -> dict[str, dict]:
        """Analyse des effectifs par adresse (voir staffing.py), calculée une fois."""
        if hasattr(self, "_staffing_cache"):
            return self._staffing_cache
        from . import staffing

        result = {}
        if self.ref:
            wages = {e["id"]: e["hourlyWage"] for e in self.employees if not e.get("poached")}
            for b in self.player_buildings:
                segment = self._segment(b)
                if segment in ("retail", "office"):
                    analysis = staffing.analyse(b, self.ref, segment, wages)
                    if analysis:
                        result[_building_address(b)] = analysis
        self._staffing_cache = result
        return result

    def _marketing(self) -> dict[str, dict]:
        """Analyse marketing par adresse (voir marketing.py), calculée une fois."""
        if hasattr(self, "_marketing_cache"):
            return self._marketing_cache
        from . import marketing

        result = {}
        if self.ref and self.pricing:
            for b in self.player_buildings:
                segment = self._segment(b)
                if segment not in ("retail", "office"):
                    continue
                demand = None
                if segment == "office":
                    product = (b.get("cachedAvailableProducts") or [None])[0]
                    entry = self.pricing.demand.get((product, self._neighborhood(b))) or {}
                    demand = (entry.get("demand") or 0) / 100
                analysis = marketing.analyse(b, self.ref, segment, self.game, demand)
                if analysis:
                    result[_building_address(b)] = analysis
        self._marketing_cache = result
        return result

    def marketing(self) -> list[Row]:
        rows = []
        for addr, a in self._marketing().items():
            cur, best, same = a["current"], a["best"], a["samePromotionCheaper"]
            rows.append({
                "address": addr, "business": self.business_name(addr), "sqm": a["sqm"],
                "trafficIndex": a["trafficIndex"], "marketingStrength": round(a["marketingStrength"], 3),
                "valuePerCustomer": round(a["valuePerCustomer"], 2) if a["valuePerCustomer"] is not None else None,
                "observedCustomersPerDay": round(a["observedCustomersPerDay"], 1), "calibration": round(a["calibration"], 3),
                "currentCampaigns": cur["label"], "currentCost": cur["cost"], "currentPromotion": cur["promotion"],
                "currentCustomersPerDay": round(cur["customersPerDay"], 1),
                "bestCampaigns": best["label"], "bestCost": best["cost"], "bestPromotion": best["promotion"],
                "bestCustomersPerDay": round(best["customersPerDay"], 1),
                "gainPerDay": round(a["gainPerDay"], 2) if a["gainPerDay"] is not None else None,
                "samePromotionCampaigns": same["label"] if same else None, "samePromotionCost": same["cost"] if same else None,
                "saturationPromotion": a["saturationPromotion"],
            })
        return rows

    def marketing_options(self) -> list[Row]:
        return [{"address": addr, "business": self.business_name(addr), "campaigns": o["label"], "cost": o["cost"],
                 "marketingPoints": o["marketingPoints"], "promotion": o["promotion"],
                 "customersPerDay": round(o["customersPerDay"], 2),
                 "profitPerDay": round(o["profitPerDay"], 2) if o["profitPerDay"] is not None else None,
                 "current": o["label"] == a["current"]["label"], "best": o["label"] == a["best"]["label"]}
                for addr, a in self._marketing().items() for o in a["options"]]

    def staffing(self) -> list[Row]:
        return [
            {"address": addr, "business": self.business_name(addr), **{k: v for k, v in a.items() if k != "hours"}}
            for addr, a in self._staffing().items()
        ]

    def staffing_hours(self) -> list[Row]:
        return [{"address": addr, "business": self.business_name(addr), **h}
                for addr, a in self._staffing().items() for h in a["hours"]]

    def suppliers(self) -> list[Row]:
        """Où acheter chaque produit : importateurs (référentiel) et grossistes (produits en vente dans la sauvegarde)."""
        if not self.ref or not self.pricing:
            return []
        p = self.pricing
        option = bool((self.game.get("gameVariables") or {}).get("allProductsAvailableFromImporters"))
        contracts = defaultdict(dict)  # adresse de l'importateur -> produit -> quantité par livraison
        for partnership in self.game.get("importPartnerships", []):
            for product in partnership.get("products", []):
                contracts[address(partnership.get("importAddress"))][product["itemName"]] = product.get("amount") or 0
        rows = []
        for imp in self.ref.importers:
            addr = f"{imp['streetNumber']} {clean(imp['streetName'])}"
            # Les produits « extra » ne sont importables qu'avec l'option de partie ; sinon ils viennent d'une usine.
            for item, gated in [(i, False) for i in imp["items"]] + [(i, True) for i in imp["extraItems"] if option]:
                purchase = p.purchase_price_estimate(item)
                rows.append({
                    "kind": "importer", "supplier": imp["name"], "address": addr,
                    "neighborhood": clean(imp["neighborhood"]), "item": clean(item), "itemLabel": self.ref.label(item),
                    "available": True, "needsGameOption": gated, "ingredients": None,
                    "contractAmount": contracts.get(addr, {}).get(item),
                    "purchasePriceEstimate": round(purchase, 4) if purchase is not None else None,
                    "maxOrder": (self.ref.item(item) or {}).get("maxOrderAmountPerImporter"),
                })
        for reg in self.buildings:
            if reg.get("businessTypeName") != "ba:businesstype_wholesalestore":
                continue
            neighborhood = self._neighborhood(reg)
            for item in reg.get("cachedAvailableProducts") or []:
                purchase = p.purchase_price_estimate(item, neighborhood)
                rows.append({
                    "kind": "wholesaler", "supplier": reg.get("BusinessName"), "address": _building_address(reg),
                    "neighborhood": clean(neighborhood), "item": clean(item), "itemLabel": self.ref.label(item),
                    "available": True, "needsGameOption": False, "ingredients": None, "contractAmount": None,
                    "purchasePriceEstimate": round(purchase, 4) if purchase is not None else None,
                    "maxOrder": (self.ref.item(item) or {}).get("maxWholesaleOrderAmount"),
                })
        for item, recipe in self.ref.recipes.items():
            out_amount = recipe["output"].get("amount") or 1
            costs = [p.purchase_price_estimate(i["item"]) for i in recipe["ingredients"]]
            rows.append({
                "kind": "factory", "supplier": "Factory (your own)", "address": None, "neighborhood": None,
                "item": clean(item), "itemLabel": self.ref.label(item),
                "available": True, "needsGameOption": False,
                "ingredients": " + ".join(f"{i['amount']} {self.ref.label(i['item'])}" for i in recipe["ingredients"])
                               + f" → {out_amount}",
                "contractAmount": None,
                # Coût des ingrédients par unité produite (hors salaires, loyer et machines de l'usine).
                "purchasePriceEstimate": round(sum(c * i["amount"] for c, i in zip(costs, recipe["ingredients"])) / out_amount, 4)
                                         if None not in costs else None,
                "maxOrder": None,
            })
        return rows

    def competitor_prices(self) -> list[Row]:
        """Offres des concurrents sur les produits que le joueur vend, dans ses quartiers."""
        if not self.pricing:
            return []
        p = self.pricing
        rows = []
        for b in self.player_buildings:
            neighborhood = self._neighborhood(b)
            for rp in b.get("retailPrices") or []:
                if rp["price"] <= 0:
                    continue
                for price, reg in p.sellers(rp["itemName"], neighborhood):
                    if reg.get("RentedByPlayer"):
                        continue
                    rows.append({
                        "playerAddress": _building_address(b), "playerBusiness": b.get("BusinessName"),
                        "item": clean(rp["itemName"]), "itemLabel": self.ref.label(rp["itemName"]),
                        "neighborhood": clean(neighborhood),
                        "competitorAddress": _building_address(reg), "competitor": reg.get("BusinessName"),
                        "rivalId": reg.get("businessOwnerRivalId") or None,
                        "rival": self.rival_name(reg.get("businessOwnerRivalId")),
                        "competitorPrice": round(price, 2), "playerPrice": round(rp["price"], 2),
                        "priceGap": round(price - rp["price"], 2),
                    })
        # Un même concurrent apparaît une fois par commerce du joueur qui vend le produit : on dédoublonne.
        unique = {(r["item"], r["neighborhood"], r["competitorAddress"]): r for r in rows}
        return sorted(unique.values(), key=lambda r: (r["item"], r["neighborhood"], r["competitorPrice"]))

    def tables(self) -> dict[str, list[Row]]:
        return {
            "businesses": self.businesses(),
            "prices": self.prices(),
            "market_prices": self.market_prices(),
            "competitor_prices": self.competitor_prices(),
            "suppliers": self.suppliers(),
            "staffing": self.staffing(),
            "staffing_hours": self.staffing_hours(),
            "marketing": self.marketing(),
            "marketing_options": self.marketing_options(),
            "employees": self.employees_table(),
            "inventory": self.inventory(),
            "retail_prices": self.retail_prices(),
            "sales_history": self.sales_history(),
            "daily_finances": self.daily_finances(),
            "daily_totals": self.daily_totals(),
            "transactions": self.transactions(),
            "vehicles": self.vehicles(),
            "market": self.market(),
            "market_events": self.market_events(),
            "city_buildings": self.city_buildings(),
            "buildings_for_sale": self.buildings_for_sale(),
            "rivals": self.rivals(),
            "import_partnerships": self.import_partnerships(),
            "candidates": self.candidates(),
            "candidate_fits": self.candidate_fits(),
            "employee_demands": self.employee_demands(),
            "salary_negotiations": self.salary_negotiations(),
            "contacts": self.contacts(),
            "messages": self.messages(),
            "manager_plans": self.manager_plans(),
            "logistics_targets": self.logistics_targets(),
            "pricing_plan_prices": self.pricing_plan_prices(),
            "quests": self.quests(),
            "notifications": self.notifications(),
        }
