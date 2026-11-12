#!/usr/bin/env python3
"""Daily options scorecard for the fixed 32-stock universe.

Scores each stock 0-100 (50 = neutral, high = bullish -> calls, low = bearish
-> puts), picks a liquid long call/put and a debit spread for the strongest
names, and tracks previously published signals so it can say when to exit.

Rules: buy-to-open only (long calls/puts or debit spreads). Maximum loss is the
premium paid. No naked option selling, margin, or borrowed money.

Data: Cboe's free delayed quotes (no account or API key): daily history plus
full option chains with Greeks, implied volatility and open interest. Quotes
are about 15 minutes delayed; verify the live bid/ask at your broker.

Usage:
  python3 scripts/options_scorer.py run [--earnings earnings.json] [--dry-run]
  python3 scripts/options_scorer.py check   # verify API access only
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import options_ml  # noqa: E402  (ML sizing overlay, v2.6)
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "data" / "options"
CT = ZoneInfo("America/Chicago")
RULES_VERSION = "options-score-v2.6"

UNIVERSE = [
    "AAPL", "AVGO", "CRM", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "HD", "COST",
    "KO", "PG", "WMT", "ABBV", "LLY", "UNH", "BAC", "JPM", "V", "CVX", "XOM",
    "CAT", "DE", "GE", "RTX", "DUK", "NEE", "FCX", "LIN", "PLD", "TSLA", "SPCX",
]
SECTOR = {
    "AAPL": "XLK", "AVGO": "XLK", "CRM": "XLK", "MSFT": "XLK", "NVDA": "XLK",
    "GOOGL": "XLC", "META": "XLC", "AMZN": "XLY", "HD": "XLY", "TSLA": "XLY",
    "COST": "XLP", "KO": "XLP", "PG": "XLP", "WMT": "XLP",
    "ABBV": "XLV", "LLY": "XLV", "UNH": "XLV",
    "BAC": "XLF", "JPM": "XLF", "V": "XLF",
    "CVX": "XLE", "XOM": "XLE",
    "CAT": "XLI", "DE": "XLI", "GE": "XLI", "RTX": "XLI",
    "DUK": "XLU", "NEE": "XLU", "FCX": "XLB", "LIN": "XLB", "PLD": "XLRE",
    "SPCX": None,
}
BENCHMARKS = ["SPY"] + sorted({s for s in SECTOR.values() if s})

# Signal thresholds
CALL_ENTRY = 70
PUT_ENTRY = 30
MAX_NEW_PER_SIDE = 3
MAX_OPEN = 10  # tracked paper signals; the user's real positions are capped at 5 separately
# Contract selection
# v2.4: 2-3 week expiry, in-the-money (delta ~0.75). Same leverage as a 30-day ATM call but only about a quarter
# of the premium is time value, so an IV drop after entry hurts far less (backtest: stress+crush -12% -> about -1%).
DTE_MIN, DTE_MAX = 14, 30
TARGET_DTE = 17
LONG_DELTA = (0.65, 0.85)
TARGET_DELTA = 0.75
FALLBACK_DELTA = 0.65  # if delta 0.75 is over the per-contract cap; never go lower (ATM/OTM)
SHORT_DELTA = (0.20, 0.35)
MAX_SPREAD_PCT = 0.10
# Exit rules (premium-based, on the long single-leg idea)
TAKE_PROFIT = 0.80   # +80% of entry mid
TAKE_PROFIT_SPREAD = 0.60  # +60% of debit (spread gain is capped)
MAX_COST_DEFAULT = 1000.0  # USD per contract (100 shares)
SINGLE_LEG_ONLY = True     # Robinhood options level 2: no spreads
STOP_LOSS = -0.50    # -50% of entry mid (tight stops cut rebounds short in the backtest)
MAX_HOLD_DAYS = 7     # calendar days; the user holds each option 1-7 days
TIME_EXIT_DTE = 10
DIP_TIME_EXIT_DTE = 1   # dip trades: sell by the last trading day before expiry
DIP_MAX_SESSIONS = 5    # dip trades: sell at the close of session 5 if nothing else fired
DISASTER_ATR = 2.0      # dip trades: close below signal-day low - 2 ATR -> sell all (rare brake)
RUNNER_ATR = 1.5        # on the rebound exit, if close >= entry + 1.5 ATR, 2+ contracts may keep half
EARNINGS_EXIT_DAYS = 2
# v2 entry: a sharp short-term dip inside a long-term uptrend (calls only).
DOWN_STREAK_ENTRY = 4   # consecutive lower closes that trigger a call signal
# Skip quiet stocks: their rebounds are too small to pay for an option (backtest: HV20<20% +2.9%/+4.8% per
# trade in 2021-24/2025-26 vs +11.1%/+10.0% for HV20>=20%; threshold set on 2021-24 only).
MIN_HV20 = 20.0
ENTRY_WINDOW_CT = ("14:30", "15:05")  # signals and rebound exits are judged near the close, as in the backtest
COOLDOWN_DAYS = 3  # no re-entry on the same stock right after an exit
MAX_NEW_PER_DAY = 2  # cap new signals per day (all sides)
MAX_PER_SECTOR = 2   # open signals in one sector (they move together)
# Position size as a share of the options budget, set by market context (backtested 2021-2026):
# dips during a broad pullback rebounded far better than a single stock falling on its own.
# 2026-11-12 the user chose 20% of the options budget per trade (bootstrapped years, 40 trades: median end
# about 1.7x, 10th percentile about 0.7x, 4% chance of losing half; 100% per trade ends near zero 69% of the time).
RISK_FULL = 0.20     # standard trade
RISK_HALF = 0.10     # weaker setups: lone faller in a pullback, or a lone faller in a calm market without sector data
RISK_STAR = 0.30     # best setup, flagged to the user: market pullback AND the stock fell with its sector
# v2.5 news proxy: compare the stock's fall over the down streak with its sector ETF over the same days.
# Backtest (v2.4 contract, per trade, 2021-24 / 2025-26): fell with its sector +19.8% / +17.0%;
# calm market and >=2% worse than its sector -3.1% / -1.9% (likely company news) -> skip;
# market pullback and >5% worse than its sector +8.4% / +8.1% -> half size.
SECTOR_LAG_SKIP = -2.0   # % vs sector, calm market
SECTOR_LAG_HALF = -5.0   # % vs sector, market pullback
DRAWDOWN_HALVE = 0.10  # account more than 10% below its peak -> halve every size
DRAWDOWN_PAUSE = 0.20  # more than 20% below its peak -> no new entries until reviewed
MAX_STRETCH_ATR = 2.0  # don't chase: skip entries this many ATRs past the 20-day average
EARNINGS_BLOCK_DAYS = 14  # no new entry if earnings are this close (hold would be too short)

RISK_RULES = [
    "只买看涨期权（Call），最大亏损 = 付出的权利金；不买看跌、不裸卖期权、不用保证金、不借钱。进场条件：长期趋势向上（股价和 50 日均线都在 200 日均线上方）且已连续 4 个交易日收盘下跌，在收盘前半小时确认后买入。",
    "仓位随行情、板块和账户变：每笔用期权资金的 20%；大盘回调且它跟板块一起跌是特别好的机会（⭐），可加到 30%；大盘回调但它比板块多跌 5% 以上时 10%；大盘平稳而它比板块多跌 2% 以上（多半是公司利空）不做；信号出现时再查新闻，有公司自身的基本面利空就不做；账户比最高点低 10% 时全部减半，低 20% 时暂停新开仓。同时最多 5 笔、同板块最多 2 笔、每天最多 2 个新信号，每张不超过 $1000。只用亏光也不影响生活的钱。",
    "合约：2–3 周后到期（14–30 天，优先第 17 天左右的周五）、Delta 约 0.75 的价内 Call；超过每张上限就降到 Delta 0.65，再贵就不做，绝不改买平值或价外。退场（收盘前半小时按收盘价判断）：收盘站上 5 日均线就卖；大反弹（股价 ≥ 入场价 + 1.5 倍 ATR）时有 2 张以上可留一半；收盘跌破“信号日低点 − 2 倍 ATR”全部卖；满 5 个交易日没反弹全部卖；到期前一天、财报前 2 天必须卖。不设期权涨跌百分比止损止盈，风控靠仓位：每笔只用期权资金的 20%（特别好的机会最多 30%），绝不满仓。",
    "趋势评分只是背景参考：5 年回测显示它对之后几天的涨跌没有预测力。回测里这套「连跌 4 天」规则每笔平均约 +8.5%、胜率约 61%（估算的期权价格，且是从十几条规则里挑出来的，实际会打折扣），不保证盈利。下单前请在券商核对实时买卖价，用限价单。",
]

OCC_RE = re.compile(r"^([A-Z.]+)(\d{6})([CP])(\d{8})$")


# ---------------------------------------------------------------- data access
ET = ZoneInfo("America/New_York")
ETF_SYMBOLS = {"SPY", "XLK", "XLC", "XLY", "XLP", "XLV", "XLF", "XLE", "XLI", "XLU", "XLB", "XLRE"}


def regular_session_open(now: datetime | None = None) -> bool:
    now = (now or datetime.now(ET)).astimezone(ET)
    return now.weekday() < 5 and "09:30" <= now.strftime("%H:%M") < "16:00"


class NasdaqClient:
    """Nasdaq.com quote API: real-time last sale for stocks; option chain bid/ask."""
    BASE = "https://api.nasdaq.com/api/quote"
    UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(f"{self.BASE}/{path}", headers={"User-Agent": self.UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp).get("data") or {}

    @staticmethod
    def _num(x) -> float | None:
        try:
            return float(str(x).replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            return None

    def last_sale(self, symbol: str) -> tuple[float, str] | None:
        """(price, 'YYYY-MM-DD') of today's real-time last sale, or None."""
        asset = "etf" if symbol in ETF_SYMBOLS else "stocks"
        try:
            p = self._get(f"{symbol}/info?assetclass={asset}").get("primaryData") or {}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None
        price = self._num(p.get("lastSalePrice"))
        ts = (p.get("lastTradeTimestamp") or "").replace(" ET", "")
        try:
            day = datetime.strptime(ts, "%b %d, %Y %I:%M %p").date().isoformat()
        except ValueError:
            return None
        return (price, day) if price else None

    def option_quote(self, contract: str) -> dict | None:
        """{'bid','ask','last'} for an OCC contract symbol, or None."""
        meta = parse_occ(contract)
        if not meta:
            return None
        exp = meta["expiration"].isoformat()
        asset = "etf" if meta["root"] in ETF_SYMBOLS else "stocks"
        try:
            data = self._get(f"{meta['root']}/option-chain?assetclass={asset}&limit=1000&fromdate={exp}"
                             f"&todate={exp}&excode=oprac&callput={meta['type']}&money=all&type=all")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None
        side = "c_" if meta["type"] == "call" else "p_"
        for row in (data.get("table") or {}).get("rows") or []:
            if self._num(row.get("strike")) == meta["strike"]:
                bid, ask = self._num(row.get(side + "Bid")), self._num(row.get(side + "Ask"))
                if bid and ask:
                    return {"bid": bid, "ask": ask, "last": self._num(row.get(side + "Last"))}
        return None


class CboeClient:
    BASE = "https://cdn-api.cboe.com/api/global/delayed_quotes"
    UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

    def __init__(self, live: NasdaqClient | None = None):
        self._chains: dict[str, dict] = {}
        self.live = live

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(f"{self.BASE}/{path}", headers={"User-Agent": self.UA, "Accept": "application/json"})
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.load(resp)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Cboe {path}: {last}")

    def chain(self, symbol: str) -> dict:
        """{"quote": {...underlying...}, "options": [...], "timestamp": str}"""
        if symbol not in self._chains:
            raw = self._get(f"options/{symbol}.json")
            data = raw.get("data") or {}
            self._chains[symbol] = {"quote": {k: v for k, v in data.items() if k != "options"},
                                    "options": data.get("options") or [],
                                    "timestamp": raw.get("timestamp")}
        return self._chains[symbol]

    def daily_bars(self, symbol: str) -> list[dict]:
        rows = self._get(f"charts/historical/{symbol}.json").get("data") or []
        bars = [{"t": r["date"], "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r["volume"]}
                for r in rows if r.get("close")]
        # The history file lags; append the latest session from the quote feed.
        try:
            q = self.chain(symbol)["quote"]
        except RuntimeError:
            return bars
        day = (q.get("last_trade_time") or "")[:10]
        # Live (delayed) price only during today's regular session; otherwise the
        # official close (pre-market / after-hours prices must not overwrite it).
        ltt = q.get("last_trade_time") or ""
        today_et = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        in_session = day == today_et and "09:30:00" <= ltt[11:19] < "16:00:00"
        price = (q.get("current_price") if in_session else None) or q.get("close")
        if day and price and q.get("high"):
            bar = {"t": day, "o": q.get("open") or price, "h": max(q["high"], price),
                   "l": min(q.get("low") or price, price), "c": price, "v": q.get("volume", 0)}
            if not bars or day > bars[-1]["t"]:
                bars.append(bar)
            elif day == bars[-1]["t"]:
                bars[-1] = bar
        # Real-time last sale (Nasdaq) replaces Cboe's delayed price during the session.
        if self.live and regular_session_open():
            sale = self.live.last_sale(symbol)
            today = datetime.now(ET).date().isoformat()
            if sale and sale[1] == today:
                px = sale[0]
                if bars and bars[-1]["t"] == today:
                    b = bars[-1]
                    bars[-1] = {**b, "c": px, "h": max(b["h"], px), "l": min(b["l"], px)}
                else:
                    bars.append({"t": today, "o": px, "h": px, "l": px, "c": px, "v": 0})
        return bars


# ---------------------------------------------------------------- indicators
def sma(values: list[float], n: int, offset: int = 0) -> float | None:
    end = len(values) - offset
    if end < n:
        return None
    return sum(values[end - n:end]) / n


def ema_series(values: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) <= n:
        return None
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def atr(bars: list[dict], n: int = 14) -> float | None:
    if len(bars) <= n:
        return None
    trs = [max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"]))
           for p, b in zip(bars, bars[1:])]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def ret(closes: list[float], n: int) -> float | None:
    if len(closes) <= n or closes[-1 - n] == 0:
        return None
    return closes[-1] / closes[-1 - n] - 1


def ret_on_dates(bars: list[dict], start: str, end: str) -> float | None:
    """Benchmark return over exactly the same dates as the stock."""
    closes = {b["t"][:10]: b["c"] for b in bars}
    if start not in closes or end not in closes or not closes[start]:
        return None
    return closes[end] / closes[start] - 1


def hist_vol(closes: list[float], n: int = 20) -> float | None:
    if len(closes) <= n:
        return None
    rs = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - n, len(closes))]
    mean = sum(rs) / n
    return math.sqrt(sum((r - mean) ** 2 for r in rs) / (n - 1) * 252)


# ---------------------------------------------------------------- scoring
def down_streak(closes: list[float], cap: int = 10) -> int:
    """Number of consecutive lower closes ending at the latest bar."""
    n = 0
    while n < cap and len(closes) > n + 1 and closes[-1 - n] < closes[-2 - n]:
        n += 1
    return n


def streak_vs(closes: list[float], dates: list[str], sector: list[dict] | None) -> float | None:
    """Stock return over its current down streak minus the sector ETF's return over the same dates."""
    n = down_streak(closes)
    if not n or not sector:
        return None
    sec = ret_on_dates(sector, dates[-1 - n], dates[-1])
    return None if sec is None else (closes[-1] / closes[-1 - n] - 1) - sec


def score_symbol(bars: list[dict], spy: list[dict], sector: list[dict] | None) -> dict:
    """Return a direction score 0-100 (50 neutral) and its transparent parts.

    Bull and bear checks mirror each other (each worth 0-100); the final score
    is 50 + (bull - bear) / 2.
    """
    closes = [b["c"] for b in bars]
    if len(closes) < 60:
        return {"score": None, "missing": f"需要至少 60 个交易日数据，只有 {len(closes)} 个"}
    px = closes[-1]
    s20, s50, s200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)  # s200 None if <200 bars
    s20_prev = sma(closes, 20, offset=5)
    r14 = rsi(closes)
    a14 = atr(bars)
    macd_line = [f - s for f, s in zip(ema_series(closes, 12), ema_series(closes, 26))]
    signal = ema_series(macd_line, 9)
    hist_now, hist_prev = macd_line[-1] - signal[-1], macd_line[-2] - signal[-2]
    r20 = ret(closes, 20)
    dates = [b["t"][:10] for b in bars]
    spy20 = ret_on_dates(spy, dates[-21], dates[-1]) if spy else None
    sec20 = ret_on_dates(sector, dates[-21], dates[-1]) if sector else None
    rel_spy = (r20 - spy20) if r20 is not None and spy20 is not None else None
    rel_sec = (r20 - sec20) if r20 is not None and sec20 is not None else None
    stretch = (px - s20) / a14 if a14 else 0.0

    def rel_points(rel: float | None, full: float, cap: float) -> tuple[float, float]:
        if rel is None:
            return 0.0, 0.0
        pts = min(abs(rel) / cap, 1.0) * full
        return (pts, 0.0) if rel > 0 else (0.0, pts)

    checks = []  # (name, bull_points, bear_points, max)
    checks.append(("价格 vs 20日均线", 10 * (px > s20), 10 * (px < s20), 10))
    checks.append(("20日 vs 50日均线", 10 * (s20 > s50), 10 * (s20 < s50), 10))
    if s200 is not None:  # newly listed stocks (e.g. SPCX) simply lack this check
        checks.append(("50日 vs 200日均线", 10 * (s50 > s200), 10 * (s50 < s200), 10))
    checks.append(("20日均线方向", 10 * (s20 > s20_prev), 10 * (s20 < s20_prev), 10))
    b, r = rel_points(rel_spy, 15, 0.06)
    checks.append(("20日相对 SPY", b, r, 15))
    b, r = rel_points(rel_sec, 10, 0.05)
    checks.append(("20日相对行业ETF", b, r, 10))
    # RSI: momentum zone earns points; overextended zones earn less.
    if r14 >= 80:
        rb, rr = 4, 0
    elif r14 >= 55:
        rb, rr = 10, 0
    elif r14 > 45:
        rb, rr = 0, 0
    elif r14 > 20:
        rb, rr = 0, 10
    else:
        rb, rr = 0, 4
    checks.append(("RSI14 动能", rb, rr, 10))
    mb = 10 * (hist_now > 0) * (1 if hist_now >= hist_prev else 0.5)
    mr = 10 * (hist_now < 0) * (1 if hist_now <= hist_prev else 0.5)
    checks.append(("MACD 柱", mb, mr, 10))
    # Not chasing: within 1 ATR of SMA20 on the trend side is the best entry.
    ext = abs(stretch)
    ext_pts = 15 if ext <= 1 else 8 if ext <= 2 else 0
    checks.append(("离20日均线不过远", ext_pts * (stretch >= 0), ext_pts * (stretch < 0), 15))

    total = sum(c[3] for c in checks)
    bull = sum(c[1] for c in checks) * 100 / total
    bear = sum(c[2] for c in checks) * 100 / total
    score = round(50 + (bull - bear) / 2)
    return {
        "score": max(0, min(100, score)),
        "bull": round(bull, 1), "bear": round(bear, 1),
        "checks": [{"name": n, "bull": round(bp, 1), "bear": round(rp, 1), "max": m}
                   for n, bp, rp, m in checks],
        "price": round(px, 2), "sma20": round(s20, 2), "sma50": round(s50, 2),
        "sma200": round(s200, 2) if s200 else None, "rsi14": round(r14, 1), "atr14": round(a14, 2),
        "stretch_atr": round(stretch, 2),
        "ret20": _pct(r20), "rel_spy20": _pct(rel_spy), "rel_sector20": _pct(rel_sec),
        "hv20": _pct(hist_vol(closes)),
        "rsi2": round(rsi(closes[-40:], 2), 1),
        "down_streak": down_streak(closes),
        "above_sma5": px > sma(closes, 5),
        "low": round(bars[-1]["l"], 2),
        "vs_sector_streak": _pct(streak_vs(closes, dates, sector)),
        "uptrend": bool(s200 and px > s200 and s50 > s200),
        "bar_date": bars[-1]["t"][:10],
    }


def _pct(x: float | None) -> float | None:
    return None if x is None else round(x * 100, 2)


# ---------------------------------------------------------------- options
def parse_occ(sym: str) -> dict | None:
    m = OCC_RE.match(sym)
    if not m:
        return None
    root, ymd, cp, strike = m.groups()
    return {"root": root, "expiration": datetime.strptime(ymd, "%y%m%d").date(),
            "type": "call" if cp == "C" else "put", "strike": int(strike) / 1000}


MIN_OPEN_INTEREST = 100


def quote_mid(row: dict) -> tuple[float | None, float | None, float | None, float | None]:
    bid, ask = row.get("bid") or 0, row.get("ask") or 0
    if bid <= 0 or ask <= 0 or ask < bid:
        return None, None, None, None
    mid = (bid + ask) / 2
    return mid, bid, ask, (ask - bid) / mid


def candidates(options: list[dict], today: date) -> list[dict]:
    out = []
    for row in options:
        meta = parse_occ(row.get("option", ""))
        mid, bid, ask, spread = quote_mid(row)
        if not meta or mid is None or not row.get("delta"):
            continue
        out.append({**meta, "contract": row["option"], "delta": row["delta"], "mid": mid, "bid": bid,
                    "ask": ask, "spread_pct": spread, "iv": row.get("iv"),
                    "open_interest": int(row.get("open_interest") or 0),
                    "volume": int(row.get("volume") or 0),
                    "dte": (meta["expiration"] - today).days})
    return out


def pick_contracts(options: list[dict], side: str, today: date, hv20_pct: float | None,
                   max_cost: float | None = None) -> dict | None:
    """Choose a long single option and a same-expiry debit spread."""
    opts = [c for c in candidates(options, today)
            if c["type"] == side and DTE_MIN <= c["dte"] <= DTE_MAX
            and c["spread_pct"] <= MAX_SPREAD_PCT and c["open_interest"] >= MIN_OPEN_INTEREST]
    longs = [c for c in opts if LONG_DELTA[0] <= abs(c["delta"]) <= LONG_DELTA[1]]
    if not longs:
        return None
    def best(pool, target):
        return min(pool, key=lambda c: (abs(abs(c["delta"]) - target) + abs(c["dte"] - TARGET_DTE) / 60))
    long = best(longs, TARGET_DELTA)
    if max_cost and long["mid"] * 100 > max_cost:  # step down to delta ~0.65, never to ATM/OTM
        cheaper = [c for c in longs if c["mid"] * 100 <= max_cost]
        if cheaper:
            long = best(cheaper, FALLBACK_DELTA)
    sign = 1 if long["type"] == "call" else -1
    shorts = [c for c in opts if c["expiration"] == long["expiration"]
              and SHORT_DELTA[0] <= abs(c["delta"]) <= SHORT_DELTA[1]
              and sign * (c["strike"] - long["strike"]) > 0]
    spread = None
    if shorts:
        short = min(shorts, key=lambda c: abs(abs(c["delta"]) - 0.28))
        debit = long["mid"] - short["mid"]
        width = abs(short["strike"] - long["strike"])
        if 0 < debit < width:
            spread = {
                "buy": short_view(long), "sell": short_view(short),
                "debit": round(debit, 2), "max_loss_per_contract": round(debit * 100, 2),
                "max_gain_per_contract": round((width - debit) * 100, 2),
                "breakeven": round(long["strike"] + sign * debit, 2),
            }
    iv = long["iv"]
    iv_vs_hv = round(iv * 100 / hv20_pct, 2) if iv and hv20_pct else None
    return {
        "single": {**short_view(long),
                   "cost_per_contract": round(long["mid"] * 100, 2),
                   "breakeven": round(long["strike"] + sign * long["mid"], 2)},
        "spread": spread,
        "iv_vs_hv20": iv_vs_hv,
        "prefer": "spread" if spread and iv_vs_hv and iv_vs_hv >= 1.3 else "single",
    }


def short_view(c: dict) -> dict:
    return {"contract": c["contract"], "type": c["type"], "strike": c["strike"],
            "expiration": c["expiration"].isoformat(), "dte": c["dte"],
            "delta": round(c["delta"], 2), "bid": c["bid"], "ask": c["ask"],
            "mid": round(c["mid"], 2), "spread_pct": round(c["spread_pct"] * 100, 1),
            "iv": round(c["iv"] * 100, 1) if c["iv"] else None,
            "open_interest": c["open_interest"], "volume": c["volume"]}


# ---------------------------------------------------------------- signals
def direction_for(score: int | None) -> str:
    if score is None:
        return "无数据"
    if score >= CALL_ENTRY:
        return "看涨"
    if score <= PUT_ENTRY:
        return "看跌"
    return "观望"


def earnings_soon(earnings: dict, sym: str, today: date, days: int) -> str | None:
    d = earnings.get(sym)
    if not d:
        return None
    ed = date.fromisoformat(d)
    return d if 0 <= (ed - today).days <= days else None


def position_value(sig: dict, option_snaps: dict) -> float | None:
    """Current net mid of all legs (per share), or None if any leg lacks a quote."""
    total = 0.0
    for leg in sig["legs"]:
        mid, *_ = quote_mid(option_snaps.get(leg["contract"]) or {})
        if mid is None:
            return None
        total += leg["qty"] * mid
    return total


def sessions_since(start: str, today: date) -> int:
    """Weekday sessions after the entry day up to and including today (holidays ignored)."""
    d, n = date.fromisoformat(start), 0
    while d < today:
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


def review_open(open_signals: list[dict], option_snaps: dict, scores: dict, earnings: dict,
                today: date, near_close: bool = True) -> tuple[list[dict], list[dict]]:
    """Return (still_open, exits)."""
    still, exits = [], []
    for sig in open_signals:
        value = position_value(sig, option_snaps)
        sig = {**sig, "last_value": round(value, 2) if value is not None else sig.get("last_value")}
        pnl = (value / sig["entry_cost"] - 1) if value is not None and sig["entry_cost"] else None
        sig["pnl_pct"] = _pct(pnl) if pnl is not None else sig.get("pnl_pct")
        dte = (date.fromisoformat(sig["expiration"]) - today).days
        score = scores.get(sig["symbol"], {}).get("score")
        tp = TAKE_PROFIT if sig["structure"] == "single" else TAKE_PROFIT_SPREAD
        dip4 = sig.get("exit_rules") == "v2.4"  # v2.4 dip trades: no option-% stop or target
        price = scores.get(sig["symbol"], {}).get("price")
        reason = None
        if not dip4 and pnl is not None and pnl >= tp:
            reason = f"止盈：+{pnl * 100:.0f}%"
        elif not dip4 and pnl is not None and pnl <= STOP_LOSS:
            reason = f"止损：{pnl * 100:.0f}%"
        elif dip4 and price is not None and sig.get("disaster_line") and price < sig["disaster_line"] and near_close:
            reason = f"走势破位：收盘 {price} 跌破止损线 {sig['disaster_line']}（信号日低点 − {DISASTER_ATR:g} 倍 ATR），全部卖出"
        elif dip4 and dte <= DIP_TIME_EXIT_DTE:
            reason = f"到期前退场：只剩 {dte} 天到期，不拿到到期日"
        elif dip4 and sig.get("entry_date") and near_close and sessions_since(sig["entry_date"], today) >= DIP_MAX_SESSIONS:
            reason = f"时间退场：已持有 {DIP_MAX_SESSIONS} 个交易日还没反弹到位"
        elif sig.get("entry_date") and (today - date.fromisoformat(sig["entry_date"])).days >= MAX_HOLD_DAYS:
            reason = f"时间退场：已持有满 {MAX_HOLD_DAYS} 天"
        elif not dip4 and dte <= TIME_EXIT_DTE:
            reason = f"时间退场：只剩 {dte} 天到期"
        elif earnings_soon(earnings, sig["symbol"], today, EARNINGS_EXIT_DAYS):
            reason = f"财报前退场（财报日 {earnings[sig['symbol']]}）"
        elif sig.get("setup") == "dip" and near_close and scores.get(sig["symbol"], {}).get("above_sma5"):
            reason = "反弹到位：收盘站上 5 日均线"
            if dip4 and price is not None and sig.get("runner_level") and price >= sig["runner_level"]:
                reason += (f"。涨幅已超过 {sig['runner_level']}（入场 + {RUNNER_ATR:g} 倍 ATR），属于大反弹："
                           "有 2 张以上可以先卖一半、留一半，留下的那一半跌回最高价值的一半、满 10 个交易日或到期前一天再卖")
        elif sig.get("setup") != "dip" and score is not None and sig["type"] == "call" and score < 50:
            reason = f"趋势失效：评分降到 {score}"
        elif sig.get("setup") != "dip" and score is not None and sig["type"] == "put" and score > 50:
            reason = f"趋势失效：评分升到 {score}"
        if reason:
            exits.append({**sig, "exit_reason": reason, "exit_date": today.isoformat()})
        else:
            still.append(sig)
    return still, exits


def choose_structure(pick: dict, max_cost: float) -> tuple[str | None, str | None]:
    """Pick single or spread within the per-contract budget. Returns (structure, block_reason)."""
    single_cost = pick["single"]["cost_per_contract"]
    spread_cost = pick["spread"]["max_loss_per_contract"] if pick["spread"] and not SINGLE_LEG_ONLY else None
    if pick["prefer"] == "spread" and spread_cost is not None and spread_cost <= max_cost:
        return "spread", None
    if single_cost <= max_cost:
        return "single", None
    if spread_cost is not None and spread_cost <= max_cost:
        return "spread", None
    cheapest = min(c for c in (single_cost, spread_cost) if c is not None)
    return None, f"最便宜的方案每张约 ${cheapest:.0f}，超过每张上限 ${max_cost:.0f}"


def market_context(spy: list[dict]) -> dict:
    """SPY state used to size positions: 5-day change, position versus its 50/200-day averages."""
    c = [b["c"] for b in spy]
    if len(c) < 200:
        return {}
    s50, s200 = sma(c, 50), sma(c, 200)
    r5 = (c[-1] / c[-6] - 1) * 100
    above50, above200 = c[-1] > s50, c[-1] > s200
    state = ("普跌回调" if r5 < -2 or not above50 else "平稳上涨")
    return {"spy": round(c[-1], 2), "spy_r5": round(r5, 2), "spy_above50": above50, "spy_above200": above200,
            "state": state, "broad_pullback": r5 < -2 or not above50,
            "note": (f"大盘 5 日 {r5:+.1f}%，{'在' if above50 else '跌破'} 50 日线、{'在' if above200 else '跌破'} 200 日线。"
                     + ("属于普跌回调：回测里这时的连跌信号反弹最好，按标准仓位。" if r5 < -2 or not above50
                        else "大盘平稳：此时单只股票独自连跌，回测反弹较弱，信号按半仓。"))}


def rule_tier(r: dict, market: dict, n_signals_today: int) -> tuple[float, str]:
    """v2.5 rule tier: 0 skip, 0.5 half, 1 full."""
    broad = market.get("broad_pullback") or n_signals_today >= 2
    lag = r.get("vs_sector_streak")
    if lag is not None and not broad and lag <= SECTOR_LAG_SKIP:
        return 0.0, f"不做：大盘平稳，它却比板块多跌 {-lag:.1f}%，多半是公司自己的利空"
    if lag is not None and broad and lag <= SECTOR_LAG_HALF:
        return 0.5, f"比板块多跌 {-lag:.1f}%，可能有公司自身利空，先查新闻"
    if lag is not None and lag > SECTOR_LAG_SKIP:
        return 1.0, "跟板块一起跌，属于被错杀"
    return (1.0, "普跌中的回调") if broad else (0.5, "大盘平稳、个股独跌")


def ml_size(r: dict, market: dict, n_signals_today: int, bars: dict) -> tuple[float, str, float | None]:
    """v2.6 position size = 20% x rule tier x model multiplier (0.5/1/1.5), capped at 30%."""
    tier, note = rule_tier(r, market, n_signals_today)
    if tier <= 0:
        return 0.0, note, None
    model = options_ml.load_model()
    feat = options_ml.features(bars.get(r["symbol"], []), bars.get(SECTOR.get(r["symbol"]) or "", None),
                               bars.get("SPY", []), n_signals_today,
                               bool(market.get("broad_pullback") or n_signals_today >= 2), tier) if model else None
    if not feat:
        risk, n2 = size_tier(r, market, n_signals_today)
        return risk, n2 + "（模型数据不足，按规则）", None
    p = options_ml.score(feat, model)
    mult, mnote = options_ml.size_multiplier(p, model)
    risk = min(RISK_STAR, RISK_FULL * tier * mult)
    star = "⭐ 特别好的机会：" if risk >= RISK_STAR else ""
    return risk, f"{star}每笔 {risk * 100:.0f}%。{note}；{mnote}", round(p, 3)


def size_tier(r: dict, market: dict, n_signals_today: int) -> tuple[float, str]:
    """Size from market state and whether the stock fell with its sector (0 = skip)."""
    broad = market.get("broad_pullback") or n_signals_today >= 2
    lag = r.get("vs_sector_streak")
    if lag is not None and not broad and lag <= SECTOR_LAG_SKIP:
        return 0.0, f"不做：大盘平稳，它却比板块多跌 {-lag:.1f}%，多半是公司自己的利空"
    if lag is not None and broad and lag <= SECTOR_LAG_HALF:
        return RISK_HALF, f"半仓：比板块多跌 {-lag:.1f}%，可能有公司自身利空，先查新闻"
    if lag is not None and lag > SECTOR_LAG_SKIP and broad:
        return RISK_STAR, "⭐ 特别好的机会：大盘回调、它跟板块一起跌（回测每笔约 +18%，两段时间都成立），可以加到 30%"
    if lag is not None and lag > SECTOR_LAG_SKIP:
        return RISK_FULL, "标准仓位：跟板块一起跌，属于被错杀"
    if broad:
        return RISK_FULL, "标准仓位（普跌中的回调）"
    return RISK_HALF, "半仓（大盘平稳、个股独跌）"


def make_entry(r: dict, side: str, pick: dict, structure: str, today: date) -> dict:
    single = pick["single"]
    if structure == "single":
        legs = [{"contract": single["contract"], "qty": 1, "strike": single["strike"], "entry_mid": single["mid"]}]
        cost, breakeven, max_gain = single["mid"], single["breakeven"], None
    else:
        sp = pick["spread"]
        legs = [{"contract": sp["buy"]["contract"], "qty": 1, "strike": sp["buy"]["strike"], "entry_mid": sp["buy"]["mid"]},
                {"contract": sp["sell"]["contract"], "qty": -1, "strike": sp["sell"]["strike"], "entry_mid": sp["sell"]["mid"]}]
        cost, breakeven, max_gain = sp["debit"], sp["breakeven"], sp["max_gain_per_contract"]
    tp = TAKE_PROFIT if structure == "single" else TAKE_PROFIT_SPREAD
    return {
        "symbol": r["symbol"], "type": side, "structure": structure, "score_at_entry": r["score"],
        "underlying_at_entry": r["price"], "legs": legs, "expiration": single["expiration"],
        "entry_cost": round(cost, 2), "cost_per_contract": round(cost * 100, 2),
        "max_gain_per_contract": max_gain, "breakeven": breakeven,
        "stop_value": round(cost * (1 + STOP_LOSS), 2), "target_value": round(cost * (1 + tp), 2),
        "exit_by": (today + timedelta(days=MAX_HOLD_DAYS)).isoformat(),
        "entry_date": today.isoformat(), "iv_vs_hv20": pick["iv_vs_hv20"],
    }


# ---------------------------------------------------------------- run
def run(client, today: date, now: datetime, earnings: dict, state: dict,
        max_cost: float = MAX_COST_DEFAULT) -> dict:
    bars: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    def fetch(sym: str) -> tuple[str, list[dict], str | None]:
        try:
            return sym, client.daily_bars(sym), None
        except Exception as exc:  # one bad symbol must not stop the scan
            return sym, [], str(exc)[:160]

    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, series, err in pool.map(fetch, UNIVERSE + BENCHMARKS):
            bars[sym] = series
            if err:
                errors[sym] = err
    spy = bars.get("SPY", [])
    market = market_context(spy)
    bench_prices = {b: bars[b][-1]["c"] for b in BENCHMARKS if bars.get(b)}
    rows = []
    for sym in UNIVERSE:
        series = bars.get(sym, [])
        sec = bars.get(SECTOR[sym] or "", None)
        res = score_symbol(series, spy, sec) if series else {"score": None, "missing": f"没有行情数据 {errors.get(sym, '')}".strip()}
        res.update(symbol=sym, sector_etf=SECTOR[sym], direction=direction_for(res.get("score")))
        soon = earnings_soon(earnings, sym, today, EARNINGS_BLOCK_DAYS)
        res["earnings"] = earnings.get(sym)
        res["earnings_soon"] = bool(soon)
        rows.append(res)
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["symbol"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    by_sym = {r["symbol"]: r for r in rows}

    # Exits for previously published signals.
    open_prev = state.get("open", [])
    open_prev = [x for x in open_prev if "legs" in x]  # ignore pre-v1 records
    osnaps: dict[str, dict] = {}
    for sym in {s["symbol"] for s in open_prev}:
        try:
            osnaps.update({o["option"]: o for o in client.chain(sym)["options"]})
        except RuntimeError:
            pass
    hm = now.astimezone(CT).strftime("%H:%M")
    near_close = ENTRY_WINDOW_CT[0] <= hm <= ENTRY_WINDOW_CT[1]
    still_open, exits = review_open(open_prev, osnaps, by_sym, earnings, today, near_close)

    # New entries: strongest calls and puts, liquid contract, no earnings inside the hold.
    held = {s["symbol"] for s in still_open}
    qualified: list[str] = []
    new_today = sum(1 for s in still_open + state.get("closed", []) if s.get("entry_date") == today.isoformat())
    cooling = {s["symbol"]: s["exit_date"] for s in state.get("closed", []) + exits
               if (today - date.fromisoformat(s["exit_date"])).days < COOLDOWN_DAYS}
    entries, watch = [], []
    cands = sorted((r for r in rows if r.get("uptrend") and r.get("down_streak", 0) >= DOWN_STREAK_ENTRY),
                   key=lambda r: (-r["down_streak"], r["rsi2"]))
    dips = cands if near_close else []  # the fourth lower close is only known near the close
    for r in rows:  # tell the reader how far each name is from a signal
        if r.get("score") is None:
            continue
        # Opportunity score 0-100: how close the stock is to a dip signal (>=95 = signal). 0 if not in an uptrend.
        r["dip_score"] = min(100, r["down_streak"] * 25) if r.get("uptrend") else 0
        r["setup"] = ("长期趋势不向上，不做" if not r.get("uptrend")
                      else "回调信号" if r in dips
                      else f"已连跌 {r['down_streak']} 天，收盘前（14:30 后）确认" if r in cands
                      else f"接近信号：已连跌 {r['down_streak']} 天" if r["down_streak"] == DOWN_STREAK_ENTRY - 1
                      else f"趋势向上，连跌 {r['down_streak']} 天" if r["down_streak"] else "趋势向上，等回调")
    for side, pool in (("call", dips),):
        added = 0
        for r in pool:
            if added >= MAX_NEW_PER_SIDE:
                break
            r["contracts"] = None
            if r["symbol"] in held:
                r["entry_block"] = "已有持仓信号"
                continue
            if r["symbol"] in cooling:
                r["entry_block"] = f"{cooling[r['symbol']]} 刚退场，冷却 {COOLDOWN_DAYS} 天"
                continue
            if (r.get("hv20") or 0) < MIN_HV20:
                r["entry_block"] = f"股价波动太小（20 日波动率 {r.get('hv20')}% < {MIN_HV20:.0f}%），反弹幅度不够付期权成本，不做"
                continue
            sector_open = sum(1 for s in still_open + entries if SECTOR.get(s["symbol"]) == SECTOR[r["symbol"]])
            if SECTOR[r["symbol"]] and sector_open >= MAX_PER_SECTOR:
                r["entry_block"] = f"同板块已有 {sector_open} 笔，最多 {MAX_PER_SECTOR} 笔"
                continue
            tier, tier_note, ml_p = ml_size(r, market, len(cands), bars)
            if tier <= 0:
                r["entry_block"] = tier_note
                continue
            if r["earnings_soon"]:
                r["entry_block"] = f"{EARNINGS_BLOCK_DAYS}天内有财报（{r['earnings']}），财报后期权价格易暴跌，先不进"
                watch.append(r["symbol"])
                continue
            px = r["price"]
            try:
                chain = client.chain(r["symbol"])["options"]
            except RuntimeError as exc:
                r["entry_block"] = f"期权链获取失败：{exc}"[:160]
                continue
            pick = pick_contracts(chain, side, today, r.get("hv20"), max_cost)
            r["contracts"] = pick
            if not pick:
                r["entry_block"] = f"没有买卖价差 ≤10%、未平仓量 ≥{MIN_OPEN_INTEREST} 的 14–30 天、Delta 0.65–0.85 合约"
                continue
            structure, block = choose_structure(pick, max_cost)
            if block:
                r["entry_block"] = block
                continue
            if len(still_open) + len(entries) >= MAX_OPEN:
                r["entry_block"] = f"已达同时持仓上限 {MAX_OPEN} 笔"
                continue
            qualified.append(r["symbol"])
            if r["symbol"] not in state.get("qualified", []):
                r["entry_block"] = "刚符合条件，下一轮扫描再确认一次"
                continue
            if new_today + len(entries) >= MAX_NEW_PER_DAY:
                r["entry_block"] = f"今天已有 {MAX_NEW_PER_DAY} 个新信号，明天再看"
                continue
            entries.append({**make_entry(r, side, pick, structure, today), "setup": "dip", "down_streak_at_entry": r["down_streak"],
                            "exit_rules": "v2.4", "stop_value": None, "target_value": None,
                            "disaster_line": round(r["low"] - DISASTER_ATR * r["atr14"], 2) if r.get("low") and r.get("atr14") else None,
                            "runner_level": round(r["price"] + RUNNER_ATR * r["atr14"], 2) if r.get("atr14") else None,
                            "risk_pct": round(tier * 100, 1), "size_note": tier_note, "ml_score": ml_p,
                            "market_state": market.get("state")})
            added += 1

    scored = [r for r in rows if r["score"] is not None]
    return {
        "rules_version": RULES_VERSION,
        "generated_at": now.isoformat(),
        "generated_at_ct": now.astimezone(CT).strftime("%Y-%m-%d %H:%M CT"),
        "data_source": "数据来源：股价为 Nasdaq 盘中实时成交价；期权链为 Cboe 数据（延迟约 15 分钟），含 Delta、隐含波动率和未平仓量。",
        "coverage": {"scored": len(scored), "total": len(UNIVERSE)},
        "risk_rules": RISK_RULES,
        "market": market,
        "sizing": {"risk_full_pct": RISK_FULL * 100, "risk_half_pct": RISK_HALF * 100, "risk_star_pct": RISK_STAR * 100,
                   "drawdown_halve_pct": DRAWDOWN_HALVE * 100, "drawdown_pause_pct": DRAWDOWN_PAUSE * 100,
                   "max_per_sector": MAX_PER_SECTOR},
        "watchlist": [{"symbol": r["symbol"], "dip_score": r["dip_score"], "down_streak": r["down_streak"], "rsi2": r["rsi2"],
                       "price": r["price"], "setup": r["setup"]}
                      for r in sorted((x for x in rows if x.get("uptrend")), key=lambda x: (-x["down_streak"], x["rsi2"]))[:8]],
        "thresholds": {"call_entry": CALL_ENTRY, "put_entry": PUT_ENTRY, "down_streak_entry": DOWN_STREAK_ENTRY, "min_hv20": MIN_HV20,
                       "max_cost_per_contract": max_cost,
                       "take_profit_pct": TAKE_PROFIT * 100, "take_profit_spread_pct": TAKE_PROFIT_SPREAD * 100, "stop_loss_pct": STOP_LOSS * 100,
                       "time_exit_dte": TIME_EXIT_DTE, "max_hold_days": MAX_HOLD_DAYS},
        "top": [r["symbol"] for r in scored[:5]],
        "bottom": [r["symbol"] for r in scored[-5:][::-1]],
        "entries": entries,
        "exits": exits,
        "open": still_open + entries,
        "qualified": qualified,
        "earnings_unverified": [s for s in UNIVERSE if s not in earnings],
        "earnings_blocked": watch,
        "blocked": [{"symbol": r["symbol"], "score": r["score"], "direction": r["direction"], "reason": r["entry_block"]}
                    for r in rows if r.get("entry_block")],
        "rankings": rows,
        "benchmark_prices": bench_prices,
    }


def legs_text(sig: dict) -> str:
    kind = "C" if sig["type"] == "call" else "P"
    parts = [("买" if l["qty"] > 0 else "卖") + f" {l['strike']:g}{kind}" for l in sig["legs"]]
    return " / ".join(parts) + f" {sig['expiration']}"


def report(result: dict) -> str:
    lines = [f"# 期权评分播报 {result['generated_at_ct']}",
             f"覆盖 {result['coverage']['scored']}/{result['coverage']['total']} 只。买入信号：上升趋势中连跌 4 天买 Call（收盘前确认）。趋势评分仅作参考。", ""]
    if result["exits"]:
        lines.append("## 🔴 退场")
        for s in result["exits"]:
            lines.append(f"- {s['symbol']} {legs_text(s)}：{s['exit_reason']}（进场 {s['entry_cost']} → 现在 {s.get('last_value')}）")
        lines.append("")
    if result["entries"]:
        lines.append("## 🟢 进场")
        for e in result["entries"]:
            kind = "看涨" if e["type"] == "call" else "看跌"
            what = "单买期权" if e["structure"] == "single" else "借方价差"
            gain = f"，最多赚 ${e['max_gain_per_contract']:.0f}" if e["max_gain_per_contract"] else ""
            lines.append(f"- **{e['symbol']} {kind}**（评分 {e['score_at_entry']}，股价 {e['underlying_at_entry']}）{what}：{legs_text(e)}")
            lines.append(f"  - 净成本约 {e['entry_cost']}（每张约 ${e['cost_per_contract']:.0f}，最多亏这么多{gain}），盈亏平衡 {e['breakeven']}")
            lines.append(f"  - 止损 {e['stop_value']} ｜ 止盈 {e['target_value']} ｜ 最晚 {e['exit_by']} 退场")
        lines.append("")
    if not result["entries"] and not result["exits"]:
        lines += ["本次没有新的进场或退场信号。", ""]
    held = [s for s in result["open"] if s not in result["entries"]]
    if held:
        lines.append("## 持有中")
        for s in held:
            lines.append(f"- {s['symbol']} {legs_text(s)}：盈亏 {s.get('pnl_pct')}%")
        lines.append("")
    if result.get("blocked"):
        lines.append("## 高/低分但没进场的原因")
        for b in result["blocked"]:
            lines.append(f"- {b['symbol']}（{b['score']}，{b['direction']}）：{b['reason']}")
        lines.append("")
    lines.append("## 排名（高 → 低）")
    for r in result["rankings"]:
        sc = "—" if r["score"] is None else r["score"]
        lines.append(f"{r['rank']:>2}. {r['symbol']:<5} {sc:>3}  {r['direction']}")
    if result["earnings_unverified"]:
        lines += ["", f"⚠️ 财报日期未核实：{len(result['earnings_unverified'])} 只。下单前请确认未来 14 天内没有财报。"]
    lines += ["", *[f"- {x}" for x in result["risk_rules"]]]
    return "\n".join(lines)


SECTOR_NAMES = {"XLK": "科技", "XLC": "通信", "XLY": "可选消费", "XLP": "必需消费", "XLV": "医疗", "XLF": "金融",
                "XLE": "能源", "XLI": "工业", "XLU": "公用事业", "XLB": "材料", "XLRE": "地产"}


def explain_row(r: dict) -> tuple[list[str], list[str]]:
    """(bullish points, bearish points) in plain Chinese, from the row's own numbers."""
    def chk(name: str) -> int:
        for c in r.get("checks", []):
            if c["name"] == name:
                return 1 if c["bull"] > c["bear"] else -1 if c["bear"] > c["bull"] else 0
        return 0

    bull, bear = [], []
    px, s20, s50, s200 = r["price"], r["sma20"], r["sma50"], r.get("sma200")
    (bull if px > s20 else bear).append(f"股价 {px:.2f} 在 20 日均线 {s20:.2f} {'上方' if px > s20 else '下方'}")
    (bull if s20 > s50 else bear).append(f"20 日均线在 50 日均线{'上方（短期趋势向上）' if s20 > s50 else '下方（短期趋势向下）'}")
    if s200:
        (bull if s50 > s200 else bear).append(f"50 日均线在 200 日均线{'上方（中期趋势向上）' if s50 > s200 else '下方（中期趋势向下）'}")
    d = chk("20日均线方向")
    if d:
        (bull if d > 0 else bear).append(f"20 日均线正在{'上行' if d > 0 else '下行'}")
    if r.get("rel_spy20") is not None:
        v = r["rel_spy20"]
        (bull if v > 0 else bear).append(f"近 20 天{'跑赢' if v > 0 else '跑输'}大盘 {abs(v):.1f} 个百分点")
    if r.get("rel_sector20") is not None:
        v = r["rel_sector20"]
        (bull if v > 0 else bear).append(f"近 20 天{'跑赢' if v > 0 else '跑输'}{SECTOR_NAMES.get(r.get('sector_etf'), '行业')}板块 {abs(v):.1f} 个百分点")
    rsi_v = r["rsi14"]
    if rsi_v >= 80:
        bear.append(f"RSI {rsi_v:.0f}，严重超买，容易回调")
    elif rsi_v >= 55:
        bull.append(f"RSI {rsi_v:.0f}，上涨动能健康")
    elif rsi_v <= 20:
        bull.append(f"RSI {rsi_v:.0f}，严重超卖，容易反弹")
    elif rsi_v <= 45:
        bear.append(f"RSI {rsi_v:.0f}，动能偏弱")
    m = chk("MACD 柱")
    if m:
        (bull if m > 0 else bear).append(f"MACD 动能{'转强' if m > 0 else '转弱'}")
    st = r.get("stretch_atr") or 0
    if abs(st) > 2:
        (bear if st > 0 else bull).append(f"离 20 日均线 {abs(st):.1f} 倍日均波幅，短期{'涨' if st > 0 else '跌'}得过多")
    return bull, bear


def annotate(result: dict) -> None:
    """Add what a reader needs to place this scan in its day: scan number, score and
    price change versus the previous session's close, today's opening score, reasons."""
    day = result["generated_at_ct"][:10]
    files = sorted((OUT_DIR / "daily").glob("*.json")) if (OUT_DIR / "daily").exists() else []
    today = next((json.loads(p.read_text()) for p in files if p.stem == day), None)
    prev = next((json.loads(p.read_text()) for p in reversed(files) if p.stem < day), None)
    result["session_date"] = day
    result["scan_no"] = (today or {}).get("scans", 0) + 1
    result["prev_session_date"] = prev["date"] if prev else None
    prices = {**{r["symbol"]: r.get("price") for r in result["rankings"]}, **result.get("benchmark_prices", {})}
    pp = prev["last"]["prices"] if prev else {}
    result["spy_day_pct"] = round((prices["SPY"] / pp["SPY"] - 1) * 100, 2) if pp.get("SPY") and prices.get("SPY") else None
    for r in result["rankings"]:
        sym = r["symbol"]
        r["score_prev_close"] = prev["last"]["scores"].get(sym) if prev else None
        r["score_open"] = today["first"]["scores"].get(sym) if today else r.get("score")
        r["day_pct"] = round((r["price"] / pp[sym] - 1) * 100, 2) if r.get("price") and pp.get(sym) else None
        if r.get("score") is not None:
            bull, bear = explain_row(r)
            r["why_bull"], r["why_bear"] = bull, bear


def write_outputs(result: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "history").mkdir(exist_ok=True)
    stamp = datetime.fromisoformat(result["generated_at"]).strftime("%Y%m%dT%H%M%SZ")
    annotate(result)
    payload = json.dumps(result, ensure_ascii=False, indent=1) + "\n"
    (OUT_DIR / "latest.json").write_text(payload)
    days = OUT_DIR / "days"  # one full snapshot per session (the day's last scan wins)
    days.mkdir(exist_ok=True)
    (days / f"{result['session_date']}.json").write_text(payload)
    (days / "index.json").write_text(json.dumps(
        {"dates": sorted((p.stem for p in days.glob("2*.json")), reverse=True)}) + "\n")
    if result["entries"] or result["exits"] or not any((OUT_DIR / "history").iterdir()):
        (OUT_DIR / "history" / f"{stamp}.json").write_text(payload)  # keep only signal snapshots
    write_daily_snapshot(result)
    state = {"updated_at": result["generated_at"], "open": result["open"], "qualified": result["qualified"],
             "closed": (load_state().get("closed", []) + result["exits"])[-200:]}
    (OUT_DIR / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n")
    return OUT_DIR / "latest.json"


def write_daily_snapshot(result: dict) -> None:
    """Keep the day's first and latest scores/prices for the end-of-day review."""
    day = result["generated_at_ct"][:10]
    path = OUT_DIR / "daily" / f"{day}.json"
    path.parent.mkdir(exist_ok=True)
    snap = {"at": result["generated_at"], "rules_version": result["rules_version"],
            "scores": {r["symbol"]: r["score"] for r in result["rankings"]},
            "prices": {**{r["symbol"]: r.get("price") for r in result["rankings"]},
                       **result.get("benchmark_prices", {})},
            "sectors": {r["symbol"]: r.get("sector_etf") for r in result["rankings"]}}
    data = json.loads(path.read_text()) if path.exists() else {"date": day}
    data.setdefault("first", snap)
    data["last"] = snap
    data["scans"] = data.get("scans", 0) + 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def load_state() -> dict:
    p = OUT_DIR / "state.json"
    return json.loads(p.read_text()) if p.exists() else {"open": [], "closed": []}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "check"])
    ap.add_argument("--earnings", type=Path, help='JSON {"dates": {"AAPL": "2027-01-29"}} of verified next earnings dates (default docs/data/options/earnings.json)')
    ap.add_argument("--max-cost", type=float, default=MAX_COST_DEFAULT, help="max USD per contract (default 1000)")
    ap.add_argument("--signal-file", type=Path, help="write {title, body} JSON here when there are entries/exits")
    ap.add_argument("--dry-run", action="store_true", help="print report, do not write files")
    args = ap.parse_args(argv)
    client = CboeClient(live=NasdaqClient())
    if args.command == "check":
        q = client.chain("SPY")
        print("OK", q["timestamp"], q["quote"].get("current_price"), len(q["options"]), "contracts")
        return 0
    epath = args.earnings or (OUT_DIR / "earnings.json")
    earnings = json.loads(epath.read_text()).get("dates", {}) if epath.exists() else {}
    now = datetime.now(timezone.utc)
    result = run(client, now.astimezone(CT).date(), now, earnings, load_state(), args.max_cost)
    if result["coverage"]["scored"] == 0:
        print("ERROR: no symbols could be scored; nothing written.", file=sys.stderr)
        return 2
    if not args.dry_run:
        write_outputs(result)
    text = report(result)
    print(text)
    if args.signal_file and (result["entries"] or result["exits"]):
        title = "期权信号：" + "，".join(
            [f"进场 {e['symbol']} {'Call' if e['type'] == 'call' else 'Put'}" for e in result["entries"]] +
            [f"退场 {x['symbol']}" for x in result["exits"]])
        args.signal_file.write_text(json.dumps({"title": title, "body": text}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
