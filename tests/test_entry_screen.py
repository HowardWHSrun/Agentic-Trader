import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import entry_screen as es  # noqa: E402
import options_analysis as oa  # noqa: E402


def uptrend(n=130, start=100.0, step=0.3, vol=1e6):
    close = [start + step * i for i in range(n)]
    return {'close': close, 'high': [c + 1 for c in close], 'low': [c - 1 for c in close], 'volume': [vol] * n}


def base_then_breakout(vol=1e6):
    """Uptrend, then a gently rising 25-session base; returns (bars, breakout price)."""
    close = [100 + 0.3 * i for i in range(105)]
    close += [close[-1] + 0.05 * i for i in range(1, 26)]
    b = {'close': close, 'high': [c + 1 for c in close], 'low': [c - 1 for c in close], 'volume': [vol] * len(close)}
    return b, max(b['high'][-20:]) + 0.3


class EntryScreenTest(unittest.TestCase):
    def test_indicators(self):
        self.assertEqual(es.sma([1, 2, 3, 4], 2), 3.5)
        self.assertEqual(es.sma([1, 2, 3, 4], 2, end=3), 2.5)
        self.assertIsNone(es.sma([1], 2))
        b = uptrend(30)
        self.assertAlmostEqual(es.atr(b['high'], b['low'], b['close']), 2.0)

    def test_pullback_candidate(self):
        b = uptrend()
        s20 = es.sma(b['close'], 20)
        r = es.entry_signal(b, s20 + 0.2, spy_closes=[100] * 130, days_to_earnings=30)
        self.assertEqual(r['setup'], '回踩20日线')
        self.assertTrue(r['checks']['T4 beats SPY 20d'])
        self.assertLess(r['invalidation'], s20)
        # 120-session high (~139.7) sits below a 2R target, so the 2R path is blocked.
        self.assertFalse(r['checks']['E4/E5 2R path'])
        self.assertFalse(r['candidate'])

    def test_breakout_candidate(self):
        b, price = base_then_breakout()
        r = es.entry_signal(b, price, spy_closes=[100] * 130, days_to_earnings=30)
        self.assertEqual(r['setup'], '突破20日高点')
        self.assertIsNone(r['resistance'])
        self.assertTrue(r['candidate'], r['failed'])
        self.assertEqual(r['failed'], [])

    def test_earnings_and_liquidity_block(self):
        b, price = base_then_breakout()
        r = es.entry_signal(b, price, spy_closes=[100] * 130, days_to_earnings=3)
        self.assertIn('L3 no earnings<=5 sessions', r['failed'])
        thin, _ = base_then_breakout(vol=1000)
        self.assertIn('L2 $vol>=20M', es.entry_signal(thin, price, [100] * 130, 30)['failed'])

    def test_downtrend_and_extended_rejected(self):
        down = uptrend(step=-0.2, start=150)
        r = es.entry_signal(down, down['close'][-1], [100] * 130, 30)
        self.assertFalse(r['candidate'])
        b = uptrend()
        r = es.entry_signal(b, b['close'][-1] + 10, [100] * 130, 30)
        self.assertIsNone(r['setup'])
        self.assertFalse(r['checks']['E6 not extended'])

    def test_unknown_reported_not_blocking(self):
        b, price = base_then_breakout()
        r = es.entry_signal(b, price, spy_closes=None, days_to_earnings=None)
        self.assertTrue(r['candidate'])
        self.assertEqual(len(r['unknown']), 2)
        self.assertIn('未确认', oa.entry_text('AAPL', r))

    def test_short_history(self):
        self.assertFalse(es.entry_signal(uptrend(30), 100, None, None)['candidate'])

    def test_bars_from_history_drops_live_bar(self):
        import pandas as pd
        idx = pd.date_range(end='2026-11-09', periods=3, freq='D')
        hist = pd.DataFrame({'High': [2, 3, 4], 'Low': [1, 2, 3], 'Close': [1.5, 2.5, 3.5], 'Volume': [10, 10, 5]}, index=idx)
        bars, price = es.bars_from_history(hist, dt.date(2026, 11, 9))
        self.assertEqual(bars['close'], [1.5, 2.5])
        self.assertEqual(price, 3.5)
        bars, _ = es.bars_from_history(hist, dt.date(2026, 11, 10))
        self.assertEqual(len(bars['close']), 3)

    def test_scan_pushes_entry_once(self):
        b, price = base_then_breakout()
        e = es.entry_signal(b, price, [100] * 130, 30)
        report = {'date': '2026-11-09', 'symbols': [{'symbol': 'AAPL', 'iv30': None, 'day_change': None,
                                                       'unusual': [], 'entry': e}]}
        now = dt.datetime(2026, 11, 9, 11, 0, tzinfo=oa.ET)
        alerts, state, _ = oa.scan_alerts(report, {}, now)
        self.assertEqual(len(alerts), 1)
        self.assertIn('🎯 AAPL', alerts[0])
        self.assertEqual(oa.scan_alerts(report, state, now)[0], [])


if __name__ == '__main__':
    unittest.main()
