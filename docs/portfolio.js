/* Dated portfolio viewer. No orders, telemetry, uploads, or browser storage. */
"use strict";

const portfolioState = { data: null, account: "all", search: "", sort: "value", local: false };
const portfolioView = document.querySelector("#portfolio-view");
const snapshotStatus = document.querySelector("#snapshot-status");
const publicMode = document.documentElement.dataset.mode === "public";
const entryParameter = new URLSearchParams(window.location.search).get("entry");
const entryPattern = /^\d{8}T\d{6}\.\d{6}Z-(intraday|after_close|baseline_archive|failed_check)$/;
const currencyFormat = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const quantityFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 8 });
const decimal = (value) => typeof value === "number" && Number.isFinite(value) ? value : typeof value === "string" && /^-?\d+(?:\.\d+)?$/.test(value) && Number.isFinite(Number(value)) ? Number(value) : null;
const amount = (value) => decimal(value) === null ? "—" : currencyFormat.format(decimal(value));
const signedAmount = (value) => decimal(value) === null ? "—" : `${decimal(value) > 0 ? "+" : ""}${amount(value)}`;
const percentage = (value, signed = false) => decimal(value) === null ? "—" : `${signed && decimal(value) > 0 ? "+" : ""}${decimal(value).toFixed(2)}%`;
const quantity = (value) => decimal(value) === null ? "—" : quantityFormat.format(decimal(value));
const plain = (value, fallback = "Not recorded") => typeof value === "string" && value.trim() ? value : fallback;
const tone = (value) => decimal(value) === null || decimal(value) === 0 ? "" : decimal(value) > 0 ? "positive" : "negative";
const list = (value) => Array.isArray(value) ? value : [];

function element(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined && child !== false) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function timestamp(value) {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) return "Time not recorded";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit", timeZone: "America/Chicago", timeZoneName: "short" }).format(new Date(value));
}

function metric(label, value, detail, className = "") {
  return element("section", { class: `metric ${className}` }, element("p", { class: "metric-label" }, label), element("strong", {}, value), element("p", { class: "metric-detail" }, detail));
}

function accountValue(account) { return account.total_value ?? account.account_value; }

function aggregate(holdings, key) {
  if (holdings.some((holding) => decimal(holding[key]) === null)) return null;
  return holdings.reduce((sum, holding) => sum + decimal(holding[key]), 0);
}

function selection() {
  const data = portfolioState.data;
  const account = list(data.accounts).find((item) => item.account_key === portfolioState.account);
  const holdings = list(data.holdings).filter((item) => !account || item.account_key === account.account_key);
  if (!account) return { account: null, holdings, totals: data.totals || {} };
  const cost = aggregate(holdings, "cost_basis"), value = aggregate(holdings, "market_value"), gain = aggregate(holdings, "unrealized_pl");
  const complete = account.positions_complete_for_scope === true;
  return { account, holdings, totals: { account_value: accountValue(account), cash: account.cash, unleveraged_buying_power: account.unleveraged_buying_power, equity_value: account.equity_value, crypto_value: account.crypto_value, tracked_cost_basis: complete ? cost : null, tracked_market_value: complete ? value : null, tracked_unrealized_pl: complete ? gain : null, tracked_unrealized_pl_pct: complete && cost > 0 && gain !== null ? gain / cost * 100 : null } };
}

function accountsPanel(accounts) {
  return element("section", { class: "accounts-panel" }, element("div", { class: "section-heading" }, element("h2", {}, "Accounts at a glance"), element("span", {}, "Broker-reported balances")),
    element("div", { class: "account-grid" }, accounts.map((account) => element("article", { class: "account-card" },
      element("div", { class: "account-card-top" }, element("h3", {}, plain(account.account_label, "Account")), element("span", { class: "badge" }, "USD")),
      element("strong", { class: "account-value" }, amount(accountValue(account))),
      element("dl", { class: "account-breakdown" }, [["Equities", account.equity_value], ["Crypto", account.crypto_value], ["Cash", account.cash]].map(([label, value]) => element("div", {}, element("dt", {}, label), element("dd", {}, amount(value))))),
      element("p", { class: "account-time" }, timestamp(account.observed_at || portfolioState.data.updated_at)),
      account.positions_complete_for_scope === false ? element("p", { class: "incomplete-note" }, "Position coverage is incomplete for this account.") : null))));
}

function referenceLabel(holding) {
  const labels = { last_trade: "Last recorded trade", bid_ask_midpoint: "Bid/ask midpoint", last_trade_stale: "Earlier recorded trade", bid_ask_midpoint_stale: "Earlier bid/ask midpoint" };
  return labels[holding.price_basis] || "Price basis not recorded";
}

function holdingRows(holding) {
  const cell = (label, ...children) => element("td", { "data-label": label }, ...children);
  const sessions = { regular: "Regular session", pre_market: "Pre-market", after_hours: "After-hours", overnight: "Overnight", closed: "Market closed", unknown: "Session not recorded" };
  const stale = holding.price_is_fresh === false || /_stale$/.test(holding.price_basis || "");
  const detail = (label, value) => element("div", {}, element("dt", {}, label), element("dd", {}, value));
  return [element("tr", { class: "position-row" },
    cell("Position", element("strong", { class: "position-symbol" }, plain(holding.symbol, "Unknown")), element("span", { class: "position-account" }, plain(holding.account_label, "Account"))),
    cell("Shares", element("strong", {}, quantity(holding.quantity))),
    cell("Average paid / share", element("strong", {}, amount(holding.average_cost))),
    cell("Market price", element("strong", {}, amount(holding.price)), element("span", { class: "cell-note" }, referenceLabel(holding)), stale ? element("span", { class: "badge amber" }, "Older price at review") : null),
    cell("Position value", element("strong", {}, amount(holding.market_value)), element("span", { class: "cell-note" }, `Cost basis ${amount(holding.cost_basis)}`)),
    cell("Unrealized P&L", element("strong", { class: tone(holding.unrealized_pl) }, signedAmount(holding.unrealized_pl)), element("span", { class: `cell-note ${tone(holding.unrealized_pl_pct)}` }, percentage(holding.unrealized_pl_pct, true))),
    cell("Weight", element("strong", {}, percentage(holding.portfolio_weight_pct)), element("span", { class: "cell-note" }, "of all account value"), element("span", { class: "cell-note" }, `${percentage(holding.account_weight_pct)} of this account`))),
  element("tr", { class: "position-context" }, element("td", { colspan: "7" }, element("details", {}, element("summary", {}, `${plain(holding.symbol, "Position")} · quote details`, element("span", {}, `${sessions[holding.session] || sessions.unknown} · ${timestamp(holding.price_at)}`)),
    element("dl", { class: "quote-details" }, detail("Price time", timestamp(holding.price_at)), detail("Bid/ask observation", timestamp(holding.quote_at)), detail("Price source", plain(holding.source)), detail("Market session", sessions[holding.session] || sessions.unknown), detail("Freshness at snapshot", holding.price_is_fresh === true ? "Within the recorded freshness window" : stale ? "Older than the recorded freshness window" : "Not recorded")),
    element("p", { class: "quote-explanation" }, "A midpoint is a quote reference, not a completed trade. These prices belong to the snapshot time and do not update while you view the page."))))];
}

function positionsPanel(selected) {
  const results = element("div", {});
  const draw = () => {
    const query = portfolioState.search.trim().toLowerCase();
    const holdings = selected.holdings.filter((holding) => `${holding.symbol || ""} ${holding.account_label || ""}`.toLowerCase().includes(query));
    holdings.sort((a, b) => portfolioState.sort === "symbol" ? String(a.symbol).localeCompare(String(b.symbol)) : (decimal(b[portfolioState.sort === "gain" ? "unrealized_pl" : "market_value"]) ?? -Infinity) - (decimal(a[portfolioState.sort === "gain" ? "unrealized_pl" : "market_value"]) ?? -Infinity));
    results.replaceChildren(element("p", { class: "result-count" }, `${holdings.length} ${holdings.length === 1 ? "position" : "positions"} shown`), holdings.length ? element("div", { class: "positions-table-wrap" },
      element("table", { class: "positions-table" }, element("caption", { class: "sr-only" }, "Tracked equity positions and their purchase costs, market values, unrealized gains and account weights"),
        element("thead", {}, element("tr", {}, ["Position", "Shares", "Avg. paid / share", "Market price", "Position value", "Unrealized P&L", "Weight"].map((label) => element("th", { scope: "col" }, label)))),
        element("tbody", {}, holdings.map(holdingRows)))) : element("div", { class: "empty-state compact" }, element("h3", {}, "No matching positions"), element("p", {}, "Choose another account or change the search. Missing positions are not assumed to be sold.")));
  };
  const search = element("input", { id: "position-search", type: "search", placeholder: "Symbol or account", value: portfolioState.search, oninput: (event) => { portfolioState.search = event.target.value; draw(); } });
  const sort = element("select", { id: "position-sort", onchange: (event) => { portfolioState.sort = event.target.value; draw(); } }, [["value", "Largest position"], ["gain", "Highest unrealized P&L"], ["symbol", "Symbol A–Z"]].map(([value, label]) => element("option", { value }, label)));
  sort.value = portfolioState.sort;
  draw();
  return element("section", { class: "positions-panel" }, element("div", { class: "section-heading" }, element("div", {}, element("h2", {}, "Tracked stock positions"), element("p", {}, "Average paid is the cost per share of the current position, not an individual purchase price."))),
    element("div", { class: "position-controls" }, element("div", { class: "field grow" }, element("label", { for: "position-search" }, "Find a position"), search), element("div", { class: "field" }, element("label", { for: "position-sort" }, "Order by"), sort)), results,
    element("p", { class: "table-note" }, "Position values and open P&L use the dated market prices shown here. Weights compare each position with the broker-reported total account values, including cash and crypto. Summary totals cover the selected account scope, regardless of search filters."));
}

function renderPortfolio() {
  const data = portfolioState.data, selected = selection(), totals = selected.totals;
  const accounts = list(data.accounts);
  const filteredAccounts = selected.account ? [selected.account] : accounts;
  const buttons = [["all", "All accounts"], ...accounts.map((account) => [account.account_key, account.account_label])].map(([key, label]) => element("button", { class: `account-button${portfolioState.account === key ? " selected" : ""}`, "aria-pressed": portfolioState.account === key ? "true" : "false", onclick: () => { portfolioState.account = key; renderPortfolio(); } }, label));
  portfolioView.replaceChildren(
    element("div", { class: "account-filter", role: "group", "aria-label": "Account scope" }, buttons),
    element("div", { class: "metrics-grid" },
      metric(selected.account ? "Broker account value" : "Combined account value", amount(totals.account_value ?? totals.total_value), "Broker balance · includes cash and crypto", "primary"),
      metric("Tracked stock value", amount(totals.tracked_market_value), `Average-cost basis ${amount(totals.tracked_cost_basis)}`),
      metric("Unrealized stock P&L", signedAmount(totals.tracked_unrealized_pl), `${percentage(totals.tracked_unrealized_pl_pct, true)} on current position cost`, tone(totals.tracked_unrealized_pl)),
      metric("Cash balance", amount(totals.cash), `Unleveraged buying power ${amount(totals.unleveraged_buying_power)}`)),
    element("aside", { class: "scope-note" }, element("span", { class: "scope-icon", "aria-hidden": "true" }, "◎"), element("div", {}, element("strong", {}, "Understand the scope"), element("p", {}, plain(data.scope_note, "The table covers the tracked equity positions. Broker account values include cash and crypto; these totals may differ from the quoted stock subtotal. Cost basis and unrealized P&L are not lifetime investment returns.")), element("p", {}, "A dash means unavailable, not zero. Incomplete totals stay unavailable rather than treating missing values as zero."))),
    accountsPanel(filteredAccounts), positionsPanel(selected),
    element("section", { class: "reading-note" }, element("h2", {}, "Read the position, then the research"), element("p", {}, "A gain or loss measures what has happened to an open position. A buy, hold, trim or exit decision still depends on the business, valuation and new evidence."), element("a", { href: "https://howardwhsrun.github.io/Agentic-Trader/#journal", class: "text-link" }, "Open the research journal →")));
  portfolioView.setAttribute("aria-busy", "false");
  snapshotStatus.textContent = `${portfolioState.local ? "Local file" : publicMode ? "Published snapshot" : "Local snapshot"} · ${timestamp(data.updated_at)} · Prices are not live`;
}

function acceptSnapshot(data, local = false) {
  if (!data || data.schema_version !== 1 || !Array.isArray(data.accounts) || !Array.isArray(data.holdings) || !data.totals || typeof data.totals !== "object") throw new Error("This file is not a supported portfolio snapshot.");
  if (data.accounts.some((account) => !account || typeof account.account_key !== "string") || data.holdings.some((holding) => !holding || typeof holding.symbol !== "string" || typeof holding.account_key !== "string")) throw new Error("The portfolio snapshot has incomplete account or position records.");
  portfolioState.data = data;
  portfolioState.local = local;
  document.querySelector("#mode-label").textContent = local ? "Local file · not published" : publicMode ? "Published account snapshot" : "Private · local only";
  if (!data.accounts.some((account) => account.account_key === portfolioState.account)) portfolioState.account = "all";
  renderPortfolio();
}

function showMessage(title, message) {
  portfolioView.replaceChildren(element("section", { class: "empty-state" }, element("span", { class: "empty-icon", "aria-hidden": "true" }, "◇"), element("h2", {}, title), element("p", {}, message)));
  portfolioView.setAttribute("aria-busy", "false");
  snapshotStatus.textContent = title;
}

async function loadSnapshot() {
  const inline = document.querySelector("#portfolio-snapshot")?.textContent.trim();
  if (inline) {
    try { acceptSnapshot(JSON.parse(inline)); } catch (error) { showMessage("Snapshot unavailable", error.message); }
    return;
  }
  if (!publicMode) {
    showMessage("Open a local portfolio snapshot", "Select a portfolio JSON file above. It is read in this tab without uploading it, storing it, or connecting to a brokerage.");
    return;
  }
  if (entryParameter !== null && !entryPattern.test(entryParameter)) {
    showMessage("Invalid journal record link", "The record identifier is not valid. Open a portfolio link from the research journal.");
    return;
  }
  const path = entryParameter === null ? "data/portfolio.json" : `data/portfolios/${encodeURIComponent(entryParameter)}.json`;
  const refresh = document.querySelector("#refresh-portfolio");
  refresh.disabled = true;
  portfolioView.setAttribute("aria-busy", "true");
  snapshotStatus.textContent = "Reading the published portfolio snapshot…";
  try {
    const response = await fetch(path, { cache: "no-store", credentials: "omit" });
    if (!response.ok) {
      if (response.status === 404) {
        showMessage(entryParameter === null ? "Portfolio snapshot not published yet" : "Portfolio not recorded for this check", entryParameter === null ? "A dated account snapshot will appear here when it has been published." : "This historical research entry has no portfolio snapshot. Current positions are never substituted for a missing historical record.");
        return;
      }
      throw new Error(`The snapshot could not be read (HTTP ${response.status}).`);
    }
    acceptSnapshot(await response.json());
  } catch (error) { showMessage("Unable to open the snapshot", error.message || "Try refreshing the published snapshot."); }
  finally { refresh.disabled = false; }
}

document.querySelector("#mode-label").textContent = publicMode ? "Published account snapshot" : "Private · local only";
document.querySelector("#refresh-portfolio").hidden = !publicMode;
document.querySelector(".file-button").hidden = publicMode;
document.querySelector("#file-note").hidden = publicMode;
document.querySelector("#refresh-portfolio").addEventListener("click", loadSnapshot);
document.querySelector("#portfolio-file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    if (file.size > 5 * 1024 * 1024) throw new Error("Choose a portfolio JSON file smaller than 5 MB.");
    acceptSnapshot(JSON.parse(await file.text()), true);
    document.querySelector("#file-note").hidden = false;
  } catch (error) { showMessage("Unable to read this file", error.message); }
  event.target.value = "";
});
loadSnapshot();
