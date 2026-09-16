/* Public, static research journal. No broker connection, execution, or telemetry. */
"use strict";

const $ = (selector) => document.querySelector(selector);
const state = {
  data: null, loading: false, error: null,
  journal: { search: "", decision: "all", date: "all" },
  universe: { search: "", kind: "all", match: "all", sector: "all" },
  sort: { key: "symbol", ascending: true },
};
const pageNames = { overview: "Overview", journal: "Research journal", universe: "Market universe", crypto: "Crypto", strategy: "Strategy", learn: "Learn" };
const decisionNames = {
  no_opportunity: "No opportunity", watch_only: "Watch only",
  qualified_opportunity: "Recorded scan qualification", monitor_failure: "Check needs attention",
};
const checkNames = { baseline_archive: "Archived baseline", intraday: "Intraday review", after_close: "After-close review", failed_check: "Failed check" };
const moneyFormatter = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const numeric = (value) => typeof value === "number" && Number.isFinite(value);
const money = (value) => numeric(value) ? moneyFormatter.format(value) : "—";
const cryptoMoney = (value) => !numeric(value) ? "—" : value > 0 && value < 0.00000001 ? `$${value.toPrecision(4)}` : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: value < 1 ? 8 : value < 100 ? 4 : 2 }).format(value);
const fixed = (value, digits = 2) => numeric(value) ? value.toFixed(digits) : "—";
const percent = (value, signed = false) => numeric(value) ? `${signed && value > 0 ? "+" : ""}${fixed(value)}%` : "—";
const pp = (value) => numeric(value) ? `${value > 0 ? "+" : ""}${fixed(value)} pp` : "—";
const ratio = (value) => numeric(value) ? `${fixed(value)}×` : "—";
const array = (value) => Array.isArray(value) ? value : [];
const object = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const words = (value) => typeof value === "string" ? value.replaceAll("_", " ") : "Unknown";
const groupName = (value) => words(value).replace(/\b\w/g, (letter) => letter.toUpperCase());
const securityName = (value) => value === "etf" ? "ETF" : value === "stock" ? "Stock" : value === "crypto" ? "Spot crypto" : "Unknown type";
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

function utcDate(value, includeTime = false) {
  if (!value || typeof value !== "string") return "Unknown UTC date";
  const parsed = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(parsed.getTime())) return "Unknown UTC date";
  const options = { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" };
  if (includeTime) Object.assign(options, { hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  return new Intl.DateTimeFormat("en-US", options).format(parsed) + (includeTime ? "" : " UTC");
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
function candidateUrl(candidate, entry) { return `#${candidate.kind === "crypto" ? "crypto" : "universe"}/symbol/${encodeURIComponent(candidate.symbol)}/entry/${encodeURIComponent(entry.id)}`; }
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
function ticker(candidate) { return el("span", { class: `ticker-icon ${candidate.kind === "crypto" ? "crypto" : candidate.kind === "stock" ? "stock" : "etf"}`, "aria-hidden": "true" }, String(candidate.symbol || "?").split("/")[0].slice(0, 4)); }
function textSection(heading, text) { return el("section", { class: "detail-section" }, el("h3", {}, heading), el("p", {}, textValue(text))); }

function snapshotStatus(entry) {
  if (!entry) {
    $("#snapshot-text").textContent = state.error ? "Published research could not be loaded." : "No published checks yet.";
    $("#snapshot-tail").textContent = "No live prices";
    return;
  }
  const stateLabel = isFailure(entry) ? "Failed check / carried-forward signals" : isArchive(entry) ? "Archived baseline" : "Published check";
  const crypto = object(entry.crypto);
  const sessionLabel = readRoute().page === "crypto" ? entry.crypto ? `Crypto daily bar ${utcDate(crypto.signal_session)}` : "No crypto review recorded" : `Equity signal session ${date(entry.signal_session)}`;
  $("#snapshot-text").textContent = `${stateLabel} · ${sessionLabel} · Checked ${date(entry.checked_at, true)}`;
  $("#snapshot-tail").textContent = `${age(entry.checked_at)} · No live prices`;
}

function stats(entry) {
  const candidates = Array.isArray(entry.candidates) ? entry.candidates : null;
  const techCount = candidates ? candidates.filter((candidate) => candidate.technical_match === true).length : "—";
  const qualified = Object.hasOwn(decisionNames, entry.decision) ? (entry.decision === "qualified_opportunity" ? 1 : 0) : "—";
  return el("div", { class: "stat-grid" }, [
    ["Equities reviewed", candidates ? candidates.length : "—", "U.S. stocks & unleveraged ETFs", "◎"],
    ["Equity technical matches", techCount, isArchive(entry) || isFailure(entry) ? "At the recorded equity signal session" : "Research candidates, still need checks", "⌁"],
    ["Recorded scan qualifications", qualified, "Technical process result, not a value judgment", "↗"],
    ["Valuation review", "Separate", "Read the company thesis and scenario assumptions", "◇"],
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
  const heading = isFailure(entry) ? "Prior equity context" : "Equity market context";
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

function quoteTime(value) {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) return "Time not recorded";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit", timeZone: "America/Chicago", timeZoneName: "short" }).format(new Date(value));
}

function quoteCard(quote, entry) {
  const positivePrice = (value) => numeric(value) && value > 0;
  const observedTime = Date.parse(quote.observed_at), checkedTime = Date.parse(entry.checked_at), tradeTime = Date.parse(quote.last_trade_at);
  const hasTrade = positivePrice(quote.last_price) && Number.isFinite(tradeTime);
  const hasSpread = positivePrice(quote.bid) && positivePrice(quote.ask) && quote.ask >= quote.bid;
  const olderQuote = Number.isFinite(observedTime) && Number.isFinite(checkedTime) && checkedTime - observedTime > 15 * 60 * 1000;
  const priorSession = olderQuote && localDate(quote.observed_at) !== localDate(entry.checked_at);
  const olderTrade = hasTrade && Number.isFinite(checkedTime) && checkedTime - tradeTime > 15 * 60 * 1000;
  const useTrade = hasTrade && (!olderTrade || !hasSpread || olderQuote);
  const reference = useTrade ? quote.last_price : hasSpread ? Number(((quote.bid + quote.ask) / 2).toFixed(6)) : null;
  const referenceLabel = useTrade ? "Last recorded trade" : hasSpread ? "Bid/ask midpoint" : "Reference unavailable";
  const sessions = { regular: "Regular session", pre_market: "Pre-market", after_hours: "After-hours", overnight: "Overnight", closed: "Market closed", unknown: "Session not recorded" };
  const names = { MSFT: "Microsoft", AAPL: "Apple", TSLA: "Tesla", GOOGL: "Alphabet · Class A", SPY: "S&P 500 ETF", QQQ: "Nasdaq-100 ETF" };
  const quoteField = (label, value) => el("div", {}, el("dt", {}, label), el("dd", {}, value));
  return el("article", { class: "market-quote-card", "aria-label": `${quote.symbol} recorded market prices` },
    el("div", { class: "market-quote-top" }, el("div", {}, el("h4", {}, quote.symbol), el("p", {}, names[quote.symbol] || "Market quote")), badge(sessions[quote.session] || sessions.unknown)),
    el("div", { class: "market-quote-reference" }, el("strong", {}, money(reference)), el("span", {}, referenceLabel)),
    olderQuote || (useTrade && olderTrade) ? el("div", { class: "market-quote-age" }, olderQuote ? badge(priorSession ? "Prior-session quote" : "Older quote at review", "amber") : null, useTrade && olderTrade ? badge("Older trade at review", "amber") : null) : null,
    el("dl", { class: "market-quote-spread" }, quoteField("Bid", positivePrice(quote.bid) ? money(quote.bid) : "—"), quoteField("Ask", positivePrice(quote.ask) ? money(quote.ask) : "—")),
    el("dl", { class: "market-quote-meta" },
      quoteField("Quote time", quoteTime(quote.observed_at)),
      hasTrade ? quoteField(olderTrade ? "Earlier trade" : "Trade time", `${useTrade ? "" : `${money(quote.last_price)} · `}${quoteTime(quote.last_trade_at)}`) : null,
      positivePrice(quote.prior_close) && quote.prior_close_date ? quoteField("Prior close", `${money(quote.prior_close)} · ${date(quote.prior_close_date)}`) : null,
      quoteField("Source", typeof quote.source === "string" && quote.source.trim() ? quote.source : "Not recorded")));
}

function marketQuoteSnapshot(entry, overviewPanel = false) {
  const trackedSymbols = ["MSFT", "AAPL", "TSLA", "GOOGL"];
  const quotes = array(entry.current_quotes).filter((quote) => quote && typeof quote.symbol === "string");
  const tracked = [
    ...trackedSymbols.map((symbol) => quotes.find((quote) => quote.symbol === symbol)).filter(Boolean),
    ...quotes.filter((quote) => ![...trackedSymbols, "SPY", "QQQ"].includes(quote.symbol)),
  ];
  const context = quotes.filter((quote) => ["SPY", "QQQ"].includes(quote.symbol));
  const missing = trackedSymbols.filter((symbol) => !tracked.some((quote) => quote.symbol === symbol));
  const heading = overviewPanel ? "h2" : "h3";
  return el("section", { class: `market-quote-snapshot ${overviewPanel ? "panel market-quote-overview" : "detail-section"}`, "aria-label": "Market prices saved with this research check" },
    el("div", { class: "market-quote-heading" }, el(heading, {}, "Market prices at this check"), badge("Saved snapshot")),
    el("p", { class: "market-quote-intro" }, `Review: ${quoteTime(entry.checked_at)}. These dated prices are not live. A bid/ask midpoint is a quote reference, not a completed trade.`),
    !tracked.length && !context.length ? empty("No prices were saved with this check", "This historical entry keeps its original evidence. Quotes from newer checks are never substituted.") : [
      tracked.length ? el("div", { class: "market-quote-grid" }, tracked.map((quote) => quoteCard(quote, entry))) : null,
      missing.length ? el("p", { class: "market-quote-missing" }, `No quote recorded for ${missing.join(", ")} in this entry. Newer prices are not substituted.`) : null,
      context.length ? el("details", { class: "market-quote-context" }, el("summary", {}, "Benchmark quote context · SPY / QQQ"), el("div", { class: "market-quote-grid" }, context.map((quote) => quoteCard(quote, entry)))) : null,
      el("p", { class: "market-quote-foot" }, "All prices are USD; times use Chicago time (CDT/CST). Older quotes and trades are more than 15 minutes before this review. A fresh bid/ask midpoint replaces an older trade as the reference. Daily closes used in technical research are shown separately."),
    ]);
}

function overview(entry) {
  const archived = isArchive(entry), failed = isFailure(entry);
  const heroTitle = failed ? "A pause for better information." : archived ? "A baseline. A disciplined beginning." : entry.decision === "qualified_opportunity" ? "One idea worth a closer look." : entry.decision === "watch_only" ? "Interesting. Not actionable yet." : "Let the business earn its place.";
  const heroCopy = failed ? "This review could not be completed. Any retained signals below are carried forward from an earlier snapshot and must not be treated as current." : archived ? "The starting point for the journal. Historical technical matches are recorded here with their limitations. No fresh opportunity is being called." : textValue(entry.summary);
  const candidates = array(entry.candidates).filter((candidate) => candidate.technical_match === true);
  const lesson = array(entry.lessons)[0];
  return [
    title("The research desk", "Business value first. Technical evidence helps with timing.", date(entry.signal_session)),
    currentApproach(true),
    el("section", { class: "hero" }, el("div", { class: "hero-copy" }, el("p", { class: "eyebrow" }, archived ? "THE OPENING RECORD" : "LATEST TECHNICAL RESEARCH RECORD"), el("h2", {}, heroTitle), el("p", {}, heroCopy), el("a", { class: "text-link", href: entryUrl(entry) }, "Read the full check")), el("div", { class: "hero-graphic", "aria-hidden": "true" }, el("div", { class: "decision-emblem" }, el("span", { class: "emblem-symbol" }, failed ? "!" : "⌁"), el("span", { class: "emblem-text" }, archived ? "BASELINE ARCHIVE" : "STAY SELECTIVE")), el("span", { class: "graphic-caption" }, "PATIENCE IS PART OF THE PROCESS"))),
    stats(entry), marketQuoteSnapshot(entry, true), el("div", { class: "two-col" }, benchmarkPanel(entry), recentPanel()),
    sectionHead("Equity ideas under the microscope", "The 60-symbol scanner supplies price and trend context. It does not measure fair value.", "Explore the universe", "#universe"),
    el("div", { class: "candidate-grid" }, candidates.length ? candidates.slice(0, 6).map((candidate) => candidateCard(candidate, entry)) : empty("No technical matches in this check", "An empty watchlist is a useful result. There is no need to manufacture a trade.")),
    cryptoSummary(entry),
    el("section", { class: "lesson-strip" }, el("span", { class: "lesson-icon", "aria-hidden": "true" }, "◇"), el("div", {}, el("p", { class: "eyebrow" }, "A LESSON FROM THIS RECORD"), el("h3", {}, "The decision matters as much as the outcome."), el("p", {}, lesson ? textValue(lesson) : "Keep a record of what was known, what was missing, and what would change the decision. This journal tracks research, not investment performance."))),
    el("p", { class: "section-note" }, `${textValue(entry.data_freshness)} All prices and indicators refer to the labeled snapshot. Refreshing this page only reloads published records; it does not request new market data.`),
  ];
}

function cryptoCounts(crypto) {
  const candidates = Array.isArray(crypto?.candidates) ? crypto.candidates : null;
  return {
    count: candidates ? candidates.length : "—",
    matches: candidates && candidates.every((candidate) => typeof candidate.technical_match === "boolean") ? candidates.filter((candidate) => candidate.technical_match).length : "—",
  };
}

function cryptoSummary(entry) {
  const crypto = entry.crypto;
  const heading = sectionHead("Crypto research", "A separate market clock. The same shared risk budget.", "Open crypto research", entryUrl(entry, "crypto"));
  if (!crypto) return el("section", { class: "crypto-overview" }, heading, el("div", { class: "crypto-summary-empty" }, el("span", { class: "crypto-summary-icon", "aria-hidden": "true" }, "◈"), el("div", {}, el("h3", {}, "No crypto review was recorded with this check."), el("p", {}, "This historical record is preserved as it was. Missing research does not mean zero opportunities."))));
  const counts = cryptoCounts(crypto);
  return el("section", { class: "crypto-overview" }, heading,
    el("div", { class: "crypto-summary-grid" },
      el("div", { class: "crypto-summary-main" }, el("span", { class: "eyebrow" }, "COMPLETED UTC DAILY BARS"), el("h3", {}, utcDate(crypto.signal_session)), el("p", {}, `${textValue(crypto.provider)} · ${textValue(crypto.feed)}`), el("a", { class: "text-link", href: entryUrl(entry, "crypto") }, "Inspect the recorded research")),
      el("div", { class: "crypto-summary-stat" }, el("strong", {}, counts.count), el("span", {}, "Crypto assets reviewed")),
      el("div", { class: "crypto-summary-stat" }, el("strong", {}, counts.matches), el("span", {}, "Technical matches · vs BTC")),
      el("div", { class: "crypto-summary-stat" }, el("strong", { class: "pending-value" }, "Pending"), el("span", {}, "Robinhood eligibility & sizing"))),
    el("p", { class: "section-note" }, "The crypto market trades 24/7. Research runs at the scheduled weekday checkpoints, not continuously or on weekends. Technical matches are not qualified opportunities."));
}

function cryptoGateBadge(crypto, entry) {
  const passed = crypto?.market_gate?.passed;
  const prefix = isFailure(entry) ? "Prior BTC gate" : "Recorded BTC gate";
  return badge(passed === true ? `${prefix} passed` : passed === false ? `${prefix} paused` : "BTC gate unknown", passed === true ? "teal" : "amber");
}

function venueQuote(candidate, compact = false) {
  const quote = object(candidate.quote);
  if (!Object.keys(quote).length) return el("div", { class: "venue-quote-empty" }, el("h3", {}, "Venue quote not published"), el("p", {}, "A current bid, ask, spread, and Robinhood execution preview have not been recorded here."));
  const details = [
    ["Venue bid", cryptoMoney(quote.bid)], ["Venue ask", cryptoMoney(quote.ask)], ["Recorded spread", percent(quote.spread_pct)],
  ];
  return el("section", { class: compact ? "venue-quote compact" : "venue-quote" },
    el("div", { class: "panel-heading" }, el("h3", {}, "Recorded venue quote"), badge("Reference only", "amber")),
    el("div", { class: "quote-values" }, details.map(([label, value]) => el("div", {}, el("span", {}, label), el("strong", {}, value)))),
    el("p", { class: "section-note" }, `${textValue(quote.provider)} · ${textValue(quote.venue)} · Observed ${utcDate(quote.observed_at, true)}.`),
    el("p", { class: "section-note" }, "Venue-specific reference pricing, not an executable Robinhood quote. Fees and the actual order preview remain unverified."));
}

function cryptoCandidateCard(candidate, entry) {
  const crypto = object(entry.crypto), metrics = object(candidate.metrics);
  const result = candidate.technical_match === true ? "Technical match" : candidate.technical_match === false ? "No technical match" : "Result unknown";
  const quote = object(candidate.quote);
  const symbol = candidate.symbol;
  return el("a", { class: "candidate-card crypto-card crypto-symbol-link", href: candidateUrl({ ...candidate, kind: "crypto" }, entry), "data-symbol": symbol, "aria-label": `Open ${symbol} crypto research from ${utcDate(crypto.signal_session)}` },
    el("div", { class: "candidate-top" }, ticker({ ...candidate, kind: "crypto" }), el("div", {}, el("div", { class: "ticker-name" }, symbol), el("div", { class: "ticker-detail" }, "Spot crypto · USD pair")), badge(result, candidate.technical_match === true ? "teal" : "amber")),
    el("div", { class: "candidate-metrics" }, el("div", {}, el("span", {}, "Completed UTC-day close"), el("strong", {}, cryptoMoney(metrics.close))), el("div", {}, el("span", {}, "20D vs BTC"), el("strong", { class: `relative${numeric(metrics.relative_return_20) && metrics.relative_return_20 < 0 ? " negative" : ""}` }, pp(metrics.relative_return_20)))),
    el("div", { class: "crypto-card-context" }, el("span", {}, `Venue-relative volume ${ratio(metrics.relative_volume)}`), el("span", {}, quote.venue ? `Quote reference: ${quote.venue}` : "Venue quote not published")),
    el("div", { class: "candidate-bottom" }, el("span", {}, `${utcDate(candidate.last_date || crypto.signal_session)} · Sizing pending`), el("span", { class: "arrow-circle", "aria-hidden": "true" }, "↗")));
}

function cryptoPage(entry) {
  const crypto = entry.crypto;
  const recordPicker = el("div", { class: "filters" }, field("Research record", "crypto-entry", selectControl(entries().map((record) => [record.id, `${date(record.checked_at, true)} · ${record.crypto ? "Crypto review recorded" : "No crypto review"}`]), entry.id, (id) => { location.hash = `crypto/entry/${encodeURIComponent(id)}`; }), true));
  const page = [title("Crypto research", "Spot markets, observed with a different clock and the same discipline."),
    el("div", { class: "crypto-clock-banner" }, el("span", { class: "crypto-clock-icon", "aria-hidden": "true" }, "◈"), el("div", {}, el("strong", {}, "24/7 market. Scheduled weekday research."), el("p", {}, "Crypto trades through nights and weekends. This research is checked at the five scheduled weekday times in Chicago; it is not continuously or weekend monitored."))), recordPicker];
  if (!crypto) return [...page, empty("No crypto review was recorded with this check", "The record contains no crypto prices, signals, or venue quotes. Choose a later record when one is available; this archive will keep its original scope.")];
  const candidates = array(crypto.candidates), counts = cryptoCounts(crypto);
  const btc = candidates.find((candidate) => candidate.symbol === "BTC/USD");
  const btcMetrics = object(btc?.metrics);
  const sharedRules = object(state.data?.risk_rules);
  const rule = (key) => numeric(sharedRules[key]) ? `${sharedRules[key]}%` : "—";
  const context = el("div", { class: "two-col crypto-context-grid" },
    el("section", { class: "panel" }, el("div", { class: "panel-heading" }, el("h2", {}, "BTC market context"), cryptoGateBadge(crypto, entry)),
      el("div", { class: "benchmark-row" }, ticker({ symbol: "BTC/USD", kind: "crypto" }), el("div", {}, el("div", { class: "ticker-name" }, "BTC/USD"), el("div", { class: "ticker-detail" }, "Crypto benchmark · completed UTC day")), el("div", { class: "benchmark-price" }, cryptoMoney(btcMetrics.close), el("small", {}, `20-day return ${percent(btcMetrics.return_20, true)}`))),
      el("dl", { class: "research-meta" }, [["UTC daily bar", utcDate(crypto.signal_session)], ["Scan generated", utcDate(crypto.scan_generated_at, true)], ["Provider / feed", `${textValue(crypto.provider)} / ${textValue(crypto.feed)}`]].map(([label, value]) => el("div", {}, el("dt", {}, label), el("dd", {}, value)))),
      el("p", { class: "section-note" }, `${sourceState(entry)}. BTC is the comparison benchmark; its relative return against itself is zero when the synchronized data is available.`)),
    el("section", { class: "panel shared-risk-panel" }, el("p", { class: "eyebrow" }, "ONE PORTFOLIO · ONE RISK BUDGET"), el("h2", {}, "Crypto does not add a second allowance."),
      el("div", { class: "shared-risk-values" }, el("div", {}, el("strong", {}, rule("max_open_risk_pct")), el("span", {}, "Combined planned risk")), el("div", {}, el("strong", {}, rule("max_total_exposure_pct")), el("span", {}, "Total exposure cap"))),
      el("p", {}, `${rule("risk_per_trade_pct")} planned risk per trade and ${rule("max_position_pct")} maximum position exposure are also subject to these shared limits across stocks, ETFs, and crypto.`),
      badge("Robinhood crypto eligibility & sizing pending", "amber"), el("p", { class: "section-note" }, "No coin quantity is approved or implied. Account eligibility, available unleveraged funds, pending orders, venue pricing, and protective-order support need a manual review.")));
  const observations = el("div", { class: "two-col" }, el("section", { class: "panel" }, el("h2", {}, "What this review observed"), itemList(crypto.observations)), el("section", { class: "panel" }, el("h2", {}, "Unresolved data checks"), itemList(crypto.data_blockers, "No data blockers were recorded. This does not clear execution, account, sizing, or event checks.")));
  return [...page, el("p", { class: "crypto-session-label" }, `${sourceState(entry)} · Crypto signal ${utcDate(crypto.signal_session)}`), context,
    sectionHead("Assets under review", `${counts.count} assets · ${counts.matches} technical matches · sizing pending`),
    el("div", { class: "candidate-grid crypto-candidate-grid" }, candidates.length ? candidates.map((candidate) => cryptoCandidateCard(candidate, entry)) : empty(Array.isArray(crypto.candidates) ? "No crypto assets were included" : "Crypto asset details are unavailable", "No candidate prices or technical results can be inferred from this record.")), observations,
    el("section", { class: "panel crypto-lessons" }, el("h2", {}, "Lessons for the next crypto check"), itemList(crypto.lessons), el("div", { class: "detail-section" }, el("h3", {}, "Sources used"), sourcesList(crypto.sources))),
    el("p", { class: "section-note" }, "Crypto candles use complete UTC calendar days, including weekends. Volume and quotes are venue-specific. Cross-venue spreads, fees, outages, and token events can change the usable entry; a technical match alone is not actionable.")];
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
    el("div", { class: "note-box" }, `${sourceState(entry)}. ${textValue(entry.data_freshness)} Recorded scan decisions do not establish intrinsic value or a current buy/sell instruction.`),
    marketQuoteSnapshot(entry),
    el("section", { class: "detail-section" }, el("h3", {}, "My portfolio at this check"), el("p", { class: "section-note" }, "Purchase costs, shares owned, position values and unrealized gains or losses are recorded separately from market research. Personal snapshots begin with the September 16 portfolio update."), el("a", { class: "text-link", href: `portfolio.html?entry=${encodeURIComponent(entry.id)}` }, "Open this portfolio snapshot ↗")),
    el("section", { class: "detail-section" }, el("h3", {}, "What the check observed"), itemList(entry.observations)),
    el("section", { class: "detail-section" }, el("h3", {}, "Why it cannot be treated as a buy signal"), itemList(entry.data_blockers, "No data blockers recorded. Candidate, account, earnings, and execution checks still apply.")),
    el("section", { class: "detail-section" }, el("h3", {}, "Stock & ETF technical candidates"), el("div", { class: "chips" }, array(entry.candidates).filter((candidate) => candidate.technical_match === true).map((candidate) => el("a", { class: "chip", href: candidateUrl(candidate, entry) }, `${candidate.symbol} ↗`))), array(entry.candidates).some((candidate) => candidate.technical_match === true) ? null : el("p", { class: "section-note" }, "No equity technical matches recorded.")),
    el("section", { class: "detail-section" }, el("h3", {}, "Crypto in this record"), entry.crypto ? el("div", {}, el("p", { class: "section-note" }, `${utcDate(entry.crypto.signal_session)} · ${cryptoCounts(entry.crypto).count} assets · ${cryptoCounts(entry.crypto).matches} technical matches. Execution eligibility and sizing remain pending.`), el("div", { class: "chips" }, array(entry.crypto.candidates).map((candidate) => el("a", { class: "chip", href: candidateUrl({ ...candidate, kind: "crypto" }, entry) }, `${candidate.symbol} ↗`))), el("a", { class: "text-link", href: entryUrl(entry, "crypto") }, "Read the crypto observations and sources")) : el("p", { class: "section-note" }, "No crypto review was recorded with this check.")),
    el("section", { class: "detail-section" }, el("h3", {}, "Lessons for the next check"), itemList(entry.lessons)),
    el("section", { class: "detail-section" }, el("h3", {}, "Sources used"), sourcesList(entry.sources)),
    textSection("Notification record", entry.notification?.reason || "No notification record supplied."));
}

function journal() {
  const results = el("div", {});
  const draw = () => {
    const filters = state.journal;
    const query = filters.search.trim().toLowerCase();
    const matches = entries().filter((entry) => (filters.decision === "all" || entry.decision === filters.decision) && (filters.date === "all" || localDate(entry.checked_at) === filters.date) && (!query || [entry.summary, ...array(entry.observations).map(textValue), ...array(entry.lessons).map(textValue), ...array(entry.candidates).map((candidate) => candidate.symbol), ...array(entry.crypto?.candidates).map((candidate) => candidate.symbol), ...array(entry.crypto?.observations).map(textValue), ...array(entry.crypto?.lessons).map(textValue)].join(" ").toLowerCase().includes(query)));
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
  return [title("Research journal", "An honest record of what was checked, what was missing, and what we learned."), el("div", { class: "note-box" }, "Earlier records preserve the swing-research method used at the time. Their fixed targets, stop scenarios, and scan decisions are historical evidence, not today’s investing instructions. The current approach uses business value and technical timing."), filters, results];
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
  return [title("Stock & ETF universe", "Price, trend, volume, and volatility research. A technical match does not establish investment value.", `${candidates.length} symbols`), el("div", { class: "note-box" }, `${sourceState(entry)}. ${textValue(entry.data_freshness)}`),
    el("div", { class: "filters" }, field("Research record", "universe-entry", selectControl(entries().map((record) => [record.id, `${date(record.checked_at, true)} · ${checkNames[record.check_type] || "Review"}`]), entry.id, (id) => { location.hash = `universe/entry/${encodeURIComponent(id)}`; }), true)),
    el("div", { class: "filters" },
      field("Search symbols or groups", "universe-search", el("input", { type: "search", placeholder: "e.g. AAPL or technology", value: state.universe.search, oninput: (event) => { state.universe.search = event.target.value; draw(); } }), true),
      field("Security type", "universe-kind", selectControl([["all", "All types"], ["stock", "Stocks"], ["etf", "ETFs"]], state.universe.kind, (value) => { state.universe.kind = value; draw(); })),
      field("Technical result", "universe-match", selectControl([["all", "All results"], ["true", "Technical matches"], ["false", "No match"]], state.universe.match, (value) => { state.universe.match = value; draw(); })),
      field("Group", "universe-sector", selectControl([["all", "All groups"], ...sectors.map((sector) => [sector, groupName(sector)])], state.universe.sector, (value) => { state.universe.sector = value; draw(); }))), results];
}

function currentApproach(compact = false) {
  const steps = [
    ["Understand the business", "Use filings to test the advantage, balance sheet, cash generation, capital needs, and growth per share."],
    ["Estimate a value range", "Build bear, base, and bull cases with explicit growth, margins, reinvestment, discount rate, and valuation assumptions."],
    ["Leave room for growth", "Compare price with that range and a margin of safety. Reaching chart resistance prompts a review; it does not automatically end a sound thesis."],
    ["Use the chart for timing", "Map support, resistance, 50/200-day trends, volume, and ATR. Technical weakness triggers investigation alongside business evidence."],
  ];
  return el("section", { class: `value-approach${compact ? " compact" : ""}` },
    el("div", { class: "value-approach-head" }, el("div", {}, el("p", { class: "eyebrow" }, "CURRENT APPROACH · UPDATED SEPTEMBER 14, 2026"), el("h2", {}, "Invest in value. Give growth time.")), badge("Fundamentals + technical timing", "teal")),
    el("p", { class: "value-intro" }, "An investment decision starts with the business and the price paid for it. Technical levels help decide when to review or act; they do not substitute for valuation."),
    compact ? el("div", { class: "value-path" }, "Business thesis", el("span", { "aria-hidden": "true" }, "→"), "Value range", el("span", { "aria-hidden": "true" }, "→"), "Margin of safety", el("span", { "aria-hidden": "true" }, "→"), "Technical timing") : el("div", { class: "value-grid" }, steps.map(([heading, copy], index) => el("article", {}, el("span", { class: "value-step" }, `0${index + 1}`), el("h3", {}, heading), el("p", {}, copy)))),
    el("p", { class: "value-status" }, "The market scanner supplies technical evidence. Company fundamentals, scenario assumptions, and valuation uncertainty are assessed separately in the company review; no fair value is inferred from a chart pattern."),
    el("div", { class: "value-review-links" }, el("a", { class: "text-link", href: "research/value-investing-review.html" }, "Read the company calls and valuation review"), compact ? el("a", { class: "text-link", href: "#strategy" }, "Explore the investing approach") : null));
}

function strategy() {
  const rules = object(state.data?.risk_rules);
  const ruleValue = (key, suffix = "%") => numeric(rules[key]) ? `${rules[key]}${suffix}` : "—";
  const ruleCards = [
    ["Single-position guardrail", ruleValue("max_position_pct"), "Recorded exposure ceiling. Size depends on the account, concentration, and uncertainty in the thesis."],
    ["Planned-risk guardrail", ruleValue("risk_per_trade_pct"), "A scenario loss budget, not a guaranteed loss cap or a reason to force a narrow technical stop."],
    ["Combined planned risk", ruleValue("max_open_risk_pct"), "One shared modeled risk budget. Actual losses can exceed a price-based scenario."],
    ["Total market exposure", ruleValue("max_total_exposure_pct"), "Recorded exposure allowance across the relevant account. Holdings and pending orders require reconciliation."],
    ["Group concentration", ruleValue("max_sector_exposure_pct"), "A ceiling for correlated exposures, not proof of diversification."],
    ["Open-position guardrail", ruleValue("max_positions", ""), "The recorded scanner limit. These risk settings alone do not establish investment suitability."],
  ];
  return [title("The investment approach", "Value and business quality guide the decision. Price action helps with timing."),
    currentApproach(),
    el("section", { class: "panel" }, el("h2", {}, "What would change the decision?"), el("div", { class: "decision-grid" },
      el("article", {}, el("h3", {}, "Consider buying"), el("p", {}, "A supported business thesis, an attractive price relative to a conservative value range, acceptable downside, and a position size that fits the risk budget.")),
      el("article", {}, el("h3", {}, "Continue holding"), el("p", {}, "The thesis remains intact and expected future returns still compensate for the risks. Allow normal price swings; a recent high or resistance line is a review area.")),
      el("article", {}, el("h3", {}, "Consider trimming or exiting"), el("p", {}, "Evidence breaks the thesis, the price leaves too little return for the risk, or concentration becomes excessive. State the supporting facts and scenario math before recommending an amount.")))),
    el("section", { class: "panel" }, el("h2", {}, "Each company needs a valuation worksheet"),
      itemList(["Dated primary sources: filings, reported results, management guidance, and share count.", "Business drivers: revenue and cash-flow growth, durable margins, debt, dilution, and reinvestment needs.", "Bear / base / bull values: explicit assumptions and a consistent multi-year horizon, with downside and upside from the observed price.", "Margin of safety: a justified discount to a conservative estimate, with sensitivity to assumptions shown.", "Technical review zones: documented support and resistance, longer-term trend, and volatility. These are evidence to reassess, not arbitrary fixed profit caps."]),
      el("div", { class: "note-box" }, "The linked company review records its evidence, assumptions, and remaining uncertainty. Missing inputs stay visible; chart patterns cannot fill a missing valuation model.")),
    el("div", { class: "two-col" }, el("section", { class: "panel" }, el("h2", {}, "Five checks. No pressure to transact."), el("p", { class: "section-note" }, "Scheduled weekday times in America/Chicago. Checks review new evidence; an unchanged thesis does not require a new trade. The journal records checks that actually completed."),
      el("div", { class: "schedule-list" }, array(state.data?.schedule).map((time) => el("span", { class: "schedule-time" }, time))),
      el("p", { class: "section-note" }, "Completed exchange sessions drive equity indicators; complete UTC days drive crypto indicators. Monitoring is not continuous or enabled on weekends.")),
      el("section", { class: "panel" }, el("h2", {}, "Stocks and crypto need different theses"), itemList(["Stocks represent businesses: value depends on future cash flows and what shareholders retain.", "Bitcoin and Ether do not provide the same claim on corporate cash flows. Keep adoption, token economics, network risks, and valuation uncertainty explicit.", "Crypto remains a separate speculative research view; a technical match does not turn it into a conventional value investment.", "Use no borrowing, options, short selling, or leveraged/inverse products."]))),
    sectionHead("Recorded risk guardrails", "These are the latest exported scanner settings. They do not replace a company-specific investment assessment."),
    el("div", { class: "strategy-grid" }, ruleCards.map(([label, value, copy]) => el("article", { class: "rule-card" }, el("p", { class: "eyebrow" }, label), el("div", { class: "rule-value" }, value), el("p", {}, copy)))),
    el("p", { class: "section-note" }, "Earlier swing-era logs remain unchanged for learning. Their days-to-weeks horizon, fixed 2R objectives, and entry limits describe that historical process. A weekly entry ceiling is not an investing goal. Market research is separate from the authorized My portfolio snapshots. Account identifiers and personalized trading instructions remain private.")];
}

function learn() {
  const cards = [
    ["Value: a range, not an exact number", "Estimate what the business can distribute to shareholders over time. Different assumptions for growth, margins, reinvestment, dilution, and risk produce different values. A useful estimate shows those assumptions and bear, base, and bull cases.", "Scenario upside / downside = scenario value ÷ observed price − 1"],
    ["Margin of safety: room to be wrong", "An attractive company can be an unattractive investment at the wrong price. A margin of safety compares the price with a conservative value estimate; it should reflect business risk and uncertainty, rather than use the same percentage for every stock.", "Margin of safety = 1 − price ÷ conservative estimated value"],
    ["Resistance: a review area", "A prior high may mark selling interest, but it does not cap a business’s future value. Reaching resistance calls for reassessing valuation, momentum, and the thesis. It does not automatically justify selling a growing business.", "Technical review zone ≠ intrinsic value ≠ automatic sell order"],
    ["R: historical technical risk math", "One R is the planned entry-to-stop distance per unit: a share for equities or a base coin for crypto. Multiply by the actual quantity for planned dollar risk. A 2R objective is arithmetic; it is not a likely return, and losses can exceed 1R.", "Planned risk = (entry − stop) × quantity · 2R = entry + 2 × (entry − stop)"],
    ["Relative strength: compared with what?", "Stock and ETF research compares 20-session returns with SPY. Crypto research compares 20 completed UTC-day returns with BTC. Positive values mean outperformance over that window, not necessarily a price gain or a prediction.", "Relative strength = asset return − its labeled benchmark return"],
    ["Relative volume: participation", "Relative volume compares the latest completed session’s share volume with the average of the preceding 20 sessions. Higher volume can add context to a price move. It does not establish that buyers will keep pushing the price higher.", "Relative volume = last session volume ÷ prior 20-session mean"],
    ["Trend: a useful filter", "Moving averages summarize past prices. A price above a rising longer-term average can support a trend thesis, but these indicators lag and can reverse. The market gate is a filter, not a prediction or a guarantee of a low-risk entry.", "SMA = average closing price over the labeled session window"],
    ["Earnings: test the thesis", "Reported earnings and cash flows help test growth, margins, capital needs, and valuation assumptions. Announcements can also move prices sharply outside regular hours. Verify dates and reassess the business evidence; a price gap alone does not explain whether the thesis changed.", "New results → update assumptions → reassess value and risk"],
    ["Waiting: a valid investment decision", "A business can be attractive while its price offers too little prospective return. Waiting for a better price or firmer evidence is a complete decision. This journal records research; it does not establish investment performance or a proven edge.", "Good business + demanding price ≠ attractive investment"],
    ["Crypto: a different clock and venue", "Crypto has no scheduled overnight market closure. Daily candles here use UTC days and volume is venue-specific, not global participation. BTC is the benchmark. Quotes can differ from Robinhood’s price, spread, and fees; account and protective-order eligibility require manual verification before sizing.", "24/7 market ≠ continuous monitoring · One shared risk budget"],
  ];
  return [title("Understand the decision", "A short field guide to the language and limits of this research process."), el("div", { class: "learn-grid" }, cards.map(([heading, copy, formula], index) => el("article", { class: "learn-card" }, el("span", { class: "learn-number" }, `FIELD NOTE ${String(index + 1).padStart(2, "0")}`), el("h2", {}, heading), el("p", {}, copy), el("div", { class: "formula" }, formula)))),
    el("div", { class: "note-box" }, "These explanations describe the rules used in this journal. They are not evidence that the strategy will make money. Verify the actual security, account constraints, and order behavior before making an investment decision.")];
}

function openCryptoCandidate(candidate, entry) {
  const dialog = $("#candidate-dialog");
  dialog.dataset.symbol = candidate.symbol;
  const crypto = object(entry.crypto), metrics = object(candidate.metrics), plan = object(candidate.plan), review = object(candidate.review);
  const close = () => { location.hash = `crypto/entry/${encodeURIComponent(entry.id)}`; };
  const metricFields = [["Completed UTC-day close", cryptoMoney(metrics.close)], ["20-day return vs BTC", pp(metrics.relative_return_20)], ["Venue-relative volume", ratio(metrics.relative_volume)], ["14-day ATR · USD / coin", cryptoMoney(metrics.atr14)]];
  const planRows = [["Entry trigger · USD", cryptoMoney(plan.entry)], ["Stop / invalidation · USD", cryptoMoney(plan.stop)], ["Illustrative 2R objective · USD", cryptoMoney(plan.target_2r)], ["Chase-rule ceiling · USD", cryptoMoney(plan.max_entry_chase)], ["Planned stop distance", percent(plan.stop_distance_pct)]];
  const scenario = el("section", {}, el("h3", {}, Object.keys(plan).length ? "Recorded technical scenario" : "No scenario generated"),
    Object.keys(plan).length ? el("table", { class: "plan-table" }, el("tbody", {}, planRows.map(([label, value]) => el("tr", {}, el("th", { scope: "row" }, label), el("td", {}, value))))) : el("p", {}, "The recorded crypto rules did not generate a valid entry-and-stop scenario for this asset."),
    el("p", { class: "section-note" }, "Levels are USD per base coin. No coin quantity is approved. A 2R objective is arithmetic; actual losses can exceed planned entry-to-stop risk."));
  const technical = el("section", {}, el("h3", {}, "UTC daily evidence"),
    el("p", { class: "section-note" }, "Quote freshness and venue checks below describe the recorded scan time. They do not refresh as you read this page."),
    el("div", { class: "filter-list" }, Object.entries(object(candidate.filters)).map(([key, passed]) => el("div", { class: "filter-item" }, el("span", { class: `filter-mark${passed === true ? "" : " fail"}`, "aria-hidden": "true" }, passed === true ? "✓" : "—"), el("span", {}, `${words(key)}: ${passed === true ? "passed" : passed === false ? "not met" : "unknown"}`)))),
    el("p", {}, `20 / 50 / 200-day averages: ${cryptoMoney(metrics.sma20)} / ${cryptoMoney(metrics.sma50)} / ${cryptoMoney(metrics.sma200)}. Prior 20-day high: ${cryptoMoney(metrics.prior20_high)}. Asset 20-day return: ${percent(metrics.return_20, true)}.`),
    el("p", { class: "section-note" }, "All day counts are complete UTC calendar days, including weekends. Relative returns use BTC; volume is specific to the recorded venue/feed."));
  const blockers = [...new Set([...array(crypto.data_blockers), ...array(candidate.blockers)].map(textValue))];
  const body = el("div", { class: "dialog-body" },
    el("div", { class: "note-box" }, `${sourceState(entry)}. The crypto market trades 24/7; this journal is monitored only at scheduled weekday checks. These levels are research scenarios, not current execution instructions.`),
    el("div", { class: "dialog-stat-grid" }, metricFields.map(([label, value]) => el("div", { class: "dialog-stat" }, el("span", {}, label), el("strong", {}, value)))),
    el("dl", { class: "research-meta crypto-dialog-meta" }, [["Completed UTC day", utcDate(candidate.last_date || crypto.signal_session)], ["Scan generated", utcDate(crypto.scan_generated_at, true)], ["Provider / feed", `${textValue(crypto.provider)} / ${textValue(crypto.feed)}`], ["Comparison benchmark", "BTC/USD"]].map(([label, value]) => el("div", {}, el("dt", {}, label), el("dd", {}, value)))),
    venueQuote(candidate), el("div", { class: "dialog-columns" }, scenario, technical),
    textSection("Why it was interesting", review.why_interesting || (candidate.technical_match === true ? `The recorded ${array(candidate.setup_types).map(words).join(" and ") || "technical"} rules matched. The BTC trend, liquidity, venue pricing, and events still need review.` : "This asset was checked but did not match a recorded crypto setup.")),
    textSection("Why it was not actionable", review.why_not_actionable || "Robinhood crypto eligibility, the executable quote, fees, available funds, and protective-order support have not been verified. No actionable quantity is published."),
    el("section", { class: "detail-section" }, el("h3", {}, "All recorded crypto blockers"), itemList(blockers, "No data or candidate blockers recorded. Account, execution, and sizing checks are still pending.")),
    textSection("What would change the decision", review.what_would_change || "A fresh UTC-day setup, verified current venue and Robinhood pricing, relevant event checks, and eligibility plus sizing that fits the shared portfolio limits."),
    textSection("Shared sizing review · pending", "Stocks, ETFs, and crypto use the same position, exposure, concentration, weekly-entry, and combined planned-risk limits. Crypto does not receive an extra risk allowance. No coin quantity is implied until eligibility and the shared account review are complete."),
    el("div", { class: "dialog-footer" }, `Crypto daily signal: ${utcDate(crypto.signal_session)} · Journal record: ${date(entry.checked_at, true)}. `, el("a", { class: "text-link", href: entryUrl(entry), onclick: () => dialog.close() }, "Open this journal entry")));
  $("#candidate-dialog-content").replaceChildren(el("div", {},
    el("header", { class: "dialog-head crypto-dialog-head" }, el("div", {}, badge("Spot crypto · research only", "amber"), el("h2", { id: "candidate-title" }, candidate.symbol), el("p", {}, `UTC daily candles · BTC benchmark · ${utcDate(crypto.signal_session)}`)), el("button", { class: "icon-button dialog-close", "aria-label": "Close crypto details", onclick: close }, "×")), body));
  if (!dialog.open) dialog.showModal();
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
      el("div", { class: "note-box" }, isArchive(entry) || isFailure(entry) ? "Historical research only. These levels are retained for the record and are not current entry instructions." : "Technical research only. These recorded levels are not a current investing sell plan. A valuation range and business thesis must guide the decision; resistance and a 2R calculation are review context."),
      el("div", { class: "dialog-stat-grid" }, fields.map(([label, value]) => el("div", { class: "dialog-stat" }, el("span", {}, label), el("strong", {}, value)))),
      el("div", { class: "dialog-columns" }, el("section", {}, el("h3", {}, Object.keys(plan).length ? "Recorded technical scenario" : "No scenario generated"), Object.keys(plan).length ? el("table", { class: "plan-table" }, el("tbody", {}, [
        ["Entry trigger", money(plan.entry)], ["Stop / invalidation", money(plan.stop)], ["Illustrative 2R objective", money(plan.target_2r)], ["Chase-rule ceiling", money(plan.max_entry_chase)], ["Planned stop distance", percent(plan.stop_distance_pct)],
      ].map(([key, value]) => el("tr", {}, el("th", { scope: "row" }, key), el("td", {}, value))))) : el("p", {}, "The recorded technical rules did not produce a valid entry-and-stop scenario for this symbol."),
      el("p", { class: "section-note" }, "These technical levels do not estimate intrinsic value. The 2R objective is arithmetic, not a forecast or an automatic profit-taking instruction. Actual losses can exceed planned risk.")),
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
  const pages = { overview: () => overview(entry), journal, universe: () => universe(entry), crypto: () => cryptoPage(entry), strategy, learn };
  view.replaceChildren(...pages[route.page]());
  if (route.entry && !entries().some((record) => record.id === route.entry)) view.prepend(el("div", { class: "note-box" }, "That research record could not be found. Showing the most recent available record."));
  if (route.symbol) {
    const candidate = array(route.page === "crypto" ? entry?.crypto?.candidates : entry?.candidates).find((item) => item.symbol === route.symbol);
    if (candidate) route.page === "crypto" ? openCryptoCandidate(candidate, entry) : openCandidate(candidate, entry);
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
    if (![1, 2].includes(data.schema_version) || !Array.isArray(data.entries)) throw new Error("The published research file has an unsupported format.");
    if (data.entries.some((entry) => !entry || typeof entry !== "object" || typeof entry.id !== "string" || (entry.candidates != null && !Array.isArray(entry.candidates)) || array(entry.candidates).some((candidate) => !candidate || typeof candidate !== "object" || typeof candidate.symbol !== "string"))) throw new Error("A published research record is incomplete or malformed.");
    if (data.entries.some((entry) => entry.crypto != null && (typeof entry.crypto !== "object" || Array.isArray(entry.crypto) || (entry.crypto.candidates != null && !Array.isArray(entry.crypto.candidates)) || array(entry.crypto.candidates).some((candidate) => !candidate || typeof candidate !== "object" || typeof candidate.symbol !== "string")))) throw new Error("A published crypto record is incomplete or malformed.");
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
  requestAnimationFrame(() => Array.from(document.querySelectorAll(".symbol-link, .crypto-symbol-link")).find((link) => link.dataset.symbol === symbol || link.textContent === symbol)?.focus());
});
load();
