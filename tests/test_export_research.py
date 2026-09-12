"""Synthetic publication-boundary tests; no real private values belong here."""

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_research.py"
SPEC = importlib.util.spec_from_file_location("export_research", MODULE_PATH)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def fixture(check_type="baseline_archive", checked_at="2031-04-05T16:00:00Z"):
    review = {
        "checked_at": checked_at,
        "check_type": check_type,
        "decision": "no_opportunity",
        "summary": "Two saved technical patterns still require manual review.",
        "data_freshness": "Saved completed-session bars. No fresh market check was performed.",
        "observations": ["SPY closed at $421.25, above its $410.20 50-session average."],
        "lessons": ["A calculated 2R target does not prove the path is clear."],
        "candidate_reviews": [{
            "symbol": "XLK",
            "why_interesting": "Its $123.45 close reclaimed the 20-session average.",
            "why_not_actionable": "The $124.20 entry exceeds the $88.80 position ceiling. The prior high requires review.",
            "what_would_change": "A future setup requires fresh spread and event checks.",
        }],
        "notification": {"sent": False, "reason": "No qualified opportunity was identified."},
        "sources": [{"title": "Public methodology", "url": "https://www.example.com/research/methodology", "as_of": "2031-04-05"}],
    }
    candidate = {
        "symbol": "XLK", "kind": "etf", "sector": "technology_growth",
        "last_date": "2031-04-04", "technical_match": True,
        "setup_types": ["pullback_reclaim"],
        "filters": {key: True for key in exporter.FILTER_FIELDS},
        "metrics": {key: 12.5 for key in exporter.METRIC_FIELDS},
        "plan": {key: 15.25 for key in exporter.PLAN_FIELDS},
        "sizing": {"available": True, "shares": 0, "blockers": ["No capacity."]},
        "blockers": ["Fresh spread checks are missing."],
    }
    scan = {
        "generated_at": "2031-04-05T15:58:17+00:00",
        "expected_session": "2031-04-04",
        "rules": dict(exporter.RISK_RULES),
        "market_gate": {
            "passed": True,
            "benchmarks": {
                symbol: {"close": 421.25, "sma50": 410.20, "sma200": 389.15, "last_date": "2031-04-04"}
                for symbol in ("SPY", "QQQ")
            },
        },
        "data_blockers": [], "candidates": [candidate],
    }
    return review, scan


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.logs = self.root / "private-logs"
        self.logs.mkdir()

    def write_archive(self, review=None, scan=None):
        if review is None:
            review, scan = fixture()
        stamp = exporter.iso_timestamp(review["checked_at"]).replace("-", "").replace(":", "").replace("Z", ".000000Z")
        folder = self.logs / review["checked_at"][:10] / (stamp + "-" + review["check_type"])
        folder.mkdir(parents=True)
        (folder / "review.json").write_text(json.dumps(review), encoding="utf-8")
        (folder / "scan.json").write_text(json.dumps(scan), encoding="utf-8")
        return folder

    def test_preserves_market_evidence_and_removes_private_sizing(self):
        self.write_archive()
        data = exporter.export_logs(self.logs)
        entry = data["entries"][0]
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["risk_rules"], exporter.RISK_RULES)
        self.assertEqual(entry["decision"], "no_opportunity")
        self.assertEqual(entry["signal_session"], "2031-04-04")
        self.assertEqual(entry["scan_generated_at"], "2031-04-05T15:58:17Z")
        self.assertIn("not a new market check", entry["data_freshness"])
        self.assertIn("$421.25", entry["observations"][0])
        candidate = entry["candidates"][0]
        self.assertEqual(candidate["sizing_status"], "does_not_fit")
        self.assertEqual(candidate["metrics"]["close"], 12.5)
        self.assertIn("did not fit sizing limits", candidate["review"]["why_not_actionable"])
        self.assertIn("prior high requires review", candidate["review"]["why_not_actionable"])
        self.assertNotIn("88.80", json.dumps(data))

    def test_only_two_explicit_source_files_and_allowlisted_fields_are_read(self):
        review, scan = fixture()
        review["future_private_field"] = {"account_number": "TEST-ACCOUNT-93827164"}
        scan["account"] = {"cash": 98765.43, "holdings": [{"shares": 314}]}
        candidate = scan["candidates"][0]
        candidate["sizing"].update({"budgets": {"secret_budget": 43210.98}, "entry_notional": 45678.90})
        candidate["metrics"]["personal_wealth"] = 123456.78
        candidate["plan"]["risk_per_share"] = 9999.12
        candidate["filters"]["account_id"] = "synthetic-only"
        folder = self.write_archive(review, scan)
        (folder / "account.json").write_text("deliberately invalid JSON")
        (folder / "config.json").write_text("deliberately invalid JSON")
        (folder / "analysis.md").write_text("private markdown sentinel")
        read_paths = []
        original_read = exporter.read_object
        def observed_read(path):
            read_paths.append(path.name)
            return original_read(path)
        with patch.object(exporter, "read_object", side_effect=observed_read):
            data = exporter.export_logs(self.logs)
        self.assertEqual(set(read_paths), {"review.json", "scan.json"})
        public = json.dumps(data)
        for secret in ("TEST-ACCOUNT", "98765.43", "43210.98", "45678.9", "123456.78", "9999.12", "synthetic-only", "sentinel"):
            self.assertNotIn(secret, public)
        self.assertEqual(set(data["entries"][0]["candidates"][0]["plan"]), set(exporter.PLAN_FIELDS))

    def test_unseen_private_narratives_are_dropped_in_every_prose_field(self):
        sensitive = [
            "Future broker account 91827364 carries $31415.92.",
            "Masked reference ****4826 remains linked.",
            "The identifier is ZZ98172364.",
            "The value ending in 4826 remains linked.",
            "Buying power is 27182.81 USD.",
            "Available funds: 16180.33 USD.",
            "The deposit is $14142.13 pending.",
            "Remaining cash is $12345; entry is $100.",
            "I have $12345 and target is $110.",
            "Our capital is $12345 while the stop is $110.",
            "Funds on hand are $12345.67; the entry is $110.",
            "The broker reports liquidity of $12345.67 while the target is $110.",
            "An allocation of $12345.67 funds this entry at $110.",
            "Broker reference ZX9217 remains linked.",
            "The balance is $17320.51.",
            "The portfolio contains 17 shares of XLK.",
            "Purchased 3.25 shares of XLK.",
            "The zero-share result prevented an entry.",
            "Open /Users/example/finance/secret-ledger.json for the details.",
            "Load file:///tmp/ledger.json for the details.",
            r"Read C:\Users\Example\ledger.json for the details.",
            "API key sk_synthetic_key_1234567890 must stay private.",
            "The credential is abcdef1234567890abcdef1234567890.",
            "Reference 12345678-1234-1234-1234-123456789abc was saved.",
            "Contact synthetic.person@example.com for the details.",
            "余额 12345 美元。",
        ]
        for text in sensitive:
            with self.subTest(text=text):
                self.assertEqual(exporter.public_text(text), "")
        review, scan = fixture()
        poison = " ".join(sensitive)
        review.update(summary=poison, observations=[poison], lessons=[poison], data_freshness=poison)
        review["notification"]["reason"] = poison
        for field in exporter.REVIEW_FIELDS:
            review["candidate_reviews"][0][field] = poison
        scan["data_blockers"] = [poison]
        scan["candidates"][0]["blockers"] = [poison]
        review["sources"].append({"title": poison, "url": "https://www.example.com/public", "as_of": poison})
        self.write_archive(review, scan)
        data = exporter.export_logs(self.logs)
        public = json.dumps(data)
        for marker in ("31415", "27182", "16180", "14142", "12345", "17320", "4826", "ZZ981", "secret-ledger", "synthetic.person", "abcdef123", "余额"):
            self.assertNotIn(marker, public)
        self.assertEqual(data["entries"][0]["observations"], [])

    def test_every_money_amount_requires_its_own_direct_price_context(self):
        good = [
            "SPY closed at $421.25, above its $410.20 50-session average.",
            "The saved close of $123.45 reclaimed the 20-session average ($120.20).",
            "The prior high is $128.20, below the arithmetic $130.40 2R target.",
            "The hypothetical $124.20 entry requires review.",
            "The entry is 124.20 USD and the stop is 121.80 USD.",
        ]
        ambiguous = [
            "The amount is $12345.67; the entry is $110.",
            "The amount is $12345.67 while the target is $110.",
            "The amount is $12345.67 and the entry is $110.",
            "The entry is $110; an additional $12345.67 remains.",
            "The target is $110 and the remaining amount is 12345.67 USD.",
            "The amount is USD 12345.67 while the entry is USD 110.",
            "The amount is $12345.67, the entry is $110.",
            "The target is $110; 12345.67 US dollars remain.",
        ]
        for text in good:
            with self.subTest(text=text):
                self.assertEqual(exporter.public_text(text), text)
        for text in ambiguous:
            with self.subTest(text=text):
                self.assertEqual(exporter.public_text(text), "")
        self.write_archive()
        data = exporter.export_logs(self.logs)
        additional_private = [
            "Funds on hand are $12345.67; the entry is $110.",
            "The broker reports liquidity of $12345.67 while the target is $110.",
            "An allocation of $12345.67 funds this entry at $110.",
            "Broker reference ZX9217 remains linked.",
        ]
        for text in ambiguous + additional_private:
            bad = copy.deepcopy(data)
            bad["entries"][0]["observations"].append(text)
            with self.subTest(historical_text=text), self.assertRaises(exporter.ExportError):
                exporter.validate_public_payload(bad)

    def test_only_public_external_nonsecret_sources_survive(self):
        bad = [
            "scan.json", "account.json", "/Users/example/review.md", "file:///tmp/review.json",
            "https://user:password@example.com/path", "https://example.com/path?token=synthetic",
            "https://example.com/path?harmless=1", "https://example.com/path#private",
            "http://localhost/report", "http://127.0.0.1/report", "http://10.0.0.5/report",
            "http://192.168.1.2/report", "http://[::1]/report", "http://host.internal/report",
            "https://example.com/account/91827364", "https://example.com/access_token/synthetic",
            "https://example.com/%61ccount/details", "https://example.com/path\nextra",
            "https://example.com/%2561ccount/details", "https://example.com/path%0Aextra",
            "https://sk_synthetic1234567890.example.com/public",
            "https://example.com:bad/", "https://example.com/abcdef1234567890abcdef1234567890",
        ]
        for url in bad:
            with self.subTest(url=url):
                self.assertIsNone(exporter.public_url(url))
        review, scan = fixture()
        review["sources"].extend({"title": "Evidence", "url": url, "as_of": "2031-04-05"} for url in bad)
        self.write_archive(review, scan)
        data = exporter.export_logs(self.logs)
        self.assertEqual(len(data["entries"][0]["sources"]), 1)

    def test_generic_holding_window_and_future_requirements_remain_grounded(self):
        review, scan = fixture()
        record = review["candidate_reviews"][0]
        record["why_not_actionable"] = "Verified earnings clearance through the intended holding window remains unknown. The account snapshot is old. The close is above its average."
        record["what_would_change"] = "A new valid setup would require verified earnings/event clearance, a size that satisfies both capital and risk limits, and chart-supported reward room with fresh regular-session quotes. An estimated earnings date does not clear those requirements."
        self.write_archive(review, scan)
        result = exporter.export_logs(self.logs)["entries"][0]["candidates"][0]["review"]
        self.assertIn("holding window remains unknown", result["why_not_actionable"])
        self.assertNotIn("did not fit sizing limits", result["why_not_actionable"])
        self.assertNotIn("account", result["why_not_actionable"])
        self.assertIn("position and risk limits", result["what_would_change"])
        self.assertIn("earnings or event clearance", result["what_would_change"])
        self.assertIn("chart-supported reward room", result["what_would_change"])
        self.assertIn("fresh execution checks", result["what_would_change"])
        self.assertEqual(exporter.future_requirements("I must deposit $12345 tomorrow."), "")

    def test_unknown_values_stay_null_and_sizing_uses_computed_state(self):
        review, scan = fixture()
        candidate = scan["candidates"][0]
        candidate["metrics"].update(close=None, sma20="123.45", sma50=True, atr14=float("nan"), sma200=float("inf"))
        candidate["filters"]["dollar_liquidity"] = "true"
        candidate["technical_match"] = None
        candidate["sizing"] = {"available": False, "shares": 0}
        candidate["plan"] = None
        scan["market_gate"]["passed"] = None
        scan["rules"].pop("max_positions")
        self.write_archive(review, scan)
        data = exporter.export_logs(self.logs)
        exported = data["entries"][0]["candidates"][0]
        for key in ("close", "sma20", "sma50", "sma200", "atr14"):
            self.assertIsNone(exported["metrics"][key])
        self.assertIsNone(exported["filters"]["dollar_liquidity"])
        self.assertIsNone(exported["technical_match"])
        self.assertIsNone(exported["plan"])
        self.assertIsNone(data["risk_rules"]["max_positions"])
        self.assertIsNone(data["entries"][0]["market_gate"]["passed"])
        self.assertEqual(exported["sizing_status"], "not_evaluated")
        self.assertEqual(exporter.sizing_status({"sizing": {"available": True, "shares": 4, "blockers": []}}), "within_limits")
        self.assertEqual(exporter.sizing_status({"sizing": {"available": True, "shares": 4, "blockers": ["unresolved"]}}), "not_evaluated")

    def test_failure_retains_old_signal_time_and_no_invented_observations(self):
        review, scan = fixture("failed_check", "2031-04-06T16:00:00Z")
        review.update(decision="monitor_failure", observations=[], lessons=[], summary="Market data refresh failed.")
        review["data_freshness"] = "The supplied scan is from the prior completed session; refresh failed."
        scan["data_blockers"] = ["Current market data is unavailable."]
        self.write_archive(review, scan)
        entry = exporter.export_logs(self.logs)["entries"][0]
        self.assertEqual(entry["decision"], "monitor_failure")
        self.assertEqual(entry["check_type"], "failed_check")
        self.assertEqual(entry["checked_at"], "2031-04-06T16:00:00Z")
        self.assertEqual(entry["signal_session"], "2031-04-04")
        self.assertEqual(entry["scan_generated_at"], "2031-04-05T15:58:17Z")
        self.assertEqual(entry["observations"], [])
        self.assertIn("refresh failed", entry["data_freshness"])

    def test_newest_check_drives_update_and_rule_values_without_wall_clock(self):
        older_review, older_scan = fixture()
        self.write_archive(older_review, older_scan)
        newer_review, newer_scan = fixture("intraday", "2031-04-08T16:00:00Z")
        newer_scan["rules"]["max_position_pct"] = 20
        self.write_archive(newer_review, newer_scan)
        data = exporter.export_logs(self.logs)
        self.assertEqual(data["updated_at"], newer_review["checked_at"])
        self.assertEqual(data["entries"][0]["check_type"], "intraday")
        self.assertEqual(data["risk_rules"]["max_position_pct"], 20)
        output = self.root / "public" / "research.json"
        self.assertTrue(exporter.atomic_write(output, data))
        before = output.stat().st_mtime_ns
        self.assertFalse(exporter.atomic_write(output, exporter.export_logs(self.logs)))
        self.assertEqual(output.stat().st_mtime_ns, before)

    def test_atomic_replace_failure_preserves_previous_file_and_cleans_temporary(self):
        self.write_archive()
        output = self.root / "research.json"
        output.write_text("previous public data")
        with patch.object(exporter.os, "replace", side_effect=OSError("simulated unavailable destination")):
            with self.assertRaises(OSError):
                exporter.atomic_write(output, exporter.export_logs(self.logs))
        self.assertEqual(output.read_text(), "previous public data")
        self.assertEqual(list(self.root.glob(".research-*.tmp")), [])

    def test_bad_input_cannot_replace_previous_output_or_reclassify_baseline(self):
        output = self.root / "research.json"
        output.write_text("previous public data")
        self.assertEqual(exporter.main(["--logs", str(self.logs), "--output", str(output)]), 1)
        review, scan = fixture()
        review["decision"] = "qualified_opportunity"
        folder = self.write_archive(review, scan)
        self.assertEqual(exporter.main(["--logs", str(self.logs), "--output", str(output)]), 1)
        (folder / "review.json").write_text("invalid json with private synthetic marker")
        result = subprocess.run([sys.executable, str(MODULE_PATH), "--logs", str(self.logs), "--output", str(output)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("private synthetic marker", result.stderr)
        self.assertEqual(output.read_text(), "previous public data")

    def test_historical_payload_audit_rejects_extra_fields_secrets_and_false_baseline(self):
        self.write_archive()
        good = exporter.export_logs(self.logs)
        self.assertIsNone(exporter.validate_public_payload(good))
        mutations = [
            lambda data: data.update(account={"cash": 99999.99}),
            lambda data: data["entries"][0]["observations"].append("Available cash is $31337 and entry is $12."),
            lambda data: data["entries"][0]["candidates"][0]["plan"].update(shares=7),
            lambda data: data["entries"][0]["candidates"][0]["metrics"].update(close=float("nan")),
            lambda data: data["entries"][0]["sources"][0].update(url="https://example.com/?api_key=synthetic"),
            lambda data: data["entries"][0]["notification"].update(sent=True),
            lambda data: data["entries"][0].update(data_freshness="Fresh live market check completed."),
            lambda data: data.update(updated_at="2035-01-01T00:00:00Z"),
            lambda data: data["entries"][0]["candidates"][0].update(kind={"unexpected": True}),
        ]
        for mutate in mutations:
            bad = copy.deepcopy(good)
            mutate(bad)
            with self.assertRaises(exporter.ExportError):
                exporter.validate_public_payload(bad)


if __name__ == "__main__":
    unittest.main()
