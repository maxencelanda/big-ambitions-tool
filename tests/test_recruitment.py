import unittest

from bigambitions import find_latest_save, load, recruitment
from bigambitions.reference import Reference, ReferenceMissing


class FakeReference:
    skills = {"ba:skill_customerservice": {"baseHourlyWage": 20.0}}
    items = {"ba:itemname_watercooler": {"itemsThatCanShowcase": ["ba:itemname_waterbottle"]},
             "ba:itemname_desk": {}}

    def item(self, name):
        return self.items.get(name)

    def label(self, key):
        return key


def business(open_days=(1, 2, 3, 4, 5, 6, 7), hours=(9, 17), items=None):
    return {
        "itemInstances": items or {},
        "dirtSpots": [],
        "scheduleDays": [{"day": d, "isOpen": d in open_days,
                          "openingHourSlots": [{"startingHour": hours[0], "endingHour": hours[1]}],
                          "workShifts": [{"employeeId": "e1", "startingHour": 9, "endingHour": 17, "type": 1,
                                          "itemInstanceId": "desk"}] if d in (1, 2, 3, 4, 5) else []}
                         for d in range(1, 8)],
    }


EMPLOYEE = {"id": "e1", "assignedWeeklyHours": 40, "assignedWeeklyDays": [1, 2, 3, 4, 5], "assignedHrManagerPlanId": None}


class Formulas(unittest.TestCase):
    def test_market_wage(self):
        self.assertAlmostEqual(recruitment.market_wage(FakeReference(), "ba:skill_customerservice", 100, 0.7),
                               20 * (1 + 100 ** 1.05 / 100) * 0.7)

    def test_satisfaction_cap_thresholds(self):
        self.assertEqual(recruitment.satisfaction_cap(1, 3), 60)
        self.assertEqual(recruitment.satisfaction_cap(2, 3), 80)
        self.assertEqual(recruitment.satisfaction_cap(3, 3), 100)
        self.assertIsNone(recruitment.satisfaction_cap(0, 0))

    def test_cleanliness_from_dirt_spots(self):
        self.assertEqual(recruitment.building_cleanliness({"dirtSpots": [{"dirtiness": 2}, {"dirtiness": 3}]}), 100)
        # moyenne 10, visible (≥ 5) 10 → 100 − 10 − 10
        self.assertEqual(recruitment.building_cleanliness({"dirtSpots": [{"dirtiness": 20}, {"dirtiness": 0}]}), 80)


class Demands(unittest.TestCase):
    def ctx(self, **kwargs):
        return recruitment.BusinessContext(business(**kwargs), FakeReference(), {}, player_happiness=80)

    def test_employee_schedule_demands(self):
        ctx = self.ctx()
        free_weekends = {"$script": "FreeOnDays", "freeDays": [6, 7]}
        full_time = {"$script": "HoursWorkingPerWeek", "betweenHours": {"x": 30, "y": 50}}
        no_evenings = {"$script": "HasNoShiftBetweenHours", "shiftPeriod": {"x": 18, "y": 22}, "nextShiftPeriod": {"x": 0, "y": 0}}
        no_afternoons = {"$script": "HasNoShiftBetweenHours", "shiftPeriod": {"x": 14, "y": 16}, "nextShiftPeriod": {"x": 0, "y": 0}}
        self.assertEqual(recruitment.evaluate(free_weekends, ctx, EMPLOYEE)[0], "met")
        self.assertEqual(recruitment.evaluate(full_time, ctx, EMPLOYEE)[0], "met")
        self.assertEqual(recruitment.evaluate(no_evenings, ctx, EMPLOYEE)[0], "met")
        self.assertEqual(recruitment.evaluate(no_afternoons, ctx, EMPLOYEE)[0], "missing")

    def test_item_in_building_must_be_filled(self):
        demand = {"$script": "HasItemInBuilding", "itemNames": ["ba:itemname_watercooler"]}
        empty = self.ctx(items={"w": {"itemName": "ba:itemname_watercooler", "cargoInstances": []}})
        full = self.ctx(items={"w": {"itemName": "ba:itemname_watercooler",
                                     "cargoInstances": [{"itemName": "ba:itemname_waterbottle", "amount": 3}]}})
        self.assertEqual(recruitment.evaluate(demand, empty, EMPLOYEE), ("missing", "refill the ba:itemname_watercooler"))
        self.assertEqual(recruitment.evaluate(demand, full, EMPLOYEE)[0], "met")

    def test_candidate_schedule_is_arrangeable_unless_business_never_allows_it(self):
        weekends = {"$script": "FreeOnDays", "freeDays": [6, 7]}
        self.assertEqual(recruitment.evaluate(weekends, self.ctx(), None)[0], "arrangeable")
        self.assertEqual(recruitment.evaluate(weekends, self.ctx(open_days=(6, 7)), None)[0], "missing")


class AgainstSave(unittest.TestCase):
    def test_satisfaction_matches_demands_cap(self):
        """La satisfaction réelle doit être au plafond calculé, ou en train d'y monter (0,6 point par heure)."""
        try:
            ref = Reference.load()
            g = load(find_latest_save())["game"]
        except (ReferenceMissing, FileNotFoundError) as e:
            self.skipTest(str(e))
        from bigambitions.model import Save, address
        save = Save({"game": g}, ref)
        contexts = save._contexts()
        ok = total = 0
        for e in g["EmployeeInstances"]:
            ctx = contexts.get(address(e.get("assignedAddress")))
            if e.get("poached") or not ctx or not e.get("demands"):
                continue
            cap = recruitment.assess(e["demands"], ctx, e, ref.job_demands)["cap"]
            total += 1
            ok += abs(e["satisfaction"] - cap) <= 1 or e["satisfaction"] < cap
        self.assertGreaterEqual(ok / total, 0.9)


if __name__ == "__main__":
    unittest.main()
