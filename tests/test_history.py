import sqlite3
import unittest

from bigambitions import history
from bigambitions.db import _insert


def rows(table, name):
    return sorted(table.execute(f'SELECT * FROM "{name}"').fetchall())


class HistoryMerge(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")

    def merge(self, tables, day):
        history.merge(self.db, tables, day, _insert)

    def test_journal_days_are_replaced_by_latest_save(self):
        self.merge({"daily_totals": [{"day": 1, "totalProfit": 10}, {"day": 2, "totalProfit": 20}]}, day=3)
        self.merge({"daily_totals": [{"day": 2, "totalProfit": 25}, {"day": 3, "totalProfit": 30}]}, day=4)
        self.assertEqual(rows(self.db, "hist_daily_totals"), [(1, 10), (2, 25), (3, 30)])

    def test_sliding_window_keeps_known_first_day(self):
        full = [{"day": 5, "hour": h, "amount": 1} for h in range(3)]
        self.merge({"transactions": full}, day=5)
        partial = [{"day": 5, "hour": 2, "amount": 1}, {"day": 6, "hour": 0, "amount": 2}]
        self.merge({"transactions": partial}, day=6)
        self.assertEqual(len([r for r in rows(self.db, "hist_transactions") if r[0] == 5]), 3)

    def test_snapshot_one_per_day(self):
        self.merge({"prices": [{"item": "burger", "price": 16}]}, day=10)
        self.merge({"prices": [{"item": "burger", "price": 17}]}, day=10)
        self.merge({"prices": [{"item": "burger", "price": 18}]}, day=11)
        self.assertEqual(rows(self.db, "hist_prices"), [(10, "burger", 17), (11, "burger", 18)])

    def test_rollback_to_older_save_drops_abandoned_timeline(self):
        self.merge({"prices": [{"item": "burger", "price": 16}]}, day=20)
        self.merge({"daily_totals": [{"day": 19, "totalProfit": 1}]}, day=20)
        self.merge({"prices": [{"item": "burger", "price": 15}]}, day=12)
        self.assertEqual(rows(self.db, "hist_prices"), [(12, "burger", 15)])
        self.assertEqual(rows(self.db, "hist_daily_totals"), [])

    def test_new_columns_are_added(self):
        self.merge({"prices": [{"item": "burger", "price": 16}]}, day=1)
        self.merge({"prices": [{"item": "burger", "price": 16, "ceiling": 16.04}]}, day=2)
        self.assertEqual(rows(self.db, "hist_prices")[-1], (2, "burger", 16, 16.04))


if __name__ == "__main__":
    unittest.main()
