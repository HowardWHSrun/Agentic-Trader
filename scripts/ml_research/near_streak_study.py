"""Relaxed dip (2026-11-13, no rule change): does "3 down days + 1 small up day" work like a strict 4-day streak?

Uptrend + HV20 >= 20%, same contract and exits as v2.5, 2005-2026, estimated option prices (base / stress).
    original 32, strict 4 lower closes           n1673  +3.7% / -2.0%   stock 5d +1.15%
    original 32, 3 down + 1 up day <= 0.5%       n1773  -4.1% / -9.0%   stock 5d +0.52%
    original 32, same during a market pullback   n697   -1.0% / -6.2%
    57 other large caps, 3 down + 1 up <= 0.5%   n3086  -2.3% / -7.1%
The up day's size does not matter (0.5-1%: -3.3%, >1%: -3.8%). Conclusion: an interrupted streak is not a signal.
Needs the candidates' bars in <SP>/expand/hist (see universe_expansion_study.py).
"""
import json, sys, math
from datetime import date, timedelta
from pathlib import Path
import numpy as np
SP = "/tmp/claude-0/-home-user-Agentic-Trader/011b42d0-55e9-5744-b666-b48b04f949c7/scratchpad"
sys.path.insert(0, SP); sys.path.insert(0, str(Path(__file__).parent))
import harness as H
from universe_expansion_study import NEWSEC
o = H.o
OLD = list(o.UNIVERSE)
for p in Path(SP + "/expand/hist").glob("*.json"):
    H.HIST[p.stem] = [dict(b, t=b["t"][:10]) for b in json.loads(p.read_text())]
SEC = {**o.SECTOR, **NEWSEC}
BAD = {"2018-11-22", "2025-05-26", "2007-07-04"}
def clean(bars):
    b = [x for x in bars if x["t"] not in BAD]; out = []
    for j, x in enumerate(b):
        if 0 < j < len(b) - 1:
            r1, r2 = x["c"] / b[j - 1]["c"], b[j + 1]["c"] / x["c"]
            if (r1 > 1.6 and r2 < 0.65) or (r1 < 0.6 and r2 > 1.55): continue
        out.append(x)
    return out
for s in list(H.HIST): H.HIST[s][:] = clean(H.HIST[s])
SPY = H.HIST["SPY"]; spy_i = {b["t"]: i for i, b in enumerate(SPY)}; spc = np.array([b["c"] for b in SPY])
idx = {s: {b["t"]: i for i, b in enumerate(H.HIST[s])} for s in H.HIST}
def fri_dte(d, mind=14):
    d0 = date.fromisoformat(d); d1 = d0 + timedelta(days=mind)
    while d1.weekday() != 4: d1 += timedelta(days=1)
    return (d1 - d0).days
def pol(st):
    pr, k, b, m = st["pr"], st["k"], st["bar"], st["mem"]
    if "cat" not in m:
        bb = pr.bars[pr.i - 14:pr.i + 1]
        a = sum(max(x["h"] - x["l"], abs(x["h"] - y["c"]), abs(x["l"] - y["c"])) for y, x in zip(bb, bb[1:])) / 14
        m["cat"] = pr.bar(0)["l"] - 2.0 * a
    if pr.dte - (date.fromisoformat(b["t"]) - pr.d0).days <= 1: return [(1.0, "close", None)]
    if b["c"] < m["cat"]: return [(1.0, "close", None)]
    if b["c"] > sum(pr.closes(k, 5)) / 5 or k >= 5: return [(1.0, "close", None)]
    return []
rows = []
for sym in OLD + list(NEWSEC):
    bars = H.HIST[sym]
    if len(bars) < 300: continue
    c = np.array([b["c"] for b in bars]); sec = SEC.get(sym); sb = H.HIST.get(sec) if sec else None
    for i in range(260, len(bars) - 12):
        d = bars[i]["t"]
        if d < "2005-01-01" or d not in spy_i: continue
        s200, s50 = c[i - 199:i + 1].mean(), c[i - 49:i + 1].mean()
        if not (c[i] > s200 and s50 > s200): continue
        ch = c[i - 3:i + 1] / c[i - 4:i] - 1          # last 4 daily changes
        if ch[-1] >= 0: continue
        strict = bool((ch < 0).all())
        ups = ch[ch >= 0]
        near = (len(ups) == 1) and ups[0] <= 0.005 and c[i] < c[i - 4]
        near_any = (len(ups) == 1) and c[i] < c[i - 4]
        if not (strict or near_any): continue
        w = c[i - 260:i + 13]
        if np.any(np.abs(np.diff(np.log(w))) > math.log(1.35)): continue
        r = np.diff(np.log(c[i - 20:i + 1])); hv = float(np.std(r, ddof=1) * math.sqrt(252)) * 100
        if hv < 20: continue
        si = spy_i[d]; st_ret = c[i] / c[i - 4] - 1; lag = None
        if sb is not None:
            j0, j1 = idx[sec].get(bars[i - 4]["t"]), idx[sec].get(d)
            if j0 is not None and j1 is not None: lag = (st_ret - (sb[j1]["c"] / sb[j0]["c"] - 1)) * 100
        broad = (spc[si] / spc[si - 5] - 1) * 100 < -2 or spc[si] < spc[si - 49:si + 1].mean()
        a = o.atr(bars[i - 30:i + 1])
        out = {}
        for scn in ("base", "stress"):
            t = H.simulate({"sym": sym, "i": i, "d": d}, pol, fri_dte(d), 0.0, scn, 0.75)
            out[scn] = t["ret"] * 100 if t else np.nan
        rows.append(dict(d=d, sym=sym, new=sym in NEWSEC, strict=strict, near=near, upday=float(ups[0]) * 100 if len(ups) else np.nan,
                         lag=lag, broad=broad, drop_atr=(c[i] - c[i - 4]) / a, st_ret=st_ret * 100,
                         stock=(c[i + 5] / c[i] - 1) * 100, **out))
import pandas as pd
df = pd.DataFrame(rows); df.to_pickle(SP + "/expand/near.pkl")
def line(a, lab):
    if len(a) < 20: return f"{lab:44} n{len(a)}"
    s = f"{lab:44} n{len(a):5} {len(a)/21.8:4.0f}/yr"
    for scn in ("base", "stress"):
        x = a[scn].dropna(); nd = a.d.loc[x.index].nunique()
        s += f" | {x.mean():+5.1f}% win{100*(x>0).mean():3.0f}% t{x.mean()/(x.std()/math.sqrt(nd)):+.1f}"
    return s + f" | stock5d {a.stock.mean():+.2f}%"
for g, f in (("OLD32", ~df.new), ("NEW57", df.new)):
    a = df[f]
    print(line(a[a.strict], g + " strict 4-day streak"))
    nn = a[~a.strict]
    print(line(nn[nn.near], g + " 3 down + 1 up day <=0.5%"))
    print(line(nn[(nn.upday > 0.5) & (nn.upday <= 1.0)], g + " 3 down + 1 up day 0.5-1%"))
    print(line(nn[nn.upday > 1.0], g + " 3 down + 1 up day >1%"))
    nr = nn[nn.near]
    print(line(nr[nr.drop_atr <= -1.5], g + " near & drop>=1.5ATR"))
    print(line(nr[(nr.lag.notna()) & (nr.lag <= -2)], g + " near & lags sector by >=2pts"))
    print(line(nr[(nr.lag.notna()) & (nr.lag > -2)], g + " near & with sector"))
    print(line(nr[nr.broad], g + " near & market pullback"))
    for lab, ff in (("2005-14", nr.d < "2015"), ("2015-20", (nr.d >= "2015") & (nr.d < "2021")), ("2021-26", nr.d >= "2021")):
        print(line(nr[ff], g + " near " + lab))
m = df[(df.sym == "MSFT")]
print(line(m[m.strict], "MSFT strict")); print(line(m[~m.strict & m.near], "MSFT near"))
