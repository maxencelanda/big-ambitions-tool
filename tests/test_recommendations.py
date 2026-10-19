import sqlite3
import unittest

from bigambitions import db as database
from bigambitions.recommendations import _ranges


class RangesTest(unittest.TestCase):
    def test_consecutive_hours_with_same_idle_count_are_merged(self):
        hours = [{"day": 1, "hour": h, "idleStations": n} for h, n in [(12, 2), (13, 2), (14, 1), (15, 0), (16, 1)]]
        self.assertEqual(_ranges(hours), ["Mon 12–14 h: 2 fewer", "Mon 14–15 h: 1 fewer", "Mon 16–17 h: 1 fewer"])

    def test_days_are_separate(self):
        hours = [{"day": 1, "hour": 19, "idleStations": 1}, {"day": 2, "hour": 12, "idleStations": 1}]
        self.assertEqual(_ranges(hours), ["Mon 19–20 h: 1 fewer", "Tue 12–13 h: 1 fewer"])


class DismissalsTest(unittest.TestCase):
    def test_user_tables_survive_reimport(self):
        db = sqlite3.connect(":memory:", isolation_level=None)
        database.set_dismissed(db, "price|1 a|burger", True)
        database._create_table(db, "prices", ["item"])
        # replace_all supprime toutes les tables non préservées : on reproduit sa règle.
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            if not database._is_preserved(name):
                db.execute(f'DROP TABLE "{name}"')
        self.assertEqual(db.execute("SELECT key FROM user_dismissals").fetchall(), [("price|1 a|burger",)])
        database.set_dismissed(db, "price|1 a|burger", False)
        self.assertEqual(db.execute("SELECT count(*) FROM user_dismissals").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
