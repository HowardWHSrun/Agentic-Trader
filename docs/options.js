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
  const pct = (x, d = 1) => (x == null ? "—" : (x > 0 ? "+" : "") + Number(x).toFixed(d) + "%");
  const sign = (x) => (x == null || x === 0 ? "" : x > 0 ? "pos" : "neg");
  const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
  const weekday = (d) => WEEK[new Date(d + "T12:00:00Z").getUTCDay()];
  const legs = (s) =>
    s.legs.map((l) => (l.qty > 0 ? "买 " : "卖 ") + l.strike + (s.type === "call" ? " Call" : " Put")).join(" / ") + " · " + s.expiration + " 到期";
  const DIR = { 看涨: "趋势强", 看跌: "趋势弱", 观望: "中性" };
  const dirTag = (d) => el("span", "tag " + (d === "看涨" ? "call" : d === "看跌" ? "put" : "wait"), DIR[d] || d);
  const clear = (...ids) => ids.forEach((id) => ($(id).textContent = ""));

  function tile(label, value, cls, sub) {
    const t = el("div", "tile");
    t.appendChild(el("div", "tile-l", label));
    t.appendChild(el("div", "tile-v " + (cls || ""), value));
    if (sub) t.appendChild(el("div", "tile-s", sub));
    return t;
  }

  function signalCard(s, kind) {
    const c = el("div", "card " + (kind === "exit" ? "exit" : s.type));
    const h = el("h3", null, (kind === "exit" ? "退场 " : "进场 ") + s.symbol + " ");
    h.appendChild(el("span", "tag " + s.type, s.type === "call" ? "看涨 Call" : "看跌 Put"));
    c.appendChild(h);
    c.appendChild(el("p", null, legs(s)));
    if (kind === "exit") {
      c.appendChild(el("p", null, `${s.exit_reason} · 进场 ${num(s.entry_cost)} → 退场 ${num(s.last_value)}（${pct(s.pnl_pct)}）`));
    } else {
      c.appendChild(el("p", null, `评分 ${s.score_at_entry} · 当时股价 ${s.underlying_at_entry} · 成本约 ${num(s.entry_cost)}（每张约 $${Math.round(s.cost_per_contract)}，这是最大亏损）`));
      c.appendChild(el("p", null, `止损 ${s.stop_value} · 止盈 ${s.target_value} · 最晚 ${s.exit_by} 退场 · 盈亏平衡 ${s.breakeven}`));
    }
    return c;
  }

  function shortStatus(status) {
    if (!status) return "可进场";
    if (/上限/.test(status)) return "太贵";
    if (/财报/.test(status)) return "财报临近";
    if (/太多/.test(status)) return "涨跌过头";
    if (/持仓/.test(status)) return "已有信号";
    if (/价差/.test(status)) return "期权难成交";
    return "暂不进";
  }

  function focusCard(r, blocked) {
    const up = r.direction === "看涨";
    const c = el("details", "pick " + (up ? "call" : "put"));
    const h = el("summary");
    h.appendChild(el("span", "pick-sym", r.symbol));
    h.appendChild(el("span", "pick-score", String(r.score)));
    if (r.score_prev_close != null && r.score !== r.score_prev_close) {
      const d = r.score - r.score_prev_close;
      h.appendChild(el("span", "delta " + sign(d), `${d > 0 ? "▲" : "▼"}${Math.abs(d)}`));
    }
    const px = el("span", "pick-px", `${num(r.price)} `);
    px.appendChild(el("span", sign(r.day_pct), pct(r.day_pct)));
    h.appendChild(px);
    const status = blocked[r.symbol];
    const setup = r.setup || "";
    const label = setup === "回调信号" ? "回调信号" : setup === "接近信号" ? "接近信号" : r.uptrend ? "等回调" : "不做";
    h.appendChild(el("span", "pick-st" + (setup === "回调信号" ? " ok" : ""), label));
    c.appendChild(h);
    const main = up ? r.why_bull : r.why_bear;
    const other = up ? r.why_bear : r.why_bull;
    c.appendChild(el("h4", null, up ? "趋势强在哪" : "趋势弱在哪"));
    const ul = el("ul");
    (main || []).slice(0, 6).forEach((x) => ul.appendChild(el("li", null, x)));
    c.appendChild(ul);
    c.appendChild(el("h4", null, "反向信号"));
    const ul2 = el("ul");
    ((other || []).length ? other.slice(0, 3) : ["暂无明显反向信号"]).forEach((x) => ul2.appendChild(el("li", null, x)));
    c.appendChild(ul2);
    const single = r.contracts && r.contracts.single;
    if (single) c.appendChild(el("p", "note", `参考合约：${single.strike} ${single.type === "call" ? "Call" : "Put"}，${single.expiration} 到期，约 $${Math.round(single.cost_per_contract)}/张`));
    c.appendChild(el("p", "note", "状态：" + (setup || "—") + (status ? "。" + status : "")));
    return c;
  }

  function render(d) {
    clear("tiles", "exits", "entries", "open", "bulls", "bears", "rows", "rule-list", "watchrows");
    (d.watchlist || []).forEach((w) => {
      const tr = el("tr");
      tr.appendChild(el("td", "b", w.symbol));
      tr.appendChild(el("td", "r b " + (w.rsi2 < 5 ? "pos" : ""), w.dip_score == null ? "—" : String(w.dip_score)));
      tr.appendChild(el("td", "r", num(w.rsi2, 0)));
      tr.appendChild(el("td", "r", num(w.price)));
      tr.appendChild(el("td", null, w.setup));
      $("watchrows").appendChild(tr);
    });
    if (!(d.watchlist || []).length) {
      const tr = el("tr");
      const td = el("td", "note", "这一天的数据没有这项（v2 之前）。");
      td.colSpan = 5;
      tr.appendChild(td);
      $("watchrows").appendChild(tr);
    }
    const day = d.session_date || d.generated_at_ct.slice(0, 10);
    const rows = d.rankings.filter((r) => r.score != null);
    const bulls = rows.filter((r) => r.direction === "看涨");
    const bears = rows.filter((r) => r.direction === "看跌").reverse();
    const blocked = Object.fromEntries((d.blocked || []).map((b) => [b.symbol, b.reason]));

    $("day-title").textContent = `${day} ${weekday(day)}`;
    const time = d.generated_at_ct.slice(11);
    $("stamp-text").textContent = `当天第 ${d.scan_no || "—"} 次扫描 · 最后更新 ${time} · 规则 ${d.rules_version}` + (d.prev_session_date ? ` · 对比基准：${d.prev_session_date} 收盘` : "");

    const movers = rows.filter((r) => r.score_prev_close != null).map((r) => ({ s: r.symbol, d: r.score - r.score_prev_close }));
    const upM = movers.slice().sort((a, b) => b.d - a.d)[0];
    const dnM = movers.slice().sort((a, b) => a.d - b.d)[0];
    $("tiles").appendChild(tile("大盘 SPY 当日", pct(d.spy_day_pct, 2), sign(d.spy_day_pct)));
    $("tiles").appendChild(tile("趋势强 / 中性 / 趋势弱", `${bulls.length} / ${rows.length - bulls.length - bears.length} / ${bears.length}`));
    $("tiles").appendChild(tile("评分上升最多", upM && upM.d > 0 ? `${upM.s} +${upM.d}` : "—", "pos", "较上一交易日收盘"));
    $("tiles").appendChild(tile("评分下降最多", dnM && dnM.d < 0 ? `${dnM.s} ${dnM.d}` : "—", "neg", "较上一交易日收盘"));

    const todays = d.open.filter((s) => s.entry_date === day);
    const flips = rows.filter((r) => r.score_prev_close != null && ((r.score >= 70 && r.score_prev_close < 70) || (r.score <= 30 && r.score_prev_close > 30)));
    $("lead").textContent =
      `最高分：${rows.slice(0, 3).map((r) => `${r.symbol} ${r.score}`).join("、")}；最低分：${rows.slice(-3).reverse().map((r) => `${r.symbol} ${r.score}`).join("、")}。` +
      (flips.length ? `今天新进入看涨/看跌区的：${flips.map((r) => `${r.symbol}（${r.score_prev_close}→${r.score}）`).join("、")}。` : "今天没有股票新进入看涨或看跌区。") +
      `当天新信号 ${todays.length} 个，退场 ${d.exits.length} 个。`;

    d.exits.forEach((s) => $("exits").appendChild(signalCard(s, "exit")));
    todays.forEach((s) => $("entries").appendChild(signalCard(s, "entry")));
    $("none").hidden = todays.length + d.exits.length > 0;
    const held = d.open.filter((s) => s.legs);
    $("open-title").hidden = $("open-wrap").hidden = held.length === 0;
    held.forEach((s) => {
      const tr = el("tr");
      tr.appendChild(el("td", "b", s.symbol));
      const td = el("td");
      td.appendChild(el("span", "tag " + s.type, s.type === "call" ? "看涨" : "看跌"));
      tr.appendChild(td);
      tr.appendChild(el("td", null, legs(s)));
      tr.appendChild(el("td", null, s.entry_date));
      tr.appendChild(el("td", "r", num(s.entry_cost)));
      tr.appendChild(el("td", "r", num(s.last_value != null ? s.last_value : s.entry_cost)));
      tr.appendChild(el("td", "r " + sign(s.pnl_pct), pct(s.pnl_pct)));
      tr.appendChild(el("td", null, s.exit_by));
      $("open").appendChild(tr);
    });

    bulls.slice(0, 5).forEach((r) => $("bulls").appendChild(focusCard(r, blocked)));
    bears.slice(0, 5).forEach((r) => $("bears").appendChild(focusCard(r, blocked)));

    const entered = new Set(todays.map((e) => e.symbol));
    rows.forEach((r) => {
      const tr = el("tr");
      tr.appendChild(el("td", null, r.rank));
      tr.appendChild(el("td", "b", r.symbol));
      const sc = el("td", "nw", String(r.score));
      const b = el("span", "bar" + (r.score <= 30 ? " low" : r.score < 70 ? " mid" : ""));
      const i = el("i");
      i.style.width = r.score + "%";
      b.appendChild(i);
      sc.appendChild(b);
      tr.appendChild(sc);
      const dl = r.score_prev_close == null ? null : r.score - r.score_prev_close;
      tr.appendChild(el("td", "r " + sign(dl), dl == null ? "—" : dl === 0 ? "0" : (dl > 0 ? "+" : "") + dl));
      tr.appendChild(el("td", "r muted", r.score_open == null ? "—" : r.score_open));
      const dt = el("td");
      dt.appendChild(dirTag(r.direction));
      tr.appendChild(dt);
      tr.appendChild(el("td", "r", num(r.price)));
      tr.appendChild(el("td", "r " + sign(r.day_pct), pct(r.day_pct)));
      tr.appendChild(el("td", "r " + sign(r.ret20), pct(r.ret20)));
      tr.appendChild(el("td", "r " + sign(r.rel_spy20), pct(r.rel_spy20)));
      tr.appendChild(el("td", "r", num(r.rsi14, 0)));
      tr.appendChild(el("td", "r", r.rsi2 == null ? "—" : num(r.rsi2, 0)));
      const side = r.direction === "看涨" ? r.why_bull : r.direction === "看跌" ? r.why_bear : [].concat((r.why_bull || []).slice(0, 1), (r.why_bear || []).slice(0, 1));
      const key = (side || []).filter((x) => /跑|RSI|过多/.test(x)).slice(0, 2);
      tr.appendChild(el("td", "note", (key.length ? key : (side || []).slice(0, 2)).join("；")));
      let note = entered.has(r.symbol) ? "✅ 当天进场" : [r.setup, blocked[r.symbol]].filter(Boolean).join("：");
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
    if (!r) {
      box.appendChild(el("p", "muted", "这一天还没有收盘复盘（收盘后约 15:50 CT 生成）。"));
      return;
    }
    const wrap = el("div", "table-wrap");
    const t = el("table");
    const head = el("tr");
    ["周期", "SPY", "看涨组平均", "真的涨了", "看跌组平均", "真的跌了", "看涨 − 看跌", "相关性"].forEach((h, i) => head.appendChild(el("th", i ? "r" : null, h)));
    t.appendChild(head);
    [["same_day", "当天（今早分数 → 收盘）"], ["one_day", "1 天（昨日分数 → 今日）"], ["five_day", "5 天"]].forEach(([k, name]) => {
      const g = r[k];
      const tr = el("tr");
      tr.appendChild(el("td", null, name));
      if (!g) {
        const td = el("td", "note", "数据还不够");
        td.colSpan = 7;
        tr.appendChild(td);
        t.appendChild(tr);
        return;
      }
      tr.appendChild(el("td", "r " + sign(g.spy_ret), pct(g.spy_ret, 2)));
      tr.appendChild(el("td", "r " + sign(g.bull.avg_ret), pct(g.bull.avg_ret, 2)));
      tr.appendChild(el("td", "r", g.bull.hit_rate == null ? "—" : g.bull.hit_rate + "%"));
      tr.appendChild(el("td", "r " + sign(g.bear.avg_ret == null ? null : -g.bear.avg_ret), pct(g.bear.avg_ret, 2)));
      tr.appendChild(el("td", "r", g.bear.hit_rate == null ? "—" : g.bear.hit_rate + "%"));
      tr.appendChild(el("td", "r " + sign(g.bull_minus_bear), pct(g.bull_minus_bear, 2)));
      tr.appendChild(el("td", "r", g.rank_corr == null ? "—" : g.rank_corr));
      t.appendChild(tr);
    });
    wrap.appendChild(t);
    box.appendChild(wrap);
    box.appendChild(el("p", "warn", `最近 ${r.rolling.days} 个交易日结论：${r.verdict}。${r.action}`));
    box.appendChild(el("p", "muted", "\"看涨 − 看跌\"为正，说明高分股票跑赢了低分股票；相关性越接近 +1 说明分数越准。攒够 10 个交易日才会据此调整方法。"));
  }

  const getJSON = (url) => fetch(url, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);

  function load(day) {
    const src = day ? `data/options/days/${day}.json` : "data/options/latest.json";
    getJSON(src).then((d) => {
      if (!d) {
        $("day-title").textContent = "还没有发布评分数据";
        return;
      }
      render(d);
      const date = d.session_date || d.generated_at_ct.slice(0, 10);
      getJSON(`data/options/review/${date}.json`).then(renderReview);
    });
  }

  getJSON("data/options/days/index.json").then((idx) => {
    const sel = $("day-select");
    const dates = (idx && idx.dates) || [];
    dates.forEach((d, i) => {
      const o = el("option", null, `${d} ${weekday(d)}${i === 0 ? "（最新）" : ""}`);
      o.value = d;
      sel.appendChild(o);
    });
    sel.addEventListener("change", () => load(sel.value));
    load(dates[0] || null);
  });
})();
