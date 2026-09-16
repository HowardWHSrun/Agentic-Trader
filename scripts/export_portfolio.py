#!/usr/bin/env python3
"""Build the separately authorized PUBLIC portfolio snapshot from sanitized input.

CLI: --input source.json --output portfolio.json. No account/network access.
All decimal amounts, quantities and percentages are lossless decimal strings or
null; percentages alone are rounded to six decimal places. Prices are dated, not
live. Freshness is measured against source.observed_at (300 seconds), preserving
historical snapshots. Account totals include assets outside the scoped equity
positions and are never added to tracked market values. This exporter is separate
from the research export's stricter no-personal-financial-data boundary.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path

MAX_INPUT_BYTES = 20 * 1024 * 1024
FRESH_SECONDS = 300
ACCOUNT_LABELS = {"agentic": "Agentic", "individual": "Individual"}
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
DECIMAL_TEXT = re.compile(r"^-?\d+(?:\.\d+)?$")
SESSIONS = {"regular", "pre_market", "after_hours", "overnight", "closed", "unknown"}
SOURCES = {"Robinhood", "Robinhood get_equity_quotes", "Alpaca", "Alpaca SIP"}
PRICE_BASES = {"last_trade", "bid_ask_midpoint", "last_trade_stale", "bid_ask_midpoint_stale"}
ACCOUNT_MONEY = ("total_value", "cash", "unleveraged_buying_power", "equity_value", "crypto_value")
TRACKED_MONEY = ("tracked_cost_basis", "tracked_market_value", "tracked_unrealized_pl")
SCOPE_NOTE = (
    "Public financial snapshot authorized by the owner. Agentic includes all scoped equity positions; "
    "Individual includes AAPL, TSLA and GOOGL only. Broker account totals include other assets, including "
    "crypto, whose individual holdings are not displayed. Tracked stock values are part of account totals, "
    "not additional money. Cash and buying power overlap. Combined totals are for display, not trade sizing. "
    "Average cost is broker-reported average purchase cost, not a verified tax basis. Unrealized P&L excludes "
    "realized gains, dividends, fees and taxes. Prices and balances retain separate observation times. "
    "Fresh means within 300 seconds of this snapshot, not necessarily fresh when this page is viewed."
)
ACCOUNT_FIELDS = {"account_key", "account_label", "observed_at", "positions_complete_for_scope", *ACCOUNT_MONEY}
HOLDING_FIELDS = {
    "symbol", "account_key", "account_label", "asset_type", "quantity", "average_cost",
    "price", "price_basis", "price_at", "quote_at", "session", "source", "price_is_fresh",
    "price_age_seconds", "market_value", "cost_basis", "unrealized_pl", "unrealized_pl_pct",
    "account_weight_pct", "portfolio_weight_pct",
}
COMPLETENESS_FIELDS = {"account_totals", "tracked_scope", "tracked_cost_basis", "tracked_market_value", "tracked_unrealized_pl"}
TOTAL_FIELDS = {
    "account_value", "cash", "unleveraged_buying_power", "equity_value", "crypto_value",
    *TRACKED_MONEY, "tracked_unrealized_pl_pct", "tracked_cost_basis_known",
    "tracked_market_value_known", "tracked_unrealized_pl_known", "completeness", "has_stale_prices",
}


class ExportError(ValueError):
    """Invalid input/public payload; errors never echo private source contents."""


def decimal_value(value, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        text = str(value)
        if len(text) > 128:
            return None
        number = Decimal(text)
        if not number.is_finite() or abs(number.adjusted()) > 40:
            return None
        if positive and number <= 0 or nonnegative and number < 0:
            return None
        return number
    except (InvalidOperation, ValueError):
        return None


def decimal_text(value):
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def percentage(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return (numerator / denominator * 100).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        return None
    try:
        if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            return None
        text = re.sub(r"\.(\d+)(?=Z|[+-]\d{2}:\d{2}$)", lambda m: "." + m.group(1)[:6].ljust(6, "0"), value)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def select_price(raw, observed_at):
    """Prefer a fresh trade, then a fresh midpoint; explicitly label older data."""
    raw = raw if isinstance(raw, dict) else {}
    quote_at, trade_at = timestamp(raw.get("observed_at")), timestamp(raw.get("last_trade_at"))
    last = decimal_value(raw.get("last_price"), positive=True)
    bid, ask = (decimal_value(raw.get(k), positive=True) for k in ("bid", "ask"))
    midpoint = (bid + ask) / 2 if bid is not None and ask is not None and bid <= ask else None
    candidates = []
    for price, stamp, basis in ((last, trade_at, "last_trade"), (midpoint, quote_at, "bid_ask_midpoint")):
        if price is None or stamp is None:
            continue
        age = (instant(observed_at) - instant(stamp)).total_seconds()
        if age < -5:  # Do not turn a future-dated observation into current evidence.
            continue
        candidates.append({"price": price, "price_at": stamp, "price_basis": basis,
                           "price_age_seconds": max(0, math.ceil(age)), "price_is_fresh": age <= FRESH_SECONDS})
    fresh = [row for row in candidates if row["price_is_fresh"]]
    selected = fresh[0] if fresh else max(candidates, key=lambda row: instant(row["price_at"])) if candidates else None
    if selected and not selected["price_is_fresh"]:
        selected["price_basis"] += "_stale"
    if selected is None:
        selected = {"price": None, "price_at": None, "price_basis": None,
                    "price_age_seconds": None, "price_is_fresh": False}
    return {**selected, "quote_at": quote_at,
            "source": raw.get("source") if isinstance(raw.get("source"), str) and raw["source"] in SOURCES else "Unknown source",
            "session": raw.get("session") if isinstance(raw.get("session"), str) and raw["session"] in SESSIONS else "unknown"}


def complete_sum(values, *, complete=True):
    known = sum((value for value in values if value is not None), Decimal(0))
    return (known if complete and all(value is not None for value in values) else None), known


def build_portfolio(source):
    with localcontext() as context:
        context.prec = 50
        return _build_portfolio(source)


def _build_portfolio(source):
    if not isinstance(source, dict) or source.get("currency") != "USD":
        raise ExportError("Portfolio source must be a USD object")
    observed_at = timestamp(source.get("observed_at"))
    if observed_at is None or not isinstance(source.get("accounts"), list) or not source["accounts"]:
        raise ExportError("Portfolio source requires dated account snapshots")
    quotes = {}
    for raw in source.get("quotes", []) if isinstance(source.get("quotes", []), list) else []:
        if not isinstance(raw, dict) or not isinstance(raw.get("symbol"), str) or not SYMBOL.fullmatch(raw["symbol"]):
            continue
        if raw["symbol"] in quotes:
            raise ExportError("Duplicate quote symbols require source reconciliation")
        quotes[raw["symbol"]] = raw
    accounts, holdings, seen_accounts, seen_positions = [], [], set(), set()
    for raw in source["accounts"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("account_key"), str) or raw["account_key"] not in ACCOUNT_LABELS:
            raise ExportError("Portfolio source contains an unknown account scope")
        key = raw["account_key"]
        if key in seen_accounts or not isinstance(raw.get("positions"), list):
            raise ExportError("Duplicate account or missing scoped position list")
        seen_accounts.add(key)
        stamp = timestamp(raw.get("observed_at", observed_at))
        if stamp is None:
            raise ExportError("An account snapshot has an invalid timestamp")
        portfolio = raw.get("portfolio") if isinstance(raw.get("portfolio"), dict) else {}
        buying_power = portfolio.get("buying_power") if isinstance(portfolio.get("buying_power"), dict) else {}
        account = {"account_key": key, "account_label": ACCOUNT_LABELS[key], "observed_at": stamp,
                   "positions_complete_for_scope": raw.get("positions_complete_for_scope") is True}
        for field in ACCOUNT_MONEY:
            account[field] = decimal_value(buying_power.get(field) if field == "unleveraged_buying_power" else portfolio.get(field))
        accounts.append(account)
        for position in raw["positions"]:
            if not isinstance(position, dict) or not isinstance(position.get("symbol"), str) or not SYMBOL.fullmatch(position["symbol"]):
                raise ExportError("A scoped position has an invalid market symbol")
            symbol = position["symbol"]
            if key == "individual" and symbol not in {"AAPL", "TSLA", "GOOGL"}:
                raise ExportError("An individual-account position is outside the authorized scope")
            identity = (key, symbol)
            if identity in seen_positions:
                raise ExportError("Duplicate scoped positions require source reconciliation")
            seen_positions.add(identity)
            quantity = decimal_value(position.get("quantity"), nonnegative=True)
            if quantity == 0:
                continue
            average = decimal_value(position.get("average_buy_price"), nonnegative=True)
            mark = select_price(quotes.get(symbol), observed_at)
            market = quantity * mark["price"] if quantity is not None and mark["price"] is not None else None
            cost = quantity * average if quantity is not None and average is not None else None
            pnl = market - cost if market is not None and cost is not None else None
            holdings.append({"symbol": symbol, "account_key": key, "account_label": ACCOUNT_LABELS[key], "asset_type": "equity",
                             "quantity": quantity, "average_cost": average, **mark,
                             "market_value": market, "cost_basis": cost, "unrealized_pl": pnl,
                             "unrealized_pl_pct": percentage(pnl, cost),
                             "account_weight_pct": percentage(market, account["total_value"])})
    totals = {}
    for field in ACCOUNT_MONEY:
        target = "account_value" if field == "total_value" else field
        totals[target] = complete_sum([row[field] for row in accounts])[0]
    scope_complete = all(row["positions_complete_for_scope"] for row in accounts)
    completeness = {"account_totals": all(totals[key] is not None for key in totals), "tracked_scope": scope_complete}
    for field, holding_field in zip(TRACKED_MONEY, ("cost_basis", "market_value", "unrealized_pl")):
        totals[field], totals[field + "_known"] = complete_sum([row[holding_field] for row in holdings], complete=scope_complete)
        completeness[field] = totals[field] is not None
    totals["tracked_unrealized_pl_pct"] = percentage(totals["tracked_unrealized_pl"], totals["tracked_cost_basis"])
    totals["completeness"] = completeness
    totals["has_stale_prices"] = any(row["price"] is not None and not row["price_is_fresh"] for row in holdings)
    for row in holdings:
        row["portfolio_weight_pct"] = percentage(row["market_value"], totals["account_value"])
    def encode(value):
        if isinstance(value, Decimal):
            return decimal_text(value)
        if isinstance(value, dict):
            return {key: encode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [encode(item) for item in value]
        return value
    payload = encode({"schema_version": 1, "updated_at": observed_at, "scope_note": SCOPE_NOTE,
                      "accounts": accounts, "holdings": sorted(holdings, key=lambda row: (row["account_key"], row["symbol"])), "totals": totals})
    validate_public_payload(payload)
    return payload


def validate_public_payload(payload):
    """Strict allowlist for current and historical authorized public portfolios."""
    def require(condition):
        if not condition:
            raise ExportError("Public portfolio failed its schema or privacy audit")
    def keys(value, expected):
        require(isinstance(value, dict) and set(value) == set(expected))
    def stamp(value, optional=False):
        require(value is None and optional or isinstance(value, str) and timestamp(value) == value)
    def money(value, nonnegative=False, positive=False):
        require(value is None or isinstance(value, str) and DECIMAL_TEXT.fullmatch(value) is not None
                and decimal_value(value, nonnegative=nonnegative, positive=positive) is not None)
    try:
        keys(payload, {"schema_version", "updated_at", "scope_note", "accounts", "holdings", "totals"})
        require(type(payload["schema_version"]) is int and payload["schema_version"] == 1)
        require(payload["scope_note"] == SCOPE_NOTE)
        stamp(payload["updated_at"])
        require(isinstance(payload["accounts"], list) and bool(payload["accounts"]))
        account_keys = set()
        for row in payload["accounts"]:
            keys(row, ACCOUNT_FIELDS)
            require(row["account_key"] in ACCOUNT_LABELS and row["account_key"] not in account_keys)
            account_keys.add(row["account_key"])
            require(row["account_label"] == ACCOUNT_LABELS[row["account_key"]])
            stamp(row["observed_at"])
            require(type(row["positions_complete_for_scope"]) is bool)
            for field in ACCOUNT_MONEY:
                money(row[field])
        require(isinstance(payload["holdings"], list))
        seen = set()
        for row in payload["holdings"]:
            keys(row, HOLDING_FIELDS)
            require(isinstance(row["symbol"], str) and SYMBOL.fullmatch(row["symbol"]) is not None)
            require(row["account_key"] in account_keys and row["account_label"] == ACCOUNT_LABELS[row["account_key"]])
            require(row["account_key"] != "individual" or row["symbol"] in {"AAPL", "TSLA", "GOOGL"})
            identity = (row["account_key"], row["symbol"])
            require(identity not in seen)
            seen.add(identity)
            require(row["asset_type"] == "equity" and row["session"] in SESSIONS)
            require(row["source"] in SOURCES | {"Unknown source"})
            require(type(row["price_is_fresh"]) is bool)
            require(row["price_age_seconds"] is None or type(row["price_age_seconds"]) is int and row["price_age_seconds"] >= 0)
            stamp(row["price_at"], True)
            stamp(row["quote_at"], True)
            require(row["price_basis"] is None or row["price_basis"] in PRICE_BASES)
            for field in ("quantity", "price"):
                money(row[field], positive=True)
            for field in ("average_cost", "market_value", "cost_basis"):
                money(row[field], nonnegative=True)
            for field in ("unrealized_pl", "unrealized_pl_pct", "account_weight_pct", "portfolio_weight_pct"):
                money(row[field])
            if row["price"] is None:
                require(row["price_basis"] is None and row["price_at"] is None and not row["price_is_fresh"] and row["price_age_seconds"] is None)
            else:
                require(row["price_at"] is not None and row["price_basis"] in PRICE_BASES and row["price_age_seconds"] is not None)
                require(row["price_is_fresh"] == (not row["price_basis"].endswith("_stale")))
                require(row["price_is_fresh"] == (row["price_age_seconds"] <= FRESH_SECONDS))
        keys(payload["totals"], TOTAL_FIELDS)
        keys(payload["totals"]["completeness"], COMPLETENESS_FIELDS)
        require(all(type(value) is bool for value in payload["totals"]["completeness"].values()))
        require(type(payload["totals"]["has_stale_prices"]) is bool)
        for field in TOTAL_FIELDS - {"completeness", "has_stale_prices"}:
            money(payload["totals"][field])
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        if isinstance(exc, ExportError):
            raise
        raise ExportError("Public portfolio failed its schema or privacy audit") from None


def load_source(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ExportError("Portfolio input is missing, linked or too large")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ExportError("Portfolio input is not valid JSON") from None


def atomic_write(path, payload):
    validate_public_payload(payload)
    path = Path(path)
    content = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if path.is_file() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".portfolio-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        payload = build_portfolio(load_source(args.input))
        changed = atomic_write(args.output, payload)
    except (ExportError, OSError, InvalidOperation):
        print("Portfolio export failed; prior public output preserved.", file=sys.stderr)
        return 1
    print("Public portfolio export " + ("updated" if changed else "unchanged") + ": " + str(len(payload["holdings"])) + " scoped positions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
