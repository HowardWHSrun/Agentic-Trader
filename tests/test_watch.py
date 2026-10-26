"""Validate the public watch feed without brokerage access or network calls."""
import json
import math
import re
import copy
import sys
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
V2_RUBRIC = "buying-score-v2"
V2_COHORTS = {
    "v2-regular", "v2-premarket", "v2-provisional-book-price",
    "v2-official-close", "v2-historical-official-close",
}


def v2_scorer():
    """Load the pure scorer; original v1 validation stays independent of v2 data."""
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import buying_score_v2
    return buying_score_v2


def _same_typed_value(actual, expected):
    """Derived integer components must not accept booleans or float lookalikes."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _same_typed_value(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _same_typed_value(a, b) for a, b in zip(actual, expected))
    return actual == expected


def validate_v2_record(record, hard, assessed):
    """Validate arithmetic and labels, not the truth or freshness of market facts."""
    summary = v2_scorer().summarize(record.get("evidence_checks"))
    if "component_scores" in record and not _same_typed_value(record["component_scores"], summary["component_scores"]):
        raise ValueError("V2 components must match the evidence checks")
    for check in record["evidence_checks"]:
        # Nullable actual values are permitted for every status. Nonempty
        # evidence/reasons are required by the scorer; do not invent a source.
        if check["source_url"] is not None:
            source_url(check["source_url"])
        if check["observed_at"] is not None and timestamp(check["observed_at"]) > assessed:
            raise ValueError("Check evidence cannot follow assessment")
    if record.get("cohort") != hard["cohort"] or hard["cohort"] not in V2_COHORTS:
        raise ValueError("V2 record and review need the same explicit v2 cohort")
    session = record.get("reference_session")
    price_type = record.get("reference_price_type")
    price = record.get("reference_price")
    reference_time = record.get("reference_price_timestamp")
    if not isinstance(price_type, str) or not price_type.strip():
        raise ValueError("V2 reference price type is required")
    price_type = price_type.lower()
    has_reference = price is not None or reference_time is not None
    if not has_reference:
        # An all-32 review must retain rows whose references are unavailable.
        # Do not manufacture an official close or a book label for those rows.
        allowed_sessions = {"regular", "unknown"}
        if hard["cohort"] == "v2-premarket":
            allowed_sessions = {"premarket", "unknown"}
        elif hard["cohort"] == "v2-provisional-book-price":
            allowed_sessions = {"regular", "premarket", "after-hours", "overnight", "unknown"}
        if session not in allowed_sessions:
            raise ValueError("Missing reference needs an unknown or cohort-compatible session")
    else:
        if hard["cohort"] == "v2-regular" and session != "regular":
            raise ValueError("Regular cohort requires regular-session evidence")
        if hard["cohort"] == "v2-premarket" and session != "premarket":
            raise ValueError("Premarket cohort requires premarket evidence")
        if hard["cohort"] in {"v2-regular", "v2-premarket"} and (
                re.search(r"\b(?:bid|ask|book)\b", price_type) or
                ("official" in price_type and "close" in price_type)):
            raise ValueError("Trade cohorts cannot contain book or official-close references")
        if hard["cohort"] in {"v2-official-close", "v2-historical-official-close"}:
            if session != "regular" or "official" not in price_type or "close" not in price_type:
                raise ValueError("Official-close cohort needs an explicitly labeled regular close")
        if hard["cohort"] == "v2-provisional-book-price":
            if session not in {"regular", "premarket", "after-hours", "overnight"} or not any(
                    label in price_type for label in ("bid", "ask", "book")):
                raise ValueError("Book-price cohort requires explicit book type and session")
    if price is not None:
        if type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid v2 reference price")
        if reference_time is None:
            raise ValueError("A v2 price needs its original timestamp")
    if reference_time is not None and timestamp(reference_time) > assessed:
        raise ValueError("Reference price cannot follow assessment")
    score = record["score"]
    if score is None:
        # Core identity/price/session verification can still withhold a score
        # when other checklist evidence is known. Keep the blocker explicit.
        if record.get("score_status") != "unavailable" or not isinstance(record.get("missing_evidence"), str) or not record["missing_evidence"].strip():
            raise ValueError("Unavailable score needs unavailable status and evidence gap")
    elif (type(score) is not int or score != summary["score"] or
          record.get("score_status") != "available_provisional"):
        raise ValueError("V2 score must match checklist points and be provisional")
    elif price is None or reference_time is None:
        raise ValueError("Numeric v2 score needs a dated reference price")


def v2_fixture(data, states=None):
    """Synthetic local-test data only; never a market assessment or public refresh."""
    data = copy.deepcopy(data)
    hard = data["last_hard_check"]
    at = (timestamp(hard["publication_timestamp"]) + timedelta(days=1)).isoformat()
    hard.update(id="v2-synthetic-test", publication_timestamp=at, assessment_snapshot=at,
                rubric_version=V2_RUBRIC, weights=copy.deepcopy(WEIGHTS),
                cohort="v2-regular", summary="Synthetic v2 validator fixture")
    states = ["unknown"] * 20 if states is None else states
    checks = [
        {"id": item["id"], "status": status, "evidence": "Synthetic test evidence or gap.",
         "source_url": None, "observed_at": None}
        for item, status in zip(v2_scorer().CHECKS, states)
    ]
    summary = v2_scorer().summarize(checks)
    for record in hard["records"]:
        record.update(rubric_version=V2_RUBRIC, cohort=hard["cohort"],
                      evidence_checks=copy.deepcopy(checks),
                      component_scores=copy.deepcopy(summary["component_scores"]),
                      score=summary["score"],
                      score_status="unavailable" if summary["score"] is None else "available_provisional",
                      reference_price=None if summary["score"] is None else 100.0,
                      reference_price_timestamp=None if summary["score"] is None else at,
                      reference_price_type="synthetic regular-session reference",
                      reference_session="regular", reference_source="Synthetic test fixture",
                      reason="Synthetic validator test; not market research.",
                      conditional_action="No current entry suggestion; synthetic test only.",
                      missing_evidence="Synthetic unknown/core evidence gap.",
                      quote_delay="unknown", sources=[])
    data["score_history"].append({
        "id": hard["id"], "publication_timestamp": at,
        "path": "data/watch-history/" + hard["id"] + ".json",
    })
    return data


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
        if hard["rubric_version"] not in {"buying-score-v1", V2_RUBRIC}:
            raise ValueError("Rubric change requires a new implementation/cohort")
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
        if hard["rubric_version"] == V2_RUBRIC:
            allowed = allowed | {"evidence_checks"}
        for r in hard["records"]:
            if set(r) - allowed:
                raise ValueError("Unexpected assessment fields")
            if any(not isinstance(r.get(k), str) or not r[k].strip() for k in ("conditional_action", "reason")):
                raise ValueError("Missing assessment or plan")
            if r.get("rubric_version") != hard["rubric_version"] or r.get("sizing") != PUBLIC_SIZING:
                raise ValueError("Invalid record rubric or public sizing")
            if hard["rubric_version"] == V2_RUBRIC:
                validate_v2_record(r, hard, assessed)
                for source in r.get("sources", []):
                    source_url(source)
                continue
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

    def numeric_fixture(self):
        """Numeric validation must not depend on the latest published cohort."""
        data = copy.deepcopy(self.data)
        # Pin an immutable v1 original so a future current v2 review cannot
        # change the meaning of these legacy mutation tests.
        for index, item in enumerate(data["score_history"]):
            path = ROOT / "docs" / item["path"]
            if not path.exists():
                continue
            original = json.loads(path.read_text())
            if original["rubric_version"] == "buying-score-v1":
                data["last_hard_check"] = original
                data["score_history"] = data["score_history"][:index + 1]
                break
        else:
            raise AssertionError("An immutable v1 regression fixture is required")
        record = data["last_hard_check"]["records"][0]
        record.update(score=50, score_status="available", reference_price=100.0,
                      reference_price_timestamp=data["last_hard_check"]["assessment_snapshot"],
                      component_scores={"entry_quality": 15, "trend_relative_strength": 10,
                                        "catalyst": 10, "fundamentals_valuation": 5,
                                        "liquidity_event_risk": 10})
        validate(data)
        return data

    def test_reject_invalid_weights_components_and_sizing(self):
        mutations = [
            lambda d: d["last_hard_check"]["weights"].update(entry_quality=31),
            lambda d: d["last_hard_check"]["records"][0].update(component_scores={"entry_quality": 60}),
            lambda d: d["last_hard_check"]["records"][0].update(sizing="Buy 100 shares"),
        ]
        for mutate in mutations:
            data = self.numeric_fixture()
            mutate(data)
            with self.assertRaises(ValueError):
                validate(data)

    def test_reject_nonfinite_and_boolean_reference_prices(self):
        self.data = self.numeric_fixture()
        for price in (float("nan"), float("inf"), -float("inf"), True):
            self.data["last_hard_check"]["records"][0]["reference_price"] = price
            with self.assertRaises(ValueError):
                validate(self.data)

    def test_reject_inconsistent_score_status(self):
        for score, status in ((50, "unavailable"), (None, "available")):
            data = copy.deepcopy(self.data)
            record = data["last_hard_check"]["records"][0]
            record["score"] = score
            record["score_status"] = status
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
        self.data = self.numeric_fixture()
        self.data["last_hard_check"]["records"][0]["reference_price_timestamp"] = (timestamp(self.data["last_hard_check"]["assessment_snapshot"]) + timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_generic_privacy_disclosures_are_not_rejected(self):
        self.data["privacy"] = "Personal holdings, account balances and private allocations are not published."
        validate(self.data)


class V2WatchTests(unittest.TestCase):
    def setUp(self):
        self.base = json.loads((ROOT / "docs/data/watch.json").read_text())

    def fixture(self, states=None):
        return v2_fixture(self.base, states)

    def test_legacy_numeric_fixture_is_independent_of_current_v2_review(self):
        legacy = WatchTests()
        legacy.data = self.fixture(["pass"] * 20)
        fixture = legacy.numeric_fixture()
        self.assertEqual(fixture["last_hard_check"]["rubric_version"], "buying-score-v1")
        validate(fixture)

    def test_v2_all_unknown_is_null_and_fully_unresolved(self):
        data = self.fixture()
        validate(data)
        record = data["last_hard_check"]["records"][0]
        result = v2_scorer().summarize(record["evidence_checks"])
        self.assertIsNone(record["score"])
        self.assertEqual(record["score_status"], "unavailable")
        self.assertEqual(result["coverage"], 0)
        self.assertEqual(result["unresolved"], 100)
        self.assertEqual(result["counts"], {"pass": 0, "fail": 0, "unknown": 20})
        self.assertIsNone(result["completion_range"])

    def test_v2_fixed_denominator_and_separate_completeness(self):
        cases = [
            (["pass"] * 20, 100, 100, 0, [100, 100]),
            (["fail"] * 20, 0, 100, 0, [0, 0]),
            (["pass"] * 8 + ["fail"] * 8 + ["unknown"] * 4, 40, 80, 20, [40, 60]),
            (["pass"] + ["unknown"] * 19, 5, 5, 95, [5, 100]),
            (["fail"] + ["unknown"] * 19, 0, 5, 95, [0, 95]),
        ]
        for states, score, coverage, unresolved, completion_range in cases:
            with self.subTest(states=states):
                data = self.fixture(states)
                validate(data)
                record = data["last_hard_check"]["records"][0]
                result = v2_scorer().summarize(record["evidence_checks"])
                self.assertEqual(record["score"], score)
                self.assertEqual(result["coverage"], coverage)
                self.assertEqual(result["unresolved"], unresolved)
                self.assertEqual(result["completion_range"], completion_range)
                self.assertEqual(result["counts"], {state: states.count(state) for state in ("pass", "fail", "unknown")})

    def test_v2_rejects_wrong_check_count_ids_states_and_fields(self):
        mutations = [
            lambda checks: checks.pop(),
            lambda checks: checks.append(copy.deepcopy(checks[0])),
            lambda checks: checks[0].update(id=checks[1]["id"]),
            lambda checks: checks[0].update(id="unrecognized-check"),
            lambda checks: checks[0].update(status="PASS"),
            lambda checks: checks[0].update(status=True),
            lambda checks: checks[0].update(status=None),
            lambda checks: checks[0].pop("status"),
            lambda checks: checks[0].update(extra="not allowlisted"),
            lambda checks: checks[0].update(evidence=" "),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                data = self.fixture()
                mutate(data["last_hard_check"]["records"][0]["evidence_checks"])
                with self.assertRaises(ValueError):
                    validate(data)

    def test_v2_rejects_arithmetic_status_components_and_unpublished_metrics(self):
        mutations = [
            lambda r: r.update(score=100),
            lambda r: r.update(score=True),
            lambda r: r.update(score=40.0),
            lambda r: r.update(score_status="available"),
            lambda r: r["component_scores"].update(entry_quality=0),
            lambda r: r["component_scores"].update(fundamentals_valuation=False),
            lambda r: r.update(coverage=80),
            lambda r: r.update(completion_range=[40, 60]),
            lambda r: r.update(unresolved=20),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                data = self.fixture(["pass"] * 8 + ["fail"] * 8 + ["unknown"] * 4)
                mutate(data["last_hard_check"]["records"][0])
                with self.assertRaises(ValueError):
                    validate(data)
        data = self.fixture()
        data["last_hard_check"]["records"][0].update(score=0, score_status="available_provisional",
                                                   reference_price=100,
                                                   reference_price_timestamp=data["last_hard_check"]["assessment_snapshot"])
        with self.assertRaises(ValueError):
            validate(data)

    def test_v2_component_scores_remain_optional(self):
        data = self.fixture(["pass"] * 20)
        for record in data["last_hard_check"]["records"]:
            record.pop("component_scores")
        validate(data)

    def test_v2_core_gate_can_withhold_known_checklist_score(self):
        data = self.fixture(["pass"] * 20)
        record = data["last_hard_check"]["records"][0]
        record.update(score=None, score_status="unavailable", reference_price=None,
                      reference_price_timestamp=None,
                      missing_evidence="Core instrument identity verification is unresolved.",
                      conditional_action="No current entry suggestion while identity is unresolved.")
        validate(data)
        self.assertEqual(v2_scorer().summarize(record["evidence_checks"])["score"], 100)
        record["missing_evidence"] = ""
        with self.assertRaises(ValueError):
            validate(data)

    def test_v2_nullable_actual_sources_and_observation_times_are_preserved(self):
        data = self.fixture(["pass"] * 20)
        validate(data)
        record = data["last_hard_check"]["records"][0]
        self.assertIsNone(record["evidence_checks"][0]["source_url"])
        self.assertIsNone(record["evidence_checks"][0]["observed_at"])
        check = record["evidence_checks"][0]
        check.update(source_url="https://example.com/public-evidence",
                     observed_at=data["last_hard_check"]["assessment_snapshot"])
        validate(data)

    def test_v2_nonnull_evidence_urls_and_times_must_be_safe_and_ordered(self):
        for updates in [
            {"source_url": "javascript:alert(1)"},
            {"source_url": "https://user:secret@example.com/public"},
            {"source_url": "https://example.com/?account=private"},
            {"observed_at": "2026-10-21T12:00:00"},
            {"observed_at": "2026-10-21"},
        ]:
            with self.subTest(updates=updates):
                data = self.fixture(["pass"] * 20)
                data["last_hard_check"]["records"][0]["evidence_checks"][0].update(updates)
                with self.assertRaises(ValueError):
                    validate(data)
        data = self.fixture(["pass"] * 20)
        data["last_hard_check"]["records"][0]["evidence_checks"][0]["observed_at"] = (
            timestamp(data["last_hard_check"]["assessment_snapshot"]) + timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            validate(data)

    def test_v2_reference_price_validation_and_ordering(self):
        for price in [True, float("nan"), float("inf"), 0, -1]:
            with self.subTest(price=price):
                data = self.fixture(["pass"] * 20)
                data["last_hard_check"]["records"][0]["reference_price"] = price
                with self.assertRaises(ValueError):
                    validate(data)
        for field in ("reference_price", "reference_price_timestamp"):
            data = self.fixture(["pass"] * 20)
            data["last_hard_check"]["records"][0][field] = None
            with self.assertRaises(ValueError):
                validate(data)
        data = self.fixture(["pass"] * 20)
        data["last_hard_check"]["records"][0]["reference_price_timestamp"] = (
            timestamp(data["last_hard_check"]["assessment_snapshot"]) + timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            validate(data)

    def test_v2_requires_explicit_matching_cohort_and_session(self):
        for cohort, session, price_type in [
            ("v2-regular", "regular", "regular-session trade"),
            ("v2-premarket", "premarket", "premarket trade"),
            ("v2-provisional-book-price", "premarket", "indicative ask"),
            ("v2-provisional-book-price", "after-hours", "bid/ask book"),
            ("v2-provisional-book-price", "overnight", "book-only ask"),
            ("v2-official-close", "regular", "verified official close"),
            ("v2-historical-official-close", "regular", "historical official close"),
        ]:
            with self.subTest(cohort=cohort, session=session):
                data = self.fixture(["pass"] * 20)
                hard = data["last_hard_check"]
                hard["cohort"] = cohort
                for record in hard["records"]:
                    record.update(cohort=cohort, reference_session=session,
                                  reference_price_type=price_type)
                validate(data)
        for cohort, session, price_type in [
            ("regular", "regular", "trade"),
            ("v2-future-unknown", "regular", "trade"),
            ("v2-regular", "premarket", "trade"),
            ("v2-regular", "regular", "indicative ask"),
            ("v2-regular", "regular", "verified official close"),
            ("v2-premarket", "premarket", "bid/ask book"),
            ("v2-premarket", "premarket", "official close"),
            ("v2-premarket", "regular", "trade"),
            ("v2-official-close", "regular", "indicative ask"),
            ("v2-historical-official-close", "premarket", "official close"),
            ("v2-provisional-book-price", "unknown", "indicative ask"),
            ("v2-provisional-book-price", "regular", "last trade"),
        ]:
            with self.subTest(cohort=cohort, session=session, price_type=price_type):
                data = self.fixture(["pass"] * 20)
                hard = data["last_hard_check"]
                hard["cohort"] = cohort
                for record in hard["records"]:
                    record.update(cohort=cohort, reference_session=session,
                                  reference_price_type=price_type)
                with self.assertRaises(ValueError):
                    validate(data)
        data = self.fixture(["pass"] * 20)
        data["last_hard_check"]["records"][0]["cohort"] = "v2-premarket"
        with self.assertRaises(ValueError):
            validate(data)

    def test_v2_missing_references_remain_unavailable_in_every_cohort(self):
        for cohort, targeted_session in [
            ("v2-regular", "regular"),
            ("v2-premarket", "premarket"),
            ("v2-provisional-book-price", "overnight"),
            ("v2-official-close", "regular"),
            ("v2-historical-official-close", "regular"),
        ]:
            for session in ("unknown", targeted_session):
                with self.subTest(cohort=cohort, session=session):
                    data = self.fixture()
                    hard = data["last_hard_check"]
                    hard["cohort"] = cohort
                    for record in hard["records"]:
                        record.update(cohort=cohort, reference_session=session,
                                      reference_price_type="unavailable",
                                      reference_price=None, reference_price_timestamp=None,
                                      reference_source=None)
                    validate(data)
                    self.assertTrue(all(record["score"] is None for record in hard["records"]))
                    self.assertTrue(all(
                        check["source_url"] is None and check["observed_at"] is None
                        for record in hard["records"] for check in record["evidence_checks"]))

    def test_v2_missing_reference_still_requires_matching_cohort_and_compatible_session(self):
        for updates in [{"cohort": "v2-premarket"}, {"reference_session": "after-hours"}]:
            data = self.fixture()
            data["last_hard_check"]["records"][0].update(updates)
            with self.assertRaises(ValueError):
                validate(data)

    def test_v2_unknown_versions_mixed_rubrics_and_v1_weight_changes_rejected(self):
        for mutate in [
            lambda h: h.update(rubric_version="buying-score-v999"),
            lambda h: h["records"][0].update(rubric_version="buying-score-v1"),
            lambda h: h["weights"].update(entry_quality=31),
        ]:
            data = self.fixture()
            mutate(data["last_hard_check"])
            with self.assertRaises(ValueError):
                validate(data)
        data = copy.deepcopy(self.base)
        data["last_hard_check"]["records"][0]["evidence_checks"] = []
        with self.assertRaises(ValueError):
            validate(data)


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



    def test_v2_append_and_soft_update_preserve_v1_original_bytes(self):
        before = {p.name: p.read_bytes() for p in self.history.iterdir()}
        review = v2_fixture(self.data, ["pass"] * 8 + ["fail"] * 8 + ["unknown"] * 4)["last_hard_check"]
        self.publisher.update("hard", review, self.root)
        after_hard = json.loads(self.path.read_text())
        self.assertEqual(after_hard["last_hard_check"], review)
        self.assertEqual(after_hard["last_soft_check"], self.data["last_soft_check"])
        for name, original in before.items():
            self.assertEqual((self.history / name).read_bytes(), original)
        for key in set(self.data) - {"last_hard_check", "score_history"}:
            self.assertEqual(after_hard[key], self.data[key])
        new_path = self.history / (review["id"] + ".json")
        original_v2 = new_path.read_bytes()
        self.publisher.update("hard", review, self.root)
        self.assertEqual(new_path.read_bytes(), original_v2)
        self.assertEqual(len(json.loads(self.path.read_text())["score_history"]), len(self.data["score_history"]) + 1)
        self.publisher.update("soft", self.soft, self.root)
        after_soft = json.loads(self.path.read_text())
        self.assertEqual(after_soft["last_hard_check"], review)
        self.assertEqual(after_soft["score_history"], after_hard["score_history"])
        self.assertEqual(new_path.read_bytes(), original_v2)
        for name, original in before.items():
            self.assertEqual((self.history / name).read_bytes(), original)

    def test_v2_original_cannot_be_rewritten(self):
        review = v2_fixture(self.data, ["pass"] * 20)["last_hard_check"]
        self.publisher.update("hard", review, self.root)
        new_path = self.history / (review["id"] + ".json")
        original = new_path.read_bytes()
        changed = copy.deepcopy(review)
        changed["records"][0]["evidence_checks"][0]["evidence"] = "Rewritten evidence"
        with self.assertRaises(ValueError):
            self.publisher.update("hard", changed, self.root)
        self.assertEqual(new_path.read_bytes(), original)

    def test_invalid_v2_input_preserves_current_and_history_bytes(self):
        before_current = self.path.read_bytes()
        before_history = {p.name: p.read_bytes() for p in self.history.iterdir()}
        review = v2_fixture(self.data, ["pass"] * 20)["last_hard_check"]
        review["records"][0]["score"] = 95
        with self.assertRaises(ValueError):
            self.publisher.update("hard", review, self.root)
        self.assertEqual(self.path.read_bytes(), before_current)
        self.assertEqual({p.name: p.read_bytes() for p in self.history.iterdir()}, before_history)


if __name__ == "__main__":
    unittest.main()
