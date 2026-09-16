#!/usr/bin/env python3
"""Export a deliberately small public view of private research archives.

Only review.json, scan.json, and an optional crypto.json are read. Holdings/account/config snapshots, markdown,
positions, sizing amounts and unknown keys never enter the output schema.
Optional equity current_quotes contain only public market prices and provenance,
never an indication that a quoted symbol is personally held.
Free text passes a separate conservative privacy filter: sentences containing
personal-finance context, identifiers, local paths or credentials are omitted.
This is a publication boundary, not a lossless archive or a fresh market scan.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

MAX_INPUT_BYTES = 20 * 1024 * 1024
CHECK_TYPES = {"baseline_archive", "intraday", "after_close", "failed_check"}
DECISIONS = {"no_opportunity", "watch_only", "qualified_opportunity", "monitor_failure"}
RISK_RULES = {
    "max_position_pct": 25,
    "risk_per_trade_pct": 1.5,
    "max_open_risk_pct": 1.5,
    "max_total_exposure_pct": 30,
    "max_sector_exposure_pct": 25,
    "max_positions": 3,
    "max_new_entries_per_week": 1,
}
METRIC_FIELDS = (
    "close", "sma20", "sma50", "sma200", "atr14", "relative_return_20",
    "return_20", "relative_volume", "prior20_high",
)
PLAN_FIELDS = ("entry", "stop", "target_2r", "max_entry_chase", "stop_distance_pct")
FILTER_FIELDS = (
    "dollar_liquidity", "long_trend", "minimum_price",
    "positive_relative_strength", "valid_atr",
)
CRYPTO_FILTER_FIELDS = (
    "data_quality", "market_gate", "trend", "relative_strength",
    "recent_trade_volume_evidence", "quote_fresh", "venue_quote_review_passed",
)
REVIEW_FIELDS = ("why_interesting", "why_not_actionable", "what_would_change")
SECTORS = {
    "broad_market", "consumer_discretionary", "consumer_staples", "energy",
    "financials", "healthcare", "industrials", "small_caps", "technology_growth",
    "utilities", "technology", "information_technology", "communication_services",
    "materials", "real_estate", "health_care", "unknown",
}
SETUPS = {"pullback_reclaim", "pullback", "breakout", "breakout_20", "breakout_20d"}
ENTRY_ID = re.compile(r"^\d{8}T\d{6}\.\d{6}Z-(?:baseline_archive|intraday|after_close|failed_check)$")
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
CRYPTO_SYMBOL = re.compile(r"^[A-Z0-9]{2,10}/USD$")
QUOTE_FIELDS = ("bid", "ask", "spread_pct", "observed_at", "provider", "venue")
CURRENT_QUOTE_FIELDS = ("symbol", "bid", "ask", "observed_at", "source", "session")
CURRENT_QUOTE_OPTIONAL_FIELDS = ("last_price", "last_trade_at", "prior_close", "prior_close_date")
QUOTE_SESSIONS = {"regular", "pre_market", "after_hours", "overnight", "closed", "unknown"}

# Dropping whole sentences avoids leaving a private amount detached from its
# context. Decimal points and ISO timestamps are not sentence boundaries.
SENTENCES = re.compile(r"(?<=[.!?。！？])\s+(?=[A-Z0-9\"'])|[\r\n]+")
PRIVATE_CONTEXT = re.compile(
    r"\b(?:account\w*|acct|balance\w*|buying[ -]?power|purchasing[ -]?power|"
    r"deposit\w*|withdraw\w*|holdings|holding(?![ -]+(?:window|period)\b)|portfolio|net[ -]?(?:worth|liquidation)|"
    r"wallet|bankroll|broker\w*|statement|cash|capital|margin|funds?|allocat\w*|I|we|my|our|"
    r"available[ -]?(?:cash|funds|capital)|"
    r"settled[ -]?cash|unsettled[ -]?cash|cash[ -]?(?:balance|available)|"
    r"equity[ -]?(?:value|balance)|funds?\s+(?:available|remaining)|"
    r"capital[ -]?(?:ceiling|budget)|whole[ -]?position|position[ -]?(?:ceiling|cap)|"
    r"(?:planned[ -]?(?:loss|risk)|loss|risk|personal)[ -]?budget|"
    r"personal|private|user(?:'s)?|customer|client[ -]?(?:id|number)|"
    r"filled|fills|executed|transactions?|order[ -]?(?:id|number)|"
    r"(?:my|our)\s+(?:cash|money|funds|capital|shares|trades|position)|"
    r"(?:bought|sold|purchased|deposited)|social[ -]?security|routing|iban)\b|"
    r"(?:账户|帳戶|余额|餘額|购买力|購買力|入金|出金|持仓|持倉|本金|预算|預算|账号|帳號)",
    re.IGNORECASE,
)
SENSITIVE_LITERAL = re.compile(
    r"(?:\b(?:api[ _-]?key|access[ _-]?token|refresh[ _-]?token|password|passwd|"
    r"secret|authorization|bearer|cookie|credential|session[ _-]?id)\b)|"
    r"(?:\b(?:sk|pk|ghp|github_pat|AKIA)[_-]?[A-Za-z0-9_-]{12,})|"
    r"(?:\b[A-Fa-f0-9]{24,}\b)|(?:\b[A-Za-z0-9_-]{32,}\b)|"
    r"(?:\b\d{4,}(?:[- ]\d{3,})+\b)|(?:\b\d{8,}\b)|"
    r"(?:[*•xX]{2,}[ -]*\d{2,})|(?:\d{2,}[ -]*[*•xX]{2,})|"
    r"(?:\b(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{8,}\b)|"
    r"(?:\b(?:ending\s+in|last\s+four)\s*[:#]?\s*\d{4}\b)|"
    r"(?:\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b)|"
    r"(?:file://|(?:^|\s)(?:~?/|[A-Za-z]:\\)|/(?:Users|home|mnt|tmp|var|private)/)|"
    r"(?:(?:^|\s)(?:\.{1,2}/|(?:logs|reports|data|spending|credentials)/)\S+)|"
    r"(?:\b(?:[\w.-]+/)+[\w.-]+\.(?:json|csv|tsv|xlsx|env|pem|key|sqlite|db)\b)|"
    r"(?:\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)|"
    r"(?:\b\d+(?:\.\d+)?\s+(?!(?:USD|EUR|GBP|CNY|RMB|JPY|UTC|SMA|ATR|SIP|US)\b)(?-i:[A-Z][A-Z0-9]{1,9})\b)|"
    r"(?:\b(?:\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|single)"
    r"[ -]+(?:whole[ -]?)?(?:shares?|contracts?|units?)\b)",
    re.IGNORECASE,
)
MONEY_NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"
MONEY = re.compile(
    r"(?:[$€£¥]\s*" + MONEY_NUMBER + r"|\b(?:USD|EUR|GBP|CNY|RMB|JPY)\s*"
    + MONEY_NUMBER + r"\b|\b" + MONEY_NUMBER
    + r"\s*(?:USD|EUR|GBP|CNY|RMB|JPY|(?:US\s+)?dollars?|bucks|euros?|yuan)\b)", re.I,
)
# A money amount must be grammatically adjacent to its own market-price label.
# A target or entry in another clause cannot legitimize an unrelated amount.
PRICE_LABEL = r"(?:closed?|price|sma\d*|average|entry|stop|target|objective|high|low|resistance|support|ATR\d*|spread)"
PRICE_BEFORE_MONEY = re.compile(
    r"\b" + PRICE_LABEL + r"\b(?:\s+(?:at|of|is|was|around|near|about|equals?|the|its|a|an)){0,4}\s*[(:=]?\s*$", re.I,
)
PRICE_AFTER_MONEY = re.compile(
    r"^\s+(?:(?:\d+[- ]session|\d+R|arithmetic|hypothetical|next[- ]session|planned)\s+){0,3}"
    + PRICE_LABEL + r"\b", re.I,
)
URL_IN_TEXT = re.compile(r"https?://\S+", re.I)


class ExportError(ValueError):
    """Input cannot safely be exported; the previous output remains intact."""


def public_url(value: object) -> str | None:
    """Allow only external, unauthenticated, query-free public HTTP(S) URLs."""
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parts = urlsplit(value.strip())
        hostname = parts.hostname
        if parts.scheme not in {"http", "https"} or not hostname:
            return None
        if parts.username or parts.password or parts.port not in {None, 80, 443}:
            return None
        if parts.query or parts.fragment:
            return None
        if hostname.lower() in {"localhost", "localhost.localdomain"} or "." not in hostname:
            return None
        if hostname.lower().endswith((".local", ".internal", ".localhost", ".test", ".invalid")):
            return None
        if PRIVATE_CONTEXT.search(hostname) or SENSITIVE_LITERAL.search(hostname):
            return None
        try:
            if not ipaddress.ip_address(hostname).is_global:
                return None
        except ValueError:
            pass
        decoded_path = parts.path
        for _ in range(3):
            decoded_path = unquote(decoded_path)
        if PRIVATE_CONTEXT.search(decoded_path) or SENSITIVE_LITERAL.search(decoded_path.lstrip("/")):
            return None
        if any(ord(char) < 32 for char in value + decoded_path) or "\\" in value + decoded_path:
            return None
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return None


def public_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    retained = []
    for sentence in SENTENCES.split(value.strip()):
        sentence = sentence.strip()
        if not sentence or len(sentence) > 4000:
            continue
        if PRIVATE_CONTEXT.search(sentence) or SENSITIVE_LITERAL.search(sentence):
            continue
        if any(
            not PRICE_BEFORE_MONEY.search(sentence[:amount.start()])
            and not PRICE_AFTER_MONEY.search(sentence[amount.end():])
            for amount in MONEY.finditer(sentence)
        ):
            continue
        if any(public_url(url.rstrip(".,;)")) is None for url in URL_IN_TEXT.findall(sentence)):
            continue
        retained.append(sentence)
    return " ".join(retained)


def public_lines(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean for item in value if (clean := public_text(item))]


def object_value(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def iso_timestamp(value: object, *, required: bool = False) -> str | None:
    try:
        if not isinstance(value, str):
            raise ValueError
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError):
        if required:
            raise ExportError("An archive has an invalid checked_at timestamp") from None
        return None


def iso_date(value: object) -> str | None:
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return None
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def read_object(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ExportError("An archive input is missing, linked, or too large")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError):
        raise ExportError("An archive input is not valid UTF-8 JSON") from None
    if not isinstance(data, dict):
        raise ExportError("An archive input must be a JSON object")
    return data


def sizing_status(candidate: dict) -> str:
    sizing = object_value(candidate.get("sizing"))
    if sizing.get("available") is not True:
        return "not_evaluated"
    shares = number(sizing.get("shares"))
    if shares is not None and shares <= 0:
        return "does_not_fit"
    if shares is not None and shares > 0 and not sizing.get("blockers"):
        return "within_limits"
    return "not_evaluated"


def future_requirements(value: object) -> str:
    """Keep future conditions useful when a private clause removes a sentence.

    These generic conditions are emitted only for requirements mentioned in that
    same omitted conditional sentence. No new observation or clearance is added.
    """
    if not isinstance(value, str):
        return ""
    retained = []
    for sentence in SENTENCES.split(value.strip()):
        safe = public_text(sentence)
        if safe:
            retained.append(safe)
            continue
        if not re.search(r"\b(?:require\w*|must|would\s+need)\b", sentence, re.I):
            continue
        conditions = []
        if re.search(r"\b(?:siz(?:e|ing)|position|risk)\b.*\b(?:limits?|fit|satisf\w*)\b|\bfit\b.*\blimits?\b", sentence, re.I):
            conditions.append("a size within position and risk limits")
        if re.search(r"\b(?:earnings|event)\b", sentence, re.I):
            conditions.append("verified earnings or event clearance" if re.search(r"\bearnings\b", sentence, re.I) else "event checks")
        if re.search(r"\bchart[- ]supported\b.*\broom\b", sentence, re.I):
            conditions.append("chart-supported reward room")
        if re.search(r"\b(?:live[- ]price|live|quotes?|spread)\b", sentence, re.I):
            conditions.append("fresh execution checks")
        if conditions:
            retained.append("A future setup requires " + ", ".join(conditions) + ".")
    return " ".join(retained)


def export_candidate(candidate: dict, reviews: dict, *, crypto: bool = False) -> dict | None:
    symbol = candidate.get("symbol")
    pattern = CRYPTO_SYMBOL if crypto else SYMBOL
    if not isinstance(symbol, str) or not pattern.fullmatch(symbol):
        return None
    raw_metrics = object_value(candidate.get("metrics"))
    raw_filters = object_value(candidate.get("filters"))
    raw_plan = object_value(candidate.get("plan"))
    plan = {key: number(raw_plan.get(key)) for key in PLAN_FIELDS} if raw_plan else None
    if crypto and plan is not None:
        plan["max_entry_chase"] = number(raw_plan.get("max_chase_price"))
    raw_review = object_value(candidate.get("review") if crypto else reviews.get(symbol))
    if crypto and raw_review:
        raw_review = {
            key: " ".join(item for item in value if isinstance(item, str)) if isinstance(value, list) else value
            for key, value in raw_review.items() if key in REVIEW_FIELDS
        }
    review = {key: public_text(raw_review.get(key)) for key in REVIEW_FIELDS} if raw_review else None
    if review:
        review["what_would_change"] = future_requirements(raw_review.get("what_would_change"))
    if review and candidate.get("technical_match") is True:
        reason = raw_review.get("why_not_actionable", "")
        rejected_sizing = isinstance(reason, str) and any(
            PRIVATE_CONTEXT.search(sentence)
            and re.search(r"\b(?:siz\w*|capital|ceiling|limit\w*|budget)\b", sentence, re.I)
            and re.search(r"\b(?:exceeds?|above|zero\s+whole\s+shares|does\s+not\s+fit)\b", sentence, re.I)
            for sentence in SENTENCES.split(reason)
        )
        if rejected_sizing:
            review["why_not_actionable"] = (
                "The recorded review also found that the setup did not fit sizing limits. "
                + review["why_not_actionable"]
            ).strip()
    raw_setups = candidate.get("setup_types")
    exported = {
        "symbol": symbol,
        "kind": "crypto" if crypto else candidate.get("kind") if candidate.get("kind") in {"stock", "etf"} else "unknown",
        "sector": "crypto" if crypto else candidate.get("sector") if candidate.get("sector") in SECTORS else "unknown",
        "last_date": iso_date(candidate.get("last_date")),
        "technical_match": boolean(candidate.get("technical_match")),
        "setup_types": [item for item in raw_setups if isinstance(item, str) and item in SETUPS]
        if isinstance(raw_setups, list) else [],
        "filters": {key: boolean(raw_filters.get(key)) for key in (CRYPTO_FILTER_FIELDS if crypto else FILTER_FIELDS)},
        "metrics": {key: number(raw_metrics.get(key)) for key in METRIC_FIELDS},
        "plan": plan,
        "blockers": public_lines(candidate.get("blockers")),
        "sizing_status": "not_evaluated" if crypto else sizing_status(candidate),
        "review": review,
    }
    if crypto:
        raw_quote = object_value(candidate.get("quote"))
        exported["quote"] = {
            "bid": number(raw_quote.get("bid")),
            "ask": number(raw_quote.get("ask")),
            "spread_pct": number(raw_quote.get("spread_pct")),
            "observed_at": iso_timestamp(raw_quote.get("observed_at")),
            "provider": public_text(raw_quote.get("provider")),
            "venue": public_text(raw_quote.get("venue")),
        } if raw_quote else None
    return exported


def export_sources(raw_sources: object) -> list[dict]:
    sources = []
    for source in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(source, dict):
            continue
        url = public_url(source.get("url"))
        title = public_text(source.get("title"))
        if url and title:
            sources.append({"title": title, "url": url, "as_of": public_text(source.get("as_of"))})
    return sources


def positive_price(value: object) -> int | float | None:
    """Accept finite positive market numbers, including broker decimal strings."""
    if isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", value):
        try:
            value = float(value)
        except (ValueError, OverflowError):
            return None
    try:
        clean = number(value)
    except OverflowError:
        return None
    return clean if clean is not None and clean > 0 else None


def quote_timestamp(value: object) -> str | None:
    """Normalize valid RFC3339 quote fractions to Python's microsecond precision."""
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        return None
    normalized = re.sub(r"\.(\d+)(?=Z|[+-]\d{2}:\d{2}$)", lambda match: "." + match.group(1)[:6].ljust(6, "0"), value)
    return iso_timestamp(normalized)


def export_current_quotes(value: object, known_symbols: set[str]) -> list[dict]:
    """Public quote contract: one newest dated observation per known equity.

    Zero, missing, invalid or crossed bid/ask values become null, never zero-price
    quotes. Invalid observation timestamps omit the row. Older archives may use
    side timestamps (the earlier valid bid/ask time), last_trade / trade_observed_at
    or prior_session_close; normalize those explicit market fields only.
    Optional last/prior fields are paired, and a missing valid timestamp/date
    suppresses its price. Conflicting observations at the same latest timestamp
    omit that symbol instead of making an arbitrary choice. [] means unavailable,
    not evidence of no holdings. No private snapshot is consulted.
    """
    latest = {}
    conflicts = set()
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict) or not isinstance(raw.get("symbol"), str) or raw["symbol"] not in known_symbols:
            continue
        observed_at = quote_timestamp(raw.get("observed_at"))
        if observed_at is None and "observed_at" not in raw:
            sides = [quote_timestamp(raw.get(key)) for key in ("bid_observed_at", "ask_observed_at")]
            if all(sides):
                observed_at = min(sides, key=lambda stamp: datetime.fromisoformat(stamp.replace("Z", "+00:00")))
        if observed_at is None:
            continue
        bid, ask = positive_price(raw.get("bid")), positive_price(raw.get("ask"))
        if bid is not None and ask is not None and bid > ask:
            bid = ask = None
        session = raw.get("session")
        quote = {
            "symbol": raw["symbol"], "bid": bid, "ask": ask,
            "observed_at": observed_at, "source": public_text(raw.get("source")),
            "session": session if isinstance(session, str) and session in QUOTE_SESSIONS else "unknown",
        }
        if any(key in raw for key in ("last_price", "last_trade_at", "last_trade", "trade_observed_at")):
            stamp = quote_timestamp(raw.get("last_trade_at", raw.get("trade_observed_at")))
            quote["last_trade_at"] = stamp
            quote["last_price"] = positive_price(raw.get("last_price", raw.get("last_trade"))) if stamp else None
        if any(key in raw for key in ("prior_close", "prior_close_date", "prior_session_close")):
            prior = object_value(raw.get("prior_session_close"))
            day = iso_date(raw.get("prior_close_date", prior.get("date")))
            quote["prior_close_date"] = day
            quote["prior_close"] = positive_price(raw.get("prior_close", prior.get("price"))) if day else None
        symbol = quote["symbol"]
        previous = latest.get(symbol)
        current_time = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        previous_time = datetime.fromisoformat(previous["observed_at"].replace("Z", "+00:00")) if previous else None
        if previous is None or current_time > previous_time:
            latest[symbol] = quote
            conflicts.discard(symbol)
        elif current_time == previous_time and quote != previous:
            conflicts.add(symbol)
    return [latest[symbol] for symbol in sorted(latest) if symbol not in conflicts]


def export_crypto(report: dict) -> dict:
    metadata = object_value(report.get("metadata"))
    gate = object_value(report.get("market_gate"))
    if metadata.get("bar_timezone") != "UTC" or gate.get("benchmark") != "BTC/USD":
        raise ExportError("Crypto research must use validated UTC bars and the BTC/USD benchmark")
    raw_candidates = report.get("candidates", [])
    if not isinstance(raw_candidates, list):
        raise ExportError("Crypto archive candidates must be a list")
    candidates = [
        clean for item in raw_candidates if isinstance(item, dict)
        if (clean := export_candidate(item, {}, crypto=True)) is not None
    ]
    return {
        "signal_session": iso_date(report.get("expected_session")),
        "scan_generated_at": iso_timestamp(report.get("generated_at")),
        "provider": public_text(metadata.get("provider")),
        "feed": public_text(metadata.get("feed")),
        "bar_timezone": "UTC",
        "market_gate": {"passed": boolean(gate.get("passed")), "benchmark": "BTC/USD"},
        "data_blockers": public_lines(report.get("data_blockers")),
        "observations": public_lines(report.get("observations")),
        "lessons": public_lines(report.get("lessons")),
        "sources": export_sources(report.get("sources")),
        "candidates": candidates,
    }


def export_entry(folder: Path) -> dict:
    if not ENTRY_ID.fullmatch(folder.name) or folder.is_symlink():
        raise ExportError("An archive folder has an invalid public entry identifier")
    review = read_object(folder / "review.json")
    scan = read_object(folder / "scan.json")
    crypto_path = folder / "crypto.json"
    crypto = export_crypto(read_object(crypto_path)) if crypto_path.exists() or crypto_path.is_symlink() else None
    if review.get("check_type") not in CHECK_TYPES or review.get("decision") not in DECISIONS:
        raise ExportError("An archive contains an unknown check type or decision")
    if not folder.name.endswith("-" + review["check_type"]):
        raise ExportError("An archive check type does not match its identifier")
    notification = object_value(review.get("notification"))
    if review["check_type"] == "baseline_archive" and (
        review["decision"] == "qualified_opportunity" or notification.get("sent") is True
    ):
        raise ExportError("An archived baseline cannot be a new opportunity alert")
    raw_reviews = review.get("candidate_reviews", [])
    reviews = {
        item["symbol"]: item for item in raw_reviews
        if isinstance(item, dict) and isinstance(item.get("symbol"), str)
    } if isinstance(raw_reviews, list) else {}
    raw_candidates = scan.get("candidates", [])
    if not isinstance(raw_candidates, list):
        raise ExportError("Archive candidates must be a list")
    candidates = [
        clean for item in raw_candidates if isinstance(item, dict)
        if (clean := export_candidate(item, reviews)) is not None
    ]
    raw_gate = object_value(scan.get("market_gate"))
    raw_benchmarks = object_value(raw_gate.get("benchmarks"))
    benchmarks = {}
    for symbol in ("SPY", "QQQ"):
        raw = object_value(raw_benchmarks.get(symbol))
        benchmarks[symbol] = {key: number(raw.get(key)) for key in ("close", "sma50", "sma200")}
        benchmarks[symbol]["last_date"] = iso_date(raw.get("last_date"))
    freshness = public_text(review.get("data_freshness"))
    if review["check_type"] == "baseline_archive":
        freshness = "Archived baseline; this entry is not a new market check. " + freshness
    return {
        "id": folder.name,
        "checked_at": iso_timestamp(review.get("checked_at"), required=True),
        "check_type": review["check_type"],
        "decision": review["decision"],
        "summary": public_text(review.get("summary")),
        "data_freshness": freshness.strip(),
        "signal_session": iso_date(scan.get("expected_session")),
        "scan_generated_at": iso_timestamp(scan.get("generated_at")),
        "market_gate": {"passed": boolean(raw_gate.get("passed")), "benchmarks": benchmarks},
        "data_blockers": public_lines(scan.get("data_blockers")),
        "observations": public_lines(review.get("observations")),
        "lessons": public_lines(review.get("lessons")),
        "sources": export_sources(review.get("sources")),
        "candidates": candidates,
        "current_quotes": export_current_quotes(review.get("current_quotes"), {item["symbol"] for item in candidates} | {"SPY", "QQQ"}),
        "notification": {
            "sent": boolean(notification.get("sent")),
            "reason": public_text(notification.get("reason")),
        },
        "crypto": crypto,
    }


def export_logs(logs: Path) -> dict:
    if not logs.is_dir():
        raise ExportError("The private logs directory does not exist")
    folders = sorted({path.parent for path in logs.glob("*/*/review.json")})
    if not folders:
        raise ExportError("No research archives found; refusing to replace public history")
    entries = [export_entry(folder) for folder in folders]
    entries.sort(key=lambda item: (datetime.fromisoformat(item["checked_at"].replace("Z", "+00:00")), item["id"]), reverse=True)
    latest_folder = next(folder for folder in folders if folder.name == entries[0]["id"])
    latest_rules = object_value(read_object(latest_folder / "scan.json").get("rules"))
    # Rules describe the latest recorded scan, not a copied account/config file.
    # Missing settings remain unknown; historic defaults are never asserted.
    risk_rules = {key: number(latest_rules.get(key)) for key in RISK_RULES}
    payload = {
        "schema_version": 2,
        "updated_at": entries[0]["checked_at"],
        "timezone": "America/Chicago",
        "schedule": ["08:45", "10:45", "12:45", "14:45", "15:45"],
        "risk_rules": risk_rules,
        "entries": entries,
    }
    validate_public_payload(payload)
    return payload


def validate_public_payload(payload: object) -> None:
    """Fail closed on schema drift or private prose in a publication candidate.

    This also accepts JSON loaded from historical commits, so publishers can
    audit pending history independently of the private source archives.
    No rejected value is echoed in the exception.
    """
    try:
        _validate_public_payload(payload)
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        raise ExportError("Public research payload failed its schema or privacy audit") from None


def _validate_public_payload(payload: object) -> None:
    def require(condition: bool) -> None:
        if not condition:
            raise ExportError("Public research payload failed its schema or privacy audit")

    def keys(value: object, expected: tuple | set) -> None:
        require(isinstance(value, dict) and set(value) == set(expected))

    def prose(value: object) -> None:
        require(isinstance(value, str) and public_text(value) == value)

    def lines(value: object) -> None:
        require(isinstance(value, list))
        for item in value:
            prose(item)

    def numeric(value: object) -> None:
        require(value is None or number(value) is not None)

    def boolish(value: object) -> None:
        require(value is None or isinstance(value, bool))

    def day(value: object) -> None:
        require(value is None or iso_date(value) == value)

    def stamp(value: object, required: bool = False) -> None:
        require((value is None and not required) or (isinstance(value, str) and iso_timestamp(value) == value))

    def sources(value: object) -> None:
        require(isinstance(value, list))
        for source in value:
            keys(source, ("title", "url", "as_of"))
            require(isinstance(source["url"], str) and public_url(source["url"]) == source["url"])
            prose(source["title"])
            prose(source["as_of"])

    def current_quotes(value: object, known_symbols: set[str]) -> None:
        require(isinstance(value, list))
        seen = set()
        for quote in value:
            require(isinstance(quote, dict))
            optional = set(quote) & set(CURRENT_QUOTE_OPTIONAL_FIELDS)
            keys(quote, set(CURRENT_QUOTE_FIELDS) | optional)
            require(isinstance(quote["symbol"], str) and quote["symbol"] in known_symbols and quote["symbol"] not in seen)
            seen.add(quote["symbol"])
            stamp(quote["observed_at"], required=True)
            prose(quote["source"])
            require(quote["session"] in QUOTE_SESSIONS)
            for field in ("bid", "ask"):
                require(quote[field] is None or number(quote[field]) is not None and quote[field] > 0)
            require(quote["bid"] is None or quote["ask"] is None or quote["bid"] <= quote["ask"])
            require(("last_price" in optional) == ("last_trade_at" in optional))
            require(("prior_close" in optional) == ("prior_close_date" in optional))
            if "last_price" in optional:
                stamp(quote["last_trade_at"])
                require(quote["last_price"] is None or number(quote["last_price"]) is not None and quote["last_price"] > 0 and quote["last_trade_at"] is not None)
            if "prior_close" in optional:
                day(quote["prior_close_date"])
                require(quote["prior_close"] is None or number(quote["prior_close"]) is not None and quote["prior_close"] > 0 and quote["prior_close_date"] is not None)

    def candidates(value: object, *, crypto: bool = False) -> None:
        require(isinstance(value, list))
        for candidate in value:
            candidate_fields = (
                "symbol", "kind", "sector", "last_date", "technical_match", "setup_types",
                "filters", "metrics", "plan", "blockers", "sizing_status", "review",
            )
            keys(candidate, candidate_fields + (("quote",) if crypto else ()))
            pattern = CRYPTO_SYMBOL if crypto else SYMBOL
            require(isinstance(candidate["symbol"], str) and pattern.fullmatch(candidate["symbol"]) is not None)
            require(candidate["kind"] == "crypto" if crypto else candidate["kind"] in {"stock", "etf", "unknown"})
            require(candidate["sector"] == "crypto" if crypto else candidate["sector"] in SECTORS)
            day(candidate["last_date"])
            boolish(candidate["technical_match"])
            require(isinstance(candidate["setup_types"], list) and all(item in SETUPS for item in candidate["setup_types"]))
            keys(candidate["filters"], CRYPTO_FILTER_FIELDS if crypto else FILTER_FIELDS)
            for item in candidate["filters"].values():
                boolish(item)
            keys(candidate["metrics"], METRIC_FIELDS)
            for item in candidate["metrics"].values():
                numeric(item)
            if candidate["plan"] is not None:
                keys(candidate["plan"], PLAN_FIELDS)
                for item in candidate["plan"].values():
                    numeric(item)
            lines(candidate["blockers"])
            require(candidate["sizing_status"] == "not_evaluated" if crypto else candidate["sizing_status"] in {"does_not_fit", "not_evaluated", "within_limits"})
            if candidate["review"] is not None:
                keys(candidate["review"], REVIEW_FIELDS)
                for item in candidate["review"].values():
                    prose(item)
            if crypto and candidate["quote"] is not None:
                quote = candidate["quote"]
                keys(quote, QUOTE_FIELDS)
                for field in ("bid", "ask", "spread_pct"):
                    numeric(quote[field])
                stamp(quote["observed_at"])
                prose(quote["provider"])
                prose(quote["venue"])

    def crypto_report(value: object) -> None:
        if value is None:
            return
        keys(value, (
            "signal_session", "scan_generated_at", "provider", "feed", "bar_timezone",
            "market_gate", "data_blockers", "observations", "lessons", "sources", "candidates",
        ))
        day(value["signal_session"])
        stamp(value["scan_generated_at"])
        prose(value["provider"])
        prose(value["feed"])
        require(value["bar_timezone"] == "UTC")
        keys(value["market_gate"], ("passed", "benchmark"))
        boolish(value["market_gate"]["passed"])
        require(value["market_gate"]["benchmark"] == "BTC/USD")
        for field in ("data_blockers", "observations", "lessons"):
            lines(value[field])
        sources(value["sources"])
        candidates(value["candidates"], crypto=True)

    keys(payload, ("schema_version", "updated_at", "timezone", "schedule", "risk_rules", "entries"))
    require(type(payload["schema_version"]) is int and payload["schema_version"] in {1, 2})
    require(payload["timezone"] == "America/Chicago")
    require(payload["schedule"] == ["08:45", "10:45", "12:45", "14:45", "15:45"])
    keys(payload["risk_rules"], RISK_RULES)
    for value in payload["risk_rules"].values():
        numeric(value)
    stamp(payload["updated_at"], required=True)
    require(isinstance(payload["entries"], list) and bool(payload["entries"]))
    checked = []
    identifiers = set()
    for entry in payload["entries"]:
        entry_fields = (
            "id", "checked_at", "check_type", "decision", "summary", "data_freshness",
            "signal_session", "scan_generated_at", "market_gate", "data_blockers",
            "observations", "lessons", "sources", "candidates", "notification",
        )
        # Historical v1/v2 payloads predate the optional quote snapshot.
        keys(entry, entry_fields + (("crypto",) if payload["schema_version"] == 2 else ()) + (("current_quotes",) if "current_quotes" in entry else ()))
        if payload["schema_version"] == 2:
            crypto_report(entry["crypto"])
        require(isinstance(entry["id"], str) and ENTRY_ID.fullmatch(entry["id"]) is not None)
        require(entry["id"] not in identifiers)
        identifiers.add(entry["id"])
        require(entry["check_type"] in CHECK_TYPES and entry["id"].endswith("-" + entry["check_type"]))
        require(entry["decision"] in DECISIONS)
        stamp(entry["checked_at"], required=True)
        checked.append(datetime.fromisoformat(entry["checked_at"].replace("Z", "+00:00")))
        stamp(entry["scan_generated_at"])
        day(entry["signal_session"])
        prose(entry["summary"])
        prose(entry["data_freshness"])
        for field in ("data_blockers", "observations", "lessons"):
            lines(entry[field])
        gate = entry["market_gate"]
        keys(gate, ("passed", "benchmarks"))
        boolish(gate["passed"])
        keys(gate["benchmarks"], ("SPY", "QQQ"))
        for benchmark in gate["benchmarks"].values():
            keys(benchmark, ("close", "sma50", "sma200", "last_date"))
            day(benchmark["last_date"])
            for field in ("close", "sma50", "sma200"):
                numeric(benchmark[field])
        sources(entry["sources"])
        candidates(entry["candidates"])
        if "current_quotes" in entry:
            current_quotes(entry["current_quotes"], {item["symbol"] for item in entry["candidates"]} | {"SPY", "QQQ"})
        keys(entry["notification"], ("sent", "reason"))
        boolish(entry["notification"]["sent"])
        prose(entry["notification"]["reason"])
        if entry["check_type"] == "baseline_archive":
            require(entry["decision"] != "qualified_opportunity" and entry["notification"]["sent"] is not True)
            require(entry["data_freshness"].startswith("Archived baseline; this entry is not a new market check."))
    require(checked == sorted(checked, reverse=True))
    require(payload["updated_at"] == payload["entries"][0]["checked_at"])


def atomic_write(output: Path, data: dict) -> bool:
    payload = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if output.is_file() and output.read_bytes() == payload:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".research-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", type=Path, required=True, help="Private archive directory (read only)")
    parser.add_argument("--output", type=Path, required=True, help="Public research.json destination")
    arguments = parser.parse_args(argv)
    try:
        data = export_logs(arguments.logs)
        changed = atomic_write(arguments.output, data)
    except (ExportError, OSError, TypeError, OverflowError) as exc:
        # Do not echo source contents, paths or values into publish logs.
        message = str(exc) if isinstance(exc, ExportError) else "Unable to read or atomically write research data"
        print("Export failed: " + message, file=sys.stderr)
        return 1
    print(f"Public research export {'updated' if changed else 'unchanged'}: {len(data['entries'])} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
