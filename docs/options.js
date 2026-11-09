(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const num = (x, d = 2) => (x == null ? "—" : Number(x).toFixed(d));
  const pct = (x) => (x == null ? "—" : (x > 0 ? "+" : "") + Number(x).toFixed(1) + "%");
  const legs = (s) =>
    s.legs.map((l) => (l.qty > 0 ? "买 " : "卖 ") + l.strike + (s.type === "call" ? "C" : "P")).join(" / ") + " · " + s.expiration;
  const dirTag = (d) => el("span", "tag " + (d === "看涨" ? "call" : d === "看跌" ? "put" : "wait"), d);

  function card(s, kind) {
    const c = el("div", "card " + (kind === "exit" ? "exit" : s.type));
    const h = el("h3", null, s.symbol + " ");
    h.appendChild(el("span", "tag " + s.type, s.type === "call" ? "看涨 Call" : "看跌 Put"));
    if (kind === "exit") h.appendChild(el("span", "tag wait", "退场"));
    if (kind === "open") h.appendChild(el("span", "tag wait", "持有中"));
    c.appendChild(h);
    c.appendChild(el("p", null, (s.structure === "spread" ? "借方价差：" : "单买期权：") + legs(s)));
    if (kind === "entry") {
      const gain = s.max_gain_per_contract ? `；最多赚 $${Math.round(s.max_gain_per_contract)}` : "";
      c.appendChild(el("p", null, `评分 ${s.score_at_entry} · 股价 ${s.underlying_at_entry} · 净成本约 ${num(s.entry_cost)}（每张约 $${Math.round(s.cost_per_contract)}，这是最大亏损${gain}）`));
      c.appendChild(el("p", null, `盈亏平衡 ${s.breakeven} · 止损 ${s.stop_value} · 止盈 ${s.target_value} · 最晚 ${s.exit_by} 退场`));
    } else if (kind === "exit") {
      c.appendChild(el("p", null, `${s.exit_reason} · 进场 ${num(s.entry_cost)} → 现在 ${num(s.last_value)}`));
    } else {
      c.appendChild(el("p", null, `进场 ${s.entry_date} @ ${num(s.entry_cost)} · 现在 ${num(s.last_value)} · 盈亏 ${pct(s.pnl_pct)} · 最晚 ${s.exit_by} 退场`));
    }
    return c;
  }

  function render(d) {
    $("meta").textContent = `更新于 ${d.generated_at_ct} · 覆盖 ${d.coverage.scored}/${d.coverage.total} 只 · 每张合约上限 $${d.thresholds.max_cost_per_contract}`;
    d.exits.forEach((s) => $("exits").appendChild(card(s, "exit")));
    d.entries.forEach((s) => $("entries").appendChild(card(s, "entry")));
    const entered = new Set(d.entries.map((e) => e.legs[0].contract));
    d.open.filter((s) => !entered.has(s.legs[0].contract)).forEach((s) => $("open").appendChild(card(s, "open")));
    $("none").hidden = d.entries.length + d.exits.length > 0;
    const blocked = Object.fromEntries((d.blocked || []).map((b) => [b.symbol, b.reason]));
    const entrySyms = new Set(d.entries.map((e) => e.symbol));
    d.rankings.forEach((r) => {
      const tr = document.createElement("tr");
      tr.appendChild(el("td", null, r.rank));
      tr.appendChild(el("td", null, r.symbol)).style.fontWeight = "700";
      const sc = el("td", null, r.score == null ? "—" : r.score);
      if (r.score != null) {
        const b = el("span", "bar" + (r.score <= 30 ? " low" : ""));
        const i = el("i");
        i.style.width = r.score + "%";
        b.appendChild(i);
        sc.appendChild(b);
      }
      tr.appendChild(sc);
      const dt = el("td");
      dt.appendChild(dirTag(r.direction));
      tr.appendChild(dt);
      tr.appendChild(el("td", null, num(r.price)));
      tr.appendChild(el("td", r.ret20 > 0 ? "pos" : "neg", pct(r.ret20)));
      tr.appendChild(el("td", r.rel_spy20 > 0 ? "pos" : "neg", pct(r.rel_spy20)));
      tr.appendChild(el("td", null, num(r.rsi14, 0)));
      let note = entrySyms.has(r.symbol) ? "✅ 本次进场" : blocked[r.symbol] || r.missing || "";
      if (r.earnings) note += (note ? " · " : "") + "财报 " + r.earnings;
      tr.appendChild(el("td", "note", note));
      $("rows").appendChild(tr);
    });
    d.risk_rules.forEach((x) => $("rule-list").appendChild(el("li", null, x)));
    $("rule-list").appendChild(el("li", null, d.data_source));
  }

  function renderReview(r) {
    const box = $("review-body");
    box.textContent = "";
    box.appendChild(el("p", "meta", `${r.date} 收盘 · 规则 ${r.rules_version}`));
    const rows = [["same_day", "今天"], ["one_day", "1 天"], ["five_day", "5 天"]];
    const wrap = el("div", "table-wrap");
    const t = el("table");
    const head = el("tr");
    ["周期", "SPY", "看涨组平均", "看涨组上涨比例", "看跌组平均", "看跌组下跌比例", "看涨−看跌", "相关性"].forEach((h) => head.appendChild(el("th", null, h)));
    t.appendChild(head);
    rows.forEach(([k, name]) => {
      const g = r[k];
      const tr = el("tr");
      tr.appendChild(el("td", null, name));
      if (!g) { const td = el("td", "note", "数据还不够"); td.colSpan = 7; tr.appendChild(td); t.appendChild(tr); return; }
      tr.appendChild(el("td", null, pct(g.spy_ret)));
      tr.appendChild(el("td", g.bull.avg_ret > 0 ? "pos" : "neg", pct(g.bull.avg_ret)));
      tr.appendChild(el("td", null, g.bull.hit_rate == null ? "—" : g.bull.hit_rate + "%"));
      tr.appendChild(el("td", g.bear.avg_ret < 0 ? "pos" : "neg", pct(g.bear.avg_ret)));
      tr.appendChild(el("td", null, g.bear.hit_rate == null ? "—" : g.bear.hit_rate + "%"));
      tr.appendChild(el("td", g.bull_minus_bear > 0 ? "pos" : "neg", pct(g.bull_minus_bear)));
      tr.appendChild(el("td", null, g.rank_corr == null ? "—" : g.rank_corr));
      t.appendChild(tr);
    });
    wrap.appendChild(t);
    box.appendChild(wrap);
    const v = el("p", "warn");
    v.textContent = `最近 ${r.rolling.days} 个交易日结论：${r.verdict}。${r.action}`;
    box.appendChild(v);
    const sg = r.signals;
    box.appendChild(el("p", null, `信号战绩：已平仓 ${sg.closed} 笔，赢 ${sg.wins} 笔${sg.closed ? `，胜率 ${sg.win_rate}%，平均 ${pct(sg.avg_pnl_pct)}` : ""}`));
  }

  fetch("data/options/review/latest.json", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((r) => r && renderReview(r))
    .catch(() => {});

  fetch("data/options/latest.json", { cache: "no-store" })
    .then((r) => {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    })
    .then(render)
    .catch(() => {
      $("meta").textContent = "还没有发布评分数据。";
    });
})();
