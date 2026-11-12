import sys, pandas as pd, numpy as np
from datetime import date, timedelta
import bm
from bm import HIST, trade, stats, o
df = pd.read_pickle("../../ml/A/sig.pkl")
acc = df[(df.tier > 0) & (df.d >= "2010-01-01")]
def fri(d, mind):
    d0 = date.fromisoformat(d); d1 = d0 + timedelta(days=mind)
    while d1.weekday() != 4: d1 += timedelta(days=1)
    return (d1 - d0).days
def v25_exit(bars, i, k):
    a = o.atr(bars[i-30:i+1]); c = bars[i+k]["c"]
    return c > sum(b["c"] for b in bars[i+k-4:i+k+1]) / 5 or c < bars[i]["l"] - 2 * a
def run(sub, legs_w, mind, sc):
    out = []
    for r in sub.itertuples():
        tot = 0; ok = True
        for w, delta in legs_w:
            t = trade(r.sym, r.i, [(True, delta)], fri(r.d, mind), 5, sc, exit_fn=v25_exit)
            if t is None: ok = False; break
            tot += w * t
        if ok: out.append((r.d, tot))
    return out
def line(name, sub, legs_w, mind):
    s = stats(run(sub, legs_w, mind, "base"))
    if not s: print(name, "n<15"); return
    per = " ".join(f"{lab}:{(stats([(d, r) for d, r in run(sub, legs_w, mind, 'base') if f(d)]) or {}).get('mean', float('nan')):+.0f}" for lab, f in bm.PER)
    st = stats(run(sub, legs_w, mind, "stress"))["mean"]; cr = stats(run(sub, legs_w, mind, "crush"))["mean"]
    print(f"{name:<44} n{s['n']:4d} 每笔{s['mean']:+6.1f}% 中位{s['med']:+4.0f} 胜{s['win']:3.0f}% 翻倍{s['dbl']:4.1f}% 3倍{s['tri']:4.1f}% 亏半{s['half']:3.0f}% [{per}] | 压力{st:+5.1f}% | IV回落{cr:+5.1f}%", flush=True)
star = acc[(acc.broad) & (acc.vs_sector > -2)]
deep = acc[acc.drop_atr <= acc.drop_atr.quantile(1/3)]
stardeep = star[star.drop_atr <= acc.drop_atr.quantile(1/2)]
for lab, sub in (("全部通过过滤的回调信号", acc), ("⭐ 大盘回调+跟板块跌", star), ("跌得最深的 1/3", deep), ("⭐ 且跌得较深", stardeep)):
    print(f"\n== {lab}")
    line("现行：2-3周 Δ0.75", sub, [(1, 0.75)], 14)
    line("1周 Δ0.75", sub, [(1, 0.75)], 5)
    line("2-3周 平值 Δ0.50", sub, [(1, 0.50)], 14)
    line("1周 平值 Δ0.50", sub, [(1, 0.50)], 5)
    line("2-3周 价外 Δ0.30", sub, [(1, 0.30)], 14)
    line("1周 价外 Δ0.30（彩票）", sub, [(1, 0.30)], 5)
    line("组合：80% 现行 + 20% 1周价外Δ0.30", sub, [(0.8, 0.75)], 14) if False else None
    # barbell computed manually
    a = dict(run(sub.assign(d=sub.d + "|" + sub.sym), [(1, 0.75)], 14, "base")) if False else None
for lab, sub in (("全部", acc), ("⭐", star)):
    for sc in ("base", "stress", "crush"):
        rows = []
        for r in sub.itertuples():
            t1 = trade(r.sym, r.i, [(True, 0.75)], fri(r.d, 14), 5, sc, exit_fn=v25_exit)
            t2 = trade(r.sym, r.i, [(True, 0.30)], fri(r.d, 5), 5, sc, exit_fn=v25_exit)
            if t1 is not None and t2 is not None: rows.append((r.d, 0.8 * t1 + 0.2 * t2))
        s = stats(rows); print(f"组合 80% 现行 + 20% 1周价外Δ0.30 · {lab} [{sc}] n{s['n']} 每笔{s['mean']:+.1f}% 胜{s['win']:.0f}% 翻倍{s['dbl']:.1f}% 亏半{s['half']:.0f}%")
