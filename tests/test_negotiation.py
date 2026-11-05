import unittest

from bigambitions import negotiation as neg


class ThresholdsTest(unittest.TestCase):
    def test_reproduces_a_negotiation_from_the_save(self):
        # Négociation commencée le jour 226 : seuils lus dans la sauvegarde (float32).
        negotiate, firm = neg.thresholds("YnujKXHqskqX8KUTaiG+Ow==", 226)
        self.assertAlmostEqual(negotiate, 0.8463777303695679, places=6)
        self.assertAlmostEqual(firm, 0.6030853390693665, places=6)

    def test_thresholds_stay_in_the_game_ranges(self):
        for day in range(1, 50):
            negotiate, firm = neg.thresholds("abc==", day)
            self.assertTrue(0.8 <= negotiate <= 0.9)
            self.assertTrue(0.6 <= firm <= 0.7)


class SimulateTest(unittest.TestCase):
    def test_closing_right_away_gets_five_percent_off(self):
        result = neg.simulate(40.0, 0.85, 0, 0.5, 5)
        self.assertAlmostEqual(result["final"], 38.01)
        self.assertEqual(result["satisfaction"], 50)

    def test_each_round_lowers_the_counter_and_the_mood(self):
        result = neg.simulate(40.0, 0.85, 2, 0.5, 5)
        counters = [s["counter"] for s in result["script"]]
        self.assertEqual(counters, [37.05, 34.3])
        self.assertEqual(result["mood"], 90)
        self.assertAlmostEqual(result["satisfaction"], 45)

    def test_plan_never_risks_a_walk_away(self):
        p = neg.plan("abc==", 30.0, 10)
        self.assertGreaterEqual(p["options"][-1]["moodCautious"], neg.DECLINE_BELOW)
        self.assertGreaterEqual(p["options"][p["balancedRounds"]]["moodCautious"], neg.GOOD_MOOD)


if __name__ == "__main__":
    unittest.main()
