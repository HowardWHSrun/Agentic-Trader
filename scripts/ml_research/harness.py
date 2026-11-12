"""Shared backtest harness for exit / expiration research on the v2.2 dip signal.

Signal: stock in long uptrend (close > SMA200 and SMA50 > SMA200) and >= 4 consecutive lower
closes; bought at that day's close (we confirm 14:30-15:05 CT, so close is a fair proxy).
920 signals, 47 symbols, 2021-10 .. 2026-11 (dyn_sig.json, bars in hist/).

Option prices are Black-Scholes estimates (no real historical option quotes are available):
    IV = iv_mult * max(HV20, 15%)      (default iv_mult 1.1)
Real options are often priced richer than that, so ALWAYS also report the stress scenarios.

Usage:
    from harness import SIG, Pricer, simulate, evaluate, report
    def policy(state): ...           # see simulate() docstring
    report("name", policy, dte=30, moneyness=0.0)

RULES FOR RESEARCHERS
- Choose parameters on IN-SAMPLE (dates < 2025-01-01) only; report OUT-OF-SAMPLE (>= 2025) separately.
- No look-ahead: on day k a policy may use bars up to and including day k. Intraday stops
  may trigger on day k's low (fill at the stop level, or at the open if the stock gapped through it).
  Close-based rules fill at day k's close.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "/home/user/Agentic-Trader/scripts")
import options_scorer as o  # noqa: E402

SP = Path(__file__).parent
HIST = {p.stem: json.loads(p.read_text()) for p in (SP / "hist").glob("*.json")}
SIG = [r for r in json.load(open(SP / "dyn_sig.json")) if r["i"] + 12 < len(HIST[r["sym"]])]
SPY = HIST["SPY"]
SPY_I = {b["t"]: i for i, b in enumerate(SPY)}
MAX_DAYS = 10  # simulate() never holds longer than this many sessions


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_call(S, K, T, sig, r=0.04):
    if T <= 1e-6:
        return max(S - K, 0.0)
    v = sig * math.sqrt(T)
    d1 = (math.log(S / K) + (r + sig * sig / 2) * T) / v
    return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d1 - v)


def bs_delta(S, K, T, sig, r=0.04):
    if T <= 1e-6:
        return 1.0 if S > K else 0.0
    v = sig * math.sqrt(T)
    return _ncdf((math.log(S / K) + (r + sig * sig / 2) * T) / v)


SCENARIOS = {
    # name: (iv_mult at entry, round-trip cost floor as fraction of premium, IV change after entry)
    "base": (1.1, 0.04, 1.00),
    "stress": (1.3, 0.08, 1.00),          # options priced 30% over realized vol, wider spreads
    "stress+crush": (1.3, 0.08, 0.85),    # plus IV falls 15% once the dip is bought
}


class Pricer:
    """Prices one signal's call at any later bar/price."""

    def __init__(self, r: dict, dte: int = 30, moneyness: float = 0.0, scenario: str = "base",
                 delta_target: float | None = None):
        self.bars = HIST[r["sym"]]
        self.i = r["i"]
        b0 = self.bars[self.i]
        self.s0 = b0["c"]
        self.d0 = date.fromisoformat(b0["t"])
        iv_mult, self.cost_floor, self.crush = SCENARIOS[scenario]
        hv = o.hist_vol([b["c"] for b in self.bars[self.i - 25:self.i + 1]]) or 0.2
        self.iv0 = max(hv, 0.15) * iv_mult
        self.dte = dte
        if delta_target is not None:  # pick strike whose delta ~= target
            lo, hi = self.s0 * 0.7, self.s0 * 1.3
            for _ in range(50):
                mid = (lo + hi) / 2
                if bs_delta(self.s0, mid, dte / 365, self.iv0) > delta_target:
                    lo = mid
                else:
                    hi = mid
            self.K = (lo + hi) / 2
        else:
            self.K = self.s0 * (1 + moneyness)
        self.p0 = bs_call(self.s0, self.K, dte / 365, self.iv0)
        # cost: max(floor %, $0.05 half-spread each way => $0.10 / premium)
        self.cost = max(self.cost_floor, 0.10 / max(self.p0, 0.01))

    def value(self, k: int, S: float) -> float:
        """Option value / entry premium at session k after entry with stock price S."""
        b = self.bars[self.i + k]
        el = (date.fromisoformat(b["t"]) - self.d0).days
        iv = self.iv0 * (self.crush if k >= 1 else 1.0)
        return bs_call(S, self.K, max(self.dte - el, 0) / 365, iv) / self.p0

    def bar(self, k: int) -> dict:
        return self.bars[self.i + k]

    def closes(self, upto_k: int, n: int) -> list[float]:
        """Last n closes up to and including session k (k=0 is entry day)."""
        j = self.i + upto_k
        return [b["c"] for b in self.bars[j - n + 1:j + 1]]


def simulate(r: dict, policy, dte=30, moneyness=0.0, scenario="base", delta_target=None, **pkw) -> dict | None:
    """Run one trade. Returns {'ret': net return on premium, 'days': sessions held, 'path': [...]}

    policy(st) is called once per session k = 1..MAX_DAYS with a dict st:
        st['k'], st['pr'] (Pricer), st['bar'] (today's OHLC), st['open_frac'] (fraction still held),
        st['peak_v'] (max close value so far, as multiple of entry premium), st['mem'] (dict for policy state),
        plus any **pkw.
    It returns a list of actions, each (fraction_of_original, price_kind, stock_price) where price_kind is
        'stop'  -> stock_price is an intraday stop level; filled if today's low <= level
                   (at min(open, level) -- gap-through fills at the open)
        'close' -> sell at today's close (stock_price ignored)
        'limit' -> intraday take-profit at stock_price; filled if high >= level (at max(open, level))
    Actions are processed in order: stops first is the caller's responsibility (conservative: put stop first).
    Remaining position is force-closed at the close of MAX_DAYS.
    """
    pr = Pricer(r, dte, moneyness, scenario, delta_target)
    if pr.p0 < 0.10:
        return None
    held, proceeds, mem, peak = 1.0, 0.0, {}, 1.0
    last_k = MAX_DAYS
    for k in range(1, MAX_DAYS + 1):
        b = pr.bar(k)
        st = dict(k=k, pr=pr, bar=b, open_frac=held, peak_v=peak, mem=mem, **pkw)
        for frac, kind, S in policy(st) or []:
            frac = min(frac, held)
            if frac <= 1e-9:
                continue
            if kind == "stop":
                if b["l"] <= S:
                    fill = min(b["o"], S)
                    proceeds += frac * pr.value(k, fill)
                    held -= frac
            elif kind == "limit":
                if b["h"] >= S:
                    fill = max(b["o"], S)
                    proceeds += frac * pr.value(k, fill)
                    held -= frac
            elif kind == "close":
                proceeds += frac * pr.value(k, b["c"])
                held -= frac
        peak = max(peak, pr.value(k, b["c"]))
        if held <= 1e-9:
            last_k = k
            break
    if held > 1e-9:
        proceeds += held * pr.value(MAX_DAYS, pr.bar(MAX_DAYS)["c"])
    return {"ret": proceeds - 1 - pr.cost, "days": last_k}


def evaluate(policy, dte=30, moneyness=0.0, scenario="base", delta_target=None, sigs=None, **pkw) -> dict:
    sigs = SIG if sigs is None else sigs
    rows = []
    for r in sigs:
        t = simulate(r, policy, dte, moneyness, scenario, delta_target, **pkw)
        if t:
            rows.append((r["d"], t["ret"] * 100, t["days"]))
    out = {}
    for lab, f in (("IS", lambda d: d < "2025"), ("OOS", lambda d: d >= "2025"), ("ALL", lambda d: True)):
        x = [p for d, p, _ in rows if f(d)]
        if len(x) < 10:
            continue
        n = len(x)
        m = sum(x) / n
        sd = (sum((v - m) ** 2 for v in x) / (n - 1)) ** 0.5
        nd = len({d for d, _, _ in rows if f(d)})
        xs = sorted(x)
        out[lab] = {"n": n, "mean": round(m, 2), "median": round(xs[n // 2], 1),
                    "win": round(sum(v > 0 for v in x) / n * 100, 1), "t": round(m / sd * math.sqrt(nd), 2),
                    "p10": round(xs[n // 10], 1), "p90": round(xs[9 * n // 10], 1),
                    "loss_gt50": round(sum(v <= -50 for v in x) / n * 100, 1),
                    "avg_days": round(sum(dd for d, _, dd in rows if f(d)) / n, 2)}
    # account: 3% of equity per trade, chronological, (ignores overlap caps -- comparative only)
    eq = peak = 1.0
    mdd = 0.0
    for _, p, _ in sorted(rows):
        eq *= 1 + 0.03 * p / 100
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    out["acct3_mdd"] = round(mdd * 100, 1)
    out["acct3_end"] = round(eq, 2)
    return out


def report(name, policy, scenarios=("base", "stress", "stress+crush"), **kw):
    for sc in scenarios:
        e = evaluate(policy, scenario=sc, **kw)
        def f(lab):
            s = e.get(lab)
            return (f"{lab} n{s['n']} {s['mean']:+6.2f}% med{s['median']:+5.0f} win{s['win']:4.0f}% t{s['t']:+5.2f} "
                    f"p10 {s['p10']:+5.0f} >-50%:{s['loss_gt50']:4.1f}% d{s['avg_days']:.1f}") if s else f"{lab} -"
        print(f"{name:<40} [{sc:<12}] {f('IS')} | {f('OOS')} | DD3% {e['acct3_mdd']:+.0f}%", flush=True)
    return


# ---------- baseline: current v2.2 exits ----------
def v22_policy(st):
    """-50% stop / +80% target on close value, exit when close > SMA5, max 5 sessions."""
    pr, k, b = st["pr"], st["k"], st["bar"]
    v = pr.value(k, b["c"])
    sma5 = sum(pr.closes(k, 5)) / 5
    if v - 1 <= -0.5 or v - 1 >= 0.8 or b["c"] > sma5 or k >= 5:
        return [(1.0, "close", None)]
    return []


if __name__ == "__main__":
    print(len(SIG), "signals")
    report("v2.2 baseline 30DTE ATM", v22_policy, dte=30)
