"""Synthetic tests for the separately authorized public portfolio boundary."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("export_portfolio", Path(__file__).resolve().parents[1] / "scripts/export_portfolio.py")
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def fixture():
    return {"currency": "USD", "observed_at": "2031-04-05T16:00:00.123456789Z", "accounts": [
        {"account_key": "agentic", "account_label": "Secret label ending 6789",
         "account_number": "never-publish-123456789", "positions_complete_for_scope": True,
         "observed_at": "2031-04-05T15:59:30Z",
         "portfolio": {"total_value": "1000", "cash": "950", "equity_value": "50", "crypto_value": "0",
                       "buying_power": {"unleveraged_buying_power": "950"}, "pending_deposits": "99999"},
         "positions": [{"symbol": "MSFT", "quantity": "0.125", "average_buy_price": "100.04",
                        "shares_available_for_sells": "0.125", "order_id": "never-publish-order"}]},
        {"account_key": "individual", "account_label": "Secret second label", "positions_complete_for_scope": True,
         "portfolio": {"total_value": "2000", "cash": "1700", "equity_value": "250", "crypto_value": "50",
                       "buying_power": {"unleveraged_buying_power": "1700"}},
         "positions": [{"symbol": "AAPL", "quantity": "1", "average_buy_price": "200"}]}
    ], "quotes": [
        {"symbol": "MSFT", "last_price": "110.08", "last_trade_at": "2031-04-05T15:59:59.733880323Z",
         "bid": "110.06", "ask": "110.10", "observed_at": "2031-04-05T15:59:59.7Z",
         "source": "Robinhood", "session": "regular", "token": "never-publish-token"},
        {"symbol": "AAPL", "last_price": "210", "last_trade_at": "2031-04-05T15:59:58Z",
         "bid": "209.98", "ask": "210.02", "observed_at": "2031-04-05T15:59:59Z", "source": "Robinhood", "session": "regular"}
    ]}


class PortfolioExportTests(unittest.TestCase):
    def test_fractional_math_scope_weights_and_no_double_count(self):
        result = exporter.build_portfolio(fixture())
        self.assertEqual(result["updated_at"], "2031-04-05T16:00:00.123456Z")
        holding = result["holdings"][0]
        self.assertEqual(holding["cost_basis"], "12.505")
        self.assertEqual(holding["market_value"], "13.76")
        self.assertEqual(holding["unrealized_pl"], "1.255")
        self.assertEqual(holding["account_weight_pct"], "1.376")
        self.assertEqual(holding["portfolio_weight_pct"], "0.458667")
        self.assertEqual(result["totals"]["account_value"], "3000")
        self.assertEqual(result["totals"]["cash"], "2650")
        self.assertEqual(result["totals"]["tracked_market_value"], "223.76")
        self.assertEqual(result["totals"]["tracked_cost_basis"], "212.505")
        self.assertEqual(result["totals"]["tracked_unrealized_pl"], "11.255")
        self.assertTrue(all(result["totals"]["completeness"].values()))

    def test_missing_price_or_cost_makes_totals_explicitly_partial(self):
        source = fixture()
        source["quotes"] = source["quotes"][:1]
        result = exporter.build_portfolio(source)
        self.assertIsNone(result["holdings"][1]["price"])
        self.assertIsNone(result["totals"]["tracked_market_value"])
        self.assertEqual(result["totals"]["tracked_market_value_known"], "13.76")
        self.assertEqual(result["totals"]["tracked_cost_basis"], "212.505")
        self.assertIsNone(result["totals"]["tracked_unrealized_pl"])
        source = fixture()
        source["accounts"][0]["positions"][0]["average_buy_price"] = None
        result = exporter.build_portfolio(source)
        self.assertIsNone(result["totals"]["tracked_cost_basis"])
        self.assertEqual(result["totals"]["tracked_cost_basis_known"], "200")
        self.assertIsNone(result["totals"]["tracked_unrealized_pl_pct"])
        source["accounts"][1]["positions_complete_for_scope"] = False
        result = exporter.build_portfolio(source)
        self.assertFalse(result["totals"]["completeness"]["tracked_scope"])
        self.assertIsNone(result["totals"]["tracked_market_value"])

    def test_price_freshness_fallback_and_stale_labels(self):
        source = fixture()
        source["quotes"][0]["last_trade_at"] = "2031-04-05T15:30:00Z"
        result = exporter.build_portfolio(source)
        self.assertEqual(result["holdings"][0]["price_basis"], "bid_ask_midpoint")
        self.assertEqual(result["holdings"][0]["price"], "110.08")
        source["quotes"][0]["observed_at"] = "2031-04-05T15:40:00Z"
        result = exporter.build_portfolio(source)
        self.assertEqual(result["holdings"][0]["price_basis"], "bid_ask_midpoint_stale")
        self.assertTrue(result["totals"]["has_stale_prices"])
        source["quotes"][0].update(bid="999", ask="1", last_price="0")
        result = exporter.build_portfolio(source)
        self.assertIsNone(result["holdings"][0]["price"])
        source = fixture()
        source["quotes"][0].update(last_trade_at="2031-04-05T15:55:00Z", observed_at="2031-04-05T15:55:00Z")
        result = exporter.build_portfolio(source)
        self.assertFalse(result["holdings"][0]["price_is_fresh"])
        self.assertEqual(result["holdings"][0]["price_age_seconds"], 301)

    def test_public_allowlist_removes_identifiers_orders_and_unknown_metadata(self):
        result = exporter.build_portfolio(fixture())
        text = json.dumps(result)
        for forbidden in ("6789", "never-publish", "pending_deposits", "99999", "shares_available", "Secret"):
            self.assertNotIn(forbidden, text)
        self.assertEqual(result["accounts"][0]["account_label"], "Agentic")
        for mutate in (
            lambda data: data.update(account_number="secret"),
            lambda data: data["holdings"][0].update(order_id="secret"),
            lambda data: data["accounts"][0].update(account_label="Agentic 6789"),
            lambda data: data["holdings"][0].update(quantity=0.125),
            lambda data: data["holdings"][0].update(price="NaN"),
            lambda data: data["holdings"][0].update(source="Secret 6789"),
        ):
            bad = copy.deepcopy(result)
            mutate(bad)
            with self.assertRaises(exporter.ExportError):
                exporter.validate_public_payload(bad)

    def test_unknown_scopes_and_duplicates_fail_closed(self):
        for mutate in (
            lambda source: source["accounts"].append(copy.deepcopy(source["accounts"][0])),
            lambda source: source["quotes"].append(copy.deepcopy(source["quotes"][0])),
            lambda source: source["accounts"][1]["positions"][0].update(symbol="UNRELATED"),
            lambda source: source.update(observed_at="2031-04-05"),
        ):
            source = fixture()
            mutate(source)
            with self.assertRaises(exporter.ExportError):
                exporter.build_portfolio(source)

    def test_cli_atomic_output_and_failure_preserve_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / "source.json", Path(temporary) / "public.json"
            source.write_text(json.dumps(fixture()))
            args = ["--input", str(source), "--output", str(output)]
            self.assertEqual(exporter.main(args), 0)
            before = output.read_bytes()
            self.assertEqual(exporter.main(args), 0)
            self.assertEqual(output.read_bytes(), before)
            source.write_text('{"currency":"EUR"}')
            self.assertEqual(exporter.main(args), 1)
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
