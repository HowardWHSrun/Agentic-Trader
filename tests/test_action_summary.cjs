"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { recordedActions, presentation } = require("../docs/action-summary.js");

const candidate = (symbol, why, condition = "Reassess only on new evidence.") => ({
  symbol,
  review: { why_interesting: why, what_would_change: condition },
});
const entry = (candidates = [], overrides = {}) => ({
  check_type: "intraday",
  decision: "watch_only",
  candidates,
  ...overrides,
});

test("real September 18 watch-only journal retains all four recorded exits", () => {
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, "../docs/data/research.json"), "utf8"));
  // Pin the currently published record so future legitimate HOLD/BUY records do
  // not change the expected decisions in this historical regression fixture.
  const real = data.entries.find((row) => row.id === "20260918T172515.919309Z-intraday");
  assert.ok(real, "the public historical regression entry must remain available");
  assert.equal(real.decision, "watch_only");
  const result = presentation(real);
  assert.deepEqual(result.actions.map((row) => row.symbol).sort(), ["AAPL", "GOOGL", "MSFT", "TSLA"]);
  assert.ok(result.actions.every((row) => row.action === "EXIT" && row.label === "SELL / EXIT"));
  assert.equal(result.exitCount, 4);
  assert.equal(result.heading, "Sell actions recorded");
  assert.equal(result.entryLabel, "New entries: none qualified");
  for (const action of result.actions) {
    const review = real.candidates.find((row) => row.symbol === action.symbol).review;
    assert.equal(action.reason, review.why_interesting.trim());
    assert.equal(action.condition, review.what_would_change);
  }
});

test("mixed exit, trim and hold calls remain distinct with their full reasons", () => {
  const result = presentation(entry([
    candidate("AAPL", "SELL. Confirmed support failure."),
    candidate("MSFT", "EXIT remains preferred."),
    candidate("GOOGL", "REDUCE: concentration is excessive."),
    candidate("TSLA", "TRIM — take some risk off."),
    candidate("QQQ", "  HOLD / DO NOT ADD. Existing support holds.  "),
  ]));
  assert.deepEqual(result.actions.map(({ symbol, action, label }) => ({ symbol, action, label })), [
    { symbol: "AAPL", action: "EXIT", label: "SELL / EXIT" },
    { symbol: "MSFT", action: "EXIT", label: "SELL / EXIT" },
    { symbol: "GOOGL", action: "TRIM", label: "TRIM" },
    { symbol: "TSLA", action: "TRIM", label: "TRIM" },
    { symbol: "QQQ", action: "HOLD", label: "HOLD" },
  ]);
  assert.equal(result.exitCount, 2);
  assert.equal(result.trimCount, 2);
  assert.equal(result.heading, "Sell actions recorded");
  assert.equal(result.actions[4].reason, "HOLD / DO NOT ADD. Existing support holds.");
});

test("only leading uppercase, whole action words are extracted", () => {
  const reasons = [
    "We might SELL after a failure.", "No BUY is qualified.", "DO NOT SELL.",
    "sell now.", "Exit remains preferred.", "SELLING pressure is elevated.",
    "BUYBACK news is supportive.", "TRIMMING exposure is a possibility.",
    "WATCH. EXIT if support fails.", "WAIT for a BUY signal.",
  ];
  assert.deepEqual(recordedActions(entry(reasons.map((reason, i) => candidate(`S${i}`, reason)))), []);
});

test("negated or withdrawn leading actions are not current instructions", () => {
  const reasons = [
    "EXIT is not warranted.", "SELL not now.", "TRIM was withdrawn.",
    "REDUCE cancelled after reconciliation.", "BUY canceled.",
    "EXIT: not warranted.", "SELL — not recommended.", "TRIM: withdrawn.",
  ];
  for (const reason of reasons) {
    assert.deepEqual(recordedActions(entry([candidate("AAPL", reason)], { decision: "qualified_opportunity" })), [], reason);
  }
});

test("conditional leading calls do not become actions before their condition", () => {
  const reasons = [
    "EXIT if the next bar closes below support.",
    "SELL only if the next session fails.",
    "BUY: only if a completed breakout holds.",
    "TRIM when resistance rejects the rally.",
    "REDUCE only after the next review confirms failure.",
    "HOLD if the stated condition is satisfied.",
  ];
  for (const reason of reasons) {
    assert.deepEqual(recordedActions(entry([candidate("AAPL", reason)], { decision: "qualified_opportunity" })), [], reason);
  }
});

test("BUY requires both explicit recorded prose and a qualified entry decision", () => {
  const buy = candidate("QQQ", "BUY. All required conditions verified.");
  for (const decision of ["watch_only", "no_opportunity", undefined]) {
    assert.deepEqual(recordedActions(entry([buy], { decision })), []);
  }
  const result = presentation(entry([buy], { decision: "qualified_opportunity" }));
  assert.deepEqual(result.actions.map((row) => row.action), ["BUY"]);
  assert.equal(result.heading, "Buy action recorded");
  assert.equal(result.entryLabel, "New entry qualified in this record");
});

test("technical flags, plans, other prose and qualified status never synthesize BUY", () => {
  const technical = {
    symbol: "QQQ", technical_match: true, ready_for_manual_review: true,
    setup_types: ["breakout"], plan: { entry: 100, stop: 95 },
    review: { why_interesting: "WATCH. Strong daily pattern.", what_would_change: "BUY after verification." },
  };
  assert.deepEqual(recordedActions(entry([technical], { decision: "qualified_opportunity" })), []);
  assert.equal(presentation(entry([technical])).heading, "New entries: none qualified");
});

test("missing or malformed reviews are harmless and missing conditions are empty", () => {
  for (const value of [undefined, null, {}, { candidates: null }, { candidates: {} }]) {
    assert.deepEqual(recordedActions(value), []);
  }
  assert.deepEqual(recordedActions(entry([
    null, {}, { symbol: "QQQ" }, { symbol: "QQQ", review: null },
    { symbol: "QQQ", review: { why_interesting: 42 } },
    { review: { why_interesting: "EXIT now." } },
  ])), []);
  const result = recordedActions(entry([{ symbol: "AAPL", review: { why_interesting: "EXIT." } }]));
  assert.equal(result.length, 1);
  assert.equal(result[0].condition, "");
});

test("failed entries ignore carried-forward decisions even if they say BUY or EXIT", () => {
  const carried = [candidate("AAPL", "EXIT."), candidate("QQQ", "BUY.")];
  for (const overrides of [
    { check_type: "failed_check", decision: "qualified_opportunity" },
    { check_type: "intraday", decision: "monitor_failure" },
  ]) {
    const result = presentation(entry(carried, overrides));
    assert.deepEqual(result.actions, []);
    assert.equal(result.exitCount, 0);
    assert.equal(result.heading, "Review incomplete");
    assert.equal(result.entryLabel, "New-entry review incomplete");
    assert.equal(result.failed, true);
  }
});

test("baseline archives label their recorded actions as historical", () => {
  const result = presentation(entry([candidate("AAPL", "EXIT.")], { check_type: "baseline_archive" }));
  assert.equal(result.archived, true);
  assert.equal(result.heading, "Historical · Sell actions recorded");
  assert.equal(result.actions[0].action, "EXIT");
  assert.match(presentation(entry([], { check_type: "baseline_archive" })).heading, /^Historical/);
});

test("calls have no cross-entry carryover and do not mutate their inputs", () => {
  const old = entry([candidate("AAPL", "EXIT.")]);
  const next = entry([candidate("QQQ", "WATCH. Await a breakout.")]);
  const before = JSON.stringify({ old, next });
  assert.equal(presentation(old).exitCount, 1);
  assert.deepEqual(presentation(next).actions, []);
  assert.equal(presentation(old).exitCount, 1);
  assert.equal(JSON.stringify({ old, next }), before);
});

test("duplicate symbols retain the first valid recorded action", () => {
  const result = recordedActions(entry([
    candidate("AAPL", "WATCH. Pending review."),
    candidate("AAPL", "EXIT. Confirmed failure."),
    candidate("AAPL", "HOLD. Conflicting later row."),
  ]));
  assert.equal(result.length, 1);
  assert.equal(result[0].action, "EXIT");
});
