import unittest

from bigambitions import planning


class BestWindowTest(unittest.TestCase):
    def test_keeps_the_most_profitable_run_of_hours(self):
        # Une heure qui perd un peu entre deux heures rentables reste ouverte : la plage entière rapporte plus.
        self.assertEqual(planning._best_window([-5, 10, -2, 8, -20, 3]), (1, 4, 16))

    def test_closed_when_no_hour_pays(self):
        self.assertIsNone(planning._best_window([-1, -3, 0]))


class ShiftsTest(unittest.TestCase):
    def test_profile_is_split_into_layers(self):
        stations = {9: 1, 10: 2, 11: 2, 12: 1}
        self.assertEqual(planning._shifts(stations), [{"start": 9, "end": 13, "stations": 1},
                                                      {"start": 10, "end": 12, "stations": 1}])

    def test_identical_layers_are_merged(self):
        self.assertEqual(planning._shifts({8: 3, 9: 3}), [{"start": 8, "end": 10, "stations": 3}])


if __name__ == "__main__":
    unittest.main()
