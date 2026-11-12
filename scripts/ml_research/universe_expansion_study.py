"""Does the v2.5 dip rule work on stocks it was never tuned on? (2026-11-12, no rule change)

57 liquid large caps outside the 32-stock list, Cboe daily bars 2005-2026, same signal, same filters, same
contract (first Friday >= 14 days, delta 0.75), same exits, same estimated option prices as the main research.
Market breadth ("broad") counts only signals from the original 32 so it does not depend on list size.

Result (accepted signals, mean option return per trade, base / stress / stress+crush):
    original 32   n1391   +5.7% / -0.5% / -4.4%     stock to exit +1.0%
    new 57        n2840   -1.1% / -6.3% / -10.4%    stock to exit +0.5%
    difference 6.8 points, day-block bootstrap 95% CI [3.6, 9.9]
    new 57, ML top tercile   +4.3% / -1.8% / -5.6%  (original 32: +22.1% / +13.6% / +10.1%, partly in-sample)
    new 57, deep star        +6.9% / +0.1% / -3.6%  (original 32: +25.5% / +16.2% / +12.9%)
    new 57 by period (base): 2005-14 -1.7%, 2015-20 +2.1%, 2021-26 -2.7%
Only 19 of the 57 had a contract passing the live liquidity filter (spread <= 10%, OI >= 100) on the test day
(21 of the original 32 did); those 19: -1.7% / -6.4% / -10.5%.

Conclusion: the list is not expanded. The rebound after a dip exists on new names but is about half as large,
which does not cover option costs. Part of the edge measured on the 32 is hindsight in how the list was chosen
and in tuning the rule on it; expect live results below the 32-stock backtest.

Usage: put the candidates' bars in <SP>/expand/hist/<SYM>.json (CboeClient._get("charts/historical/SYM.json")),
then run this file. Needs pandas, numpy and the harness layout described in README.md.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SP = "/tmp/claude-0/-home-user-Agentic-Trader/011b42d0-55e9-5744-b666-b48b04f949c7/scratchpad"
sys.path.insert(0, SP)
import harness as H  # noqa: E402

CAND = {
    "XLK": ["AMD", "ORCL", "ADBE", "QCOM", "MU", "TXN", "CSCO", "IBM", "NOW", "INTU", "AMAT", "PLTR", "INTC"],
    "XLC": ["NFLX", "DIS", "TMUS", "VZ", "T"], "XLY": ["MCD", "NKE", "SBUX", "LOW", "BKNG", "TJX"],
    "XLP": ["PEP", "PM", "MDLZ", "CL"], "XLV": ["JNJ", "MRK", "ABT", "TMO", "PFE", "AMGN", "ISRG"],
    "XLF": ["GS", "MS", "WFC", "MA", "AXP", "C", "BLK", "SCHW"], "XLE": ["COP", "SLB", "EOG"],
    "XLI": ["BA", "HON", "UNP", "LMT", "UPS", "UBER"], "XLU": ["SO"], "XLB": ["NEM", "SHW"],
    "XLRE": ["AMT", "EQIX"],
}
NEWSEC = {s: e for e, syms in CAND.items() for s in syms}
OLD = set(H.o.UNIVERSE)

if __name__ == "__main__":
    for p in Path(SP + "/expand/hist").glob("*.json"):
        H.HIST[p.stem] = [dict(b, t=b["t"][:10]) for b in json.loads(p.read_text())]
    H.o.UNIVERSE = list(H.o.UNIVERSE) + list(NEWSEC)
    H.o.SECTOR = {**H.o.SECTOR, **NEWSEC}
    out = SP + "/expand/sig_all.pkl"
    src = (Path(__file__).parent / "build_dip_signals.py").read_text()
    src = src.replace('SP + "/ml/A/sig.pkl"', repr(out)).replace("import harness as H\n", "")
    exec(compile(src, "build_dip_signals", "exec"), {"H": H, "__name__": "__main__"})

    df = pd.read_pickle(out)
    df["new"] = ~df.sym.isin(OLD)
    oldcnt = df[~df.new].groupby("d").size()
    df["n_sig_day"] = df.d.map(oldcnt).fillna(0).astype(int) + df.new.astype(int)
    df["broad"] = (df.spy_r5 < -2) | (df.spy_d50 < 0) | (df.n_sig_day >= 2)

    def tier(r):
        lag = r.vs_sector
        if r.hv20 < 20 or (not np.isnan(lag) and not r.broad and lag <= -2):
            return 0.0
        if not np.isnan(lag):
            return 0.5 if (r.broad and lag <= -5) else 1.0 if lag > -2 else (1.0 if r.broad else 0.5)
        return 1.0 if r.broad else 0.5

    df["tier"] = df.apply(tier, axis=1)
    acc = df[df.tier > 0]
    for lab, a in (("original 32", acc[~acc.new]), ("new 57", acc[acc.new])):
        row = f"{lab:12} n{len(a):5}"
        for scn in ("y_base", "y_stress", "y_stress+crush"):
            x = a[scn].dropna()
            t = x.mean() / (x.std() / math.sqrt(a.d.loc[x.index].nunique()))
            row += f" | {x.mean():+5.1f}% win {100 * (x > 0).mean():.0f}% t {t:+.1f}"
        print(row, f"| stock to exit {a.y_stock_exit.mean():+.2f}%")
