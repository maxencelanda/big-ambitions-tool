import sqlite3
import unittest

from bigambitions import pnl
from bigambitions.db import _create_table, _insert, columns_of

BUSINESSES = [
    {"address": "1 a", "name": "Shop", "segment": "retail", "typeLabel": "Shop", "employees": 3, "creationDay": 1},
    {"address": "2 b", "name": "Agency", "segment": "office", "typeLabel": "Agency", "employees": 1, "creationDay": 1},
    {"address": "3 c", "name": "HQ", "segment": "headquarters", "typeLabel": "HQ", "employees": 2, "creationDay": 1},
    {"address": "4 d", "name": "Depot", "segment": "logistics", "typeLabel": "Warehouse", "employees": 1, "creationDay": 1},
]


def finance(day, address, sales=0.0, resources=0.0, salaries=0.0, rent=0.0):
    return {"day": day, "address": address, "sales": sales, "resources": resources, "salaries": salaries,
            "rent": rent, "marketing": 0.0, "theft": 0.0, "licensingFees": 0.0,
            "profit": sales - resources - salaries - rent}


def totals(day, business_profit, health=0.0, housing=0.0):
    return {"day": day, "totalBusinessProfit": business_profit, "totalLoanExpenses": 0.0,
            "totalHealthInsuranceExpenses": health, "totalHeadhunterReplacementFees": 0.0, "totalRealEstate": 0.0,
            "totalResidentialExpenses": housing, "totalUnassignedStaffWages": 0.0, "parkingFees": 0.0,
            "salaryIncome": 0.0, "totalProfit": business_profit + health - housing}


class PnlTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        finances = []
        for day in (1, 2):
            finances += [finance(day, "1 a", 1000, 200, 100, 10), finance(day, "2 b", 500, 0, 300, 20),
                         finance(day, "3 c", salaries=150, rent=50), finance(day, "4 d", salaries=40, rent=60)]
        business_profit = {d: sum(f["profit"] for f in finances if f["day"] == d) for d in (1, 2)}
        tables = {
            "source": [{"daysPerYear": 60}],
            "businesses": BUSINESSES,
            "hist_daily_finances": finances,
            "hist_daily_totals": [totals(d, business_profit[d], health=-40, housing=25) for d in (1, 2)],
            # L'entrepôt ne livre que la boutique.
            "logistics_targets": [{"sourceAddress": "4 d", "destinationAddress": "1 a"}],
        }
        for name, rows in tables.items():
            _create_table(self.db, name, columns_of(rows))
            _insert(self.db, name, rows, columns_of(rows))

    def line(self, statement, key):
        return next(l for l in statement["lines"] if l["key"] == key)

    def test_net_profit_reconciles_with_game_total(self):
        s = pnl.statement(self.db, "day", 2)
        self.assertEqual(s["reconciliationGap"], 0)
        self.assertEqual(self.line(s, "operatingProfit")["total"], 2 * (690 + 180))
        self.assertEqual(self.line(s, "overheadHeadquarters")["total"], -400)
        self.assertEqual(self.line(s, "overheadLogistics")["total"], -200)
        self.assertEqual(self.line(s, "housing")["total"], -50)

    def test_allocation_conserves_overhead(self):
        rows = {r["address"]: r for r in pnl.by_business(self.db, 1, 2)}
        allocated = sum(r["allocatedOverhead"] or 0 for r in rows.values())
        # siège (-400) + entrepôt (-200) + assurance santé (-80)
        self.assertAlmostEqual(allocated, -680)

    def test_warehouse_cost_goes_to_the_businesses_it_supplies(self):
        rows = {r["address"]: r for r in pnl.by_business(self.db, 1, 2)}
        self.assertAlmostEqual(rows["1 a"]["allocatedDetail"]["allocatedLogistics"], -200)
        self.assertNotIn("allocatedLogistics", rows["2 b"]["allocatedDetail"])

    def test_headquarters_split_by_headcount(self):
        rows = {r["address"]: r for r in pnl.by_business(self.db, 1, 2)}
        # (-400 siège - 80 assurance) réparti 3 / 1 selon les effectifs
        self.assertAlmostEqual(rows["1 a"]["allocatedDetail"]["allocatedHeadquarters"], -360)
        self.assertAlmostEqual(rows["2 b"]["allocatedDetail"]["allocatedHeadquarters"], -120)

    def test_segment_scope_keeps_only_its_businesses(self):
        s = pnl.statement(self.db, "week", 1, "segment:office")
        self.assertEqual(self.line(s, "revenue")["total"], 1000)
        self.assertFalse(any(l["key"] == "netProfit" for l in s["lines"]))

    def test_weeks_start_on_day_one(self):
        self.assertEqual(pnl.period_of(7, "week", 60), 1)
        self.assertEqual(pnl.period_of(8, "week", 60), 2)
        self.assertEqual(pnl.period_bounds(31, "week", 60), (211, 217))


if __name__ == "__main__":
    unittest.main()
