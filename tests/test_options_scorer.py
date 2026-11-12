"""Offline tests for scripts/options_scorer.py using synthetic data (no network)."""
import sys
import unittest
from unittest import mock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import options_scorer as o  # noqa: E402

TODAY = date(2026, 11, 9)


def series(n, start, step, wiggle=0.0):
    bars, d = [], date(2025, 1, 2)
    for i in range(n):
        c = start + step * i + (wiggle if i % 2 else -wiggle)
        bars.append({"t": d.isoformat(), "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 1e6})
        d += timedelta(days=1)
    return bars


def occ(root, exp, cp, strike):
    return f"{root}{exp.strftime('%y%m%d')}{cp}{int(strike * 1000):08d}"


def chain(root, px, exp, cp, oi=500, spread=0.05, step=5):
    rows = []
    for k in range(int(px * 0.8), int(px * 1.2) + 1, step):
        moneyness = (px - k) / px if cp == "C" else (k - px) / px
        delta = max(0.02, min(0.98, 0.5 + moneyness * 4))
        mid = max(0.1, px * 0.04 + (px - k if cp == "C" else k - px) * delta)
        rows.append({"option": occ(root, exp, cp, k), "bid": round(mid - spread / 2, 2),
                     "ask": round(mid + spread / 2, 2), "delta": delta if cp == "C" else -delta,
                     "iv": 0.3, "open_interest": oi, "volume": 10})
    return rows


class FakeClient:
    def __init__(self, bars, chains):
        self._bars, self._chains = bars, chains

    def daily_bars(self, sym):
        return self._bars.get(sym, [])

    def chain(self, sym):
        return {"quote": {}, "options": self._chains.get(sym, []), "timestamp": "x"}


class IndicatorTests(unittest.TestCase):
    def test_sma_and_rsi_extremes(self):
        closes = list(range(1, 31))
        self.assertEqual(o.sma(closes, 5), 28)
        self.assertEqual(o.rsi(closes), 100.0)
        self.assertLess(o.rsi(closes[::-1]), 1)

    def test_parse_occ(self):
        m = o.parse_occ("AAPL261218C00250000")
        self.assertEqual((m["type"], m["strike"], m["expiration"]), ("call", 250.0, date(2026, 12, 18)))
        self.assertIsNone(o.parse_occ("garbage"))


class ScoreTests(unittest.TestCase):
    def test_uptrend_scores_high_downtrend_low(self):
        spy = series(260, 100, 0.05)
        up = o.score_symbol(series(260, 100, 0.5, 0.3), spy, None)
        down = o.score_symbol(series(260, 300, -0.5, 0.3), spy, None)
        self.assertGreaterEqual(up["score"], o.CALL_ENTRY)
        self.assertLessEqual(down["score"], o.PUT_ENTRY)

    def test_short_history_skips_sma200_and_too_short_is_unavailable(self):
        spy = series(260, 100, 0.05)
        res = o.score_symbol(series(100, 100, 0.5, 0.3), spy, None)
        self.assertIsNotNone(res["score"])
        self.assertIsNone(res["sma200"])
        self.assertIsNone(o.score_symbol(series(30, 100, 0.5), spy, None)["score"])


class ContractTests(unittest.TestCase):
    def test_pick_respects_dte_delta_and_liquidity(self):
        exp = TODAY + timedelta(days=30)
        pick = o.pick_contracts(chain("X", 100, exp, "C"), "call", TODAY, 25)
        self.assertIsNotNone(pick)
        self.assertTrue(o.LONG_DELTA[0] <= pick["single"]["delta"] <= o.LONG_DELTA[1])
        self.assertIsNone(o.pick_contracts(chain("X", 100, exp, "C", oi=5), "call", TODAY, 25))
        self.assertIsNone(o.pick_contracts(chain("X", 100, TODAY + timedelta(days=5), "C"), "call", TODAY, 25))

    def test_budget_falls_back_to_spread_or_blocks(self):
        pick = {"single": {"cost_per_contract": 900}, "spread": {"max_loss_per_contract": 300}, "prefer": "single"}
        o.SINGLE_LEG_ONLY = False
        self.assertEqual(o.choose_structure(pick, 500), ("spread", None))
        o.SINGLE_LEG_ONLY = True
        self.assertIsNone(o.choose_structure(pick, 500)[0])  # level 2: no spreads
        pick["spread"] = None
        structure, reason = o.choose_structure(pick, 500)
        self.assertIsNone(structure)
        self.assertIn("$900", reason)


class ExitTests(unittest.TestCase):
    def sig(self, **kw):
        base = {"symbol": "X", "type": "call", "structure": "single", "expiration": "2026-12-18",
                "entry_cost": 2.0, "legs": [{"contract": "C1", "qty": 1, "strike": 100, "entry_mid": 2.0}]}
        return {**base, **kw}

    def check(self, mid, score=80, today=TODAY, earnings=None, **kw):
        snaps = {"C1": {"bid": mid - 0.05, "ask": mid + 0.05}}
        return o.review_open([self.sig(**kw)], snaps, {"X": {"score": score}}, earnings or {}, today)

    def test_rules(self):
        self.assertIn("止盈", self.check(3.7)[1][0]["exit_reason"])
        self.assertIn("止损", self.check(0.9)[1][0]["exit_reason"])
        self.assertIn("时间", self.check(2.0, today=date(2026, 12, 10))[1][0]["exit_reason"])
        self.assertIn("财报", self.check(2.0, earnings={"X": "2026-11-10"})[1][0]["exit_reason"])
        self.assertIn("趋势", self.check(2.0, score=45)[1][0]["exit_reason"])  # legacy v1 signals
        # v2 dip signals leave on the rebound, not on the trend score.
        snaps = {"C1": {"bid": 2.05, "ask": 2.15}}
        dip = self.sig(setup="dip")
        _, exits = o.review_open([dip], snaps, {"X": {"score": 40, "above_sma5": True}}, {}, TODAY)
        self.assertIn("反弹到位", exits[0]["exit_reason"])
        still, exits = o.review_open([dip], snaps, {"X": {"score": 40, "above_sma5": False}}, {}, TODAY)
        self.assertEqual((len(still), len(exits)), (1, 0))
        # The rebound exit is only judged near the close.
        still, exits = o.review_open([dip], snaps, {"X": {"score": 40, "above_sma5": True}}, {}, TODAY, near_close=False)
        self.assertEqual((len(still), len(exits)), (1, 0))
        still, exits = self.check(2.2)
        self.assertEqual((len(still), len(exits)), (1, 0))
        self.assertEqual(still[0]["pnl_pct"], 10.0)


class RunTests(unittest.TestCase):
    @mock.patch.object(o, "MIN_HV20", 0.0)  # the fake series are smooth; volatility filter tested below
    def test_end_to_end_with_fake_data(self):
        bars = {s: series(260, 100, 0.05) for s in o.UNIVERSE + o.BENCHMARKS}
        bars["KO"] = series(260, 50, 0.2, 0.1)    # strong uptrend ...
        for k, drop in zip((-4, -3, -2, -1), (1.5, 3.0, 4.5, 6.0)):  # ... then four lower closes in a row
            b = bars["KO"][k]
            bars["KO"][k] = {**b, "c": b["c"] - drop, "l": b["l"] - drop}
            x = bars["XLP"][k]  # the sector fell too, so this is a market dip rather than company news
            bars["XLP"][k] = {**x, "c": x["c"] - drop, "l": x["l"] - drop}
        bars["BAC"] = series(260, 120, -0.3, 0.1)  # strong downtrend
        exp = TODAY + timedelta(days=30)
        chains = {"KO": chain("KO", bars["KO"][-1]["c"], exp, "C"),
                  "BAC": chain("BAC", bars["BAC"][-1]["c"], exp, "P")}
        now = datetime(2026, 11, 9, 20, 45, tzinfo=timezone.utc)  # 14:45 CT, inside the entry window
        first = o.run(FakeClient(bars, chains), TODAY, now, {}, {"open": []}, max_cost=5000)
        self.assertEqual(first["entries"], [])  # must be confirmed on a second scan
        self.assertEqual(set(first["qualified"]), {"KO"})  # calls on dips only; no puts
        res = o.run(FakeClient(bars, chains), TODAY, now, {}, {"open": [], "qualified": first["qualified"]}, max_cost=5000)
        self.assertEqual(res["coverage"]["scored"], 32)
        ko = next(r for r in res["rankings"] if r["symbol"] == "KO")
        self.assertTrue(ko["uptrend"] and ko["down_streak"] >= o.DOWN_STREAK_ENTRY)
        self.assertEqual(ko["dip_score"], 100)
        # Outside the closing window the same data only produces a "confirm near the close" note.
        early = o.run(FakeClient(bars, chains), TODAY, datetime(2026, 11, 9, 16, tzinfo=timezone.utc), {},
                      {"open": [], "qualified": ["KO"]}, max_cost=5000)
        self.assertEqual(early["entries"], [])
        self.assertIn("收盘前", next(r for r in early["rankings"] if r["symbol"] == "KO")["setup"])
        self.assertEqual(res["rankings"][-1]["symbol"], "BAC")
        self.assertEqual({(e["symbol"], e["type"], e["setup"]) for e in res["entries"]}, {("KO", "call", "dip")})
        self.assertIn("进场", o.report(res))
        # Earnings inside the window blocks the entry.
        res2 = o.run(FakeClient(bars, chains), TODAY, now, {"KO": "2026-11-12"}, {"open": [], "qualified": ["KO", "BAC"]}, max_cost=5000)
        self.assertNotIn("KO", {e["symbol"] for e in res2["entries"]})
        # A stock falling alone in a calm market (likely company news) is skipped.
        alone = {**bars, "XLP": series(260, 100, 0.05)}
        res4 = o.run(FakeClient(alone, chains), TODAY, now, {}, {"open": [], "qualified": ["KO"]}, max_cost=5000)
        self.assertEqual(res4["entries"], [])
        self.assertIn("板块", next(r for r in res4["rankings"] if r["symbol"] == "KO")["entry_block"])
        # A quiet stock (20-day volatility under MIN_HV20) is skipped.
        with mock.patch.object(o, "MIN_HV20", 1000.0):
            res3 = o.run(FakeClient(bars, chains), TODAY, now, {}, {"open": [], "qualified": ["KO"]}, max_cost=5000)
        self.assertEqual(res3["entries"], [])
        self.assertIn("波动", next(r for r in res3["rankings"] if r["symbol"] == "KO")["entry_block"])
        # A fresh exit puts the stock on cooldown.
        state = {"open": [], "qualified": ["KO", "BAC"], "closed": [{"symbol": "KO", "exit_date": "2026-11-08"}]}
        res3 = o.run(FakeClient(bars, chains), TODAY, now, {}, state, max_cost=5000)
        self.assertNotIn("KO", {e["symbol"] for e in res3["entries"]})
        # Daily cap: two signals already opened today blocks a third.
        opened = [{"symbol": s, "entry_date": TODAY.isoformat(), "exit_date": TODAY.isoformat()} for s in ("X1", "X2")]
        res4 = o.run(FakeClient(bars, chains), TODAY, now, {}, {"open": [], "closed": opened, "qualified": ["KO", "BAC"]}, max_cost=5000)
        self.assertEqual(res4["entries"], [])


if __name__ == "__main__":
    unittest.main()


class DipV24Tests(unittest.TestCase):
    def sig(self, **kw):
        base = {"symbol": "X", "type": "call", "structure": "single", "expiration": "2026-11-27",
                "entry_cost": 2.0, "legs": [{"contract": "C1", "qty": 1, "strike": 100, "entry_mid": 2.0}],
                "setup": "dip", "exit_rules": "v2.4", "entry_date": "2026-11-09",
                "disaster_line": 90.0, "runner_level": 106.0}
        return {**base, **kw}

    def run_one(self, mid, price, above5=False, today=TODAY, **kw):
        snaps = {"C1": {"bid": mid - 0.05, "ask": mid + 0.05}}
        return o.review_open([self.sig(**kw)], snaps, {"X": {"score": 60, "price": price, "above_sma5": above5}}, {}, today)

    def test_no_option_percent_stop_or_target(self):
        self.assertEqual(len(self.run_one(0.6, 95)[1]), 0)   # -70% but chart intact: hold
        self.assertEqual(len(self.run_one(4.0, 99)[1]), 0)   # +100% but not above SMA5 yet: hold

    def test_disaster_line_time_and_runner(self):
        self.assertIn("破位", self.run_one(1.0, 89.5)[1][0]["exit_reason"])
        self.assertIn("交易日", self.run_one(2.0, 95, today=date(2026, 11, 16))[1][0]["exit_reason"])
        self.assertIn("到期前", self.run_one(2.0, 95, today=date(2026, 11, 26))[1][0]["exit_reason"])
        self.assertNotIn("留一半", self.run_one(2.5, 101, above5=True)[1][0]["exit_reason"])
        self.assertIn("留一半", self.run_one(4.0, 107, above5=True)[1][0]["exit_reason"])

    def test_pick_prefers_itm_short_expiry_and_steps_down_for_cost(self):
        exp = TODAY + timedelta(days=18)
        fine = chain("X", 100, exp, "C", step=1)
        pick = o.pick_contracts(fine, "call", TODAY, 25)
        self.assertAlmostEqual(pick["single"]["delta"], 0.74, places=2)
        cheap = o.pick_contracts(fine, "call", TODAY, 25, max_cost=pick["single"]["cost_per_contract"] - 1)
        self.assertLess(cheap["single"]["delta"], pick["single"]["delta"])
        self.assertGreaterEqual(cheap["single"]["delta"], 0.65)


class ShortAltTests(unittest.TestCase):
    def test_short_dated_alternative_is_offered(self):
        main = chain("X", 100, TODAY + timedelta(days=18), "C", step=1)
        near = chain("X", 100, TODAY + timedelta(days=8), "C", step=1)
        pick = o.pick_contracts(main + near, "call", TODAY, 25)
        self.assertGreaterEqual(pick["single"]["dte"], o.DTE_MIN)
        self.assertEqual(pick["short_alt"]["dte"], 8)
        self.assertGreaterEqual(pick["short_alt"]["delta"], 0.70)
        exp = o.expectation(0.7)
        self.assertEqual(exp["group"], "high")
        self.assertIn("2021-2026", exp["by_score"])


class DeepStarTests(unittest.TestCase):
    def test_deep_star_needs_all_three(self):
        mk = {"broad_pullback": True}
        r = {"vs_sector_streak": -0.5, "streak_drop_atr": -3.1}
        self.assertTrue(o.is_deep_star(r, mk, 1))
        self.assertFalse(o.is_deep_star({**r, "streak_drop_atr": -1.5}, mk, 1))   # shallow
        self.assertFalse(o.is_deep_star({**r, "vs_sector_streak": -4.0}, mk, 1))  # fell alone
        self.assertFalse(o.is_deep_star(r, {"broad_pullback": False}, 1))         # calm market
