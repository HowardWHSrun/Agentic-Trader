"""ML sizing overlay for v2.5 dip signals (options-score-v2.6).

A small L2 logistic regression scores each dip signal: P(the v2.5 option trade ends positive).
It only changes SIZE (0.5x / 1x / 1.5x by tercile of its training predictions); it never adds or
skips a trade. Walk-forward test 2010-2026 (train on earlier years only, 7-session purge):
return per unit of risk +7.0% -> +9.3% per trade, better in 13 of 17 years; top tercile +10.1%,
bottom tercile -1.3%. Weights live in docs/data/options/ml_model.json (refit once a year with
the research script; inference here is plain Python).
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "options" / "ml_model.json"


def _sma(c, n):
    return sum(c[-n:]) / n


def _streak(c, cap=10):
    n = 0
    while n < cap and len(c) > n + 1 and c[-1 - n] < c[-2 - n]:
        n += 1
    return n


def _hv(c, n=20):
    r = [math.log(c[k] / c[k - 1]) for k in range(len(c) - n, len(c))]
    m = sum(r) / n
    return math.sqrt(sum((x - m) ** 2 for x in r) / (n - 1)) * math.sqrt(252)


def _rsi(c, n):
    c = c[-(n * 6 + 1):]
    gains = losses = 0.0
    for a, b in zip(c[:n + 1], c[1:n + 1]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for a, b in zip(c[n:], c[n + 1:]):
        d = b - a
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def _atr(bars, n=14):
    """Wilder ATR over the last 31 bars (same as options_scorer.atr(bars[-31:]), used in training)."""
    b = bars[-31:]
    trs = [max(x["h"] - x["l"], abs(x["h"] - y["c"]), abs(x["l"] - y["c"])) for y, x in zip(b, b[1:])]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def _ret_between(bars, start, end):
    m = {b["t"][:10]: b["c"] for b in bars}
    return m[end] / m[start] - 1 if start in m and end in m and m[start] else None


def features(bars: list[dict], sector: list[dict] | None, spy: list[dict], n_sig_day: int,
             broad: bool, tier: float) -> dict | None:
    """Features at the latest bar of `bars` (must be a dip: >=4 lower closes). Needs ~262 bars."""
    bad = {"2018-11-22", "2025-05-26", "2007-07-04"}  # holidays that carry fake bars in the Cboe history
    bars = [b for b in bars if b["t"][:10] not in bad]
    spy = [b for b in spy if b["t"][:10] not in bad]
    sector = [b for b in sector if b["t"][:10] not in bad] if sector else sector
    if len(bars) < 262 or len(spy) < 210:
        return None
    c = [b["c"] for b in bars]
    v = [b.get("v") or 0 for b in bars]
    n = _streak(c)
    if n < 1:
        return None
    px, a = c[-1], _atr(bars)
    if not a:
        return None
    d0, d1 = bars[-1 - n]["t"][:10], bars[-1]["t"][:10]
    st_ret = px / c[-1 - n] - 1
    sec_ret = _ret_between(sector, d0, d1) if sector else None
    spy_ret = _ret_between(spy, d0, d1)
    s = [b["c"] for b in spy]
    s200, s50 = _sma(c, 200), _sma(c, 50)
    hi52 = max(b["h"] for b in bars[-252:])
    rng = bars[-1]["h"] - bars[-1]["l"]
    gaps = [bars[j]["o"] / bars[j - 1]["c"] - 1 for j in range(len(bars) - n, len(bars))]
    vs = sum(v[-n:]) / n
    vb = sum(v[-n - 51:-n]) / 51 if len(v) > n + 51 else 0
    hv20, hv60 = _hv(c, 20), _hv(c, 60)
    dt = date.fromisoformat(d1)
    return {
        "streak": n, "st_drop": st_ret * 100, "drop_atr": (px - c[-1 - n]) / a,
        "max_day_atr": min(c[k] - c[k - 1] for k in range(len(c) - n, len(c))) / a,
        "day0_atr": (c[-1] - c[-2]) / a,
        "n_gapdn": sum(g < 0 for g in gaps), "gap_sum": sum(min(g, 0) for g in gaps) * 100,
        "vs_sector": (st_ret - sec_ret) * 100 if sec_ret is not None else None,
        "vs_spy": (st_ret - spy_ret) * 100 if spy_ret is not None else None,
        "rsi2": _rsi(c, 2), "rsi14": _rsi(c, 14),
        "d20_atr": (px - _sma(c, 20)) / a, "d50_atr": (px - s50) / a, "d200_atr": (px - s200) / a,
        "s200_slope": (s200 / (sum(c[-220:-20]) / 200) - 1) * 100,
        "s50_slope": (s50 / (sum(c[-60:-10]) / 50) - 1) * 100,
        "hv20": hv20 * 100, "hv_ratio": hv20 / hv60 if hv60 else None, "atr_pct": a / px * 100,
        "vol_ratio": vs / vb if vb > 0 else None,
        "clv": (bars[-1]["c"] - bars[-1]["l"]) / rng if rng > 0 else 0.5,
        "r20": (px / c[-21] - 1) * 100, "r60": (px / c[-61] - 1) * 100,
        "from_hi_atr": (hi52 - px) / a,
        "spy_r5": (s[-1] / s[-6] - 1) * 100, "spy_r20": (s[-1] / s[-21] - 1) * 100,
        "spy_d50": (s[-1] / _sma(s, 50) - 1) * 100, "spy_d200": (s[-1] / _sma(s, 200) - 1) * 100,
        "spy_hv20": _hv(s, 20) * 100, "spy_streak": _streak(s),
        "n_sig_day": n_sig_day, "dow": dt.weekday(), "month": dt.month,
        "broad_f": float(bool(broad)), "tier": tier,
    }


def load_model(path: Path = MODEL_PATH) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def score(feat: dict, model: dict) -> float:
    z = model["intercept"]
    for name, med, mu, sd, w in zip(model["features"], model["median"], model["mean"], model["scale"], model["coef"]):
        x = feat.get(name)
        x = med if x is None else x
        z += w * (x - mu) / (sd or 1)
    return 1 / (1 + math.exp(-z))


def size_multiplier(p: float, model: dict) -> tuple[float, str]:
    if p < model["q33"]:
        return 0.5, f"模型评分 {p:.2f}（偏低，后三分之一）：仓位减半"
    if p > model["q67"]:
        return 1.5, f"模型评分 {p:.2f}（偏高，前三分之一）：仓位 ×1.5"
    return 1.0, f"模型评分 {p:.2f}（中等）"
