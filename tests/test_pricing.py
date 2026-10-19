import unittest

from bigambitions import find_latest_save, load
from bigambitions.pricing import Pricing, neighborhood_price_index
from bigambitions.reference import Reference, ReferenceMissing

GD = "ba:neighborhood_garmentdistrict"
BURGER = "ba:itemname_burger"


class FakeReference:
    """Référentiel minimal : un quartier (Garment District) et un produit (burger)."""

    neighborhoods = {GD: {"neighbourhood": GD, "workingClassPercentage": 70, "middleClassPercentage": 22,
                          "upperClassClassPercentage": 8}}
    items = {BURGER: {"itemName": BURGER, "defaultMarketPrice": 12.5, "wholesalePrice": 4.75, "isADemandedProduct": 1}}

    def item(self, name):
        return self.items.get(name)

    def neighborhood_of(self, street, number):
        return GD


def registration(price, player=False, in_stock=True, name="Shop"):
    return {"BusinessName": name, "RentedByPlayer": player, "StreetName": "s", "StreetNumber": 1,
            "retailPrices": [{"itemName": BURGER, "price": price}],
            "cachedAvailableProducts": [BURGER] if in_stock else []}


def game(registrations=(), monopoly=False):
    return {"BuildingRegistrations": list(registrations), "gameVariables": {"marketPriceMultiplier": 0.7},
            "productMarketEntries": [{"itemName": BURGER, "importPriceIndex": 1.0,
                                      "demandValues": [{"neighborhood": GD, "hasPlayerMonopoly": monopoly}]}]}


class PricingFormulas(unittest.TestCase):
    def test_neighborhood_index(self):
        self.assertAlmostEqual(neighborhood_price_index(FakeReference.neighborhoods[GD]), 1.284, places=5)

    def test_optimal_and_ceiling_without_competition(self):
        p = Pricing(game(), FakeReference())
        self.assertAlmostEqual(p.optimal_price(BURGER, GD), 16.05, places=3)
        # float32 : 12.5 × 1.284 = 16.0499…, tronqué au centime comme le fait le jeu
        self.assertEqual(p.ceiling(BURGER, GD), 16.04)

    def test_monopoly_adds_thirty_percent_of_default(self):
        p = Pricing(game(monopoly=True), FakeReference())
        self.assertAlmostEqual(p.optimal_price(BURGER, GD), 12.5 * (1.284 + 0.3), places=3)
        self.assertAlmostEqual(p.max_acceptable_price(BURGER, GD), 12.5 * (1.284 + 0.3), places=3)

    def test_cheaper_competitor_lowers_ceiling(self):
        p = Pricing(game([registration(10.0, name="Rival")]), FakeReference())
        self.assertEqual(p.reference_price(BURGER, GD), 10.0)
        # 10 × 1.284 en float32 = 12.8399…, tronqué à 12.83
        self.assertEqual(p.ceiling(BURGER, GD), 12.83)
        self.assertEqual(p.lowest_competitor(BURGER, GD)[1]["BusinessName"], "Rival")

    def test_competitor_without_stock_is_ignored(self):
        p = Pricing(game([registration(10.0, in_stock=False)]), FakeReference())
        self.assertEqual(p.ceiling(BURGER, GD), 16.04)

    def test_player_price_counts_even_without_stock_flag(self):
        p = Pricing(game([registration(11.0, player=True, in_stock=False)]), FakeReference())
        self.assertEqual(p.lowest_market_price(BURGER, GD), 11.0)

    def test_purchase_estimate_uses_difficulty_multiplier(self):
        p = Pricing(game(), FakeReference())
        self.assertAlmostEqual(p.purchase_price_estimate(BURGER), 4.75 * 0.7)


class MarketFormulas(unittest.TestCase):
    def test_optimal_providers(self):
        p = Pricing(game(), FakeReference())
        self.assertEqual(p.optimal_providers(BURGER), 7)  # ceil(sqrt(1300 / 12.5)) = 11, plafonné à 7
        FakeReference.items["ba:itemname_fee"] = {"itemName": "ba:itemname_fee", "defaultMarketPrice": 150.0}
        self.addCleanup(FakeReference.items.pop, "ba:itemname_fee")
        self.assertEqual(p.optimal_providers("ba:itemname_fee"), 3)

    def test_shortage_raises_purchase_price(self):
        g = game()
        g["Day"] = 10
        g["marketEvents"] = [{"type": 3, "itemName": BURGER, "neighbourhood": GD, "startDay": 8, "durationInDays": 5}]
        p = Pricing(g, FakeReference())
        self.assertAlmostEqual(p.purchase_price_estimate(BURGER, GD), 4.75 * 0.7 * 1.25)
        self.assertAlmostEqual(p.purchase_price_estimate(BURGER, "elsewhere"), 4.75 * 0.7)


class PricingAgainstSave(unittest.TestCase):
    def test_rent_formula_matches_rented_buildings(self):
        try:
            ref = Reference.load()
            g = load(find_latest_save())["game"]
        except (ReferenceMissing, FileNotFoundError) as e:
            self.skipTest(str(e))
        for reg in g["BuildingRegistrations"]:
            if reg.get("RentedByPlayer"):
                with self.subTest(business=reg.get("BusinessName")):
                    self.assertEqual(ref.daily_rent(ref.building(reg["StreetName"], reg["StreetNumber"])), round(reg["RentPerDay"]))

    """Les prix fixés par les managers de prix (compétence max) doivent égaler le plafond calculé."""

    def test_pricing_manager_prices_match_ceiling(self):
        try:
            ref = Reference.load()
            g = load(find_latest_save())["game"]
        except (ReferenceMissing, FileNotFoundError) as e:
            self.skipTest(str(e))
        p = Pricing(g, ref)
        managed = {(a["itemName"], plan["supervisedNeighborhood"])
                   for plan in g.get("pricingManagerPlans", []) for a in plan.get("appliedPrices", [])}
        checked = 0
        for reg in g["BuildingRegistrations"]:
            if not reg.get("RentedByPlayer"):
                continue
            neighborhood = ref.neighborhood_of(reg["StreetName"], reg["StreetNumber"])
            for rp in reg.get("retailPrices") or []:
                if rp["price"] > 0 and (rp["itemName"], neighborhood) in managed:
                    with self.subTest(business=reg["BusinessName"], item=rp["itemName"]):
                        self.assertAlmostEqual(rp["price"], p.ceiling(rp["itemName"], neighborhood), delta=0.005)
                    checked += 1
        if not checked:
            self.skipTest("aucun prix géré par un manager dans cette sauvegarde")


if __name__ == "__main__":
    unittest.main()
