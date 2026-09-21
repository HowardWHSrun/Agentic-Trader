# Research-watch publication contract

Effective September 21, 2026. These settings supersede older descriptions of five local checks, compulsory daily action briefs and short-term-only research for the current ChatGPT watch. Historical research and its recorded rules are not rewritten.

## Schedule and ownership

Reuse the existing Investment Opportunity Watch: approximately 08:00, 12:00 and 16:00 Monday–Friday, America/Chicago. No new scheduled watch, weekend schedule or autonomous execution is authorized. The separate local/Codex monitor described in older documentation is outside the website; its scheduler has not been inspected or changed by this update. Editing this repository does not reschedule that host.

`docs/watch.html` displays `docs/data/watch.json`. This is a static publication destination, not a broker connection or scheduler. The current website update is configuration only, so `last_check` starts as null. Do not seed it with a fictional successful market check, copy an old alert as a new one, or mark a partial check as no opportunities.

## Updating after an actual scheduled check

1. Read the latest default-branch contents, this contract and the current JSON. Preserve intervening edits and the existing alert history. Preserve all legacy research and dated portfolio files.
2. Run the current research instructions, including fresh Finances accounts/holdings, watchlist and coverage checks. Use primary sources and timestamped market data; challenge the thesis and check calculations. Prior messages and scanner outputs are not independent evidence.
3. Replace `last_check` only with the actual check time, status and public-safe summary/coverage. Use `completed_alert`, `completed_no_alert` or `incomplete`. A holdings check alone is not a completed market review. A quiet completed check can update the site without notifying the user. A persistent material access issue is not a no-opportunity result.
4. Append a materially supported public-safe alert only once, using a stable unique ID. Keep earlier dated alerts; correct a material earlier error explicitly instead of silently changing history. Do not publish stale entry conditions as current. Public alerts must omit the user's portfolio-specific sentences, holdings, balances, quantities, deposits and private plans. Leave the separately authorized portfolio pipeline and source snapshots unchanged under this contract.
5. Validate with `python3 -m unittest discover -s tests -p 'test_watch.py' -v` and existing tests when available. Commit only intended paths, never force-push. Read the latest blob SHA before a content update. On conflict, re-read and merge; do not overwrite newer checks.
6. Verify the exact commit's GitHub Pages build/deploy result. A committed change is not confirmation of deployment. If publication fails, keep verified research results and report a persistent material publication problem without inventing a successful website update.

No personal account IDs, tokens, authentication material, transaction histories, bank records, private source logs, contribution plans or individual allocation instructions belong in this feed. A request to maintain this public research page is not permission to export raw Finances results. Model/Ultra settings cannot be selected or verified by the task controls; the two-pass method is a research instruction only.

## JSON schema (version 1)

Keep the existing configuration fields. `configuration_updated_at` changes only when settings change, not on every review. All event timestamps require ISO 8601 with a timezone offset or Z. Public market quote timestamps need the actual source time, not the fetch time.

`last_check` is null until a real review is published, or an object with:

- `checked_at`: actual ISO timestamp.
- `status`: `completed_alert`, `completed_no_alert` or `incomplete`.
- `summary`: short public-safe description; do not claim exhaustive market coverage.
- `coverage`: limitations of quotes, sources and verification; no private account values.

`alerts` is an array, initially empty. Each entry includes `id`, `label` (`TRADING CANDIDATE` or `LONGER-TERM INVESTMENT CANDIDATE`), `ticker`, `name`, `published_at`, `summary`, `entry`, `horizon`, `invalidation`, `risks`, `alternative`, `conclusion`, `quote` and `sources`. Use a risk-update phrase in `name` for material changes, without asserting public ownership. `exit` is optional and must be evidence-supported, not invented.

`quote` contains numeric `price`, `currency`, source timestamp `as_of`, `session` and known `delay` (explicitly `unknown` if not supplied). `sources` contains at least one verified public source as `{ "title": "...", "url": "https://..." }`. Evidence for catalysts/fundamentals must come from primary documents, not just a quote page. Conditional upside/downside is not a prediction. Stops can gap.

The website refresh button only fetches the latest published JSON. It does not initiate market research or refresh Finances.
