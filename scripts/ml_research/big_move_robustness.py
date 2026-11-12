import pandas as pd, numpy as np, math
import bm
from convex import acc, run, fri, v25_exit, trade, stats
print("drop_atr 分位:", acc.drop_atr.quantile([.25, .5, .75]).round(2).tolist(), " 2010-17 中位", round(acc[acc.d < "2018"].drop_atr.median(), 2))
star = acc[(acc.broad) & (acc.vs_sector > -2)]
for th in (-2.0, -2.5, -3.0, -3.5, -4.0):
    sub = star[star.drop_atr <= th]; days = sub.d.nunique()
    for nm, legs, mind in (("现行Δ0.75 2-3周", [(1, .75)], 14), ("1周 Δ0.75", [(1, .75)], 5), ("1周 平值", [(1, .5)], 5)):
        b = stats(run(sub, legs, mind, "base")); s = stats(run(sub, legs, mind, "stress")); c = stats(run(sub, legs, mind, "crush"))
        if not b: continue
        per = " ".join(f"{lab}:{(stats([(d, r) for d, r in run(sub, legs, mind, 'base') if f(d)]) or {'mean': float('nan')})['mean']:+.0f}" for lab, f in bm.PER)
        print(f"⭐ 且连跌幅度 ≥{-th} ATR  {nm:<14} n{b['n']:4d}（{days}天） 每笔{b['mean']:+6.1f}% 胜{b['win']:3.0f}% t{b['t']:+.1f} 翻倍{b['dbl']:4.1f}% 3倍{b['tri']:4.1f}% 亏半{b['half']:3.0f}% [{per}] 压力{s['mean']:+5.1f} IV回落{c['mean']:+5.1f}")
sub = star[star.drop_atr <= -3.0]
print("\n按年（⭐ 且 ≥3 ATR，现行合约 / 1周平值）：")
for y, g in sub.groupby(sub.d.str[:4]):
    a = run(g, [(1, .75)], 14, "base"); b = run(g, [(1, .5)], 5, "base")
    print(f"  {y} n{len(a):3d}（{g.d.nunique()}天） {np.mean([r for _, r in a])*100:+6.1f}%  /  {np.mean([r for _, r in b])*100:+6.1f}%")
# not-star but deep, and star but shallow, to see which condition matters
for lab, g in (("非⭐ 但 ≥3 ATR", acc[~((acc.broad) & (acc.vs_sector > -2)) & (acc.drop_atr <= -3)]), ("⭐ 但 <3 ATR", star[star.drop_atr > -3])):
    b = stats(run(g, [(1, .75)], 14, "base")); s = stats(run(g, [(1, .75)], 14, "stress"))
    print(f"{lab}: n{b['n']} 每笔{b['mean']:+.1f}% 胜{b['win']:.0f}% 压力{s['mean']:+.1f}%")
# one per day cap (deepest), to mimic real capacity
one = sub.sort_values("drop_atr").groupby("d").head(2)
for nm, legs, mind in (("现行", [(1, .75)], 14), ("1周平值", [(1, .5)], 5)):
    b = stats(run(one, legs, mind, "base")); print(f"每天最多 2 只（跌最深） {nm}: n{b['n']} 每笔{b['mean']:+.1f}% 胜{b['win']:.0f}% 翻倍{b['dbl']:.1f}%")
