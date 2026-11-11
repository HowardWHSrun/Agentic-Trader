"""Leverage test: does shorter DTE / OTM strike on the v2.2 signal raise payoff without killing edge?"""
import json, sys, math
from datetime import date
from pathlib import Path
sys.path.insert(0, "/home/user/Agentic-Trader/scripts")
import options_scorer as o
import options_backtest as bt
SP = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent  # dir with hist/ and dyn_sig.json
hist = {p.stem: json.loads(p.read_text()) for p in (SP / "hist").glob("*.json")}
sig = json.load(open(SP / "dyn_sig.json"))

def trade(r, dte, otm, stop, tp, days=5):
    bars = hist[r["sym"]]; i = r["i"]
    s0 = bars[i]["c"]; K = s0 * (1 + otm)
    vol = max(o.hist_vol([b["c"] for b in bars[i-25:i+1]]) or 0.2, 0.15) * 1.1
    # OTM skew: calls a bit cheaper vol; keep same (conservative for payoff? neutral)
    p0 = bt.bs_price(s0, K, dte/365, vol)
    if p0 < 0.05: return None
    # cost: half-spread both ways, at least 4% or $0.10 per share round trip
    cost = max(0.04, 0.10 / p0)
    d0 = date.fromisoformat(bars[i]["t"]); best = 0; pnl = 0
    for k in range(1, days+1):
        el = (date.fromisoformat(bars[i+k]["t"]) - d0).days
        v = bt.bs_price(bars[i+k]["c"], K, max(dte-el, 0)/365, vol)
        pnl = v/p0 - 1; best = max(best, pnl)
        if pnl <= stop or (tp and pnl >= tp): break
        if bars[i+k]["c"] > sum(b["c"] for b in bars[i+k-4:i+k+1])/5: break
    return (pnl - cost)*100, best

def acct(pnls, risk=0.03):
    eq = peak = 1.0; mdd = 0
    for p in pnls:
        eq += eq*risk*p/100; peak = max(peak, eq); mdd = min(mdd, eq/peak-1)
    return eq, mdd

print(f"{'设置':<26}{'笔数':>6}{'每笔均':>8}{'中位':>7}{'胜率':>6}{'≥2倍':>6}{'≥3倍':>6}{'≥5倍':>6}{'亏光%':>6}{'3%仓年化':>9}{'回撤':>7}  21-24/25-26")
yrs = 5
for dte in (7, 14, 21, 30, 45):
    for otm in (0, 0.03, 0.06, 0.10):
        for stop, tp in ((-0.5, 0.8), (-1.0, None)):
            rows = []
            for r in sig:
                t = trade(r, dte, otm, stop, tp)
                if t: rows.append((r["d"], *t))
            if not rows: continue
            p = [x[1] for x in rows]; n = len(p)
            ps = sorted(p)
            a = [x[1] for x in rows if x[0] < "2025"]; b = [x[1] for x in rows if x[0] >= "2025"]
            eq, mdd = acct([x[1] for x in sorted(rows)])
            lab = f"{dte}天 {'平值' if otm==0 else f'价外{int(otm*100)}%'} {'止损50/止盈80' if tp else '不设止盈止损'}"
            print(f"{lab:<26}{n:>6}{sum(p)/n:>7.1f}%{ps[n//2]:>6.0f}%{sum(x>0 for x in p)/n*100:>5.0f}%"
                  f"{sum(x>=100 for x in p)/n*100:>5.1f}%{sum(x>=200 for x in p)/n*100:>5.1f}%{sum(x>=400 for x in p)/n*100:>5.1f}%"
                  f"{sum(x<=-90 for x in p)/n*100:>5.0f}%{(eq**(1/yrs)-1)*100:>8.0f}%{mdd*100:>6.0f}%  {sum(a)/len(a):+.1f}/{sum(b)/len(b):+.1f}")
