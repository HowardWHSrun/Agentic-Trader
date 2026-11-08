import datetime as dt
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import options_analysis as oa  # noqa: E402
import trading_calendar as tc  # noqa: E402


class CalendarTest(unittest.TestCase):
    def test_known_2026_holidays(self):
        expected = {
            dt.date(2026, 1, 1), dt.date(2026, 1, 19), dt.date(2026, 2, 16), dt.date(2026, 4, 3),
            dt.date(2026, 5, 25), dt.date(2026, 6, 19), dt.date(2026, 7, 3), dt.date(2026, 9, 7),
            dt.date(2026, 11, 26), dt.date(2026, 12, 25),
        }
        self.assertEqual(set(tc.nyse_holidays(2026)), expected)

    def test_saturday_new_year_not_observed(self):
        self.assertNotIn(dt.date(2021, 12, 31), tc.nyse_holidays(2021))
        self.assertNotIn(dt.date(2021, 12, 31), tc.nyse_holidays(2022))
        self.assertTrue(tc.is_trading_day(dt.date(2021, 12, 31)))

    def test_good_friday(self):
        self.assertEqual(tc.holiday_name(dt.date(2025, 4, 18)), 'Good Friday')
        self.assertEqual(tc.holiday_name(dt.date(2027, 3, 26)), 'Good Friday')

    def test_weekend_and_early_close(self):
        self.assertFalse(tc.is_trading_day(dt.date(2026, 11, 7)))
        self.assertEqual(tc.early_close(dt.date(2026, 11, 27)), 'Day after Thanksgiving')
        self.assertEqual(tc.early_close(dt.date(2026, 12, 24)), 'Christmas Eve')
        self.assertIsNone(tc.early_close(dt.date(2026, 7, 3)))  # holiday itself
        self.assertEqual(tc.next_trading_day(dt.date(2026, 11, 25)), dt.date(2026, 11, 27))


def chain(spot, iv=0.3, vol=100, oi=1000):
    calls, puts = [], []
    for k in range(int(spot * 0.8), int(spot * 1.2) + 1, 5):
        intrinsic_c, intrinsic_p = max(spot - k, 0), max(k - spot, 0)
        calls.append({'strike': k, 'bid': intrinsic_c + 1, 'ask': intrinsic_c + 1.2,
                      'lastPrice': intrinsic_c + 1.1, 'volume': vol, 'openInterest': oi,
                      'impliedVolatility': iv})
        puts.append({'strike': k, 'bid': intrinsic_p + 1, 'ask': intrinsic_p + 1.2,
                     'lastPrice': intrinsic_p + 1.1, 'volume': vol, 'openInterest': oi,
                     'impliedVolatility': iv + (0.1 if k < spot else 0)})
    return calls, puts


class MetricsTest(unittest.TestCase):
    def test_historical_volatility_constant_growth_is_zero(self):
        closes = [100 * 1.01 ** i for i in range(30)]
        self.assertAlmostEqual(oa.historical_volatility(closes), 0.0, places=9)
        self.assertIsNone(oa.historical_volatility(closes[:10]))

    def test_historical_volatility_alternating(self):
        closes = [100, 101] * 15
        hv = oa.historical_volatility(closes)
        r = math.log(1.01)
        self.assertAlmostEqual(hv, math.sqrt(r * r * 20 / 19) * math.sqrt(252), places=6)

    def test_atm_iv_skew_straddle(self):
        calls, puts = chain(100)
        self.assertAlmostEqual(oa.atm_iv(calls, puts, 100), 0.3)
        self.assertAlmostEqual(oa.skew(calls, puts, 100), 0.1)
        self.assertAlmostEqual(oa.straddle_move(calls, puts, 100), 2.2)

    def test_placeholder_iv_ignored(self):
        calls, puts = chain(100, iv=0.00001)
        self.assertIsNone(oa.atm_iv(calls, puts, 100))

    def test_max_pain(self):
        calls = [{'strike': 90, 'openInterest': 100}, {'strike': 100, 'openInterest': 10}]
        puts = [{'strike': 110, 'openInterest': 100}, {'strike': 100, 'openInterest': 10}]
        self.assertEqual(oa.max_pain(calls, puts), 100)

    def test_unusual(self):
        rows = [{'strike': 100, 'volume': 2000, 'openInterest': 100},
                {'strike': 105, 'volume': 200, 'openInterest': 1},
                {'strike': 110, 'volume': 900, 'openInterest': 900}]
        hits = oa.unusual(rows, 'call', '2026-11-20')
        self.assertEqual([h['strike'] for h in hits], [100])

    def test_iv_rank_needs_history(self):
        self.assertIsNone(oa.iv_rank(0.3, [0.2] * 5))
        self.assertAlmostEqual(oa.iv_rank(0.3, [0.2, 0.4] * 10), 50)

    def test_pick_expiry(self):
        today = dt.date(2026, 11, 9)
        exps = ['2026-11-09', '2026-11-13', '2026-11-20', '2026-12-11', '2026-12-18']
        self.assertEqual(oa.pick_expiry(exps, today, 30), ('2026-12-11', 32))
        self.assertEqual(oa.pick_expiry(exps, today, 7), ('2026-11-13', 4))

    def test_classify(self):
        notes, ideas = oa.classify({'iv_rank': 80, 'days_to_earnings': 3, 'pc_volume_ratio': 2})
        self.assertIn('IV偏贵', notes)
        self.assertTrue(any('covered call' in i for i in ideas))
        self.assertTrue(any('财报' in n for n in notes))


class EndToEndTest(unittest.TestCase):
    def fake_yfinance(self):
        import pandas as pd

        class Ticker:
            def __init__(self, symbol):
                self.symbol = symbol
                self.options = ('2026-11-13', '2026-11-20', '2026-12-11', '2027-01-15')
                self.calendar = {'Earnings Date': [dt.date(2026, 11, 12)]}

            def history(self, **_):
                if self.symbol == 'BAD':
                    return pd.DataFrame()
                idx = pd.date_range(end='2026-11-09', periods=120, freq='D')
                return pd.DataFrame({'Close': [100 + (i % 3) for i in range(119)] + [110]}, index=idx)

            def option_chain(self, _exp):
                c, p = chain(101, vol=50)
                c[0]['volume'] = 5000
                return types.SimpleNamespace(calls=pd.DataFrame(c), puts=pd.DataFrame(p))

        return types.SimpleNamespace(Ticker=Ticker)

    def test_main_writes_reports(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest('pandas not installed')
        now = dt.datetime(2026, 11, 9, 10, 45, tzinfo=oa.ET)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(sys.modules, {'yfinance': self.fake_yfinance()}), \
                mock.patch.object(oa, 'dt', wraps=dt) as fake_dt, \
                mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            fake_dt.datetime = mock.Mock(wraps=dt.datetime)
            fake_dt.datetime.now.return_value = now
            fake_dt.date = dt.date
            hist = Path(tmp) / 'iv.json'
            code = oa.main(['--symbols', 'SPY,AAPL,BAD', '--out', tmp, '--iv-history', str(hist)])
            self.assertEqual(code, 0)
            report = json.loads((Path(tmp) / 'options-2026-11-09.json').read_text())
            md = (Path(tmp) / 'options-2026-11-09.md').read_text()
            self.assertEqual([m['symbol'] for m in report['symbols']], ['SPY', 'AAPL'])
            self.assertIn('BAD', report['errors'])
            aapl = report['symbols'][1]
            self.assertEqual(aapl['days_to_earnings'], 3)
            self.assertAlmostEqual(aapl['day_change'], 110 / 101 - 1)
            self.assertEqual(aapl['front_expiry'], '2026-11-20')
            self.assertTrue(aapl['unusual'])
            self.assertIn('| AAPL |', md)
            self.assertIn('2026-11-09', json.loads(hist.read_text())['AAPL'])
            self.assertIn('期权日报 2026-11-09', out.getvalue())
            state = Path(tmp) / 'state.json'
            scan_args = ['--symbols', 'AAPL', '--out', tmp, '--iv-history', str(hist), '--scan', '--state', str(state)]
            self.assertEqual(oa.main(scan_args), 0)
            self.assertTrue(json.loads(state.read_text())['baseline_set'])
            self.assertIn('digest not pushed', out.getvalue())
            out.truncate(0)
            self.assertEqual(oa.main(scan_args), 0)
            self.assertIn('0 important alert(s)', out.getvalue())

    def test_skips_non_trading_day(self):
        now = dt.datetime(2026, 11, 26, 10, 0, tzinfo=oa.ET)
        with mock.patch.object(oa, 'dt', wraps=dt) as fake_dt, \
                mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            fake_dt.datetime = mock.Mock(wraps=dt.datetime)
            fake_dt.datetime.now.return_value = now
            fake_dt.date = dt.date
            self.assertEqual(oa.main(['--symbols', 'SPY']), 0)
        self.assertIn('not an NYSE trading day', out.getvalue())

    def test_default_symbols_from_watch(self):
        symbols = oa.load_symbols(Path(__file__).resolve().parents[1] / 'docs/data/watch.json')
        self.assertIn('AAPL', symbols)
        self.assertGreaterEqual(len(symbols), 30)


class ScanTest(unittest.TestCase):
    def report(self, iv=0.30, flow_volume=5000, mid=3.0, move=0.0):
        flows = []
        if flow_volume:
            flows.append({'side': 'call', 'expiry': '2026-11-20', 'strike': 230.0, 'volume': flow_volume,
                          'open_interest': 100, 'iv': 0.4, 'mid': mid, 'premium': flow_volume * mid * 100})
        return {'date': '2026-11-09', 'symbols': [{'symbol': 'AAPL', 'iv30': iv, 'day_change': move, 'unusual': flows}]}

    def at(self, hh, mm, day=9):
        return dt.datetime(2026, 11, day, hh, mm, tzinfo=oa.ET)

    def test_big_flow_pushed_once(self):
        alerts, state, baseline = oa.scan_alerts(self.report(), {}, self.at(9, 40))
        self.assertFalse(baseline)
        self.assertEqual(len(alerts), 1)
        self.assertIn('大单', alerts[0])
        alerts, state, baseline = oa.scan_alerts(self.report(flow_volume=20000), state, self.at(10, 0))
        self.assertTrue(baseline)
        self.assertEqual(alerts, [])  # same contract never repeats the same day

    def test_small_flow_ignored(self):
        self.assertEqual(oa.scan_alerts(self.report(flow_volume=1500), {}, self.at(10, 0))[0], [])
        self.assertEqual(oa.scan_alerts(self.report(mid=0.5), {}, self.at(10, 0))[0], [])  # $250k premium

    def test_iv_alert_needs_big_change_and_fires_once(self):
        _, state, _ = oa.scan_alerts(self.report(flow_volume=0), {}, self.at(10, 0))
        alerts, state, _ = oa.scan_alerts(self.report(iv=0.37, flow_volume=0), state, self.at(10, 10))
        self.assertEqual(alerts, [])  # +7 pts: not important
        alerts, state, _ = oa.scan_alerts(self.report(iv=0.39, flow_volume=0), state, self.at(10, 20))
        self.assertEqual(len(alerts), 1)
        self.assertIn('飙升', alerts[0])
        alerts, _, _ = oa.scan_alerts(self.report(iv=0.50, flow_volume=0), state, self.at(10, 30))
        self.assertEqual(alerts, [])

    def test_no_iv_alert_before_baseline(self):
        _, state, _ = oa.scan_alerts(self.report(iv=0.30, flow_volume=0), {}, self.at(9, 40))
        alerts, _, _ = oa.scan_alerts(self.report(iv=0.60, flow_volume=0), state, self.at(9, 50))
        self.assertEqual(alerts, [])

    def test_move_alert(self):
        sigma = 0.30 / math.sqrt(252)  # ~1.9%
        self.assertEqual(oa.scan_alerts(self.report(flow_volume=0, move=-0.028), {}, self.at(11, 0))[0], [])
        alerts, state, _ = oa.scan_alerts(self.report(flow_volume=0, move=-2.5 * sigma), {}, self.at(11, 0))
        self.assertEqual(len(alerts), 1)
        self.assertIn('📉', alerts[0])
        self.assertEqual(oa.scan_alerts(self.report(flow_volume=0, move=-0.08), state, self.at(11, 10))[0], [])

    def test_state_resets_next_day(self):
        _, state, _ = oa.scan_alerts(self.report(), {}, self.at(10, 0))
        nxt = self.report()
        nxt['date'] = '2026-11-10'
        alerts, state, baseline = oa.scan_alerts(nxt, state, self.at(10, 0, day=10))
        self.assertTrue(baseline)
        self.assertEqual(len(alerts), 1)

    def test_in_session(self):
        et = oa.ET
        self.assertTrue(tc.in_session(dt.datetime(2026, 11, 9, 9, 30, tzinfo=et)))
        self.assertFalse(tc.in_session(dt.datetime(2026, 11, 9, 9, 29, tzinfo=et)))
        self.assertTrue(tc.in_session(dt.datetime(2026, 11, 9, 16, 5, tzinfo=et)))
        self.assertFalse(tc.in_session(dt.datetime(2026, 11, 9, 16, 6, tzinfo=et)))
        self.assertFalse(tc.in_session(dt.datetime(2026, 11, 27, 14, 0, tzinfo=et)))  # early close
        self.assertFalse(tc.in_session(dt.datetime(2026, 11, 26, 11, 0, tzinfo=et)))  # Thanksgiving


class NotifyTest(unittest.TestCase):
    def test_no_channels(self):
        import notify
        with mock.patch.dict('os.environ', {}, clear=True):
            self.assertEqual(notify.send_all('t', 'b'), [])

    def test_chunks(self):
        import notify
        parts = list(notify._chunks('a' * 10 + '\n' + 'b' * 10, 12))
        self.assertEqual(parts, ['a' * 10, 'b' * 10])

    def test_ntfy_request(self):
        import notify
        with mock.patch.dict('os.environ', {'NTFY_TOPIC': 'x'}, clear=True), \
                mock.patch.object(notify, '_post') as post:
            self.assertEqual(notify.send_all('标题', 'body'), ['ntfy'])
        self.assertEqual(post.call_args[0][0], 'https://ntfy.sh/x')


if __name__ == '__main__':
    unittest.main()
