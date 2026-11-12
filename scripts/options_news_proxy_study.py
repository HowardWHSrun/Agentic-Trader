import sys; sys.path.insert(0, "/tmp/claude-0/-home-user-Agentic-Trader/011b42d0-55e9-5744-b666-b48b04f949c7/scratchpad")
from harness import *
from datetime import date, timedelta
def fri(r, mind=14):
    d0 = date.fromisoformat(r["d"]); d = d0 + timedelta(days=mind)
    while d.weekday() != 4: d += timedelta(days=1)
    return (d - d0).days
def pa(st):
    pr, k, b = st["pr"], st["k"], st["bar"]
    atr = o.atr(pr.bars[pr.i-30:pr.i+1]); dis = pr.bar(0)["l"] - 2*atr
    return [(1.0, "close", None)] if b["c"] > sum(pr.closes(k,5))/5 or k >= 5 or b["c"] < dis else []
S = [r for r in SIG if r["stock_vol"] >= 0.20]
feat = []
for r in S:
    b = HIST[r["sym"]]; i = r["i"]; atr = r["atr"]
    n = 4
    while n < 10 and b[i-n]["c"] < b[i-n-1]["c"]: n += 1
    days = [(b[j]["c"]/b[j-1]["c"]-1, (b[j]["o"]/b[j-1]["c"]-1)) for j in range(i-n+1, i+1)]
    big = min(d for d,_ in days); gap = min(g for _,g in days)
    bigatr = max((b[j-1]["c"]-b[j]["c"])/atr for j in range(i-n+1, i+1))
    sec = HIST.get(r["sector"]) if r["sector"] else None
    rel = None
    if sec:
        si = {x["t"]: k for k, x in enumerate(sec)}
        if r["d"] in si and b[i-n]["t"] in si:
            rel = (b[i]["c"]/b[i-n]["c"]-1) - (sec[si[r["d"]]]["c"]/sec[si[b[i-n]["t"]]]["c"]-1)
    t = simulate(r, pa, dte=fri(r), delta_target=0.75)
    ts = simulate(r, pa, dte=fri(r), delta_target=0.75, scenario="stress")
    if t: feat.append((r, big, gap, bigatr, rel, t["ret"]*100, ts["ret"]*100))
def show(lab, f):
    g = [x for x in feat if f(x)]
    if len(g) < 15: print(f"{lab:<34} n{len(g)} 太少"); return
    a = [x[5] for x in g if x[0]["d"] < "2025"]; b = [x[5] for x in g if x[0]["d"] >= "2025"]
    m = sum(x[5] for x in g)/len(g); ms = sum(x[6] for x in g)/len(g)
    print(f"{lab:<34} n{len(g):4d} 每笔{m:+6.1f}% 胜率{sum(x[5]>0 for x in g)/len(g)*100:3.0f}% 压力{ms:+6.1f}% | 21-24 {sum(a)/max(len(a),1):+6.1f}% ({len(a)}) 25-26 {sum(b)/max(len(b),1):+6.1f}% ({len(b)})")
show("全部（v2.4 合约）", lambda x: True)
print("-- 连跌中最大单日跌幅（新闻冲击的痕迹）")
show("最大单日跌幅 < 2.5 ATR(温和阴跌)", lambda x: x[3] < 1.5)
show("最大单日跌幅 1.5–2.5 ATR", lambda x: 1.5 <= x[3] < 2.5)
show("最大单日跌幅 ≥ 2.5 ATR(突发大跌)", lambda x: x[3] >= 2.5)
print("-- 跳空低开")
show("没有跳空低开 >2%", lambda x: x[2] > -0.02)
show("有跳空低开 2–4%", lambda x: -0.04 < x[2] <= -0.02)
show("有跳空低开 >4%", lambda x: x[2] <= -0.04)
print("-- 比同板块 ETF 多跌多少（只有它跌 = 多半是自己的消息）")
show("跟板块一起跌（差 > -2%）", lambda x: x[4] is not None and x[4] > -0.02)
show("比板块多跌 2–5%", lambda x: x[4] is not None and -0.05 < x[4] <= -0.02)
show("比板块多跌 > 5%", lambda x: x[4] is not None and x[4] <= -0.05)
print("-- 组合：独跌且有突发大跌（最像坏消息）")
show("比板块多跌>3% 且 单日≥2.5ATR", lambda x: x[4] is not None and x[4] <= -0.03 and x[3] >= 2.5)
show("其余", lambda x: not (x[4] is not None and x[4] <= -0.03 and x[3] >= 2.5))
print("-- 交叉：大盘状态 × 跟板块")
from collections import Counter
nd = Counter(x[0]["d"] for x in feat)
for bl, bf in (("大盘回调", lambda x: x[0]["spy_r5"] < -2 or not x[0]["spy_up50"] or nd[x[0]["d"]] >= 2), ("大盘平稳", lambda x: not (x[0]["spy_r5"] < -2 or not x[0]["spy_up50"] or nd[x[0]["d"]] >= 2))):
    for sl, sf in (("跟板块(>-2%)", lambda x: x[4] is not None and x[4] > -0.02), ("多跌2-5%", lambda x: x[4] is not None and -0.05 < x[4] <= -0.02), ("独跌>5%", lambda x: x[4] is not None and x[4] <= -0.05)):
        show(f"{bl} × {sl}", lambda x, bf=bf, sf=sf: bf(x) and sf(x))
