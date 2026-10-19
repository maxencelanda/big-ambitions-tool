import unittest

from bigambitions import marketing


class FakeContext(marketing.Context):
    """Contexte sans sauvegarde : seules les valeurs utiles au calcul de la promotion."""

    def __init__(self, sqm, traffic, strength, reach_multiplier=1.0):
        self.sqm, self.traffic, self.strength, self.reach_multiplier = sqm, traffic, strength, reach_multiplier


class PromotionTest(unittest.TestCase):
    def test_reach_is_relative_to_the_building_size(self):
        ctx = FakeContext(sqm=285, traffic=12, strength=0.9)
        # Error Affairs : 20 + 40 + 60 + 100 m² sur 285 m² -> 77 points, promotion 81 dans le jeu.
        self.assertEqual(ctx.marketing_points(220), 77)
        self.assertEqual(ctx.promotion(220), 81)

    def test_float32_rounding_matches_the_game(self):
        # Error Legal Group : 13 + 95 × 0,7f = 79,5 en float32, arrondi à 80 comme dans la sauvegarde.
        ctx = FakeContext(sqm=285, traffic=13, strength=0.699999988079071)
        self.assertEqual(ctx.marketing_points(270), 95)
        self.assertEqual(ctx.promotion(270), 80)

    def test_reach_and_promotion_are_capped(self):
        ctx = FakeContext(sqm=75, traffic=30, strength=0.9)
        self.assertEqual(ctx.marketing_points(600), 100)
        self.assertEqual(ctx.promotion(600), 100)


if __name__ == "__main__":
    unittest.main()
