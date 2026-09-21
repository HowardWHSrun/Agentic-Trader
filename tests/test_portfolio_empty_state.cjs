"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class TestNode {
  constructor(tag, text = "") { this.tag = tag; this.text = text; this.children = []; this.attributes = {}; }
  append(child) { this.children.push(child); }
  replaceChildren(...children) { this.text = ""; this.children = children; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener() {}
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(" "); }
  set textContent(value) { this.text = value; this.children = []; }
}

function viewer() {
  const nodes = new Map();
  const document = {
    documentElement: { dataset: { mode: "local" } },
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, new TestNode("div"));
      return nodes.get(selector);
    },
    createElement: (tag) => new TestNode(tag),
    createTextNode: (text) => new TestNode("text", text),
  };
  const context = vm.createContext({ document, Node: TestNode, window: { location: { search: "" } }, URLSearchParams, Intl });
  const source = fs.readFileSync(path.join(__dirname, "../docs/portfolio.js"), "utf8");
  vm.runInContext(source + "\nglobalThis.testViewer = { acceptSnapshot, renderPortfolio, state: portfolioState };", context);
  return { ...context.testViewer, text: () => document.querySelector("#portfolio-view").textContent };
}

function flatSnapshot(complete = true) {
  return {
    schema_version: 1,
    updated_at: "2031-04-05T16:00:00Z",
    accounts: ["agentic", "individual"].map((key) => ({
      account_key: key, account_label: key, total_value: "100", cash: "100",
      equity_value: "0", crypto_value: "0", unleveraged_buying_power: "100",
      positions_complete_for_scope: complete,
    })),
    holdings: [],
    totals: {
      account_value: "200", cash: "200", unleveraged_buying_power: "200",
      tracked_cost_basis: complete ? "0" : null,
      tracked_market_value: complete ? "0" : null,
      tracked_unrealized_pl: complete ? "0" : null,
      tracked_unrealized_pl_pct: null,
      completeness: { tracked_scope: complete },
    },
  };
}

test("verified flat accounts render confirmed zero tracked positions, without implying a sale", () => {
  const ui = viewer();
  ui.acceptSnapshot(flatSnapshot());
  assert.match(ui.text(), /No tracked stock positions/);
  assert.match(ui.text(), /broker snapshot confirms no stock positions in the selected tracked scope/);
  assert.match(ui.text(), /Tracked stock value \$0\.00/);
  assert.doesNotMatch(ui.text(), /No matching positions|Coverage is incomplete|assumed to be sold/);
  for (const account of ["agentic", "individual"]) {
    ui.state.account = account;
    ui.renderPortfolio();
    assert.match(ui.text(), /No tracked stock positions/);
    assert.match(ui.text(), /Tracked stock value \$0\.00/);
  }
});

test("incomplete empty scopes do not claim verified zero holdings", () => {
  const ui = viewer();
  ui.acceptSnapshot(flatSnapshot(false));
  assert.match(ui.text(), /Position coverage incomplete/);
  assert.match(ui.text(), /zero holdings cannot be confirmed/);
  assert.match(ui.text(), /Tracked stock value —/);
  assert.doesNotMatch(ui.text(), /broker snapshot confirms no stock positions/);
  ui.state.account = "individual";
  ui.renderPortfolio();
  assert.match(ui.text(), /Position coverage incomplete/);
  assert.match(ui.text(), /Tracked stock value —/);
});

test("a search without results does not turn recorded positions into a flat account", () => {
  const ui = viewer();
  const data = flatSnapshot();
  data.holdings = [{ symbol: "AAPL", account_key: "individual", account_label: "Individual" }];
  ui.state.search = "MSFT";
  ui.acceptSnapshot(data);
  assert.match(ui.text(), /No matching positions/);
  assert.match(ui.text(), /change the search/);
  assert.doesNotMatch(ui.text(), /broker snapshot confirms no stock positions/);
  ui.state.account = "agentic";
  ui.renderPortfolio();
  assert.match(ui.text(), /No tracked stock positions/);
  assert.match(ui.text(), /selected tracked scope/);
});

test("combined incomplete coverage does not hide a separately verified flat account", () => {
  const ui = viewer();
  const data = flatSnapshot(false);
  data.accounts[0].positions_complete_for_scope = true;
  ui.acceptSnapshot(data);
  assert.match(ui.text(), /Position coverage incomplete/);
  ui.state.account = "agentic";
  ui.renderPortfolio();
  assert.match(ui.text(), /No tracked stock positions/);
  assert.doesNotMatch(ui.text(), /zero holdings cannot be confirmed/);
});
