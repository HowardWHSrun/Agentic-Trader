# Public 32-stock scorecard publication contract

Version 2 scoring extension prepared October 26, 2026; original publication contract effective October 21, 2026. This replaces the old September three-check configuration for the current watch. It does not alter or rewrite historical research, legacy exports, or dated portfolio snapshots. This site is a static publication destination, not a broker connection, scheduler or execution system.

## Hard reviews and soft checks

Use the existing schedules, not a new automation. Hard reviews target 07:00, 08:00, 08:30, 09:00, 13:30 and 14:30 America/Chicago on full trading days. Verify official exchange holidays and early closes; skip full market holidays. Published remaining 2026 half-day afternoon targets are 10:30 and 11:30, November 27 and December 24. Soft checks run every ten minutes around the clock, including weekends and holidays; actual session and symbol tradability still require verification.

Every hard review publishes the actual all-32 score assessment and conditional action plans alongside the private text report. Every soft check publishes its own actual attempted/completed status and timestamp. A soft check MUST NOT change the hard-review publication time, assessment time, reference quotes, scores, or score history. Do not imply continuous protection or guaranteed delivery.

## Public-only schema version 2

`docs/watch.html` reads `docs/data/watch.json`. The landing page links to the scorecard. The original alert array and legacy archives are preserved.

- `last_hard_check`: an actually published assessment, or null. Fields: `id`, `publication_timestamp`, `assessment_snapshot`, `rubric_version`, `weights`, `cohort`, `summary`, `records`, `history_note`. Optional explicit correction metadata: `correction_of` and `correction_reason`.
- `last_soft_check`: null, or exactly `checked_at` (actual completion/check timestamp with timezone), `status` (`completed`, `partial`, `failed`), `summary`, `coverage`, `attempted` and `current`. All prose must be market-only. `current` is the count with usable current evidence, not a claim that every symbol is trading. Distinguish fresh trades, book-only evidence and stale/missing data in coverage. A failed attempt is not a successful check or a no-opportunity finding.
- `score_history`: immutable public originals in `docs/data/watch-history/<id>.json`. Every hard review has 32 records, including unavailable names. Never backfill a score with later information. Append corrections with their own publication time and reason; never overwrite an original.
- The legacy `last_check` field is retained for compatibility only; the UI uses the two separate fields above.

Record allowlist: `symbol`, `score`, `score_status`, `rubric_version`, `component_scores`, `reference_price`, `reference_price_type`, `reference_price_timestamp`, `reference_session`, `cohort`, `reference_source`, `reason`, `improvement_condition`, `conditional_action`, `horizon`, `sources`, `event`, `evidence_limitations`, `quote_delay`, `sizing`, `missing_evidence`. Version-2 rubric records additionally require `evidence_checks`; no other derived-metric fields are accepted.

Use the fixed universe: AAPL AVGO CRM MSFT NVDA GOOGL META AMZN HD COST KO PG WMT ABBV LLY UNH BAC JPM V CVX XOM CAT DE GE RTX DUK NEE FCX LIN PLD TSLA SPCX. Numeric scores are 0–100 in steps of five, descending with alphabetical ties. Unavailable scores are null, listed last, with specific gaps. Preserve actual reference-price timestamps and source sessions. An indicative ask is not a live trade or guaranteed executable price. Unknown quote delay stays unknown. Separate provisional-price, intraday and official-close cohorts.

Historical `buying-score-v1` weights: entry/risk-reward 30; trend/relative strength 25; catalyst 20; fundamentals/valuation 10; liquidity/event risk 15. Scores measure comparative several-day entry attractiveness, not probability of profit, a proven edge, order instruction or existing-position sell suitability. A new rubric starts a new version/cohort.


## buying-score-v2 — twenty fixed five-point checks

The feed remains schema version 2. The scoring rubric is `buying-score-v2`; it is a new rubric and cohort, not a reinterpretation of v1 history. Preserve all original v1 records and their validation. V2 retains component weights 30/25/20/10/15 through 6 entry, 5 trend, 4 catalyst, 2 fundamental and 3 liquidity/event checks.

Every v2 record requires `evidence_checks`, an array of exactly twenty objects. Each object contains **only** `id`, `status`, `evidence`, `source_url`, and `observed_at`. IDs must be unique and exactly E1–E6, T1–T5, C1–C4, F1–F2 and L1–L3. Status is `pass`, `fail` or `unknown`. Evidence is nonempty public-safe text supporting the conclusion or explaining the missing evidence. Use null source_url/observed_at when genuinely unavailable, for any status; never invent provenance. Non-null source URLs must pass the existing HTTPS/privacy checks, and non-null observed_at values must be zoned timestamps no later than the assessment.

Derive the metrics from states; do not publish independently editable coverage or range fields:

- Score = 5 × passes, with a **fixed denominator of 100**.
- Evidence coverage = 5 × (passes + fails) percent.
- Unresolved weight = 5 × unknown, in score points.
- Conditional completion range = score through score + unresolved weight, assuming evaluated checks stay unchanged. It is not a confidence interval or probability of profit.
- All twenty unknown means no numeric score (`score: null`, `score_status: "unavailable"`).
- Every numeric v2 result has `score_status: "available_provisional"` and must be labeled **Provisional evidence-based entry score**. Supplied numeric score must equal the derived value. Optional `component_scores`, when supplied, must equal the derived sums. A genuine zero with evaluated failed checks differs from unavailable.
- Unknown earns no verified credit but is not a negative business finding. Never divide by known checks or normalize missing weight upward. A failed setup check is not a sell instruction for an existing position.

Exact fixed checks (definitions also live in the versioned strategy book and deterministic scorer):

| ID | Pass condition |
| --- | --- |
| E1 | A support, retest or breakout setup level is identified from completed bars. |
| E2 | Reference entry lies within 0.5 ATR14 of that setup level. |
| E3 | A structural invalidation level is identified below a prospective long entry. |
| E4 | First defensible target gives at least 2R using reference entry and invalidation. |
| E5 | No intervening verified resistance obstructs the 2R path. |
| E6 | Reference entry is no more than 1 ATR14 above the 20-session SMA. |
| T1 | Last completed close is above SMA20. |
| T2 | SMA20 is above SMA50. |
| T3 | SMA20 is above its value five sessions earlier. |
| T4 | 20-session price return exceeds SPY on matching dates. |
| T5 | 20-session price return exceeds an explicitly assigned sector benchmark on matching dates. |
| C1 | A material FAVORABLE catalyst supporting a prospective long entry is primary-source verified. |
| C2 | That qualifying favorable catalyst's event/impact is within the next five trading sessions, or happened within the previous five with a supported continuing effect. |
| C3 | That favorable catalyst has a documented positive mechanism supporting earnings, cash flow or demand, rather than a headline alone. |
| C4 | Relevant primary disconfirming evidence was checked and does not invalidate that favorable long-entry thesis. |
| F1 | Latest TTM operating cash flow is positive. |
| F2 | Positive trailing P/E is at or below its own three-year median. Unknown if the comparison is unsupported; fail for verified negative earnings or above-median valuation. |
| L1 | A fresh two-sided noncrossed spread is at most 0.20% at the reference timestamp. |
| L2 | Average 20-session daily dollar volume is at least USD20 million. |
| L3 | No verified scheduled earnings or major binary event lies within the next five trading sessions. Unknown if the event calendar has not been adequately checked; include relevant macro events such as FOMC. |

These thresholds are transparent screening heuristics, not empirically validated edges or user-adopted loss/stop limits. A high score never overrides settled own funds, complete relevant holdings/orders, confirmed private dollar-risk budgets, or the user placing every order. Sizing remains exactly `Not provided on this public market-research page.`

### Core gates and reference cohorts

The researcher must verify correct security identity, a sufficiently fresh explicitly labeled reference price and sufficient relevant history before publishing a current-price score. The validator can enforce structure, time ordering and labels; it cannot verify market facts, actual identity, freshness or adequate history. State unresolved core gates in `missing_evidence` and withhold the numeric score until resolved, even if some checklist states are known. Checklist completeness is not entry eligibility.

Use one of these explicit v2 cohorts consistently on the review and every record:

- `v2-regular`: verified regular-session current trade reference, session `regular`.
- `v2-premarket`: verified premarket current trade reference, session `premarket`.
- `v2-provisional-book-price`: fresh bid/ask/book reference with its actual session explicitly labeled. This is not a live trade or guaranteed executable price.
- `v2-official-close`: verified official regular-session close for a review whose intended reference is that close.
- `v2-historical-official-close`: a dated verified official regular-session close plus adequate relevant history, assessed **now**, when a usable current reference is absent. Display **Historical observation; not a current entry score**, preserving close date, session and actual reference time.

Do not backdate assessment or publication. Never mix regular, premarket, book and official-close references in one cohort, or compare v1 and v2 numbers as if calibrated alike. A missing current price does not permit an invented historical reference; unavailable remains valid when core evidence or all check states are unknown. Unknown quote delay remains unknown. Keep the existing `conditional_action` field (the schema has no `conditional_action_plan` alias), and make historical-only action prose explicitly avoid current-entry implications.

The v2 helper validates all twenty checks and derived component sums, then applies the existing append-only publication procedure. Original v1 histories remain immutable, and soft updates cannot modify either rubric's scores, references or assessment/publication timestamps. Existing numeric v1 `available_provisional` records must also be visibly labeled provisional.

## Privacy boundary

Build a reviewed allowlist export. NEVER copy an entire private report or brokerage response. No holdings, balances, quantities, cost bases, deposits, personalized allocations, account identifiers, credentials, private audit paths, transaction histories, private plans or account-specific trading restrictions may appear in this feed. Text also needs review: removing private JSON keys does not sanitize narrative sentences. Public `sizing` must say only that sizing is not provided on this public market-research page. Existing separately authorized legacy pages are outside this update's scope and must not be modified by this publisher.

## Safe update procedure

1. Read latest main and JSON; preserve intervening updates, alerts, research and history. Do not publish findings before the review is actually completed/published. Read-only market research is separate from website publication.
2. Prepare a sanitized public-only input outside the repository. For a hard review, include all 32 and their actual original publication/reference times. For soft checks, use only the six status fields above.
3. Run `python3 scripts/update_watch.py hard /path/to/public-review.json` or `python3 scripts/update_watch.py soft /path/to/public-soft-status.json`. This helper only writes local files; it does not query markets, trade, schedule or push. It rejects unknown fields, missing symbols, naive timestamps, invalid scores and rewriting an original history ID. Human review remains required for narrative privacy. Soft updates leave hard scores untouched.
4. Run `python3 -m unittest discover -s tests -v`. Review the exact diff for public safety. Commit only intended paths and never force-push. On branch conflict, reread and merge newer changes rather than overwrite.
5. Verify the exact commit's GitHub Pages build/deploy outcome, then fetch the live JSON/page and verify the publication ID or soft timestamp. A commit is not deployment confirmation. If deployment fails, preserve the research and report the publication problem honestly.

Refresh only reloads published JSON. The page does not execute checks or read a brokerage. Chat reporting continues separately under its existing notification rules.

## Separate descriptive outcome archive (version 1)

`docs/outcomes.html` reads `docs/data/outcomes/index.json` and immutable audit files. This is separate from schema-v2 score assessments. An outcome audit must not mutate `watch.json`, its hard/soft timestamps, or any original score-history record. It is not a new buying score or a claim of executable returns.

Use `python3 scripts/publish_outcome.py /path/to/reviewed-public-audit.json` with sanitized input outside the repository. The helper enforces an allowlist, all-32 coverage, correct reference-return arithmetic, explicit rubric, dated cohorts, and append-only IDs. Narrative privacy still requires human review. Corrections get a new ID and their own real timestamps. The catalog appends rather than replacing past audits. Preserve original publication/reference times, analysis completion/first-publication time and actual website-export creation time separately. Git commit and verified Pages deployment provide actual release evidence, never backdate deployment to the export.

Include all publication windows, not selected winners; show sample sizes, fixed buckets, rank correlations, reference-to-publication lag and sensitivity. Keep intraday, provisional and official-close cohorts distinct. Unsupported benchmark excess returns and immature/unverified horizons remain unavailable. Label overlap, incomplete data and corporate-action gaps. The public archive contains research conclusions, evidence and limitations, never internal reasoning or private account information. Review exact scoped diffs, run all tests, lease against fresh main, and verify the exact Pages deployment plus live audit ID before claiming publication.
