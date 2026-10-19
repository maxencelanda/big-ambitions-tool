import unittest

from bigambitions import staffing
from bigambitions.market import demand_with


class FakeReference:
    business_types = {"ba:businesstype_agency": {
        "dayFactorMultipliers": [{"dayOfWeekOrdered": d, "multiplier": 1.0} for d in range(1, 8)],
        "hourlyFactorMultipliers": [{"startingHour": 0, "endingHour": 24, "multiplier": 1.0}],
    }}
    items = {"ba:itemname_desk": {"addedCustomersPerHour": 1}}

    def item(self, name):
        return self.items.get(name)


def agency(desks: int, customers_per_day: int, hours=(10, 14)):
    """Agence ouverte le lundi de 10 h à 14 h, ``desks`` bureaux occupés tout le créneau."""
    return {
        "businessTypeName": "ba:businesstype_agency",
        "itemInstances": {f"d{i}": {"itemName": "ba:itemname_desk"} for i in range(desks)},
        "orderHistory": [{"dayNumber": 1, "totalCustomers": customers_per_day}],  # jour 1 = lundi
        "scheduleDays": [{"day": 1, "isOpen": True, "openingHourSlots": [{"startingHour": hours[0], "endingHour": hours[1]}],
                          "workShifts": [{"type": 1, "employeeId": f"e{i}", "itemInstanceId": f"d{i}",
                                          "startingHour": hours[0], "endingHour": hours[1]} for i in range(desks)]}],
    }


class StaffingTest(unittest.TestCase):
    def test_idle_desks_are_counted_with_margin(self):
        wages = {f"e{i}": 10.0 for i in range(6)}
        result = staffing.analyse(agency(6, 8), FakeReference(), "office", wages)
        # 8 clients sur 4 h = 2/h ; avec 20 % de marge : ⌈2,4⌉ = 3 bureaux nécessaires, 3 inutiles par heure
        self.assertEqual(result["neededStationHoursPerWeek"], 12)
        self.assertEqual(result["idleStationHoursPerWeek"], 12)
        self.assertEqual(result["idleWagesPerWeek"], 120.0)
        self.assertEqual(result["understaffedHours"], 0)

    def test_departed_employee_shift_is_ignored(self):
        wages = {"e0": 10.0}  # e1 a été débauché : son créneau ne compte pas
        result = staffing.analyse(agency(2, 4), FakeReference(), "office", wages)
        self.assertEqual(result["staffedStationHoursPerWeek"], 4)

    def test_understaffed_hours(self):
        result = staffing.analyse(agency(1, 12), FakeReference(), "office", {"e0": 10.0})
        self.assertEqual(result["understaffedHours"], 4)  # 3 clients/h pour 1 bureau


class DemandTest(unittest.TestCase):
    def test_formula_and_floor(self):
        self.assertAlmostEqual(demand_with(1, 3), 100 - 100 / 3)
        self.assertEqual(demand_with(3, 3), 31.5)  # sous 30 : le jeu tire 29–34
        self.assertEqual(demand_with(0, 3, event_impact=20), 100.0)

    def test_third_agency_costs_little_once_at_floor(self):
        now, after = demand_with(2, 3), demand_with(3, 3)
        self.assertLess((now - after) / now, 0.06)


if __name__ == "__main__":
    unittest.main()
