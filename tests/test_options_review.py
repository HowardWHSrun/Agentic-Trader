"""Offline tests for scripts/options_review.py."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import options_review as rv  # noqa: E402


def snap(at, prices, scores):
    return {"at": at, "rules_version": "t", "scores": scores, "prices": prices}


def day(date, first, last):
    return {"date": date, "first": first, "last": last}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.scores = {"A": 90, "B": 80, "C": 50, "D": 20, "E": 10}

    def make_days(self, n, good=True):
        days, pa, pd = [], 100.0, 100.0
        for i in range(n):
            pa *= 1.01 if good else 0.99
            pd *= 0.99 if good else 1.01
            prices = {"A": pa, "B": pa, "C": 100, "D": pd, "E": pd, "SPY": 100}
            s = snap(f"2026-11-{i + 1:02d}T20:00:00Z", prices, self.scores)
            days.append(day(f"2026-11-{i + 1:02d}", s, s))
        return days

    def test_grade_groups_and_correlation(self):
        start = snap("a", {"A": 100, "B": 100, "C": 100, "D": 100, "E": 100, "SPY": 100}, self.scores)
        end = snap("b", {"A": 103, "B": 101, "C": 100, "D": 98, "E": 97, "SPY": 100}, self.scores)
        g = rv.grade(start, end)
        self.assertEqual(g["bull"]["n"], 2)
        self.assertEqual(g["bull"]["hit_rate"], 100.0)
        self.assertEqual(g["bear"]["hit_rate"], 100.0)
        self.assertEqual(g["bull_minus_bear"], 4.5)
        self.assertEqual(g["rank_corr"], 1.0)

    def test_verdict_needs_ten_days_then_judges(self):
        self.assertEqual(rv.review(self.make_days(5), "2026-11-05")["verdict"], "样本不足")
        self.assertEqual(rv.review(self.make_days(12), "2026-11-12")["verdict"], "有效")
        self.assertEqual(rv.review(self.make_days(12, good=False), "2026-11-12")["verdict"], "表现差")

    def test_report_renders(self):
        self.assertIn("收盘复盘", rv.report(rv.review(self.make_days(6), "2026-11-06")))


if __name__ == "__main__":
    unittest.main()
