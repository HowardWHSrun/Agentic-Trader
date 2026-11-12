"""Track A step 1: rebuild dip signals 2005..2026 from HIST (cleaned in memory), compute features available at
the signal close, the v2.5 rule decision, and labels (v2.5 option return in 3 scenarios via harness.simulate,
plus stock outcome labels). Output: ml/A/sig.pkl (pandas DataFrame)."""
import math, sys, pickle
from datetime import date, timedelta
import numpy as np, pandas as pd
SP = "/tmp/claude-0/-home-user-Agentic-Trader/011b42d0-55e9-5744-b666-b48b04f949c7/scratchpad"
sys.path.insert(0, SP)
import harness as H
o = H.o

# ---------- in-memory cleaning (files untouched) ----------
BAD_DATES = {"2018-11-22", "2025-05-26", "2007-07-04"}   # market holidays carrying fake bars
def clean(bars):
    b = [x for x in bars if x["t"] not in BAD_DATES]
    out = []
    for j, x in enumerate(b):  # spike-and-revert glitches
        if 0 < j < len(b) - 1:
            r1, r2 = x["c"] / b[j - 1]["c"], b[j + 1]["c"] / x["c"]
            if (r1 > 1.6 and r2 < 0.65) or (r1 < 0.6 and r2 > 1.55):
                continue
        out.append(x)
    return out
for s in list(H.HIST):
    H.HIST[s][:] = clean(H.HIST[s])

SPY = H.HIST["SPY"]; spy_i = {b["t"]: i for i, b in enumerate(SPY)}
spc = np.array([b["c"] for b in SPY])

def sma(c, n): return float(np.mean(c[-n:]))
def streak(c, cap=10):
    n = 0
    while n < cap and len(c) > n + 1 and c[-1 - n] < c[-2 - n]: n += 1
    return n
def hv(c, n=20):
    r = np.diff(np.log(c[-n - 1:]));  return float(np.std(r, ddof=1) * math.sqrt(252))
def rsi(c, n):
    return o.rsi(list(c[-(n * 6 + 1):]), n)
def atr14(bars, i):
    return o.atr(bars[i - 30:i + 1])

def fri_dte(d, mind=14):
    d0 = date.fromisoformat(d); d1 = d0 + timedelta(days=mind)
    while d1.weekday() != 4: d1 += timedelta(days=1)
    return (d1 - d0).days

def v25_policy(st):
    pr, k, b, m = st["pr"], st["k"], st["bar"], st["mem"]
    if "cat" not in m:
        bb = pr.bars[pr.i - 14:pr.i + 1]
        a = sum(max(x["h"] - x["l"], abs(x["h"] - y["c"]), abs(x["l"] - y["c"])) for y, x in zip(bb, bb[1:])) / 14
        m["cat"] = pr.bar(0)["l"] - 2.0 * a
    if pr.dte - (date.fromisoformat(b["t"]) - pr.d0).days <= 1:
        return [(1.0, "close", None)]
    if b["c"] < m["cat"]:
        return [(1.0, "close", None)]
    if b["c"] > sum(pr.closes(k, 5)) / 5 or k >= 5:
        return [(1.0, "close", None)]
    return []

idx = {s: {b["t"]: i for i, b in enumerate(H.HIST[s])} for s in H.HIST}
rows = []
dates = [b["t"] for b in SPY if b["t"] >= "2005-01-01"]
for sym in o.UNIVERSE:
    bars = H.HIST[sym]
    if len(bars) < 300: continue
    c_all = np.array([b["c"] for b in bars]); v_all = np.array([b["v"] for b in bars], float)
    sec = o.SECTOR[sym]; sbars = H.HIST.get(sec) if sec else None
    for i in range(260, len(bars) - 12):
        d = bars[i]["t"]
        if d < "2005-01-01" or d not in spy_i: continue
        c = c_all[:i + 1]
        s200, s50 = sma(c, 200), sma(c, 50)
        if not (c[-1] > s200 and s50 > s200): continue
        n = streak(c)
        if n < 4: continue
        # split / glitch guard: any |1d move| > 35% in the feature or label window -> drop
        w = c_all[i - 260:i + 13]
        if np.any(np.abs(np.diff(np.log(w))) > math.log(1.35)): continue
        si = spy_i[d]; s = spc[:si + 1]
        a = atr14(bars, i); px = c[-1]
        st_ret = px / c[-1 - n] - 1
        day_rets = c[-n:] / c[-n - 1:-1] - 1
        gaps = [bars[j]["o"] / bars[j - 1]["c"] - 1 for j in range(i - n + 1, i + 1)]
        sec_ret = None
        if sbars is not None:
            j0, j1 = idx[sec].get(bars[i - n]["t"]), idx[sec].get(d)
            if j0 is not None and j1 is not None:
                sec_ret = sbars[j1]["c"] / sbars[j0]["c"] - 1
        spy_ret_st = None
        j0 = spy_i.get(bars[i - n]["t"])
        if j0 is not None: spy_ret_st = spc[si] / spc[j0] - 1
        hv20 = hv(c, 20); hv60 = hv(c, 60)
        hi52 = max(b["h"] for b in bars[i - 251:i + 1])
        rng = bars[i]["h"] - bars[i]["l"]
        vol_streak = v_all[i - n + 1:i + 1].mean(); vol_base = v_all[i - n - 50:i - n + 1].mean()
        r = dict(d=d, sym=sym, i=i, sector=sec or "NONE", si=si,
                 streak=n, st_drop=st_ret * 100, drop_atr=(px - c[-1 - n]) / a,
                 max_day_atr=float(min(c[-n:] - c[-n - 1:-1])) / a,
                 day0_atr=(c[-1] - c[-2]) / a,
                 n_gapdn=sum(g < 0 for g in gaps), gap_sum=sum(min(g, 0) for g in gaps) * 100,
                 vs_sector=(st_ret - sec_ret) * 100 if sec_ret is not None else np.nan,
                 vs_spy=(st_ret - spy_ret_st) * 100 if spy_ret_st is not None else np.nan,
                 rsi2=rsi(c, 2), rsi14=rsi(c, 14),
                 d20_atr=(px - sma(c, 20)) / a, d50_atr=(px - s50) / a, d200_atr=(px - s200) / a,
                 s200_slope=(s200 / float(np.mean(c[-220:-20])) - 1) * 100,
                 s50_slope=(s50 / float(np.mean(c[-60:-10])) - 1) * 100,
                 hv20=hv20 * 100, hv_ratio=hv20 / hv60, atr_pct=a / px * 100,
                 vol_ratio=vol_streak / vol_base if vol_base > 0 else np.nan,
                 clv=(bars[i]["c"] - bars[i]["l"]) / rng if rng > 0 else 0.5,
                 r20=(px / c[-21] - 1) * 100, r60=(px / c[-61] - 1) * 100,
                 from_hi_atr=(hi52 - px) / a,
                 spy_r5=(s[-1] / s[-6] - 1) * 100, spy_r20=(s[-1] / s[-21] - 1) * 100,
                 spy_d50=(s[-1] / sma(s, 50) - 1) * 100, spy_d200=(s[-1] / sma(s, 200) - 1) * 100,
                 spy_hv20=hv(s, 20) * 100, spy_streak=streak(s),
                 dow=date.fromisoformat(d).weekday(), month=int(d[5:7]))
        rows.append(r)
df = pd.DataFrame(rows).sort_values(["d", "sym"]).reset_index(drop=True)
df["n_sig_day"] = df.groupby("d")["sym"].transform("count")
# ---------- v2.5 rule ----------
df["broad"] = (df.spy_r5 < -2) | (df.spy_d50 < 0) | (df.n_sig_day >= 2)
def tier(r):
    if r.hv20 < 20: return 0.0
    lag = r.vs_sector
    if not np.isnan(lag) and not r.broad and lag <= -2: return 0.0
    if not np.isnan(lag) and r.broad and lag <= -5: return 0.5
    if not np.isnan(lag) and lag > -2: return 1.0
    return 1.0 if r.broad else 0.5
df["tier"] = df.apply(tier, axis=1)
# ---------- labels ----------
for sc in ("base", "stress", "stress+crush"):
    out = []
    for r in df.itertuples():
        rr = {"sym": r.sym, "i": r.i, "d": r.d}
        t = H.simulate(rr, v25_policy, fri_dte(r.d), 0.0, sc, 0.75)
        out.append(t["ret"] * 100 if t else np.nan)
        if sc == "base": df.loc[r.Index, "days"] = t["days"] if t else np.nan
    df["y_" + sc] = out
ys, y5 = [], []
for r in df.itertuples():
    b = H.HIST[r.sym]; k = int(r.days) if not np.isnan(r.days) else 5
    ys.append((b[r.i + k]["c"] / b[r.i]["c"] - 1) * 100)
    y5.append((b[r.i + 5]["c"] / b[r.i]["c"] - 1) * 100)
df["y_stock_exit"] = ys; df["y_stock5"] = y5
df["y_win"] = (df.y_base > 0).astype(int)
# label window end (SPY index of exit day) for purging
df["lab_end_si"] = df.si + df.days.fillna(5).astype(int)
df.to_pickle(SP + "/ml/A/sig.pkl")
print(len(df), "signals", df.d.min(), df.d.max())
print(df.groupby(df.d.str[:4]).agg(n=("sym", "size"), v25=("tier", lambda x: (x > 0).sum()), yb=("y_base", "mean")).T.to_string())
# match against harness SIG 917
orig = {(r["d"], r["sym"]) for r in H.SIG}
mine = {(r.d, r.sym) for r in df.itertuples() if r.d >= min(x[0] for x in orig) and r.d <= max(x[0] for x in orig)}
print("orig", len(orig), "mine in range", len(mine), "overlap", len(orig & mine), "range", min(x[0] for x in orig), max(x[0] for x in orig))
