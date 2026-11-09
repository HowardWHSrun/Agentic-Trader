#!/usr/bin/env python3
"""End-of-day review: did high-score stocks rise and low-score stocks fall?

Reads the daily snapshots written by options_scorer.py
(docs/data/options/daily/<date>.json) and grades the scores against what
prices actually did:

  * same day  - first scan of the day -> latest price that day
  * 1 day     - day D's last scan -> day D+1's last scan
  * 5 days    - day D's last scan -> day D+5's last scan

For each horizon it compares the bullish group (score >= 70) with the bearish
group (score <= 30), in raw returns and versus SPY, plus the rank correlation
between score and return. It also totals the published signals' P&L.

A verdict on the method uses the rolling last 10 trading days (1-day horizon)
so one noisy day cannot trigger a rule change.

Usage: python3 scripts/options_review.py [--date YYYY-MM-DD] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPT = ROOT / "docs" / "data" / "options"
BULL, BEAR = 70, 30
ROLLING_DAYS = 10
MIN_DAYS_FOR_VERDICT = 10


def ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 5:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return None if va == 0 or vb == 0 else round(cov / (va * vb), 3)


def mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def grade(start: dict, end: dict) -> dict | None:
    """Score at `start` vs returns from start prices to end prices."""
    sp0, sp1 = start["prices"].get("SPY"), end["prices"].get("SPY")
    spy_ret = (sp1 / sp0 - 1) * 100 if sp0 and sp1 else None
    rows = []
    for sym, score in start["scores"].items():
        p0, p1 = start["prices"].get(sym), end["prices"].get(sym)
        if score is None or not p0 or not p1:
            continue
        r = (p1 / p0 - 1) * 100
        rows.append({"symbol": sym, "score": score, "ret": round(r, 2),
                     "excess": round(r - spy_ret, 2) if spy_ret is not None else None})
    if not rows:
        return None
    bull = [x for x in rows if x["score"] >= BULL]
    bear = [x for x in rows if x["score"] <= BEAR]

    def group(g: list[dict], want_up: bool) -> dict:
        right = [x for x in g if (x["ret"] > 0) == want_up and x["ret"] != 0]
        return {"n": len(g), "avg_ret": mean([x["ret"] for x in g]),
                "avg_excess": mean([x["excess"] for x in g if x["excess"] is not None]),
                "hit_rate": round(len(right) / len(g) * 100, 1) if g else None,
                "best": max(g, key=lambda x: x["ret"] if want_up else -x["ret"])["symbol"] if g else None,
                "worst": min(g, key=lambda x: x["ret"] if want_up else -x["ret"])["symbol"] if g else None}

    b, s = group(bull, True), group(bear, False)
    spread = round(b["avg_ret"] - s["avg_ret"], 3) if b["avg_ret"] is not None and s["avg_ret"] is not None else None
    return {"from": start["at"], "to": end["at"], "spy_ret": round(spy_ret, 2) if spy_ret is not None else None,
            "bull": b, "bear": s, "bull_minus_bear": spread,
            "rank_corr": spearman([x["score"] for x in rows], [x["ret"] for x in rows]),
            "rows": sorted(rows, key=lambda x: -x["score"])}


def load_days() -> list[dict]:
    d = OPT / "daily"
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.exists() else []


def signal_pnl() -> dict:
    state_p = OPT / "state.json"
    state = json.loads(state_p.read_text()) if state_p.exists() else {}
    closed = [s for s in state.get("closed", []) if s.get("pnl_pct") is not None]
    opened = state.get("open", [])
    wins = [s for s in closed if s["pnl_pct"] > 0]
    dollars = sum(s["pnl_pct"] / 100 * s["cost_per_contract"] for s in closed if "cost_per_contract" in s)
    return {"closed": len(closed), "wins": len(wins),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
            "avg_pnl_pct": mean([s["pnl_pct"] for s in closed]),
            "closed_pnl_usd_per_contract": round(dollars, 2),
            "open": [{"symbol": s["symbol"], "type": s["type"], "pnl_pct": s.get("pnl_pct"),
                      "entry_date": s["entry_date"]} for s in opened]}


def review(days: list[dict], date: str) -> dict:
    idx = next((i for i, d in enumerate(days) if d["date"] == date), None)
    if idx is None:
        raise SystemExit(f"No snapshot for {date}")
    today = days[idx]
    out = {"date": date, "rules_version": today["last"].get("rules_version"),
           "same_day": grade(today["first"], today["last"]),
           "one_day": grade(days[idx - 1]["last"], today["last"]) if idx >= 1 else None,
           "five_day": grade(days[idx - 5]["last"], today["last"]) if idx >= 5 else None}
    # Rolling 1-day results over the last N trading days.
    hist = [grade(days[i - 1]["last"], days[i]["last"]) for i in range(max(1, idx - ROLLING_DAYS + 1), idx + 1)]
    hist = [h for h in hist if h]
    spreads = [h["bull_minus_bear"] for h in hist if h["bull_minus_bear"] is not None]
    corrs = [h["rank_corr"] for h in hist if h["rank_corr"] is not None]
    roll = {"days": len(hist), "avg_bull_minus_bear": mean(spreads), "avg_rank_corr": mean(corrs),
            "days_bull_beat_bear": sum(1 for x in spreads if x > 0)}
    if len(hist) < MIN_DAYS_FOR_VERDICT:
        verdict, action = "样本不足", f"已有 {len(hist)}/{MIN_DAYS_FOR_VERDICT} 个交易日，暂不调整方法。"
    elif (roll["avg_rank_corr"] or 0) < 0 or (roll["avg_bull_minus_bear"] or 0) < 0:
        verdict, action = "表现差", "最近 10 个交易日高分组没有跑赢低分组，需要调整打分方法。"
    elif (roll["avg_rank_corr"] or 0) < 0.05:
        verdict, action = "效果不明显", "分数和涨跌关系很弱，继续观察，考虑小幅调整权重。"
    else:
        verdict, action = "有效", "高分组持续跑赢低分组，保持当前方法。"
    out.update(rolling=roll, verdict=verdict, action=action, signals=signal_pnl())
    return out


def fmt(x, suffix="%"):
    return "—" if x is None else f"{x:+.2f}{suffix}"


def report(r: dict) -> str:
    lines = [f"# 收盘复盘 {r['date']}（规则 {r['rules_version']}）", ""]
    for key, name in (("same_day", "今天（早盘分数 → 收盘）"), ("one_day", "1 天（昨天分数 → 今天）"), ("five_day", "5 天")):
        g = r[key]
        if not g:
            lines.append(f"**{name}**：数据还不够。")
            continue
        b, s = g["bull"], g["bear"]
        lines.append(f"**{name}**　SPY {fmt(g['spy_ret'])}")
        lines.append(f"- 看涨组（≥{BULL}分，{b['n']} 只）：平均 {fmt(b['avg_ret'])}，比 SPY {fmt(b['avg_excess'])}，"
                     f"{b['hit_rate'] if b['hit_rate'] is not None else '—'}% 真的涨了。最好 {b['best'] or '—'}，最差 {b['worst'] or '—'}")
        lines.append(f"- 看跌组（≤{BEAR}分，{s['n']} 只）：平均 {fmt(s['avg_ret'])}，比 SPY {fmt(s['avg_excess'])}，"
                     f"{s['hit_rate'] if s['hit_rate'] is not None else '—'}% 真的跌了。最准 {s['best'] or '—'}，最不准 {s['worst'] or '—'}")
        lines.append(f"- 看涨组 − 看跌组：{fmt(g['bull_minus_bear'])}；分数与涨跌相关性 {g['rank_corr'] if g['rank_corr'] is not None else '—'}")
        lines.append("")
    ro = r["rolling"]
    lines.append(f"**最近 {ro['days']} 个交易日**：看涨组平均每天领先看跌组 {fmt(ro['avg_bull_minus_bear'])}，"
                 f"{ro['days_bull_beat_bear']} 天领先，平均相关性 {ro['avg_rank_corr'] if ro['avg_rank_corr'] is not None else '—'}")
    lines.append(f"**结论：{r['verdict']}**。{r['action']}")
    sg = r["signals"]
    lines += ["", f"**信号战绩**：已平仓 {sg['closed']} 笔，赢 {sg['wins']} 笔"
              + (f"（胜率 {sg['win_rate']}%，平均 {fmt(sg['avg_pnl_pct'])}，合计每张约 ${sg['closed_pnl_usd_per_contract']:+.0f}）" if sg["closed"] else "")]
    for o in sg["open"]:
        lines.append(f"- 持有中 {o['symbol']} {'Call' if o['type'] == 'call' else 'Put'}（{o['entry_date']} 进场）：{fmt(o['pnl_pct'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="CT date to review (default: latest snapshot)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    days = load_days()
    if not days:
        print("还没有每日快照，扫描程序运行一天后再复盘。", file=sys.stderr)
        return 2
    r = review(days, args.date or days[-1]["date"])
    if not args.dry_run:
        out = OPT / "review"
        out.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(r, ensure_ascii=False, indent=1) + "\n"
        (out / f"{r['date']}.json").write_text(payload)
        (out / "latest.json").write_text(payload)
    print(report(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
