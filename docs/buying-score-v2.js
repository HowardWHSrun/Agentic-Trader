/* buying-score-v2: evidence arithmetic only; no data retrieval or trading. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.BuyingScoreV2 = api;
})(typeof globalThis === 'undefined' ? this : globalThis, function() {
  'use strict';
  const CHECKS = [
  {
    "id": "E1",
    "component": "entry_quality",
    "label": "A support, retest or breakout setup level is identified from completed bars."
  },
  {
    "id": "E2",
    "component": "entry_quality",
    "label": "Reference entry lies within 0.5 ATR14 of that setup level."
  },
  {
    "id": "E3",
    "component": "entry_quality",
    "label": "A structural invalidation level is identified below a prospective long entry."
  },
  {
    "id": "E4",
    "component": "entry_quality",
    "label": "The first defensible target gives at least 2R, using reference entry and invalidation."
  },
  {
    "id": "E5",
    "component": "entry_quality",
    "label": "No intervening verified resistance obstructs the 2R path."
  },
  {
    "id": "E6",
    "component": "entry_quality",
    "label": "Reference entry is no more than 1 ATR14 above the 20-session SMA."
  },
  {
    "id": "T1",
    "component": "trend_relative_strength",
    "label": "The last completed close is above SMA20."
  },
  {
    "id": "T2",
    "component": "trend_relative_strength",
    "label": "SMA20 is above SMA50."
  },
  {
    "id": "T3",
    "component": "trend_relative_strength",
    "label": "SMA20 is above its value five sessions earlier."
  },
  {
    "id": "T4",
    "component": "trend_relative_strength",
    "label": "The 20-session price return exceeds SPY on matching dates."
  },
  {
    "id": "T5",
    "component": "trend_relative_strength",
    "label": "The 20-session price return exceeds an explicitly assigned sector benchmark on matching dates."
  },
  {
    "id": "C1",
    "component": "catalyst",
    "label": "A material FAVORABLE catalyst supporting a prospective long entry is primary-source verified."
  },
  {
    "id": "C2",
    "component": "catalyst",
    "label": "That qualifying favorable catalyst's event or impact is within the next five trading sessions, or happened within the previous five with a supported continuing effect."
  },
  {
    "id": "C3",
    "component": "catalyst",
    "label": "That favorable catalyst has a documented positive mechanism supporting earnings, cash flow or demand rather than a headline alone."
  },
  {
    "id": "C4",
    "component": "catalyst",
    "label": "Relevant primary disconfirming evidence was checked and does not invalidate that favorable long-entry thesis."
  },
  {
    "id": "F1",
    "component": "fundamentals_valuation",
    "label": "Latest TTM operating cash flow is positive."
  },
  {
    "id": "F2",
    "component": "fundamentals_valuation",
    "label": "Positive trailing P/E is at or below its own three-year median; unknown if unsupported, fail for verified negative earnings or above-median valuation."
  },
  {
    "id": "L1",
    "component": "liquidity_event_risk",
    "label": "A fresh two-sided noncrossed spread is at most 0.20% at the reference timestamp."
  },
  {
    "id": "L2",
    "component": "liquidity_event_risk",
    "label": "Average 20-session daily dollar volume is at least USD20 million."
  },
  {
    "id": "L3",
    "component": "liquidity_event_risk",
    "label": "No verified scheduled earnings or major binary event lies within the next five trading sessions; unknown if the calendar was inadequately checked; include relevant macro events such as FOMC."
  }
];
  const WEIGHTS = {"entry_quality":30,"trend_relative_strength":25,"catalyst":20,"fundamentals_valuation":10,"liquidity_event_risk":15};
  const fields = ['evidence','id','observed_at','source_url','status'].join(',');
  function summarize(checks) {
    if (!Array.isArray(checks) || checks.length !== 20) throw Error('Exactly twenty evidence checks are required');
    const byId = new Map();
    for (const check of checks) {
      if (!check || typeof check !== 'object' || Object.keys(check).sort().join(',') !== fields ||
          !CHECKS.some(x => x.id === check.id) || byId.has(check.id) ||
          !['pass','fail','unknown'].includes(check.status) ||
          typeof check.evidence !== 'string' || !check.evidence.trim() ||
          !(check.source_url === null || typeof check.source_url === 'string') ||
          !(check.observed_at === null || typeof check.observed_at === 'string'))
        throw Error('Invalid evidence check');
      byId.set(check.id, check);
    }
    const counts = {pass:0,fail:0,unknown:0};
    const component_scores = Object.fromEntries(Object.keys(WEIGHTS).map(k=>[k,0]));
    for (const definition of CHECKS) {
      const status = byId.get(definition.id).status;
      counts[status]++;
      if (status === 'pass') component_scores[definition.component] += 5;
    }
    const score = counts.pass + counts.fail ? 5 * counts.pass : null;
    const unresolved = 5 * counts.unknown;
    return {score,coverage:5*(counts.pass+counts.fail),unresolved,counts,component_scores,
      completion_range:score===null?null:[score,score+unresolved]};
  }
  return {CHECKS,WEIGHTS,summarize};
});
