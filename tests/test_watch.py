"""Validate the public watch feed without brokerage access or network calls."""
import json
import math
import re
import copy
import tempfile
from unittest import mock
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_KEYS = {"account_id", "item_id", "balance", "balances", "quantity", "share_count", "buying_power", "access_token", "api_key", "password", "deposit", "transactions", "holdings", "positions", "cost_basis", "allocation", "tradability", "account_number"}
TOP_FIELDS = set("schema_version configuration_updated_at timezone schedule scope portfolio_check research_method reasoning_mode alert_policy execution risk_limits privacy last_check alerts last_soft_check last_hard_check score_history".split())
HARD_FIELDS = set("id publication_timestamp assessment_snapshot rubric_version weights cohort summary records history_note correction_of correction_reason".split())
SOFT_FIELDS = set("checked_at status summary coverage attempted current".split())
WEIGHTS = {"entry_quality": 30, "trend_relative_strength": 25, "catalyst": 20, "fundamentals_valuation": 10, "liquidity_event_risk": 15}
PUBLIC_SIZING = "Not provided on this public market-research page."


def history_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
        raise ValueError("Unsafe history ID")
    return value


def source_url(source):
    if isinstance(source, dict):
        if set(source) != {"url", "title"} or not isinstance(source["title"], str) or not source["title"].strip():
            raise ValueError("Unexpected source fields")
        source = source["url"]
    if not isinstance(source, str):
        raise ValueError("Unsafe source link")
    url = urlparse(source)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("Unsafe source link")
    # Public research links may use ordinary query IDs, but never credentials or
    # account/personal identifiers. Narrative privacy still requires human review.
    for area in (url.query, url.fragment):
        for key, _ in parse_qsl(area, keep_blank_values=True):
            key = re.sub(r"[^a-z0-9]", "", unquote(key).lower())
            if re.search(r"account|token|secret|password|passwd|apikey|credential|authorization|session|signature|email|customer|userid|clientid|xamz|xgoog", key) or key in {"auth", "key", "code", "sig"}:
                raise ValueError("Private query field in source link")



def timestamp(value):
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("A timestamp with time and timezone is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Missing timezone")
    return parsed


def validate(data):
    if not isinstance(data, dict) or set(data) != TOP_FIELDS:
        raise ValueError("Unexpected or missing top-level fields")
    if data["schema_version"] != 2 or data["timezone"] != "America/Chicago":
        raise ValueError("Unsupported configuration")
    timestamp(data["configuration_updated_at"])
    if set(data["schedule"]) != {"soft_checks", "hard_checks", "controller"}:
        raise ValueError("Unexpected schedule fields")
    if not data["schedule"].get("soft_checks") or not data["schedule"].get("hard_checks"):
        raise ValueError("Missing separate check cadence")
    def privacy(value):
        if isinstance(value, dict):
            if PRIVATE_KEYS.intersection(value):
                raise ValueError("Private field in public feed")
            for child in value.values():
                privacy(child)
        elif isinstance(value, list):
            for child in value:
                privacy(child)
    privacy(data)
    soft = data.get("last_soft_check")
    if soft is not None:
        if not isinstance(soft, dict) or set(soft) != SOFT_FIELDS:
            raise ValueError("Unexpected soft fields")
        timestamp(soft["checked_at"])
        if type(soft["current"]) is not int or type(soft["attempted"]) is not int:
            raise ValueError("Coverage counts must be integers")
        if any(not isinstance(soft[k], str) or not soft[k].strip() for k in ("summary", "coverage")):
            raise ValueError("Missing soft-check evidence")
        if soft["status"] not in {"completed", "partial", "failed"} or not 0 <= soft["current"] <= soft["attempted"] <= 32:
            raise ValueError("Invalid soft coverage")
    hard = data.get("last_hard_check")
    if hard is not None:
        if not isinstance(hard, dict) or set(hard) - HARD_FIELDS or not (HARD_FIELDS - {"correction_of", "correction_reason"}) <= set(hard):
            raise ValueError("Unexpected or missing hard-review fields")
        history_id(hard["id"])
        published = timestamp(hard["publication_timestamp"])
        assessed = timestamp(hard["assessment_snapshot"])
        if assessed > published:
            raise ValueError("Assessment cannot follow publication")
        if hard["weights"] != WEIGHTS:
            raise ValueError("Unexpected rubric weights")
        if ("correction_of" in hard) != ("correction_reason" in hard):
            raise ValueError("Correction needs its original ID and reason")
        if "correction_of" in hard:
            history_id(hard["correction_of"])
            if hard["correction_of"] == hard["id"] or not isinstance(hard["correction_reason"], str) or not hard["correction_reason"].strip():
                raise ValueError("Invalid correction metadata")
        universe = set("AAPL AVGO CRM MSFT NVDA GOOGL META AMZN HD COST KO PG WMT ABBV LLY UNH BAC JPM V CVX XOM CAT DE GE RTX DUK NEE FCX LIN PLD TSLA SPCX".split())
        if len(hard["records"]) != 32 or {r["symbol"] for r in hard["records"]} != universe:
            raise ValueError("Fixed universe must contain all 32 once")
        allowed = {"symbol","score","score_status","rubric_version","component_scores","reference_price","reference_price_type","reference_price_timestamp","reference_session","cohort","reference_source","reason","improvement_condition","conditional_action","horizon","sources","event","evidence_limitations","quote_delay","sizing","missing_evidence"}
        for r in hard["records"]:
            if set(r) - allowed:
                raise ValueError("Unexpected assessment fields")
            if any(not isinstance(r.get(k), str) or not r[k].strip() for k in ("conditional_action", "reason")):
                raise ValueError("Missing assessment or plan")
            if r.get("rubric_version") != hard["rubric_version"] or r.get("sizing") != PUBLIC_SIZING:
                raise ValueError("Invalid record rubric or public sizing")
            score = r["score"]
            if score is not None:
                if type(score) != int or score < 0 or score > 100 or score % 5:
                    raise ValueError("Invalid score")
                if r.get("score_status") not in {"available", "available_provisional"}:
                    raise ValueError("Numeric score requires available status")
                if timestamp(r["reference_price_timestamp"]) > assessed:
                    raise ValueError("Reference price cannot follow assessment")
                if type(r["reference_price"]) not in (int, float) or not math.isfinite(r["reference_price"]) or r["reference_price"] <= 0:
                    raise ValueError("Missing or nonfinite reference price")
                if "component_scores" in r:
                    components = r["component_scores"]
                    if not isinstance(components, dict) or set(components) != set(WEIGHTS) or any(type(v) is not int or not 0 <= v <= WEIGHTS[k] for k, v in components.items()) or sum(components.values()) != score:
                        raise ValueError("Invalid components or sum")
            elif r.get("score_status") != "unavailable" or not isinstance(r.get("missing_evidence"), str) or not r["missing_evidence"].strip():
                raise ValueError("Unavailable score needs unavailable status and evidence gap")
            for source in r.get("sources", []):
                source_url(source)
        if hard["rubric_version"] != "buying-score-v1":
            raise ValueError("Rubric change requires a new implementation/cohort")
    history = data["score_history"]
    seen = {}
    prior = None
    if not isinstance(history, list):
        raise ValueError("Invalid score history")
    for item in history:
        if not isinstance(item, dict) or set(item) != {"id", "publication_timestamp", "path"}:
            raise ValueError("Unexpected history index fields")
        ident = history_id(item["id"])
        when = timestamp(item["publication_timestamp"])
        if ident in seen or item["path"] != "data/watch-history/" + ident + ".json" or (prior is not None and when < prior):
            raise ValueError("Invalid, duplicate or out-of-order history entry")
        seen[ident] = item
        prior = when
    if hard is not None:
        if hard["id"] not in seen or seen[hard["id"]]["publication_timestamp"] != hard["publication_timestamp"] or history[-1]["id"] != hard["id"]:
            raise ValueError("Latest hard review must match latest history index")
        if "correction_of" in hard and hard["correction_of"] not in seen:
            raise ValueError("Correction must identify a published original")
    check = data["last_check"]
    if check is not None:
        if set(check) != {"checked_at", "status", "summary", "coverage"}:
            raise ValueError("Unexpected legacy check fields")
        timestamp(check["checked_at"])
        if check["status"] not in {"completed_alert", "completed_no_alert", "incomplete"}:
            raise ValueError("Unsupported review status")
        if not check.get("summary") or not check.get("coverage"):
            raise ValueError("Missing review evidence or coverage")
    ids = set()
    for alert in data["alerts"]:
        if not alert.get("id") or alert["id"] in ids:
            raise ValueError("Missing or duplicate alert ID")
        ids.add(alert["id"])
        if alert["label"] not in {"TRADING CANDIDATE", "LONGER-TERM INVESTMENT CANDIDATE"}:
            raise ValueError("Unsupported candidate label")
        timestamp(alert["published_at"])
        for key in ["ticker", "name", "summary", "entry", "horizon", "invalidation", "risks", "alternative", "conclusion"]:
            if not isinstance(alert.get(key), str) or not alert[key].strip():
                raise ValueError("Missing candidate field: " + key)
        quote = alert["quote"]
        timestamp(quote["as_of"])
        if not isinstance(quote["price"], (int, float)) or not math.isfinite(quote["price"]) or quote["price"] <= 0:
            raise ValueError("Invalid quote")
        if any(not quote.get(key) for key in ["currency", "session", "delay"]):
            raise ValueError("Unlabeled quote")
        if not alert.get("sources"):
            raise ValueError("Missing sources")
        for source in alert["sources"]:
            source_url(source)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "docs/data/watch.json").read_text())

    def test_current_feed(self):
        validate(self.data)

    def test_reject_naive_time(self):
        with self.assertRaises(ValueError):
            timestamp("2026-09-21T12:00:00")

    def test_reject_date_only(self):
        with self.assertRaises(ValueError):
            timestamp("2026-09-21")

    def test_reject_private_fields(self):
        self.data["account_id"] = "test-only"
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_reject_unsupported_status(self):
        self.data["last_check"] = {"checked_at": "2026-09-21T12:00:00-05:00", "status": "live"}
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_page_uses_safe_text_rendering(self):
        page = (ROOT / "docs/watch.html").read_text() + (ROOT / "docs/watch.js").read_text()
        self.assertNotIn("innerHTML", page)
        self.assertIn("textContent", page)
        self.assertIn("cache:'no-store'", page)
        self.assertIn("No completed check has been published", page)


    def test_reject_unknown_top_level_and_nested_fields(self):
        for mutation in (lambda d: d.update(private_note="hidden"),
                         lambda d: d["last_hard_check"].update(private_note="hidden"),
                         lambda d: d["schedule"].update(private_note="hidden")):
            data = copy.deepcopy(self.data)
            mutation(data)
            with self.assertRaises(ValueError):
                validate(data)

    def test_reject_invalid_weights_components_and_sizing(self):
        mutations = [
            lambda d: d["last_hard_check"]["weights"].update(entry_quality=31),
            lambda d: d["last_hard_check"]["records"][0].update(component_scores={"entry_quality": 60}),
            lambda d: d["last_hard_check"]["records"][0].update(sizing="Buy 100 shares"),
        ]
        for mutate in mutations:
            data = copy.deepcopy(self.data)
            mutate(data)
            with self.assertRaises(ValueError):
                validate(data)

    def test_reject_nonfinite_and_boolean_reference_prices(self):
        for price in (float("nan"), float("inf"), -float("inf"), True):
            self.data["last_hard_check"]["records"][0]["reference_price"] = price
            with self.assertRaises(ValueError):
                validate(self.data)

    def test_reject_inconsistent_score_status(self):
        for index, status in ((0, "unavailable"), (-1, "available")):
            data = copy.deepcopy(self.data)
            data["last_hard_check"]["records"][index]["score_status"] = status
            with self.assertRaises(ValueError):
                validate(data)

    def test_reject_private_source_query_fields_but_keep_public_ids(self):
        source_url("https://example.com/news?id=public-news-id")
        for query in ("account=1234", "access_token=secret", "X-Amz-Signature=secret", "api%5Fkey=secret", "USER_ID=123", "email=user%40example.com"):
            with self.assertRaises(ValueError):
                source_url("https://example.com/news?" + query)
        with self.assertRaises(ValueError):
            source_url({"url": "https://example.com/", "title": "News", "private_note": "hidden"})

    def test_reject_bad_history_index(self):
        for mutation in (lambda d: d["score_history"][0].update(path="../../private.json"),
                         lambda d: d["score_history"].append(copy.deepcopy(d["score_history"][0])),
                         lambda d: d["score_history"][-1].update(publication_timestamp=(timestamp(d["last_hard_check"]["publication_timestamp"]) - timedelta(seconds=1)).isoformat())):
            data = copy.deepcopy(self.data)
            mutation(data)
            with self.assertRaises(ValueError):
                validate(data)

    def test_reject_impossible_timestamp_order(self):
        self.data["last_hard_check"]["records"][0]["reference_price_timestamp"] = (timestamp(self.data["last_hard_check"]["assessment_snapshot"]) + timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_generic_privacy_disclosures_are_not_rejected(self):
        self.data["privacy"] = "Personal holdings, account balances and private allocations are not published."
        validate(self.data)


class UpdateWatchTests(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import update_watch
        self.publisher = update_watch
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "docs/data/watch.json"
        self.history = self.root / "docs/data/watch-history"
        self.history.mkdir(parents=True)
        self.data = json.loads((ROOT / "docs/data/watch.json").read_text())
        self.path.write_text(json.dumps(self.data))
        for item in self.data["score_history"]:
            (self.root / "docs" / item["path"]).write_bytes((ROOT / "docs" / item["path"]).read_bytes())
        latest = timestamp(self.data["last_hard_check"]["publication_timestamp"])
        if self.data["last_soft_check"] is not None:
            latest = max(latest, timestamp(self.data["last_soft_check"]["checked_at"]))
        self.base_time = (latest.astimezone(timezone.utc) + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
        self.soft = {"checked_at": self.base_time.isoformat(), "status": "completed", "summary": "Public review complete", "coverage": "32 names attempted", "attempted": 32, "current": sum(r["score"] is not None for r in self.data["last_hard_check"]["records"])}

    def test_soft_updates_preserve_hard_scores_and_original_bytes(self):
        before_history = {p.name: p.read_bytes() for p in self.history.iterdir()}
        self.publisher.update("soft", self.soft, self.root)
        after = json.loads(self.path.read_text())
        self.assertEqual(after["last_hard_check"], self.data["last_hard_check"])
        self.assertEqual(after["score_history"], self.data["score_history"])
        self.assertEqual(before_history, {p.name: p.read_bytes() for p in self.history.iterdir()})
        self.assertEqual(after["last_soft_check"], self.soft)

    def test_soft_monotonicity_uses_parsed_timezone(self):
        self.publisher.update("soft", self.soft, self.root)
        newer = dict(self.soft, checked_at=(self.base_time + timedelta(minutes=1)).astimezone(timezone(timedelta(hours=-4))).isoformat())
        self.publisher.update("soft", newer, self.root)
        older_but_lexically_later = dict(self.soft, checked_at=(self.base_time - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=2))).isoformat())
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.publisher.update("soft", older_but_lexically_later, self.root)
        self.assertEqual(self.path.read_bytes(), before)

    def test_hard_timezone_update_and_original_immutability(self):
        review = copy.deepcopy(self.data["last_hard_check"])
        review.update(id="timezone-review", publication_timestamp=(timestamp(review["publication_timestamp"]) + timedelta(minutes=1)).astimezone(timezone(timedelta(hours=-4))).isoformat())
        self.publisher.update("hard", review, self.root)
        self.assertEqual(json.loads(self.path.read_text())["last_hard_check"], review)
        self.publisher.update("hard", review, self.root)
        original = (self.history / "timezone-review.json").read_bytes()
        review["summary"] = "Changed original"
        with self.assertRaises(ValueError):
            self.publisher.update("hard", review, self.root)
        self.assertEqual((self.history / "timezone-review.json").read_bytes(), original)

    def test_unsafe_id_is_rejected_before_history_path_access(self):
        review = copy.deepcopy(self.data["last_hard_check"])
        review["id"] = "../../private"
        before = self.path.read_bytes()
        real_exists = Path.exists
        def guarded_exists(path):
            self.assertNotIn("..", path.parts, "Unsafe ID used in filesystem access")
            return real_exists(path)
        with mock.patch.object(Path, "exists", guarded_exists):
            with self.assertRaises(ValueError):
                self.publisher.update("hard", review, self.root)
        self.assertEqual(self.path.read_bytes(), before)

    def test_atomic_failure_preserves_current_and_cleans_temporary(self):
        before = self.path.read_bytes()
        with mock.patch.object(self.publisher.os, "replace", side_effect=OSError("simulated replacement failure")):
            with self.assertRaises(OSError):
                self.publisher.update("soft", self.soft, self.root)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob(".*.tmp")), [])

    def test_invalid_existing_history_blocks_update(self):
        first = self.history / (self.data["score_history"][0]["id"] + ".json")
        invalid = json.loads(first.read_text())
        invalid["private_note"] = "Not public"
        first.write_text(json.dumps(invalid))
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.publisher.update("soft", self.soft, self.root)
        self.assertEqual(self.path.read_bytes(), before)

    def test_symlink_current_file_is_rejected(self):
        original = self.path.read_bytes()
        target = self.root / "private.json"
        target.write_bytes(original)
        self.path.unlink()
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.publisher.update("soft", self.soft, self.root)
        self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
