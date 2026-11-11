#!/usr/bin/env python3
"""Historical test of the score: does a high score precede gains and a low score losses?

Modelled on factor-analysis tools such as alphalens: for every past trading day
the score is recomputed from data available on that day only, then compared
with what each stock did over the next 1, 3 and 5 sessions.

Reports, overall and split by year and by market regime (SPY above/below its
50-day average):
  * rank IC  - daily Spearman correlation of score vs forward return
  * groups   - average forward return and hit rate of bullish (>=70) and
               bearish (<=30) names, and the bullish-minus-bearish spread
  * factors  - the same IC for each of the nine checks and for candidate
               factors, to see which parts carry the signal

It also simulates whole trading rules with an approximate option price
(Black-Scholes, at-the-money, 30 days to expiry, implied volatility taken as
1.1 x the 20-day realized volatility, 4% round-trip cost) so rules can be
compared by expected profit per trade.

Limits: 32 large caps only (a small cross-section), stock returns rather than
option P&L (no historical option prices), and a fixed universe chosen today
(survivorship bias). Treat results as evidence, not proof.

Usage: python3 scripts/options_backtest.py [--years 3] [--cache DIR] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import options_scorer as o  # noqa: E402
from options_review import mean, spearman  # noqa: E402

HORIZONS = (1, 3, 5)
WINDOW = 300


def load_history(cache: Path | None) -> dict[str, list[dict]]:
    client = o.CboeClient()
    out = {}
    for sym in o.UNIVERSE + o.BENCHMARKS:
        path = cache / f"{sym}.json" if cache else None
        if path and path.exists():
            out[sym] = json.loads(path.read_text())
            continue
        rows = client._get(f"charts/historical/{sym}.json").get("data") or []
        bars = [{"t": r["date"], "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r["volume"]}
                for r in rows if r.get("close")]
        out[sym] = bars
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(bars))
    return out


def extra_factors(bars: list[dict]) -> dict[str, float | None]:
    """Candidate factors not in the score, signed so that higher = more bullish."""
    c = [b["c"] for b in bars]
    hi252 = max(c[-252:]) if len(c) >= 252 else None
    r5, r60 = o.ret(c, 5), o.ret(c, 60)
    r252_21 = (c[-22] / c[-253] - 1) if len(c) >= 253 else None
    rsi2 = o.rsi(c[-40:], 2)
    hv = o.hist_vol(c)
    r20 = o.ret(c, 20)
    return {
        "反转：近5天跌幅（−ret5）": -r5 if r5 is not None else None,
        "反转：RSI(2) 低": -rsi2 if rsi2 is not None else None,
        "动量：近60天涨幅": r60,
        "动量：12个月减最近1个月": r252_21,
        "接近52周高点": c[-1] / hi252 if hi252 else None,
        "风险调整动量：ret20÷波动率": r20 / hv if r20 is not None and hv else None,
        "低波动（−hv20）": -hv if hv else None,
    }


def gh_features(win: list[dict]) -> dict:
    """Inputs for rules taken from public GitHub strategy repos (Connors, Quantitativo)."""
    c = [b["c"] for b in win]
    b = win[-1]
    rng = b["h"] - b["l"]
    s200 = o.sma(c, 200)
    s50 = o.sma(c, 50)
    return {
        "above200": bool(s200 and c[-1] > s200),
        "downtrend": bool(s200 and c[-1] < s200 and s50 < s200),
        "cum2": o.rsi(c[-40:], 2) + o.rsi(c[-41:-1], 2),
        "ibs": (b["c"] - b["l"]) / rng if rng else 0.5,
        "qband": c[-1] < max(x["h"] for x in win[-10:]) - 2.5 * sum(x["h"] - x["l"] for x in win[-25:]) / 25,
    }


def build_panel(hist: dict[str, list[dict]], years: float) -> list[dict]:
    spy = hist["SPY"]
    spy_idx = {b["t"]: i for i, b in enumerate(spy)}
    n_days = int(years * 252)
    dates = [b["t"] for b in spy][-(n_days + max(HORIZONS)):]
    idx = {s: {b["t"]: i for i, b in enumerate(bars)} for s, bars in hist.items()}
    spy_close = [b["c"] for b in spy]
    panel = []
    for d in dates[:-max(HORIZONS)]:
        si = spy_idx[d]
        spy_sma50 = sum(spy_close[si - 49:si + 1]) / 50
        regime = "大盘在50日线上方" if spy_close[si] > spy_sma50 else "大盘在50日线下方"
        spy_win = spy[max(0, si - 60):si + 1]
        for sym in o.UNIVERSE:
            i = idx[sym].get(d)
            bars = hist[sym]
            if i is None or i < 60 or i + max(HORIZONS) >= len(bars):
                continue
            win = bars[max(0, i - WINDOW + 1):i + 1]
            sec = hist.get(o.SECTOR[sym] or "")
            sec_win = None
            if sec:
                j = idx[o.SECTOR[sym]].get(d)
                sec_win = sec[max(0, j - 60):j + 1] if j is not None else None
            res = o.score_symbol(win, spy_win, sec_win)
            if res.get("score") is None:
                continue
            row = {"date": d, "symbol": sym, "i": i, "score": res["score"], "regime": regime,
                   "uptrend": res["uptrend"], "rsi2": res["rsi2"], "streak": res["down_streak"], **gh_features(win),
                   "stretch": res["stretch_atr"],
                   "checks": {c["name"]: c["bull"] - c["bear"] for c in res["checks"]},
                   "extra": extra_factors(win)}
            for h in HORIZONS:
                fwd = bars[i + h]["c"] / bars[i]["c"] - 1
                sfwd = spy_close[si + h] / spy_close[si] - 1
                row[f"ret{h}"] = fwd * 100
                row[f"ex{h}"] = (fwd - sfwd) * 100
            panel.append(row)
    return panel


def ic_stats(panel: list[dict], factor, ret_key: str) -> dict:
    by_day = defaultdict(list)
    for r in panel:
        f = factor(r)
        if f is not None:
            by_day[r["date"]].append((f, r[ret_key]))
    ics = [x for x in (spearman([a for a, _ in v], [b for _, b in v]) for v in by_day.values() if len(v) >= 10) if x is not None]
    if len(ics) < 20:
        return {"days": len(ics), "ic": None, "t": None, "pos": None}
    m = sum(ics) / len(ics)
    sd = (sum((x - m) ** 2 for x in ics) / (len(ics) - 1)) ** 0.5
    return {"days": len(ics), "ic": round(m, 4), "t": round(m / sd * math.sqrt(len(ics)), 2) if sd else None,
            "pos": round(sum(1 for x in ics if x > 0) / len(ics) * 100, 1)}


def group_stats(panel: list[dict], h: int, bull=lambda r: r["score"] >= 70, bear=lambda r: r["score"] <= 30) -> dict:
    def side(rows, want_up):
        if not rows:
            return {"n": 0, "ret": None, "excess": None, "hit": None}
        rets = [r[f"ret{h}"] for r in rows]
        return {"n": len(rows), "ret": mean(rets), "excess": mean([r[f"ex{h}"] for r in rows]),
                "hit": round(sum(1 for x in rets if (x > 0) == want_up) / len(rets) * 100, 1)}
    b, s = side([r for r in panel if bull(r)], True), side([r for r in panel if bear(r)], False)
    spread = round(b["excess"] - s["excess"], 3) if b["n"] and s["n"] else None
    return {"bull": b, "bear": s, "spread_excess": spread}


def summarize(panel: list[dict]) -> dict:
    out = {"rows": len(panel), "from": panel[0]["date"], "to": panel[-1]["date"], "overall": {}, "by_year": {}, "by_regime": {}}
    for h in HORIZONS:
        out["overall"][h] = {"ic": ic_stats(panel, lambda r: r["score"], f"ex{h}"), **group_stats(panel, h)}
    for key, name in (("date", "by_year"), ("regime", "by_regime")):
        groups = defaultdict(list)
        for r in panel:
            groups[r[key][:4] if key == "date" else r[key]].append(r)
        for g, rows in sorted(groups.items()):
            out[name][g] = {"ic": ic_stats(rows, lambda r: r["score"], "ex5"), **group_stats(rows, 5)}
    names = list(panel[0]["checks"]) + list(panel[0]["extra"])
    out["factors"] = {}
    for n in names:
        f = (lambda r, n=n: r["checks"].get(n)) if n in panel[0]["checks"] else (lambda r, n=n: r["extra"].get(n))
        out["factors"][n] = {h: ic_stats(panel, f, f"ex{h}") for h in HORIZONS}
    return out


# ------------------------------------------------------- rule simulation
def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(S: float, K: float, T: float, sig: float, call: bool = True, r: float = 0.04) -> float:
    if T <= 0:
        return max(S - K, 0) if call else max(K - S, 0)
    d1 = (math.log(S / K) + (r + sig * sig / 2) * T) / (sig * math.sqrt(T))
    c = S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d1 - sig * math.sqrt(T))
    return c if call else c - S + K * math.exp(-r * T)


def option_trade(bars: list[dict], i: int, call: bool, stop: float, tp: float, days: int = 5,
                 rsi_exit: float | None = None, sma5_exit: bool = False, dte: int = 30, cost: float = 0.04) -> float:
    """Approximate % P&L of one at-the-money option bought at bar i's close."""
    from datetime import date as _d
    s0 = bars[i]["c"]
    sig = max(o.hist_vol([b["c"] for b in bars[i - 25:i + 1]]) or 0.2, 0.15) * 1.1
    p0 = bs_price(s0, s0, dte / 365, sig, call)
    d0 = _d.fromisoformat(bars[i]["t"])
    pnl = 0.0
    for k in range(1, days + 1):
        el = (_d.fromisoformat(bars[i + k]["t"]) - d0).days
        pnl = bs_price(bars[i + k]["c"], s0, (dte - el) / 365, sig, call) / p0 - 1
        if pnl <= stop or pnl >= tp:
            break
        if rsi_exit is not None and o.rsi([b["c"] for b in bars[i + k - 39:i + k + 1]], 2) > rsi_exit:
            break
        if sma5_exit and bars[i + k]["c"] > sum(b["c"] for b in bars[i + k - 4:i + k + 1]) / 5:
            break
    return (pnl - cost) * 100


RULES = [
    ("v2.1 现行：上升趋势 且 连跌≥4天 买Call", lambda r: r["uptrend"] and r["streak"] >= o.DOWN_STREAK_ENTRY, True,
     dict(stop=o.STOP_LOSS, tp=o.TAKE_PROFIT, sma5_exit=True)),
    ("上升趋势 且 正好连跌3天 买Call", lambda r: r["uptrend"] and r["streak"] == 3, True, dict(stop=o.STOP_LOSS, tp=o.TAKE_PROFIT, sma5_exit=True)),
    ("非上升趋势 且 连跌≥4天 买Call", lambda r: not r["uptrend"] and r["streak"] >= 4, True, dict(stop=o.STOP_LOSS, tp=o.TAKE_PROFIT, sma5_exit=True)),
    ("v2.0 旧：上升趋势 且 RSI(2)<5 买Call", lambda r: r["uptrend"] and r["rsi2"] < 5, True,
     dict(stop=o.STOP_LOSS, tp=o.TAKE_PROFIT, rsi_exit=65)),
    ("GitHub/Connors：>200日线 且 两日RSI(2)之和<10", lambda r: r["above200"] and r["cum2"] < 10, True,
     dict(stop=o.STOP_LOSS, tp=o.TAKE_PROFIT, rsi_exit=65)),
    ("GitHub/Quantitativo：跌破10日高−2.5×波幅 且 IBS<0.3", lambda r: r["qband"] and r["ibs"] < 0.3, True,
     dict(stop=o.STOP_LOSS, tp=o.TAKE_PROFIT, sma5_exit=True)),
    ("Put：下降趋势 且 RSI(2)>95", lambda r: r["downtrend"] and r["rsi2"] > 95, False, dict(stop=o.STOP_LOSS, tp=o.TAKE_PROFIT)),
    ("旧 v1 追高分买Call：评分≥70 且不追高", lambda r: r["score"] >= 70 and r["stretch"] <= 2, True, dict(stop=-0.35, tp=0.5)),
    ("旧 v1 低分买Put：评分≤30 且不追跌", lambda r: r["score"] <= 30 and r["stretch"] >= -2, False, dict(stop=-0.35, tp=0.5)),
    ("基准：任何股票任何一天买Call", lambda r: True, True, dict(stop=-0.35, tp=0.5)),
    ("基准：任何股票任何一天买Put", lambda r: True, False, dict(stop=-0.35, tp=0.5)),
]
PERIODS = [("2021–2024", lambda r: r["date"] < "2025"), ("2025–2026", lambda r: r["date"] >= "2025"), ("全部", lambda r: True)]


def rule_table(panel: list[dict], hist: dict[str, list[dict]]) -> list[dict]:
    out = []
    for name, cond, call, kw in RULES:
        row = {"rule": name, "periods": {}}
        picked = [r for r in panel if r["i"] >= 40 and cond(r)]
        pnl = {id(r): option_trade(hist[r["symbol"]], r["i"], call, **kw) for r in picked}
        for label, pc in PERIODS:
            sel = [r for r in picked if pc(r)]
            if len(sel) < 30:
                row["periods"][label] = {"n": len(sel)}
                continue
            x = [pnl[id(r)] for r in sel]
            m = sum(x) / len(x)
            sd = (sum((v - m) ** 2 for v in x) / (len(x) - 1)) ** 0.5
            days = len({r["date"] for r in sel})  # trades on one day move together, so use days for the t-stat
            row["periods"][label] = {"n": len(sel), "avg_pnl_pct": round(m, 2), "win_rate": round(sum(1 for v in x if v > 0) / len(x) * 100, 1),
                                     "t": round(m / sd * math.sqrt(days), 2) if sd else None}
        out.append(row)
    return out


def fmt(x, nd=2, suffix=""):
    return "—" if x is None else f"{x:+.{nd}f}{suffix}"


def report(s: dict) -> str:
    L = [f"# 历史回测 {s['from']} → {s['to']}（{s['rows']} 个 股票×交易日 样本）", ""]
    L.append("## 总体：分数 vs 之后的涨跌（相对 SPY 的超额）")
    L.append("周期 | IC | t值 | IC为正的天数 | 看涨组超额 | 看涨命中率 | 看跌组超额 | 看跌命中率 | 看涨−看跌")
    for h in HORIZONS:
        v = s["overall"][h]
        L.append(f"{h}天 | {fmt(v['ic']['ic'], 4)} | {fmt(v['ic']['t'])} | {v['ic']['pos']}% | {fmt(v['bull']['excess'], 3, '%')} (n={v['bull']['n']}) | "
                 f"{v['bull']['hit']}% | {fmt(v['bear']['excess'], 3, '%')} (n={v['bear']['n']}) | {v['bear']['hit']}% | {fmt(v['spread_excess'], 3, '%')}")
    for name, title in (("by_year", "按年份（5天）"), ("by_regime", "按大盘状态（5天）")):
        L += ["", f"## {title}"]
        for g, v in s[name].items():
            L.append(f"{g} | IC {fmt(v['ic']['ic'], 4)} t {fmt(v['ic']['t'])} | 看涨 {fmt(v['bull']['excess'], 3, '%')} / 看跌 {fmt(v['bear']['excess'], 3, '%')} | 差 {fmt(v['spread_excess'], 3, '%')}")
    L += ["", "## 各项因子的 IC（1天 / 3天 / 5天，括号内为 t 值）"]
    for n, v in s["factors"].items():
        L.append(f"{n:<26} " + " | ".join(f"{fmt(v[h]['ic'], 4)} ({fmt(v[h]['t'])})" for h in HORIZONS))
    L += ["", "IC 为正 = 分数高的股票之后确实涨得多。|t| > 2 才算统计上站得住；IC 在 0.02–0.05 已属不错。"]
    L += ["", "## 整套规则的模拟期权盈亏（每笔平均 %，胜率，t 值）"]
    for row in s.get("rules", []):
        L.append(row["rule"])
        for label, v in row["periods"].items():
            L.append(f"   {label}: n={v['n']}" + (f" 平均 {fmt(v['avg_pnl_pct'], 1, '%')} 胜率 {v['win_rate']}% t {fmt(v['t'], 1)}" if "avg_pnl_pct" in v else ""))
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=float, default=3)
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    hist = load_history(args.cache)
    panel = build_panel(hist, args.years)
    s = summarize(panel)
    s["rules"] = rule_table(panel, hist)
    s["assumptions"] = "平值期权、30 天到期、隐含波动率=20日实际波动率×1.1、来回成本 4%、按收盘价进出；32 只大盘股；非真实期权成交价。"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(s, ensure_ascii=False, indent=1) + "\n")
    print(report(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
