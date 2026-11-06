import unittest

from bigambitions import portfolio as pf


def option(**kw):
    o = {"salesRatio": 0.66, "demand": 58, "impact": 1.0, "amountFactor": 1.0, "importCost": None, "wholesaleCost": None,
         "kind": "product", "costEstimate": 5.0, "fromFactory": False}
    o.update(kw)
    return o


class ModelTest(unittest.TestCase):
    def test_game_formula(self):
        # 57 clients, satisfaction 91 : 57 × 0,66 × 0,58 × 1,41 ≈ 30,8 romans par jour (réel : 31,3).
        self.assertAlmostEqual(pf._model_units(option(), 57, 91), 57 * 0.66 * 0.58 * 1.41, places=6)

    def test_cheapest_supply_wins(self):
        self.assertEqual(pf._best_cost(option(importCost=3.0, wholesaleCost=4.0)), (3.0, "import"))
        self.assertEqual(pf._best_cost(option()), (5.0, None))


class VerdictTest(unittest.TestCase):
    def base(self, **kw):
        c = {"kind": "product", "consumed": False, "marginPerDay": 100.0, "share": 0.2, "manualRestock": False, "importSavingPerDay": None}
        c.update(kw)
        return c

    def test_small_hand_restocked_product_is_dropped(self):
        self.assertEqual(pf._product_verdict(self.base(share=0.01, manualRestock=True))[0], "drop")

    def test_products_used_by_services_are_kept(self):
        self.assertEqual(pf._product_verdict(self.base(marginPerDay=-90, consumed=True))[0], "keep")

    def test_business_losing_money(self):
        r = {"profitPerDay": -10, "likelyGainPerDay": 0, "productGainPerDay": 0, "possibleGainPerDay": 0, "manualRestock": 0}
        self.assertEqual(pf._verdict(r, 1000)[0], "close")


if __name__ == "__main__":
    unittest.main()
