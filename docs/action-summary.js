/* Display recorded public decisions; never infer trades from price patterns. */
(function (root) {
  "use strict";
  function recordedActions(entry) {
    if (!entry || entry.check_type === "failed_check" || entry.decision === "monitor_failure") return [];
    const seen = new Set();
    return (Array.isArray(entry.candidates) ? entry.candidates : []).flatMap((candidate) => {
      const reason = candidate?.review?.why_interesting;
      if (typeof reason !== "string" || typeof candidate.symbol !== "string" || seen.has(candidate.symbol)) return [];
      const text = reason.trim();
      const match = /^(EXIT|SELL|TRIM|REDUCE|HOLD|BUY)(?=[\s:;.!/—]|$)/.exec(text);
      if (!match) return [];
      const qualification = text.slice(match[0].length).replace(/^[\s:;.!/—–-]+/, "");
      if (/^(?:(?:is|was)\s+)?(?:not\b|withdrawn\b|cancelled\b|canceled\b|if\b|when\b|unless\b|only\b|pending\b)/i.test(qualification)) return [];
      const action = ({ SELL: "EXIT", REDUCE: "TRIM" })[match[1]] || match[1];
      if (action === "BUY" && entry.decision !== "qualified_opportunity") return [];
      seen.add(candidate.symbol);
      return [{ symbol: candidate.symbol, action, label: action === "EXIT" ? "SELL / EXIT" : action,
        reason: text, condition: typeof candidate.review.what_would_change === "string" ? candidate.review.what_would_change : "" }];
    });
  }
  function presentation(entry) {
    const actions = recordedActions(entry);
    const failed = entry?.check_type === "failed_check" || entry?.decision === "monitor_failure";
    const archived = entry?.check_type === "baseline_archive";
    const exitCount = actions.filter((action) => action.action === "EXIT").length;
    const trimCount = actions.filter((action) => action.action === "TRIM").length;
    const entryLabel = failed ? "New-entry review incomplete" : entry?.decision === "qualified_opportunity"
      ? "New entry qualified in this record" : "New entries: none qualified";
    const heading = failed ? "Review incomplete" : exitCount ? "Sell actions recorded" : trimCount ? "Trim actions recorded"
      : actions.some((action) => action.action === "BUY") ? "Buy action recorded"
      : actions.some((action) => action.action === "HOLD") ? "Hold actions recorded" : entryLabel;
    return { actions, exitCount, trimCount, entryLabel, heading: archived ? `Historical · ${heading}` : heading,
      tone: failed || exitCount || trimCount ? "red" : entry?.decision === "qualified_opportunity" ? "teal" : "amber", failed, archived };
  }
  const api = Object.freeze({ recordedActions, presentation });
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ResearchActions = api;
})(typeof globalThis === "object" ? globalThis : this);
