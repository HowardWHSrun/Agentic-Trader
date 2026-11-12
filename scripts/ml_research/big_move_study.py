"""Big-move strategies: can long options catch large up/down moves? Events on 32 stocks, 2010-2026.
Options priced with Black-Scholes (IV = mult x HV), entry at the event-day close."""
import sys, math, json
from datetime import date
from collections import defaultdict
SP = "/tmp/claude-0/-home-user-Agentic-Trader/011b42d0-55e9-5744-b666-b48b04f949c7/scratchpad"
sys.path.insert(0, SP)
import harness as H
o = H.o
BAD = {"2018-11-22", "2025-05-26", "2007-07-04"}
def clean(bars):
    b = [x for x in bars if x["t"] not in BAD]; out = []
    for j, x in enumerate(b):
        if 0 < j < len(b) - 1:
            r1, r2 = x["c"] / b[j-1]["c"], b[j+1]["c"] / x["c"]
            if (r1 > 1.6 and r2 < 0.65) or (r1 < 0.6 and r2 > 1.55): continue
        out.append(x)
    return out
HIST = {s: clean(v) for s, v in H.HIST.items()}
N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs(S, K, T, sig, call=True, r=0.04):
    if T <= 1e-6: return max(S - K, 0) if call else max(K - S, 0)
    v = sig * math.sqrt(T); d1 = (math.log(S / K) + (r + sig * sig / 2) * T) / v
    c = S * N(d1) - K * math.exp(-r * T) * N(d1 - v)
    return c if call else c - S + K * math.exp(-r * T)
def strike_for_delta(S, T, sig, delta, call=True):
    lo, hi = S * 0.5, S * 1.5
    for _ in range(50):
        K = (lo + hi) / 2; v = sig * math.sqrt(T)
        d = N((math.log(S / K) + (0.04 + sig * sig / 2) * T) / v)
        d = d if call else 1 - d
        if call: lo, hi = (K, hi) if d > delta else (lo, K)
        else: lo, hi = (lo, K) if d > delta else (K, hi)
    return (lo + hi) / 2
def hv(c, n):
    r = [math.log(c[k] / c[k-1]) for k in range(len(c) - n, len(c))]; m = sum(r) / n
    return math.sqrt(sum((x - m) ** 2 for x in r) / (n - 1)) * math.sqrt(252)
SC = {"base": (1.1, 0.04, 1.0), "stress": (1.3, 0.08, 1.0), "crush": (1.3, 0.08, 0.80)}
def trade(sym, i, legs, dte, hold, sc="base", ivref="hv20", tp=None, exit_fn=None):
    """legs: list of (call?, delta). Returns net return on total premium."""
    bars = HIST[sym]
    if i + hold >= len(bars): return None
    c = [b["c"] for b in bars[i-65:i+1]]; S0 = c[-1]
    ivm, cost, crush = SC[sc]
    h = max(hv(c, 20), hv(c, 60)) if ivref == "max" else hv(c, 20)
    sig = max(h, 0.15) * ivm; T0 = dte / 365
    Ks = [(cl, strike_for_delta(S0, T0, sig, d, cl)) for cl, d in legs]
    p0 = sum(bs(S0, K, T0, sig, cl) for cl, K in Ks)
    if p0 < 0.10: return None
    cst = max(cost, 0.10 * len(legs) / p0)
    d0 = date.fromisoformat(bars[i]["t"]); v = 1.0
    for k in range(1, hold + 1):
        b = bars[i + k]; el = (date.fromisoformat(b["t"]) - d0).days
        v = sum(bs(b["c"], K, max(dte - el, 0) / 365, sig * crush, cl) for cl, K in Ks) / p0
        if tp and v - 1 >= tp: break
        if exit_fn and exit_fn(bars, i, k): break
    return v - 1 - cst
def stats(rows):
    x = [r for _, r in rows]; n = len(x)
    if n < 15: return None
    m = sum(x) / n; sd = (sum((v - m) ** 2 for v in x) / (n - 1)) ** .5; nd = len({d for d, _ in rows}); xs = sorted(x)
    return dict(n=n, mean=m * 100, med=xs[n // 2] * 100, win=sum(v > 0 for v in x) / n * 100, t=m / sd * math.sqrt(nd) if sd else 0,
                dbl=sum(v >= 1 for v in x) / n * 100, tri=sum(v >= 2 for v in x) / n * 100, half=sum(v <= -.5 for v in x) / n * 100)
PER = (("10-17", lambda d: d < "2018"), ("18-21", lambda d: "2018" <= d < "2022"), ("22-26", lambda d: d >= "2022"))
def show(name, events, legs, dte, hold, **kw):
    line = f"{name:<46}"
    for sc in ("base", "stress", "crush"):
        rows = [(d, r) for s, i, d in events if (r := trade(s, i, legs, dte, hold, sc, **kw)) is not None]
        st = stats(rows)
        if not st: print(line, "n<15"); return
        if sc == "base":
            per = " ".join(f"{lab}:{(stats(pr) or {}).get('mean', float('nan')):+.0f}" for lab, f in PER if (pr := [(d, r) for d, r in rows if f(d)]) is not None)
            line += f"n{st['n']:5d} 每笔{st['mean']:+6.1f}% 中位{st['med']:+4.0f} 胜{st['win']:3.0f}% t{st['t']:+5.1f} 翻倍{st['dbl']:4.1f}% 3倍{st['tri']:4.1f}% 亏半{st['half']:3.0f}% [{per}]"
        else: line += f" | {sc}{st['mean']:+6.1f}%"
    print(line, flush=True)
# ---------- build events ----------
EV = defaultdict(list)
SPYI = {b["t"]: i for i, b in enumerate(HIST["SPY"])}
for sym in o.UNIVERSE:
    bars = HIST[sym]; c = [b["c"] for b in bars]; v = [b.get("v") or 0 for b in bars]
    sec = HIST.get(o.SECTOR.get(sym) or ""); seci = {b["t"]: k for k, b in enumerate(sec)} if sec else {}
    last = defaultdict(lambda: -99)
    bbw = [None] * len(bars)
    for i in range(20, len(bars)):
        w = c[i-19:i+1]; m = sum(w) / 20; sd = (sum((x - m) ** 2 for x in w) / 20) ** .5; bbw[i] = 4 * sd / m
    for i in range(260, len(bars) - 12):
        d = bars[i]["t"]
        if d < "2010-01-01": continue
        if max(abs(math.log(c[k] / c[k-1])) for k in range(i - 60, i + 12)) > math.log(1.45): continue  # split glitches
        px, prev = c[i], c[i-1]; r1 = px / prev - 1; gap = bars[i]["o"] / prev - 1
        s200 = sum(c[i-199:i+1]) / 200; s50 = sum(c[i-49:i+1]) / 50; up = px > s200 and s50 > s200
        vr = v[i] / (sum(v[i-50:i]) / 50) if sum(v[i-50:i]) else 0
        secr = None
        if d in seci and seci[d] > 0: secr = sec[seci[d]]["c"] / sec[seci[d]-1]["c"] - 1
        def add(name, gapdays=10):
            if i - last[name] >= gapdays: EV[name].append((sym, i, d)); last[name] = i
        if i % 7 == hash(sym) % 7: EV["random"].append((sym, i, d))
        if bbw[i] and bbw[i] <= min(x for x in bbw[i-125:i+1] if x) and hv(c[:i+1], 10) / hv(c[:i+1], 60) < 0.6: add("squeeze")
        if gap >= 0.04 and r1 >= 0.04 and vr >= 1.5: add("gapup_up" if px > s200 else "gapup_dn")
        if gap <= -0.04 and r1 <= -0.04 and vr >= 1.5: add("gapdn_up" if px > s200 else "gapdn_dn")
        if r1 <= -0.07:
            add("shockdn"); add("shockdn_up" if prev > s200 else "shockdn_dn")
            if secr is not None: add("shockdn_alone" if secr > -0.02 else "shockdn_mkt")
        if r1 >= 0.07: add("shockup"); add("shockup_up" if px > s200 else "shockup_dn")
        if px >= max(b["h"] for b in bars[i-251:i]) and vr >= 1.5 and up: add("breakout")
        if px <= min(b["l"] for b in bars[i-251:i]) and vr >= 1.5: add("breakdown")
print({k: len(v) for k, v in EV.items()})
C, P = (True, 0.5), (False, 0.5)
if __name__ == "__main__":
    print("\n== 0. 基准：随便哪天买（看模型本身偏不偏）")
    show("随机日 平值Call 30天 持5日", EV["random"], [C], 30, 5)
    show("随机日 平值Put 30天 持5日", EV["random"], [P], 30, 5)
    show("随机日 跨式(Call+Put) 30天 持10日", EV["random"], [C, P], 30, 10)
    print("\n== 1. 波动收缩后买跨式（不猜方向，赌大波动）")
    for dte, hold in ((30, 10), (45, 10), (21, 5)):
        show(f"收缩 跨式 {dte}天 持{hold}日 (IV=HV20)", EV["squeeze"], [C, P], dte, hold)
        show(f"收缩 跨式 {dte}天 持{hold}日 (IV=max(HV20,HV60))", EV["squeeze"], [C, P], dte, hold, ivref="max")
    print("\n== 2. 单日暴跌 ≥7% 之后（英伟达这类）")
    for nm, lab in (("shockdn", "全部"), ("shockdn_up", "原在200日线上"), ("shockdn_dn", "原在200日线下"), ("shockdn_alone", "板块没跌(公司自己)"), ("shockdn_mkt", "板块也跌")):
        for legs, ln in (([(True, 0.6)], "买Call抄底"), ([(False, 0.6)], "买Put追跌"), ([C, P], "跨式")):
            show(f"暴跌·{lab} {ln} 30天 持5日", EV[nm], legs, 30, 5)
    print("\n== 3. 单日暴涨 ≥7% 之后追涨")
    for nm, lab in (("shockup", "全部"), ("shockup_up", "200日线上"), ("shockup_dn", "200日线下")):
        show(f"暴涨·{lab} 买Call 30天 持5日", EV[nm], [(True, 0.6)], 30, 5)
        show(f"暴涨·{lab} 买Call 30天 持10日", EV[nm], [(True, 0.6)], 30, 10)
    print("\n== 4. 放量跳空（财报类）后顺势")
    show("跳空高开≥4% 200日线上 买Call 45天 持10日", EV["gapup_up"], [(True, 0.6)], 45, 10)
    show("跳空高开≥4% 200日线上 买Call 30天 持5日", EV["gapup_up"], [(True, 0.6)], 30, 5)
    show("跳空高开≥4% 200日线下 买Call 30天 持5日", EV["gapup_dn"], [(True, 0.6)], 30, 5)
    show("跳空低开≥4% 200日线下 买Put 30天 持5日", EV["gapdn_dn"], [(False, 0.6)], 30, 5)
    show("跳空低开≥4% 200日线下 买Put 45天 持10日", EV["gapdn_dn"], [(False, 0.6)], 45, 10)
    show("跳空低开≥4% 200日线上 买Call抄底 30天 持5日", EV["gapdn_up"], [(True, 0.6)], 30, 5)
    print("\n== 5. 放量创 52 周新高/新低")
    show("新高突破 买Call 45天 持10日", EV["breakout"], [(True, 0.6)], 45, 10)
    show("新高突破 买价外Call(Δ0.3) 30天 持10日", EV["breakout"], [(True, 0.3)], 30, 10)
    show("新低破位 买Put 45天 持10日", EV["breakdown"], [(False, 0.6)], 45, 10)
