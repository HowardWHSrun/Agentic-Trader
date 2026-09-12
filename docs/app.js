/* Public, static research journal. No broker connection, execution, or telemetry. */
"use strict";

const $ = (selector) => document.querySelector(selector);
const state = {
  data: null, loading: false, error: null,
  journal: { search: "", decision: "all", date: "all" },
  universe: { search: "", kind: "all", match: "all", sector: "all" },
  sort: { key: "symbol", ascending: true },
};
const pageNames = { overview: "Overview", journal: "Research journal", universe: "Market universe", strategy: "Strategy", learn: "Learn" };
const decisionNames = {
  no_opportunity: "No opportunity", watch_only: "Watch only",
  qualified_opportunity: "Qualified opportunity", monitor_failure: "Check needs attention",
};
const checkNames = { baseline_archive: "Archived baseline", intraday: "Intraday review", after_close: "After-close review", failed_check: "Failed check" };
const moneyFormatter = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const numeric = (value) => typeof value === "number" && Number.isFinite(value);
const money = (value) => numeric(value) ? moneyFormatter.format(value) : "—";
const fixed = (value, digits = 2) => numeric(value) ? value.toFixed(digits) : "—";
const percent = (value, signed = false) => numeric(value) ? `${signed && value > 0 ? "+" : ""}${fixed(value)}%` : "—";
const pp = (value) => numeric(value) ? `${value > 0 ? "+" : ""}${fixed(value)} pp` : "—";
const ratio = (value) => numeric(value) ? `${fixed(value)}×` : "—";
const array = (value) => Array.isArray(value) ? value : [];
const object = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const words = (value) => typeof value === "string" ? value.replaceAll("_", " ") : "Unknown";
const groupName = (value) => words(value).replace(/\b\w/g, (letter) => letter.toUpperCase());
const securityName = (value) => value === "etf" ? "ETF" : value === "stock" ? "Stock" : "Unknown type";
const textValue = (value) => {
  if (value == null) return "Not recorded";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(textValue).join(" · ");
  if (typeof value === "object") return [value.title, value.text || value.detail || value.description || value.observation || value.lesson].filter(Boolean).map(textValue).join(" — ") || JSON.stringify(value);
  return String(value);
};

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "value") node.value = value;
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function safeExternalUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

function date(value, includeTime = false) {
  if (!value || typeof value !== "string") return "Unknown date";
  const parsed = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00Z` : value);
  if (Number.isNaN(parsed.getTime())) return "Unknown date";
  const options = { month: "short", day: "numeric", year: "numeric", timeZone: "America/Chicago" };
  if (includeTime) Object.assign(options, { hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  return new Intl.DateTimeFormat("en-US", options).format(parsed);
}

function localDate(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "unknown" : new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: "America/Chicago" }).format(parsed);
}

function age(value) {
  const time = new Date(value || "").getTime();
  if (!Number.isFinite(time)) return "age unknown";
  const minutes = Math.floor((Date.now() - time) / 60000);
  if (minutes < -5) return "timestamp is in the future";
  if (minutes < 1) return "less than a minute ago";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return `${Math.floor(minutes / 1440)}d ago`;
}

function readRoute() {
  let parts;
  try { parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent); }
  catch { parts = ["overview"]; }
  const page = Object.hasOwn(pageNames, parts[0]) ? parts[0] : "overview";
  const entryIndex = parts.indexOf("entry");
  const symbolIndex = parts.indexOf("symbol");
  return { page, entry: entryIndex >= 0 ? parts[entryIndex + 1] : null, symbol: symbolIndex >= 0 ? parts[symbolIndex + 1] : null };
}

function entries() { return array(state.data?.entries); }
function selectedEntry(route = readRoute()) { return entries().find((entry) => entry.id === route.entry) || entries()[0] || null; }
function entryUrl(entry, page = "journal") { return `#${page}/entry/${encodeURIComponent(entry.id)}`; }
function candidateUrl(candidate, entry) { return `#universe/symbol/${encodeURIComponent(candidate.symbol)}/entry/${encodeURIComponent(entry.id)}`; }
function isArchive(entry) { return entry?.check_type === "baseline_archive"; }
function isFailure(entry) { return entry?.check_type === "failed_check" || entry?.decision === "monitor_failure"; }
function decisionLabel(entry) { return decisionNames[entry?.decision] || "Decision not recorded"; }
function badge(text, tone = "") { return el("span", { class: `badge ${tone}` }, text); }
function decisionBadge(entry) { return badge(decisionLabel(entry), isFailure(entry) ? "red" : entry.decision === "qualified_opportunity" ? "teal" : "amber"); }
function sourceState(entry) { return isFailure(entry) ? "Carried-forward data · not a current check" : isArchive(entry) ? "Historical snapshot · not a fresh signal" : "Published snapshot · not a live quote"; }
function title(text, subtitle, aside) { return el("div", { class: "page-heading" }, el("div", {}, el("h1", {}, text), el("p", {}, subtitle)), aside ? el("span", { class: "heading-count" }, aside) : null); }
function sectionHead(heading, subtitle, linkText, href) { return el("div", { class: "section-head" }, el("div", {}, el("h2", {}, heading), subtitle ? el("p", {}, subtitle) : null), href ? el("a", { class: "text-link", href }, linkText) : null); }
function empty(titleText, copy) { return el("div", { class: "empty-card" }, el("h3", {}, titleText), el("p", {}, copy)); }
function itemList(values, fallback = "Nothing recorded for this check.") { return el("ul", { class: "plain-list" }, (array(values).length ? values : [fallback]).map((value) => el("li", {}, textValue(value)))); }
function ticker(candidate) { return el("span", { class: `ticker-icon ${candidate.kind === "stock" ? "stock" : "etf"}`, "aria-hidden": "true" }, String(candidate.symbol || "?").slice(0, 3)); }
function textSection(heading, text) { return el("section", { class: "detail-section" }, el("h3", {}, heading), el("p", {}, textValue(text))); }

function snapshotStatus(entry) {
  if (!entry) {
    $("#snapshot-text").textContent = state.error ? "Published research could not be loaded." : "No published checks yet.";
    $("#snapshot-tail").textContent = "No live prices";
    return;
  }
  const stateLabel = isFailure(entry) ? "Failed check / carried-forward signals" : isArchive(entry) ? "Archived baseline" : "Published check";
  $("#snapshot-text").textContent = `${stateLabel} · Signal session ${date(entry.signal_session)} · Checked ${date(entry.checked_at, true)}`;
  $("#snapshot-tail").textContent = `${age(entry.checked_at)} · No live prices`;
}

function stats(entry) {
  const candidates = Array.isArray(entry.candidates) ? entry.candidates : null;
  const techCount = candidates ? candidates.filter((candidate) => candidate.technical_match === true).length : "—";
  const qualified = Object.hasOwn(decisionNames, entry.decision) ? (entry.decision === "qualified_opportunity" ? 1 : 0) : "—";
  const rules = object(state.data?.risk_rules);
  const weekly = numeric(rules.max_new_entries_per_week) ? rules.max_new_entries_per_week : "—";
  return el("div", { class: "stat-grid" }, [
    ["Universe reviewed", candidates ? candidates.length : "—", "U.S. stocks & unleveraged ETFs", "◎"],
    ["Technical matches", techCount, isArchive(entry) || isFailure(entry) ? "At the recorded signal session" : "Research candidates, still need checks", "⌁"],
    ["Qualified opportunities", qualified, qualified === 0 ? "No new entry from this check" : "Lead opportunity; manual review required", "↗"],
    ["Weekly entry ceiling", weekly, "A limit, never a target", "◷"],
  ].map(([label, value, description, icon]) => el("div", { class: "stat-card" },
    el("div", { class: "stat-label" }, label, el("span", { class: "stat-icon", "aria-hidden": "true" }, icon)),
    el("div", { class: "stat-value" }, value), el("div", { class: "stat-description" }, description))));
}

function benchmarkPanel(entry) {
  const gate = object(entry.market_gate);
  const benchmarks = object(gate.benchmarks);
  const tone = gate.passed === true ? "teal" : "amber";
  const gatePrefix = isFailure(entry) ? "Prior gate" : "Recorded gate";
  const gateLabel = gate.passed === true ? `${gatePrefix} passed` : gate.passed === false ? `${gatePrefix} paused` : "Gate unknown";
  const heading = isFailure(entry) ? "Prior market context" : "Market context";
  return el("section", { class: "panel" },
    el("div", { class: "panel-heading" }, el("h2", {}, heading), badge(gateLabel, tone)),
    el("div", { class: "benchmark-list" }, ["SPY", "QQQ"].map((symbol) => {
      const benchmark = object(benchmarks[symbol]);
      const difference = numeric(benchmark.close) && numeric(benchmark.sma50) && benchmark.sma50 > 0 ? (benchmark.close / benchmark.sma50 - 1) * 100 : null;
      return el("div", { class: "benchmark-row" }, ticker({ symbol, kind: "etf" }), el("div", {}, el("div", { class: "ticker-name" }, symbol), el("div", { class: "ticker-detail" }, symbol === "SPY" ? "S&P 500 · broad market" : "Nasdaq-100 · growth")), el("div", { class: "benchmark-price" }, money(benchmark.close), el("small", {}, numeric(difference) ? `${percent(difference, true)} vs 50-day average` : "Average comparison unavailable")));
    })),
    el("div", { class: "benchmark-foot" }, `${sourceState(entry)}. Prices from ${date(entry.signal_session)}.`));
}

function recentPanel() {
  return el("section", { class: "panel" }, el("div", { class: "panel-heading" }, el("h2", {}, "From the journal"), el("a", { class: "text-link", href: "#journal" }, "View all")),
    entries().slice(0, 3).map((entry) => el("article", { class: "timeline-item" }, el("div", { class: "timeline-date" }, date(entry.checked_at, true)), el("a", { class: "timeline-title", href: entryUrl(entry) }, decisionLabel(entry)), el("p", { class: "timeline-copy" }, textValue(entry.summary)))));
}

function candidateCard(candidate, entry) {
  const metrics = object(candidate.metrics);
  return el("a", { class: "candidate-card", href: candidateUrl(candidate, entry), "aria-label": `Open ${candidate.symbol} research from ${date(entry.signal_session)}` },
    el("div", { class: "candidate-top" }, ticker(candidate), el("div", {}, el("div", { class: "ticker-name" }, candidate.symbol), el("div", { class: "ticker-detail" }, securityName(candidate.kind))), badge(isArchive(entry) || isFailure(entry) ? "Historical match" : "Needs checks", "amber")),
    el("div", { class: "candidate-metrics" }, el("div", {}, el("span", {}, "Recorded close"), el("strong", {}, money(metrics.close))), el("div", {}, el("span", {}, "20D vs SPY"), el("strong", { class: "relative" }, pp(metrics.relative_return_20)))),
    el("div", { class: "candidate-bottom" }, el("span", {}, array(candidate.setup_types).map(words).join(" · ") || "Technical review"), el("span", { class: "arrow-circle", "aria-hidden": "true" }, "↗")));
}

function overview(entry) {
  const archived = isArchive(entry), failed = isFailure(entry);
  const heroTitle = failed ? "A pause for better information." : archived ? "A baseline. A disciplined beginning." : entry.decision === "qualified_opportunity" ? "One idea worth a closer look." : entry.decision === "watch_only" ? "Interesting. Not actionable yet." : "No trade is a decision.";
  const heroCopy = failed ? "This review could not be completed. Any retained signals below are carried forward from an earlier snapshot and must not be treated as current." : archived ? "The starting point for the journal. Historical technical matches are recorded here with their limitations. No fresh opportunity is being called." : textValue(entry.summary);
  const candidates = array(entry.candidates).filter((candidate) => candidate.technical_match === true);
  const lesson = array(entry.lessons)[0];
  return [
    title("The research desk", "A considered view of the market. Every opportunity has to earn its place.", date(entry.signal_session)),
    el("section", { class: "hero" }, el("div", { class: "hero-copy" }, el("p", { class: "eyebrow" }, archived ? "THE OPENING RECORD" : "LATEST RESEARCH DECISION"), el("h2", {}, heroTitle), el("p", {}, heroCopy), el("a", { class: "text-link", href: entryUrl(entry) }, "Read the full check")), el("div", { class: "hero-graphic", "aria-hidden": "true" }, el("div", { class: "decision-emblem" }, el("span", { class: "emblem-symbol" }, failed ? "!" : "⌁"), el("span", { class: "emblem-text" }, archived ? "BASELINE ARCHIVE" : "STAY SELECTIVE")), el("span", { class: "graphic-caption" }, "PATIENCE IS PART OF THE PROCESS"))),
    stats(entry), el("div", { class: "two-col" }, benchmarkPanel(entry), recentPanel()),
    sectionHead("Ideas under the microscope", "Technical matches are starting points. All blockers remain visible.", "Explore the universe", "#universe"),
    el("div", { class: "candidate-grid" }, candidates.length ? candidates.slice(0, 6).map((candidate) => candidateCard(candidate, entry)) : empty("No technical matches in this check", "An empty watchlist is a useful result. There is no need to manufacture a trade.")),
    el("section", { class: "lesson-strip" }, el("span", { class: "lesson-icon", "aria-hidden": "true" }, "◇"), el("div", {}, el("p", { class: "eyebrow" }, "A NOTE TO CARRY FORWARD"), el("h3", {}, "The decision matters as much as the outcome."), el("p", {}, lesson ? textValue(lesson) : "Keep a record of what was known, what was missing, and what would change the decision. This journal tracks research, not investment performance."))),
    el("p", { class: "section-note" }, `${textValue(entry.data_freshness)} All prices and indicators refer to the labeled snapshot. Refreshing this page only reloads published records; it does not request new market data.`),
  ];
}

function field(labelText, id, control, grow = false) {
  control.id = id;
  return el("div", { class: `field${grow ? " grow" : ""}` }, el("label", { for: id }, labelText), control);
}

function selectControl(options, value, callback) {
  const select = el("select", { onchange: (event) => callback(event.target.value) }, options.map(([key, text]) => el("option", { value: key }, text)));
  select.value = value;
  return select;
}

function sourcesList(sources) {
  const valid = array(sources).filter((source) => source && safeExternalUrl(source.url));
  return valid.length ? el("ul", { class: "source-list" }, valid.map((source) => el("li", {}, el("a", { href: safeExternalUrl(source.url), target: "_blank", rel: "noopener noreferrer" }, `${source.title || "Source"} ↗`), el("small", {}, `As of ${source.as_of ? textValue(source.as_of) : "date not recorded"}`)))) : el("p", { class: "section-note" }, "No public source links were recorded for this check.");
}

function journalDetail(entry) {
  return el("article", { class: "panel journal-detail", "aria-label": `Research check from ${date(entry.checked_at, true)}` },
    el("div", { class: "panel-heading" }, badge(checkNames[entry.check_type] || "Research record"), decisionBadge(entry)),
    el("h2", {}, decisionLabel(entry)), el("p", { class: "dialog-source-date" }, `${date(entry.checked_at, true)} · Signal session ${date(entry.signal_session)}`),
    el("p", { class: "summary-copy" }, textValue(entry.summary)),
    el("div", { class: "note-box" }, `${sourceState(entry)}. ${textValue(entry.data_freshness)}`),
    el("section", { class: "detail-section" }, el("h3", {}, "What the check observed"), itemList(entry.observations)),
    el("section", { class: "detail-section" }, el("h3", {}, "Why it cannot be treated as a buy signal"), itemList(entry.data_blockers, "No data blockers recorded. Candidate, account, earnings, and execution checks still apply.")),
    el("section", { class: "detail-section" }, el("h3", {}, "Technical candidates in this record"), el("div", { class: "chips" }, array(entry.candidates).filter((candidate) => candidate.technical_match === true).map((candidate) => el("a", { class: "chip", href: candidateUrl(candidate, entry) }, `${candidate.symbol} ↗`))), array(entry.candidates).some((candidate) => candidate.technical_match === true) ? null : el("p", { class: "section-note" }, "No technical matches recorded.")),
    el("section", { class: "detail-section" }, el("h3", {}, "Lessons for the next check"), itemList(entry.lessons)),
    el("section", { class: "detail-section" }, el("h3", {}, "Sources used"), sourcesList(entry.sources)),
    textSection("Notification record", entry.notification?.reason || "No notification record supplied."));
}

function journal() {
  const results = el("div", {});
  const draw = () => {
    const filters = state.journal;
    const query = filters.search.trim().toLowerCase();
    const matches = entries().filter((entry) => (filters.decision === "all" || entry.decision === filters.decision) && (filters.date === "all" || localDate(entry.checked_at) === filters.date) && (!query || [entry.summary, ...array(entry.observations).map(textValue), ...array(entry.lessons).map(textValue), ...array(entry.candidates).map((candidate) => candidate.symbol)].join(" ").toLowerCase().includes(query)));
    const selected = matches.find((entry) => entry.id === readRoute().entry) || matches[0];
    results.replaceChildren(el("p", { class: "result-count" }, `${matches.length} ${matches.length === 1 ? "record" : "records"} · Newest first`), matches.length ? el("div", { class: "journal-grid" },
      el("div", { class: "journal-list", "aria-label": "Research history" }, matches.map((entry) => el("a", { class: `journal-card${entry.id === selected.id ? " selected" : ""}`, href: entryUrl(entry), "aria-current": entry.id === selected.id ? "true" : null }, el("div", { class: "journal-card-date" }, date(entry.checked_at, true)), el("h3", {}, decisionLabel(entry)), decisionBadge(entry), el("p", {}, `${checkNames[entry.check_type] || "Research check"} · Signal ${date(entry.signal_session)}`)))), journalDetail(selected)) : empty("No matching records", "Try a different date, decision, or search term."));
  };
  const dateOptions = [["all", "All dates"], ...[...new Set(entries().map((entry) => localDate(entry.checked_at)))].filter((value) => value !== "unknown").map((value) => [value, date(value)])];
  const filters = el("div", { class: "filters" },
    field("Search the journal", "journal-search", el("input", { type: "search", placeholder: "Search symbols, observations, lessons…", value: state.journal.search, oninput: (event) => { state.journal.search = event.target.value; draw(); } }), true),
    field("Decision", "journal-decision", selectControl([["all", "All decisions"], ...Object.entries(decisionNames)], state.journal.decision, (value) => { state.journal.decision = value; draw(); })),
    field("Check date · Chicago", "journal-date", selectControl(dateOptions, state.journal.date, (value) => { state.journal.date = value; draw(); })));
  draw();
  return [title("Research journal", "An honest record of what was checked, what was missing, and what we learned."), filters, results];
}

function universe(entry) {
  const candidates = array(entry.candidates);
  const results = el("div", {});
  const sectors = [...new Set(candidates.map((candidate) => candidate.sector).filter(Boolean))].sort();
  const sortColumns = [["symbol", "Symbol"], ["kind", "Type"], ["close", "Recorded close"], ["relative_return_20", "20D vs SPY"], ["relative_volume", "Rel. volume"], ["technical_match", "Technical result"], ["sector", "Group"]];
  const valueForSort = (candidate, key) => ["close", "relative_return_20", "relative_volume"].includes(key) ? candidate.metrics?.[key] : candidate[key];
  const draw = () => {
    const filters = state.universe;
    const query = filters.search.trim().toLowerCase();
    const matches = candidates.filter((candidate) => (filters.kind === "all" || candidate.kind === filters.kind) && (filters.match === "all" || String(candidate.technical_match === true) === filters.match) && (filters.sector === "all" || candidate.sector === filters.sector) && (!query || `${candidate.symbol} ${candidate.sector} ${groupName(candidate.sector)}`.toLowerCase().includes(query)));
    matches.sort((a, b) => {
      const av = valueForSort(a, state.sort.key), bv = valueForSort(b, state.sort.key);
      if (av == null && bv == null) return String(a.symbol).localeCompare(String(b.symbol));
      if (av == null) return 1;
      if (bv == null) return -1;
      const comparison = typeof av === "number" && typeof bv === "number" ? av - bv : typeof av === "boolean" ? Number(av) - Number(bv) : String(av).localeCompare(String(bv));
      return comparison * (state.sort.ascending ? 1 : -1);
    });
    const maximum = Math.max(1, ...candidates.map((candidate) => numeric(candidate.metrics?.relative_return_20) ? Math.abs(candidate.metrics.relative_return_20) : 0));
    const table = el("table", {}, el("thead", {}, el("tr", {}, sortColumns.map(([key, label]) => el("th", { scope: "col", "aria-sort": state.sort.key === key ? state.sort.ascending ? "ascending" : "descending" : "none" }, el("button", { onclick: () => { state.sort.ascending = state.sort.key === key ? !state.sort.ascending : ["symbol", "kind", "sector"].includes(key); state.sort.key = key; draw(); const button = results.querySelector(`button[data-sort="${key}"]`); button?.focus(); }, "data-sort": key, "aria-label": `Sort by ${label}` }, label, el("span", { "aria-hidden": "true" }, state.sort.key === key ? state.sort.ascending ? "↑" : "↓" : "↕")))))),
      el("tbody", {}, matches.map((candidate) => {
        const metrics = object(candidate.metrics);
        const relative = metrics.relative_return_20;
        const bar = el("div", { class: `mini-bar${numeric(relative) && relative < 0 ? " negative" : ""}` });
        bar.style.width = `${numeric(relative) ? Math.abs(relative) / maximum * 100 : 0}%`;
        return el("tr", {},
          el("td", {}, el("div", { class: "symbol-cell" }, ticker(candidate), el("a", { class: "symbol-link", href: candidateUrl(candidate, entry), "aria-label": `Open ${candidate.symbol} research details` }, candidate.symbol))),
          el("td", {}, candidate.kind === "etf" ? "ETF" : candidate.kind === "stock" ? "Stock" : "Unknown"), el("td", {}, money(metrics.close)),
          el("td", {}, el("div", { class: "bar-cell" }, el("span", { class: numeric(relative) ? relative >= 0 ? "positive" : "negative" : "" }, pp(relative)), el("div", { class: "mini-bar-track", "aria-hidden": "true" }, bar))),
          el("td", {}, ratio(metrics.relative_volume)), el("td", {}, badge(candidate.technical_match === true ? "Technical match" : candidate.technical_match === false ? "No match" : "Unknown", candidate.technical_match === true ? "teal" : "")),
          el("td", { class: "sector-cell", title: groupName(candidate.sector) }, groupName(candidate.sector)));
      })));
    results.replaceChildren(el("p", { class: "result-count" }, `${matches.length} of ${candidates.length} symbols · Select a symbol to inspect the full reasoning`), matches.length ? el("div", { class: "table-panel" }, el("div", { class: "table-scroll", tabindex: "0", "aria-label": "Market universe table; scroll horizontally for more columns" }, table), el("div", { class: "table-foot" }, `Signal session ${date(entry.signal_session)}. 20D vs SPY is a return difference in percentage points; bar lengths reflect absolute magnitude. All values are historical observations.`)) : empty("No symbols match these filters", "Clear a filter or search for another symbol."));
  };
  draw();
  return [title("Market universe", "Follow the evidence from the broad list to the individual idea.", `${candidates.length} symbols`), el("div", { class: "note-box" }, `${sourceState(entry)}. ${textValue(entry.data_freshness)}`),
    el("div", { class: "filters" }, field("Research record", "universe-entry", selectControl(entries().map((record) => [record.id, `${date(record.checked_at, true)} · ${checkNames[record.check_type] || "Review"}`]), entry.id, (id) => { location.hash = `universe/entry/${encodeURIComponent(id)}`; }), true)),
    el("div", { class: "filters" },
      field("Search symbols or groups", "universe-search", el("input", { type: "search", placeholder: "e.g. AAPL or technology", value: state.universe.search, oninput: (event) => { state.universe.search = event.target.value; draw(); } }), true),
      field("Security type", "universe-kind", selectControl([["all", "All types"], ["stock", "Stocks"], ["etf", "ETFs"]], state.universe.kind, (value) => { state.universe.kind = value; draw(); })),
      field("Technical result", "universe-match", selectControl([["all", "All results"], ["true", "Technical matches"], ["false", "No match"]], state.universe.match, (value) => { state.universe.match = value; draw(); })),
      field("Group", "universe-sector", selectControl([["all", "All groups"], ...sectors.map((sector) => [sector, groupName(sector)])], state.universe.sector, (value) => { state.universe.sector = value; draw(); }))), results];
}

function strategy() {
  const rules = object(state.data?.risk_rules);
  const ruleValue = (key, suffix = "%") => numeric(rules[key]) ? `${rules[key]}${suffix}` : "—";
  const ruleCards = [
    ["Maximum single position", ruleValue("max_position_pct"), "A ceiling on one position’s share of account equity, subject to the other limits."],
    ["Planned risk per trade", ruleValue("risk_per_trade_pct"), "Entry-to-stop risk as a share of equity. It is planned risk, not a maximum possible loss."],
    ["Combined open planned risk", ruleValue("max_open_risk_pct"), "All open positions share this risk budget. Each candidate cannot use it independently."],
    ["Total market exposure", ruleValue("max_total_exposure_pct"), "The combined cost/exposure budget for existing holdings, pending orders, and new entries."],
    ["Maximum group exposure", ruleValue("max_sector_exposure_pct"), "A concentration limit by group. It cannot eliminate overlap or correlation between ETFs."],
    ["Maximum open positions", ruleValue("max_positions", ""), "Fewer moving parts to review. Cash is a valid allocation when the evidence is incomplete."],
  ];
  return [title("The strategy", "Selective swing research, with the constraints written down before the excitement."),
    el("div", { class: "strategy-grid" }, ruleCards.map(([label, value, copy]) => el("article", { class: "rule-card" }, el("p", { class: "eyebrow" }, label), el("div", { class: "rule-value" }, value), el("p", {}, copy)))),
    el("div", { class: "two-col" }, el("section", { class: "panel" }, el("h2", {}, "One process. Five checkpoints."), el("p", { class: "section-note" }, "Scheduled weekday check times in America/Chicago. This is the intended cadence; the journal shows which checks actually completed."),
      el("div", { class: "schedule-list" }, array(state.data?.schedule).map((time) => el("span", { class: "schedule-time" }, time))),
      el("p", { class: "section-note" }, "Daily indicators use completed sessions. Intraday reviews can check quotes, spreads, events, and invalidations without presenting an unfinished daily bar as a new signal."),
      el("div", { class: "note-box" }, `At most ${ruleValue("max_new_entries_per_week", "")} new entry per week. This is a ceiling, not a weekly quota or an income promise.`)),
      el("section", { class: "panel" }, el("h2", {}, "What belongs in the plan"), itemList(["Long U.S. stocks and unleveraged ETFs only.", "No borrowing, options, short selling, or leveraged/inverse products.", "Hold for several days to weeks; verify earnings and event exposure first.", "Use liquid securities and confirm Robinhood availability and order support.", "Every new entry requires a complete, current account and execution review."]))),
    el("section", { class: "panel" }, el("h2", {}, "From a scan to a decision"), el("ol", { class: "process-list" },
      el("li", {}, el("div", {}, el("strong", {}, "Confirm the information"), "Check the exchange calendar, completed session, prices, corporate actions, and whether the data is current enough to use.")),
      el("li", {}, el("div", {}, el("strong", {}, "Let the market and setup qualify"), "Inspect the benchmark trend, liquidity, relative strength, and the breakout or pullback setup. A technical match is only the beginning.")),
      el("li", {}, el("div", {}, el("strong", {}, "Make the risk fit"), "Reconcile holdings and pending orders, earnings dates, unleveraged buying power and settlement status, weekly entries, concentration, and the combined risk budget. Recalculate size at the intended entry.")),
      el("li", {}, el("div", {}, el("strong", {}, "Record a reasoned decision"), "Publish the observations, blockers, and what would change the decision. Missing information, poor sizing, or an unattractive entry means no opportunity.")))),
    el("div", { class: "note-box" }, "Stops are not guarantees. Gaps, slippage, and periods when stops do not execute can produce larger losses than planned. A stop-limit can remain unfilled. An illustrative 2R objective is arithmetic, not a forecast."),
    el("p", { class: "section-note" }, "Risk settings are the values recorded with the published research, not a statement that any order is suitable or approved. The public journal contains no private balances or position sizes.")];
}

function learn() {
  const cards = [
    ["R: make risk comparable", "One R is the planned difference between entry and stop per share. A 2R objective sits two of those distances above entry. It does not mean a trade is likely to reach the objective, and losses can exceed 1R.", "1R = entry − stop · 2R objective = entry + 2 × 1R"],
    ["Relative strength: compared with what?", "Here, relative strength means a stock or ETF’s 20-session return minus SPY’s return over the same sessions. Positive values mean outperformance during that window. They do not predict future outperformance.", "Relative strength = security return − SPY return"],
    ["Relative volume: participation", "Relative volume compares the latest completed session’s share volume with the average of the preceding 20 sessions. Higher volume can add context to a price move. It does not establish that buyers will keep pushing the price higher.", "Relative volume = last session volume ÷ prior 20-session mean"],
    ["Trend: a useful filter", "Moving averages summarize past prices. A price above a rising longer-term average can support a trend thesis, but these indicators lag and can reverse. The market gate is a filter, not a prediction or a guarantee of a low-risk entry.", "SMA = average closing price over the labeled session window"],
    ["Earnings: a different kind of risk", "A company’s earnings announcement can move its price sharply while the regular market is closed. A planned stop cannot guarantee protection through that move. Dates must be verified; an unknown date is a blocker, not evidence that no announcement is coming.", "Unknown event calendar → incomplete trade review"],
    ["No opportunity: a complete answer", "A setup can look attractive and still be unsuitable at the available price or under the account’s limits. Recording a rejection protects the process from a weekly trading quota. This journal tracks research decisions, not profit, win rate, or evidence of a proven edge.", "Interesting setup + unresolved blocker ≠ qualified opportunity"],
  ];
  return [title("Understand the decision", "A short field guide to the language and limits of this research process."), el("div", { class: "learn-grid" }, cards.map(([heading, copy, formula], index) => el("article", { class: "learn-card" }, el("span", { class: "learn-number" }, `FIELD NOTE 0${index + 1}`), el("h2", {}, heading), el("p", {}, copy), el("div", { class: "formula" }, formula)))),
    el("div", { class: "note-box" }, "These explanations describe the rules used in this journal. They are not evidence that the strategy will make money. Verify the actual security, account constraints, and order behavior before making an investment decision.")];
}

function openCandidate(candidate, entry) {
  const dialog = $("#candidate-dialog");
  dialog.dataset.symbol = candidate.symbol;
  const metrics = object(candidate.metrics), plan = object(candidate.plan), review = object(candidate.review);
  const fields = [
    ["Recorded close", money(metrics.close)], ["20D vs SPY", pp(metrics.relative_return_20)],
    ["Relative volume", ratio(metrics.relative_volume)], ["14-day ATR", money(metrics.atr14)],
  ];
  const close = () => { location.hash = `universe/entry/${encodeURIComponent(entry.id)}`; };
  const content = el("div", {},
    el("header", { class: "dialog-head" }, el("div", {}, badge(sourceState(entry), "amber"), el("h2", { id: "candidate-title" }, candidate.symbol), el("p", {}, `${securityName(candidate.kind)} · ${groupName(candidate.sector)} · ${date(candidate.last_date || entry.signal_session)}`)), el("button", { class: "icon-button dialog-close", "aria-label": "Close candidate details", onclick: close }, "×")),
    el("div", { class: "dialog-body" },
      el("div", { class: "note-box" }, isArchive(entry) || isFailure(entry) ? "Historical research only. These levels are retained for the record and are not current entry instructions." : "Research only. Verify current prices, events, account limits, and orders before using any scenario."),
      el("div", { class: "dialog-stat-grid" }, fields.map(([label, value]) => el("div", { class: "dialog-stat" }, el("span", {}, label), el("strong", {}, value)))),
      el("div", { class: "dialog-columns" }, el("section", {}, el("h3", {}, Object.keys(plan).length ? "Recorded hypothetical scenario" : "No scenario generated"), Object.keys(plan).length ? el("table", { class: "plan-table" }, el("tbody", {}, [
        ["Entry trigger", money(plan.entry)], ["Stop / invalidation", money(plan.stop)], ["Illustrative 2R objective", money(plan.target_2r)], ["Chase-rule ceiling", money(plan.max_entry_chase)], ["Planned stop distance", percent(plan.stop_distance_pct)],
      ].map(([key, value]) => el("tr", {}, el("th", { scope: "row" }, key), el("td", {}, value))))) : el("p", {}, "The recorded technical rules did not produce a valid entry-and-stop scenario for this symbol."),
      el("p", { class: "section-note" }, "The objective is arithmetic, not a price forecast. Actual loss can exceed planned entry-to-stop risk.")),
      el("section", {}, el("h3", {}, "Technical evidence"), el("div", { class: "filter-list" }, Object.entries(object(candidate.filters)).map(([key, passed]) => el("div", { class: "filter-item" }, el("span", { class: `filter-mark${passed === true ? "" : " fail"}`, "aria-hidden": "true" }, passed === true ? "✓" : "—"), el("span", {}, `${words(key)}: ${passed === true ? "passed" : passed === false ? "not met" : "unknown"}`)))),
      el("p", {}, `20 / 50 / 200-day averages: ${money(metrics.sma20)} / ${money(metrics.sma50)} / ${money(metrics.sma200)}. Prior 20-session high: ${money(metrics.prior20_high)}. Security 20-session return: ${percent(metrics.return_20, true)}.`))),
      textSection("Why it was interesting", review.why_interesting || (candidate.technical_match === true ? `Matched the recorded ${array(candidate.setup_types).map(words).join(" and ") || "technical"} setup. A match alone does not qualify an opportunity.` : "This symbol was part of the research universe but did not match a recorded technical setup.")),
      textSection("Why it was not actionable", review.why_not_actionable || "No complete, current trade approval is recorded for this symbol. Inspect every blocker below."),
      el("section", { class: "detail-section" }, el("h3", {}, "All recorded blockers"), itemList(candidate.blockers, "No candidate blockers recorded; this alone is not proof of a complete account or execution review.")),
      textSection("What would change the decision", review.what_would_change || "A fresh valid setup, reliable current data, verified events, and a complete account/execution review that fits all risk limits."),
      textSection("Sizing review", candidate.sizing_status === "within_limits" ? "Recorded as within limits for the reviewed scenario. Recheck after any price, holding, order, or risk-setting change; no private size is published here." : candidate.sizing_status === "does_not_fit" ? "The recorded scenario does not fit the applicable sizing constraints." : "Not evaluated. No position size or account capacity is implied."),
      el("div", { class: "dialog-footer" }, `Source record: ${date(entry.checked_at, true)} · Signal session: ${date(entry.signal_session)}. `, el("a", { class: "text-link", href: entryUrl(entry), onclick: () => dialog.close() }, "Open this journal entry"))));
  $("#candidate-dialog-content").replaceChildren(content);
  if (!dialog.open) dialog.showModal();
}

function render() {
  const view = $("#view"), route = readRoute();
  $("#breadcrumb-page").textContent = pageNames[route.page];
  document.title = `${pageNames[route.page]} · Agentic Trader`;
  document.querySelectorAll(".main-nav a").forEach((link) => link.dataset.page === route.page ? link.setAttribute("aria-current", "page") : link.removeAttribute("aria-current"));
  view.setAttribute("aria-busy", "false");
  if (state.error) {
    if ($("#candidate-dialog").open) $("#candidate-dialog").close();
    snapshotStatus(null);
    view.replaceChildren(el("section", { class: "error-state" }, el("p", { class: "eyebrow" }, "THE JOURNAL IS TEMPORARILY UNAVAILABLE"), el("h1", {}, "We could not load the research."), el("p", {}, "No prices, counts, or decisions are being inferred. Try reloading the published snapshot."), el("button", { class: "button", onclick: load }, "Try again"), el("p", { class: "error-detail" }, state.error)));
    return;
  }
  const entry = selectedEntry(route);
  snapshotStatus(entry);
  if (!entry && !["strategy", "learn"].includes(route.page)) {
    view.replaceChildren(title("The journal starts here", "Completed checks will appear when a research record is published."), empty("No published records yet", "There are no prices, technical matches, or opportunities to display. The strategy and field notes are still available."));
    return;
  }
  const pages = { overview: () => overview(entry), journal, universe: () => universe(entry), strategy, learn };
  view.replaceChildren(...pages[route.page]());
  if (route.entry && !entries().some((record) => record.id === route.entry)) view.prepend(el("div", { class: "note-box" }, "That research record could not be found. Showing the most recent available record."));
  if (route.symbol) {
    const candidate = array(entry?.candidates).find((item) => item.symbol === route.symbol);
    if (candidate) openCandidate(candidate, entry);
    else {
      if ($("#candidate-dialog").open) $("#candidate-dialog").close();
      view.prepend(el("div", { class: "note-box" }, "That symbol was not found in this research record. Choose a symbol from the available universe."));
    }
  } else if ($("#candidate-dialog").open) $("#candidate-dialog").close();
}

async function load() {
  if (state.loading) return;
  state.loading = true;
  $("#refresh-button").disabled = true;
  $("#view").setAttribute("aria-busy", "true");
  try {
    const response = await fetch("data/research.json", { cache: "no-store", credentials: "omit" });
    if (!response.ok) throw new Error(`Research snapshot returned HTTP ${response.status}.`);
    const data = await response.json();
    if (data.schema_version !== 1 || !Array.isArray(data.entries)) throw new Error("The published research file has an unsupported format.");
    if (data.entries.some((entry) => !entry || typeof entry !== "object" || typeof entry.id !== "string" || (entry.candidates != null && !Array.isArray(entry.candidates)) || array(entry.candidates).some((candidate) => !candidate || typeof candidate !== "object" || typeof candidate.symbol !== "string"))) throw new Error("A published research record is incomplete or malformed.");
    state.data = data;
    state.error = null;
  } catch (error) {
    state.error = error instanceof Error ? error.message : "The snapshot could not be read.";
    state.data = null;
  } finally {
    state.loading = false;
    $("#refresh-button").disabled = false;
    render();
  }
}

$("#refresh-button").addEventListener("click", load);
window.addEventListener("hashchange", () => {
  if (location.hash === "#main") { $("#main").focus(); return; }
  if (state.data || state.error) render();
});
$(".skip-link").addEventListener("click", (event) => { event.preventDefault(); $("#main").focus(); });
$("#candidate-dialog").addEventListener("click", (event) => { if (event.target === $("#candidate-dialog")) $("#candidate-dialog").close(); });
$("#candidate-dialog").addEventListener("close", () => {
  const route = readRoute();
  if (route.symbol) location.hash = route.entry ? `${route.page}/entry/${encodeURIComponent(route.entry)}` : route.page;
  const symbol = $("#candidate-dialog").dataset.symbol;
  requestAnimationFrame(() => Array.from(document.querySelectorAll(".symbol-link")).find((link) => link.textContent === symbol)?.focus());
});
load();
