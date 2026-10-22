# Public 32-stock scorecard publication contract

Effective October 21, 2026. This replaces the old September three-check configuration for the current watch. It does not alter or rewrite historical research, legacy exports, or dated portfolio snapshots. This site is a static publication destination, not a broker connection, scheduler or execution system.

## Hard reviews and soft checks

Use the existing schedules, not a new automation. Hard reviews target 07:00, 08:00, 08:30, 09:00, 13:30 and 14:30 America/Chicago on full trading days. Verify official exchange holidays and early closes; skip full market holidays. Published remaining 2026 half-day afternoon targets are 10:30 and 11:30, November 27 and December 24. Soft checks run every ten minutes around the clock, including weekends and holidays; actual session and symbol tradability still require verification.

Every hard review publishes the actual all-32 score assessment and conditional action plans alongside the private text report. Every soft check publishes its own actual attempted/completed status and timestamp. A soft check MUST NOT change the hard-review publication time, assessment time, reference quotes, scores, or score history. Do not imply continuous protection or guaranteed delivery.

## Public-only schema version 2

`docs/watch.html` reads `docs/data/watch.json`. The landing page links to the scorecard. The original alert array and legacy archives are preserved.

- `last_hard_check`: an actually published assessment, or null. Fields: `id`, `publication_timestamp`, `assessment_snapshot`, `rubric_version`, `weights`, `cohort`, `summary`, `records`, `history_note`. Optional explicit correction metadata: `correction_of` and `correction_reason`.
- `last_soft_check`: null, or exactly `checked_at` (actual completion/check timestamp with timezone), `status` (`completed`, `partial`, `failed`), `summary`, `coverage`, `attempted` and `current`. All prose must be market-only. `current` is the count with usable current evidence, not a claim that every symbol is trading. Distinguish fresh trades, book-only evidence and stale/missing data in coverage. A failed attempt is not a successful check or a no-opportunity finding.
- `score_history`: immutable public originals in `docs/data/watch-history/<id>.json`. Every hard review has 32 records, including unavailable names. Never backfill a score with later information. Append corrections with their own publication time and reason; never overwrite an original.
- The legacy `last_check` field is retained for compatibility only; the UI uses the two separate fields above.

Record allowlist: `symbol`, `score`, `score_status`, `rubric_version`, `component_scores`, `reference_price`, `reference_price_type`, `reference_price_timestamp`, `reference_session`, `cohort`, `reference_source`, `reason`, `improvement_condition`, `conditional_action`, `horizon`, `sources`, `event`, `evidence_limitations`, `quote_delay`, `sizing`, `missing_evidence`.

Use the fixed universe: AAPL AVGO CRM MSFT NVDA GOOGL META AMZN HD COST KO PG WMT ABBV LLY UNH BAC JPM V CVX XOM CAT DE GE RTX DUK NEE FCX LIN PLD TSLA SPCX. Numeric scores are 0–100 in steps of five, descending with alphabetical ties. Unavailable scores are null, listed last, with specific gaps. Preserve actual reference-price timestamps and source sessions. An indicative ask is not a live trade or guaranteed executable price. Unknown quote delay stays unknown. Separate provisional-price, intraday and official-close cohorts.

`buying-score-v1` weights: entry/risk-reward 30; trend/relative strength 25; catalyst 20; fundamentals/valuation 10; liquidity/event risk 15. Scores measure comparative several-day entry attractiveness, not probability of profit, a proven edge, order instruction or existing-position sell suitability. A new rubric starts a new version/cohort.

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
