import sys, math, random
sys.path.insert(0, "/tmp/claude-0/-home-user-Agentic-Trader/011b42d0-55e9-5744-b666-b48b04f949c7/scratchpad")
from harness import *
from collections import defaultdict
rows = []
for r in SIG:
    t = simulate(r, v22_policy, dte=30)
    if t: rows.append((r["sym"], r["d"], t["ret"]*100, r["stock_vol"], o.SECTOR.get(r["sym"])))
def st(x):
    n=len(x); m=sum(x)/n if n else 0
    return n, m, (sum(v>0 for v in x)/n*100 if n else 0)
by = defaultdict(lambda: {"IS":[], "OOS":[], "ALL":[]})
for s,d,p,v,sec in rows:
    by[s]["ALL"].append(p); by[s]["IS" if d<"2025" else "OOS"].append(p)
print(f"{'股票':<6}{'板块':<6}{'次数':>5}{'每笔':>8}{'胜率':>6}{'21-24':>12}{'25-26':>12}")
for s in sorted(by, key=lambda s: -st(by[s]["ALL"])[1]):
    n,m,w = st(by[s]["ALL"]); a=st(by[s]["IS"]); b=st(by[s]["OOS"])
    print(f"{s:<6}{(o.SECTOR.get(s) or '-'):<6}{n:>5}{m:>+7.1f}%{w:>5.0f}%{a[1]:>+8.1f}%({a[0]:>2}){b[1]:>+8.1f}%({b[0]:>2})")
# persistence: does IS per-stock mean predict OOS per-stock mean?
pairs=[(st(by[s]["IS"])[1], st(by[s]["OOS"])[1], st(by[s]["OOS"])[0]) for s in by if len(by[s]["IS"])>=5 and len(by[s]["OOS"])>=3]
xs=[p[0] for p in pairs]; ys=[p[1] for p in pairs]
def rank(v): s=sorted(range(len(v)),key=lambda i:v[i]); r=[0]*len(v); [r.__setitem__(i,k) for k,i in enumerate(s)]; return r
rx,ry=rank(xs),rank(ys); n=len(pairs)
rho=1-6*sum((a-b)**2 for a,b in zip(rx,ry))/(n*(n*n-1))
print(f"\n持续性检验：{n} 只股票，2021-24 的表现 vs 2025-26 的表现，秩相关 = {rho:+.2f}")
top=[p for p in pairs if p[0]>=sorted(xs)[2*n//3]]; bot=[p for p in pairs if p[0]<=sorted(xs)[n//3]]
w=lambda g: sum(p[1]*p[2] for p in g)/sum(p[2] for p in g)
print(f"2021-24 最好的 1/3 股票，在 2025-26 每笔 {w(top):+.1f}%；最差的 1/3 → {w(bot):+.1f}%")
# noise: expected spread of per-stock means if all stocks identical
allp=[p for _,_,p,_,_ in rows]; sd=(sum((v-sum(allp)/len(allp))**2 for v in allp)/len(allp))**.5
print(f"单笔标准差 {sd:.0f}%：一只股票 20 笔时，纯运气造成的每笔平均误差约 ±{sd/math.sqrt(20):.0f}%")
# sector and volatility
print("\n按板块：")
sec=defaultdict(list)
for s,d,p,v,sc in rows: sec[sc].append((d,p))
for k,v in sorted(sec.items(), key=lambda kv:-sum(p for _,p in kv[1])/len(kv[1])):
    a=[p for d,p in v if d<"2025"]; b=[p for d,p in v if d>="2025"]
    print(f"  {k or '-':<6} n{len(v):>4} {sum(p for _,p in v)/len(v):+6.1f}%  IS {sum(a)/max(len(a),1):+6.1f}% OOS {sum(b)/max(len(b),1):+6.1f}% (n{len(b)})")
print("\n按股票自身波动率（HV20）三等分：")
vs=sorted(v for _,_,_,v,_ in rows); q=[vs[len(vs)//3], vs[2*len(vs)//3]]
for lab,f in (("低波动",lambda v:v<q[0]),("中波动",lambda v:q[0]<=v<q[1]),("高波动",lambda v:v>=q[1])):
    a=[p for _,d,p,v,_ in rows if f(v) and d<"2025"]; b=[p for _,d,p,v,_ in rows if f(v) and d>="2025"]
    print(f"  {lab} IS {sum(a)/len(a):+6.1f}% (n{len(a)})  OOS {sum(b)/len(b):+6.1f}% (n{len(b)})")
print(f"  分界 {q[0]:.0f}% / {q[1]:.0f}%")
