#!/usr/bin/env python3
"""Build the daily options analysis report as a PDF.

Reads the public scan output (docs/data/options/latest.json, daily snapshots,
review) and, optionally, a private positions file and a commentary text file,
renders an A4 HTML report and prints it to PDF with headless Chromium.

The PDF may contain private positions, so it is written to reports/ (which is
git-ignored) and never published to the website.

Usage:
  python3 scripts/options_report.py [--positions FILE] [--commentary FILE] [--out FILE]
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPT = ROOT / "docs" / "data" / "options"
REPORTS = ROOT / "reports"

SECTOR_NAMES = {"XLK": "科技", "XLC": "通信", "XLY": "可选消费", "XLP": "必需消费", "XLV": "医疗", "XLF": "金融",
                "XLE": "能源", "XLI": "工业", "XLU": "公用事业", "XLB": "材料", "XLRE": "地产", None: "—"}


def esc(x) -> str:
    return html.escape(str(x))


def pct(x, digits=1) -> str:
    return "—" if x is None else f"{x:+.{digits}f}%"


def cls(x) -> str:
    return "" if x is None or x == 0 else ("pos" if x > 0 else "neg")


def check(row: dict, name: str) -> int:
    """+1 bullish, -1 bearish, 0 neutral/missing for a named check."""
    for c in row.get("checks", []):
        if c["name"] == name:
            return 1 if c["bull"] > c["bear"] else -1 if c["bear"] > c["bull"] else 0
    return 0


sys.path.insert(0, str(ROOT / "scripts"))
from options_scorer import explain_row as reasons  # noqa: E402


def short_reason(r: dict) -> str:
    bull, bear = reasons(r)
    side = bull if r["direction"] == "看涨" else bear if r["direction"] == "看跌" else (bull[:1] + bear[:1])
    keep = [x for x in side if "跑" in x or "RSI" in x or "过多" in x][:2] or side[:2]
    return "；".join(keep)


def day_changes(date: str) -> dict:
    days = sorted((OPT / "daily").glob("*.json"))
    cur = next((p for p in days if p.stem == date), None)
    if not cur:
        return {}
    idx = days.index(cur)
    today = json.loads(cur.read_text())["last"]["prices"]
    if idx == 0:
        return {}
    prev = json.loads(days[idx - 1].read_text())["last"]["prices"]
    return {s: (today[s] / prev[s] - 1) * 100 for s in today if prev.get(s) and today.get(s)}


def score_bar(score) -> str:
    if score is None:
        return "—"
    color = "var(--green)" if score >= 70 else "var(--red)" if score <= 30 else "var(--gray)"
    return (f'<span class="score">{score}</span><span class="bar"><i style="width:{score}%;background:{color}"></i></span>')


def tag(direction: str) -> str:
    c = {"看涨": "t-bull", "看跌": "t-bear"}.get(direction, "t-wait")
    return f'<span class="tag {c}">{esc(direction)}</span>'


def detail_card(r: dict, chg: dict, blocked: dict) -> str:
    bull, bear = reasons(r)
    main, other = (bull, bear) if r["direction"] == "看涨" else (bear, bull)
    c = (r.get("contracts") or {}).get("single")
    contract = ""
    if c:
        contract = (f'<p class="contract"><b>参考合约：</b>{esc(c["strike"])} {"Call" if c["type"] == "call" else "Put"}，'
                    f'{esc(c["expiration"])} 到期，中间价 {c["mid"]}（每张约 ${c["cost_per_contract"]:.0f}），'
                    f'Delta {c["delta"]}，隐含波动率 {c["iv"]}%，盈亏平衡 {c["breakeven"]}</p>')
    note = blocked.get(r["symbol"])
    status = f'<p class="status"><b>系统处理：</b>{esc(note)}</p>' if note else '<p class="status ok"><b>系统处理：</b>符合进场条件</p>'
    risks = "".join(f"<li>{esc(x)}</li>" for x in other[:3]) or "<li>暂无明显反向信号</li>"
    return f'''<div class="card {'bull' if r['direction'] == '看涨' else 'bear'}">
<div class="card-head"><span class="sym">{esc(r['symbol'])}</span>{tag(r['direction'])}
<span class="card-score">评分 <b>{r['score']}</b></span>
<span class="card-px">{r['price']:.2f} <span class="{cls(chg.get(r['symbol']))}">{pct(chg.get(r['symbol']))}</span></span></div>
<div class="cols"><div><h4>为什么{esc(r['direction'])}</h4><ul>{''.join(f'<li>{esc(x)}</li>' for x in main[:6])}</ul></div>
<div><h4>风险 / 反向信号</h4><ul>{risks}</ul></div></div>{contract}{status}</div>'''


def build_html(latest: dict, review: dict | None, positions: list[dict], commentary: str) -> str:
    date = latest["generated_at_ct"][:10]
    rows = [r for r in latest["rankings"] if r["score"] is not None]
    chg = day_changes(date)
    blocked = {b["symbol"]: b["reason"] for b in latest.get("blocked", [])}
    bulls = [r for r in rows if r["direction"] == "看涨"]
    bears = [r for r in rows if r["direction"] == "看跌"][::-1]
    spy = chg.get("SPY")

    # --- KPI tiles
    pnl_total = sum((p["mark"] - p["fill"]) * 100 * p["qty"] for p in positions if p.get("mark") is not None)
    cost_total = sum(p["fill"] * 100 * p["qty"] for p in positions)
    one = (review or {}).get("one_day") or (review or {}).get("same_day") or {}
    tiles = [
        ("大盘 SPY 当日", pct(spy, 2), cls(spy)),
        ("趋势强 / 中性 / 趋势弱", f"{len(bulls)} / {len(rows) - len(bulls) - len(bears)} / {len(bears)}", ""),
        ("看涨组 − 看跌组（1 天）", pct(one.get("bull_minus_bear"), 2), cls(one.get("bull_minus_bear"))),
    ]
    if positions:
        tiles.append(("我的持仓浮动盈亏", f"{'+' if pnl_total >= 0 else '−'}${abs(pnl_total):,.0f}", cls(pnl_total)))
    tiles_html = "".join(f'<div class="tile"><div class="tile-l">{esc(a)}</div><div class="tile-v {c}">{esc(b)}</div></div>' for a, b, c in tiles)

    # --- positions
    pos_html = ""
    if positions:
        trs = ""
        for p in positions:
            mark = p.get("mark")
            pl = (mark - p["fill"]) * 100 * p["qty"] if mark is not None else None
            plp = (mark / p["fill"] - 1) * 100 if mark is not None else None
            sc = next((r["score"] for r in rows if r["symbol"] == p["symbol"]), None)
            state = "正常持有"
            if mark is not None and mark <= p["stop"]:
                state = "触及止损"
            elif mark is not None and mark >= p["target"]:
                state = "触及止盈"
            trs += (f'<tr><td class="b">{esc(p["symbol"])}</td><td>{esc(p["label"])}</td><td class="r">{p["qty"]}</td>'
                    f'<td class="r">{p["fill"]:.2f}</td><td class="r">{"—" if mark is None else f"{mark:.2f}"}</td>'
                    f'<td class="r {cls(pl)}">{"—" if pl is None else f"{pl:+,.0f}"}</td><td class="r {cls(plp)}">{pct(plp)}</td>'
                    f'<td class="r">{p["stop"]:.2f}</td><td class="r">{p["target"]:.2f}</td><td>{esc(p["exit_by"])}</td>'
                    f'<td class="r">{sc if sc is not None else "—"}</td><td>{state}</td></tr>')
        pos_html = f'''<h2>我的持仓</h2><table class="grid"><thead><tr><th>股票</th><th>合约</th><th class="r">张数</th><th class="r">成本</th>
<th class="r">现价</th><th class="r">盈亏 $</th><th class="r">盈亏 %</th><th class="r">止损</th><th class="r">止盈</th><th>最晚退场</th><th class="r">评分</th><th>状态</th></tr></thead>
<tbody>{trs}</tbody><tfoot><tr><td colspan="5" class="b">合计（投入 ${cost_total:,.0f}）</td><td class="r b {cls(pnl_total)}">{pnl_total:+,.0f}</td>
<td class="r b {cls(pnl_total)}">{pct(pnl_total / cost_total * 100 if cost_total else None)}</td><td colspan="5"></td></tr></tfoot></table>
<p class="fine">现价为期权买卖中间价。止损、止盈按每笔买入时的规则设定；最晚退场 = 买入后第 7 天。</p>'''

    # --- signals
    def sig_line(s: dict, kind: str) -> str:
        legs = " / ".join(("买 " if leg["qty"] > 0 else "卖 ") + f"{leg['strike']:g}{'C' if s['type'] == 'call' else 'P'}" for leg in s["legs"])
        if kind == "exit":
            return f"<li><b>退场 {esc(s['symbol'])}</b> {legs} {esc(s['expiration'])}：{esc(s['exit_reason'])}</li>"
        return (f"<li><b>进场 {esc(s['symbol'])} {'看涨' if s['type'] == 'call' else '看跌'}</b>（评分 {s['score_at_entry']}）{legs} {esc(s['expiration'])}，"
                f"成本约 {s['entry_cost']}（每张 ${s['cost_per_contract']:.0f}），止损 {s['stop_value']}，止盈 {s['target_value']}，最晚 {esc(s['exit_by'])} 退场</li>")

    today_entries = [s for s in latest["open"] if s.get("entry_date") == date]
    sig = "".join(sig_line(s, "entry") for s in today_entries) + "".join(sig_line(s, "exit") for s in latest["exits"])
    sig_html = f"<ul class='sig'>{sig}</ul>" if sig else "<p>今天没有新的进场或退场信号。</p>"

    # --- full table
    body = ""
    for r in rows:
        body += (f'<tr><td class="r">{r["rank"]}</td><td class="b">{esc(r["symbol"])}</td><td class="nw">{esc(SECTOR_NAMES.get(r.get("sector_etf"), "—"))}</td>'
                 f'<td class="sc">{score_bar(r["score"])}</td><td>{tag(r["direction"])}</td><td class="r">{r["price"]:.2f}</td>'
                 f'<td class="r {cls(chg.get(r["symbol"]))}">{pct(chg.get(r["symbol"]))}</td><td class="r {cls(r["ret20"])}">{pct(r["ret20"])}</td>'
                 f'<td class="r {cls(r["rel_spy20"])}">{pct(r["rel_spy20"])}</td><td class="r">{r["rsi14"]:.0f}</td>'
                 f'<td class="why">{esc(short_reason(r))}</td></tr>')

    # --- review
    rev_html = "<p>复盘数据将在第一个完整交易日后出现。</p>"
    if review:
        trs = ""
        for key, name in (("same_day", "当天（早盘分数 → 收盘）"), ("one_day", "1 天（昨日分数 → 今日）"), ("five_day", "5 天")):
            g = review.get(key)
            if not g:
                trs += f'<tr><td>{name}</td><td colspan="7" class="muted">数据还不够</td></tr>'
                continue
            b, s = g["bull"], g["bear"]
            trs += (f'<tr><td>{name}</td><td class="r {cls(g["spy_ret"])}">{pct(g["spy_ret"], 2)}</td>'
                    f'<td class="r {cls(b["avg_ret"])}">{pct(b["avg_ret"], 2)}</td><td class="r">{b["hit_rate"] if b["hit_rate"] is not None else "—"}%</td>'
                    f'<td class="r {cls(-s["avg_ret"] if s["avg_ret"] is not None else None)}">{pct(s["avg_ret"], 2)}</td><td class="r">{s["hit_rate"] if s["hit_rate"] is not None else "—"}%</td>'
                    f'<td class="r {cls(g["bull_minus_bear"])}">{pct(g["bull_minus_bear"], 2)}</td><td class="r">{g["rank_corr"] if g["rank_corr"] is not None else "—"}</td></tr>')
        ro = review["rolling"]
        rev_html = f'''<table class="grid"><thead><tr><th>周期</th><th class="r">SPY</th><th class="r">看涨组平均</th><th class="r">真的涨了</th>
<th class="r">看跌组平均</th><th class="r">真的跌了</th><th class="r">看涨 − 看跌</th><th class="r">相关性</th></tr></thead><tbody>{trs}</tbody></table>
<div class="verdict"><b>滚动结论（最近 {ro["days"]} 个交易日）：{esc(review["verdict"])}。</b>{esc(review["action"])}
看涨组平均每天领先看跌组 {pct(ro["avg_bull_minus_bear"], 2)}，{ro["days_bull_beat_bear"]} 天领先。</div>
<p class="fine">"看涨 − 看跌"为正说明高分股票跑赢低分股票；相关性在 −1 到 +1 之间，越接近 +1 说明分数越准。至少累计 10 个交易日才会据此调整方法。</p>'''

    comm_html = "".join(f"<p>{esc(par)}</p>" for par in commentary.strip().split("\n") if par.strip()) if commentary.strip() else ""
    comm_block = f'<h2>分析师点评</h2><div class="comment">{comm_html}</div>' if comm_html else ""
    cards = lambda group: "".join(detail_card(r, chg, blocked) for r in group[:6])  # noqa: E731
    rules = "".join(f"<li>{esc(x)}</li>" for x in latest["risk_rules"])

    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>每日期权分析报告 {date}</title><style>
:root{{--ink:#14302d;--muted:#5f716c;--line:#d5ddd6;--green:#17694f;--red:#b23a2e;--gray:#8a9792;--mint:#e3efe6;--rose:#f7e4e0;--paper:#f5f6f1}}
*{{box-sizing:border-box}}@page{{size:A4;margin:14mm 12mm 16mm}}
body{{margin:0;color:var(--ink);font:9.6pt/1.5 -apple-system,'Segoe UI','Noto Sans CJK SC','PingFang SC','Microsoft YaHei',sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.mast{{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid var(--ink);padding-bottom:8px}}
.brand{{display:flex;align-items:center;gap:10px}}.logo{{width:34px;height:34px;background:var(--ink);color:#d1f3d5;border-radius:8px;display:grid;place-items:center;font:20pt Georgia,serif}}
.brand b{{font-size:13pt}}.brand small{{display:block;font-size:7pt;letter-spacing:.18em;color:var(--gray)}}
.mast-r{{text-align:right;font-size:8pt;color:var(--muted)}}.mast-r b{{display:block;font-size:10pt;color:var(--ink)}}
h1{{font:normal 23pt/1.15 Georgia,'Noto Serif CJK SC',serif;margin:14px 0 2px}}.sub{{color:var(--muted);margin:0 0 12px}}
h2{{font:normal 14pt Georgia,'Noto Serif CJK SC',serif;margin:20px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--line);break-after:avoid}}
h3{{font-size:10.5pt;margin:14px 0 6px;break-after:avoid}}h4{{margin:0 0 3px;font-size:8.6pt;color:var(--muted);font-weight:600}}
.tiles{{display:grid;grid-template-columns:repeat({len(tiles)},1fr);gap:8px}}.tile{{border:1px solid var(--line);border-radius:6px;padding:9px 11px;background:var(--paper)}}
.tile-l{{font-size:7.6pt;color:var(--muted)}}.tile-v{{font:600 15pt Georgia,serif;margin-top:2px}}
table.grid{{width:100%;border-collapse:collapse;font-size:8.3pt}}.grid th{{background:var(--ink);color:#fff;font-weight:600;text-align:left;padding:5px 6px;font-size:7.6pt}}
.grid td{{padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:middle}}.grid tbody tr:nth-child(even) td{{background:#fafbf8}}
.grid tfoot td{{border-top:2px solid var(--ink);border-bottom:0;padding-top:6px}}.grid tr{{break-inside:avoid}}
.r{{text-align:right!important;font-variant-numeric:tabular-nums}}.b{{font-weight:700}}.pos{{color:var(--green)}}.neg{{color:var(--red)}}.muted{{color:var(--muted)}}
.sc{{white-space:nowrap}}.score{{display:inline-block;width:20px;font-weight:700;text-align:right}}.bar{{display:inline-block;width:46px;height:6px;background:#e4e9e3;border-radius:3px;margin-left:5px;vertical-align:middle;overflow:hidden}}.bar i{{display:block;height:100%}}
.tag{{display:inline-block;font-size:7.4pt;font-weight:700;border-radius:10px;padding:0 7px;white-space:nowrap}}.t-bull{{background:var(--mint);color:var(--green)}}.t-bear{{background:var(--rose);color:var(--red)}}.t-wait{{background:#eceee9;color:var(--muted)}}
.why{{font-size:7.5pt;color:var(--muted);line-height:1.35}}.fine{{font-size:7.4pt;color:var(--muted);margin:5px 0 0}}
.card{{border:1px solid var(--line);border-left:4px solid var(--green);border-radius:6px;padding:8px 11px;margin:0 0 8px;break-inside:avoid}}.card.bear{{border-left-color:var(--red)}}
.card-head{{display:flex;align-items:center;gap:9px;margin-bottom:5px}}.sym{{font:700 12pt Georgia,serif}}.card-score{{margin-left:auto;font-size:8.6pt}}.card-score b{{font-size:12pt}}.card-px{{font-size:8.6pt;text-align:right}}
.cardgrid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;align-items:start}}.cardgrid .card{{margin:0}}.cols h4{{margin-top:5px}}.nw{{white-space:nowrap}}ul{{margin:0;padding-left:15px}}li{{margin:1px 0}}.card li{{font-size:8.3pt}}
.contract,.status{{margin:5px 0 0;font-size:8.1pt}}.status{{color:var(--muted)}}.status.ok{{color:var(--green)}}
.sig li{{margin:3px 0}}.comment{{background:var(--paper);border-left:4px solid var(--ink);padding:9px 13px;border-radius:0 6px 6px 0}}.comment p{{margin:0 0 6px}}.comment p:last-child{{margin:0}}
.verdict{{margin-top:8px;padding:8px 11px;background:#fff7e3;border:1px solid #ead9a8;border-radius:6px;font-size:8.6pt}}
.disc{{margin-top:16px;padding-top:8px;border-top:1px solid var(--line);font-size:7.3pt;color:var(--muted)}}.pb{{break-before:page}}
</style></head><body>
<div class="mast"><div class="brand"><div class="logo">A</div><div><b>Agentic Trader</b><small>DAILY OPTIONS ANALYSIS</small></div></div>
<div class="mast-r"><b>{date}</b>规则 {esc(latest["rules_version"])} · 数据截至 {esc(latest["generated_at_ct"][11:])}</div></div>
<h1>每日期权分析报告</h1><p class="sub">32 只股票的评分排名、看涨看跌理由、持仓与准确度复盘</p>
<div class="tiles">{tiles_html}</div>
{pos_html}
<h2>今日信号</h2>{sig_html}
{comm_block}
<h2 class="pb">趋势最强的 6 只（背景参考，不是买入建议）</h2><div class="cardgrid">{cards(bulls)}</div>
<h2 class="pb">趋势最弱的 6 只（背景参考，系统不买 Put）</h2><div class="cardgrid">{cards(bears)}</div>
<h2 class="pb">全部 32 只评分排名</h2>
<table class="grid"><thead><tr><th class="r">#</th><th>股票</th><th>板块</th><th>评分</th><th>方向</th><th class="r">股价</th><th class="r">当日</th><th class="r">20日</th><th class="r">比大盘</th><th class="r">RSI</th><th>主要理由</th></tr></thead><tbody>{body}</tbody></table>
<p class="fine">评分 0–100：50 为中性，≥70 看涨（考虑买 Call），≤30 看跌（考虑买 Put），中间观望。"比大盘"为近 20 天相对 SPY 的超额涨跌。</p>
<h2>准确度复盘：分析得准不准</h2>{rev_html}
<h2>评分方法与交易规则</h2>
<p><b>买入信号（v2）：</b>长期趋势向上（股价和 50 日均线都在 200 日均线上方）且 RSI(2) &lt; 5 时买 Call；不买 Put。趋势评分只作背景：5 年回测显示它不能预测之后几天的涨跌。</p><p>趋势评分的算法：每只股票做 9 项对称检查并加权：均线排列（股价/20日/50日/200日，共 40 分）、相对大盘与行业强弱（25 分）、RSI 与 MACD 动能（20 分）、是否离均线过远（15 分）。看涨分与看跌分相抵后换算成 0–100。</p>
<ul>{rules}</ul>
<div class="disc">本报告由自动化程序根据公开行情生成，仅供个人研究参考，不构成投资建议。期权可能损失全部权利金。评分是技术面排序，不是盈利概率。{esc(latest["data_source"])}</div>
</body></html>'''


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--positions", type=Path, default=ROOT.parent / ".options-private" / "positions.json")
    ap.add_argument("--commentary", type=Path, help="plain-text file, one paragraph per line")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    latest = json.loads((OPT / "latest.json").read_text())
    date = latest["generated_at_ct"][:10]
    rev_path = OPT / "review" / f"{date}.json"
    review = json.loads(rev_path.read_text()) if rev_path.exists() else None
    positions = []
    if args.positions.exists():
        for p in json.loads(args.positions.read_text())["positions"]:
            meta = p["contract"]
            strike = int(meta[-8:]) / 1000
            positions.append({**p, "label": f"{strike:g} {'Call' if p['type'] == 'call' else 'Put'} · {p['expiration']}"})
    commentary = args.commentary.read_text() if args.commentary and args.commentary.exists() else ""
    REPORTS.mkdir(exist_ok=True)
    out = args.out or REPORTS / f"daily-options-report-{date}.pdf"
    html_path = out.with_suffix(".html")
    html_path.write_text(build_html(latest, review, positions, commentary))
    js = ("const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();const p=await b.newPage();"
          "await p.goto('file://'+process.argv[1]);await p.pdf({path:process.argv[2],format:'A4',printBackground:true,"
          "displayHeaderFooter:true,headerTemplate:'<span></span>',footerTemplate:"
          "'<div style=\"width:100%;font-size:7px;color:#8a9792;padding:0 12mm;display:flex;justify-content:space-between\">"
          "<span>Agentic Trader · 每日期权分析报告 · 仅供个人研究参考</span><span>第 <span class=\"pageNumber\"></span> / <span class=\"totalPages\"></span> 页</span></div>',"
          "preferCSSPageSize:true});await b.close()})()")
    subprocess.run(["node", "-e", js, str(html_path), str(out)], check=True)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
