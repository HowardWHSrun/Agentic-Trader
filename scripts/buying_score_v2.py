"""Deterministic buying-score-v2 evidence arithmetic; no market or account access.

A check's factual conclusion is supplied by the researcher, not verified here.
The score is never normalized to known evidence and is not a probability.
"""
from datetime import datetime
import re
from urllib.parse import parse_qsl, unquote, urlparse

WEIGHTS = {"entry_quality":30,"trend_relative_strength":25,"catalyst":20,"fundamentals_valuation":10,"liquidity_event_risk":15}
CHECKS = [
    {
        "id": "E1",
        "component": "entry_quality",
        "label": "A support, retest or breakout setup level is identified from completed bars."
    },
    {
        "id": "E2",
        "component": "entry_quality",
        "label": "Reference entry lies within 0.5 ATR14 of that setup level."
    },
    {
        "id": "E3",
        "component": "entry_quality",
        "label": "A structural invalidation level is identified below a prospective long entry."
    },
    {
        "id": "E4",
        "component": "entry_quality",
        "label": "The first defensible target gives at least 2R, using reference entry and invalidation."
    },
    {
        "id": "E5",
        "component": "entry_quality",
        "label": "No intervening verified resistance obstructs the 2R path."
    },
    {
        "id": "E6",
        "component": "entry_quality",
        "label": "Reference entry is no more than 1 ATR14 above the 20-session SMA."
    },
    {
        "id": "T1",
        "component": "trend_relative_strength",
        "label": "The last completed close is above SMA20."
    },
    {
        "id": "T2",
        "component": "trend_relative_strength",
        "label": "SMA20 is above SMA50."
    },
    {
        "id": "T3",
        "component": "trend_relative_strength",
        "label": "SMA20 is above its value five sessions earlier."
    },
    {
        "id": "T4",
        "component": "trend_relative_strength",
        "label": "The 20-session price return exceeds SPY on matching dates."
    },
    {
        "id": "T5",
        "component": "trend_relative_strength",
        "label": "The 20-session price return exceeds an explicitly assigned sector benchmark on matching dates."
    },
    {
        "id": "C1",
        "component": "catalyst",
        "label": "A material FAVORABLE catalyst supporting a prospective long entry is primary-source verified."
    },
    {
        "id": "C2",
        "component": "catalyst",
        "label": "That qualifying favorable catalyst's event or impact is within the next five trading sessions, or happened within the previous five with a supported continuing effect."
    },
    {
        "id": "C3",
        "component": "catalyst",
        "label": "That favorable catalyst has a documented positive mechanism supporting earnings, cash flow or demand rather than a headline alone."
    },
    {
        "id": "C4",
        "component": "catalyst",
        "label": "Relevant primary disconfirming evidence was checked and does not invalidate that favorable long-entry thesis."
    },
    {
        "id": "F1",
        "component": "fundamentals_valuation",
        "label": "Latest TTM operating cash flow is positive."
    },
    {
        "id": "F2",
        "component": "fundamentals_valuation",
        "label": "Positive trailing P/E is at or below its own three-year median; unknown if unsupported, fail for verified negative earnings or above-median valuation."
    },
    {
        "id": "L1",
        "component": "liquidity_event_risk",
        "label": "A fresh two-sided noncrossed spread is at most 0.20% at the reference timestamp."
    },
    {
        "id": "L2",
        "component": "liquidity_event_risk",
        "label": "Average 20-session daily dollar volume is at least USD20 million."
    },
    {
        "id": "L3",
        "component": "liquidity_event_risk",
        "label": "No verified scheduled earnings or major binary event lies within the next five trading sessions; unknown if the calendar was inadequately checked; include relevant macro events such as FOMC."
    }
]
CHECK_IDS = tuple(check["id"] for check in CHECKS)
FIELDS = {"id", "status", "evidence", "source_url", "observed_at"}


def _provenance(check):
    source = check["source_url"]
    if source is not None:
        if not isinstance(source, str):
            raise ValueError("source_url must be an HTTPS URL or null")
        url = urlparse(source)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Unsafe check source URL")
        for area in (url.query, url.fragment):
            for key, _ in parse_qsl(area, keep_blank_values=True):
                key = re.sub(r"[^a-z0-9]", "", unquote(key).lower())
                if re.search(r"account|token|secret|password|passwd|apikey|credential|authorization|session|signature|email|customer|userid|clientid|xamz|xgoog", key) or key in {"auth", "key", "code", "sig"}:
                    raise ValueError("Private query field in check source URL")
    observed = check["observed_at"]
    if observed is not None:
        if not isinstance(observed, str) or "T" not in observed:
            raise ValueError("observed_at must be a zoned timestamp or null")
        parsed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Check observation is missing timezone")


def summarize(checks):
    """Return derived metrics; callers still enforce core instrument/price gates."""
    if not isinstance(checks, list) or len(checks) != 20:
        raise ValueError("Exactly twenty evidence checks are required")
    by_id = {}
    for check in checks:
        if not isinstance(check, dict) or set(check) != FIELDS:
            raise ValueError("Unexpected or missing evidence-check fields")
        ident = check["id"]
        if not isinstance(ident, str) or ident not in CHECK_IDS or ident in by_id:
            raise ValueError("Unknown or duplicate evidence-check ID")
        if not isinstance(check["status"], str) or check["status"] not in {"pass", "fail", "unknown"}:
            raise ValueError("Evidence status must be pass, fail or unknown")
        if not isinstance(check["evidence"], str) or not check["evidence"].strip():
            raise ValueError("Every check needs evidence or an unknown reason")
        _provenance(check)
        by_id[ident] = check
    counts = {status: sum(c["status"] == status for c in checks)
              for status in ("pass", "fail", "unknown")}
    components = {key: 0 for key in WEIGHTS}
    for definition in CHECKS:
        if by_id[definition["id"]]["status"] == "pass":
            components[definition["component"]] += 5
    score = 5 * counts["pass"] if counts["pass"] + counts["fail"] else None
    unresolved = 5 * counts["unknown"]
    return {
        "score": score,
        "coverage": 5 * (counts["pass"] + counts["fail"]),
        "unresolved": unresolved,
        "counts": counts,
        "component_scores": components,
        "completion_range": None if score is None else [score, score + unresolved],
    }
