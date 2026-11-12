import json, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
df = pd.read_pickle("A/sig.pkl")
df["broad_f"] = df["broad"].astype(float)
F = ['streak','st_drop','drop_atr','max_day_atr','day0_atr','n_gapdn','gap_sum','vs_sector','vs_spy','rsi2','rsi14','d20_atr','d50_atr','d200_atr','s200_slope','s50_slope','hv20','hv_ratio','atr_pct','vol_ratio','clv','r20','r60','from_hi_atr','spy_r5','spy_r20','spy_d50','spy_d200','spy_hv20','spy_streak','n_sig_day','dow','month','broad_f','tier']
acc = df[df.tier > 0].dropna(subset=["y_base"]).copy()
# walk-forward check (no sector one-hots)
res = []
for Y in range(2010, 2027):
    first = df[df.d >= f"{Y}-01-01"].si.min()
    tr = acc[acc.lab_end_si < first - 7]; te = acc[acc.d.str[:4] == str(Y)]
    if len(te) == 0: continue
    X = tr[F]; med = X.median(); mu = X.fillna(med).mean(); sd = X.fillna(med).std().replace(0, 1)
    m = LogisticRegression(C=0.05, max_iter=2000).fit(((X.fillna(med) - mu) / sd).values, tr.y_win.values)
    p_tr = m.predict_proba(((X.fillna(med) - mu) / sd).values)[:, 1]; q33, q67 = np.quantile(p_tr, [1/3, 2/3])
    p = m.predict_proba(((te[F].fillna(med) - mu) / sd).values)[:, 1]
    mult = np.where(p < q33, 0.5, np.where(p > q67, 1.5, 1.0)) * te.tier.values
    w = te.tier.values * (mult.sum() / te.tier.values.sum()) / te.tier.values  # risk-match scale
    rule = (te.tier * te.y_base).sum() / te.tier.sum(); ml = (mult * te.y_base).sum() / mult.sum()
    hi = te.y_base[p > q67].mean(); lo = te.y_base[p < q33].mean()
    res.append((Y, len(te), rule, ml, hi, lo))
    print(f"{Y} n{len(te):3d} 规则每单位风险 {rule:+6.1f}  ML加权 {ml:+6.1f}  高分组 {hi:+6.1f}  低分组 {lo:+6.1f}")
r = np.array([x[2:] for x in res]); print("平均", r.mean(0).round(1), "ML 胜出年数", int((r[:,1] > r[:,0]).sum()), "/", len(r))
# final fit on everything to date
X = acc[F]; med = X.median(); mu = X.fillna(med).mean(); sd = X.fillna(med).std().replace(0, 1)
m = LogisticRegression(C=0.05, max_iter=2000).fit(((X.fillna(med) - mu) / sd).values, acc.y_win.values)
p = m.predict_proba(((X.fillna(med) - mu) / sd).values)[:, 1]; q33, q67 = np.quantile(p, [1/3, 2/3])
out = {"model": "L2 logistic regression, C=0.05, standardized, median-imputed; target P(v2.5 option trade > 0)",
       "trained_on": f"{len(acc)} v2.5-accepted dip signals {acc.d.min()}..{acc.d.max()} (32-stock universe, estimated option prices)",
       "trained_at": "2026-11-12", "refit": "once a year",
       "features": F, "median": med.round(6).tolist(), "mean": mu.round(6).tolist(), "scale": sd.round(6).tolist(),
       "coef": m.coef_[0].round(6).tolist(), "intercept": round(float(m.intercept_[0]), 6),
       "q33": round(float(q33), 4), "q67": round(float(q67), 4)}
json.dump(out, open("/home/user/Agentic-Trader/docs/data/options/ml_model.json", "w"), ensure_ascii=False, indent=1)
print("q33/q67", q33, q67, "top coefs", sorted(zip(F, m.coef_[0]), key=lambda x: -abs(x[1]))[:8])
