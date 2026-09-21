# Agentic Trader

A browsable research journal for long-only swing candidates and longer-term investments, with dated evidence, conditional entry criteria, downside analysis and manual execution.

**[Open the research dashboard](https://howardwhsrun.github.io/Agentic-Trader/)** · **[Current research watch](https://howardwhsrun.github.io/Agentic-Trader/watch.html)**

The dashboard has a [My portfolio view](https://howardwhsrun.github.io/Agentic-Trader/portfolio.html), an overview, dated research journal, searchable stock/ETF universe, a separate crypto archive, candidate details, historical strategy rules, and a learning guide. It uses real saved research snapshots. Baseline archives are labeled as archives; hypothetical price levels are not live quotes or executed trades.

## Current watch — September 21, 2026

The existing ChatGPT Investment Opportunity Watch checks approximately **08:00, 12:00 and 16:00 Monday–Friday, America/Chicago**. Each check starts with fresh Finances account and investment-holdings queries, including Robinhood, plus the available watchlist. Coverage, sync status and source valuation timestamps must be distinguished; a synced balance is not confirmed investable cash.

The research scope includes liquid U.S.-listed stocks and unleveraged ETFs: days-to-weeks long-only swing hypotheses and longer-term investment cases. Build the evidence, then challenge it with contrary evidence and independently verify material claims/calculations. This does not enable or verify an Ultra/maximum-thinking model setting. No options, leverage, margin, shorts or autonomous execution. No personalized dollar allocations or share quantities without confirmed suitability inputs.

Only materially supported new candidates or material thesis/risk changes qualify for alerts. There is no compulsory daily action brief, no repeated unchanged hold message, and no requirement to invest. The active watch's [settings, check status and public-safe alerts](https://howardwhsrun.github.io/Agentic-Trader/watch.html) are separate from earlier scanner records. See [WATCH_PUBLISHING.md](WATCH_PUBLISHING.md) for the update contract.

The legacy scanner's published universe contains 60 U.S. stocks/ETFs plus spot Bitcoin and Ethereum. Equities use completed exchange sessions and SPY-relative strength; crypto uses completed UTC days and a BTC/USD benchmark. Crypto volume and quotes are specific to the displayed venue, not consolidated market activity or Robinhood execution prices. These dated scanner results do not establish fair value, an investment recommendation or the active watch's scope. Crypto is not part of the current stock/ETF alert mandate. Earlier strategy examples, their percentage-based rules and their 1–5-session review clock remain historical context, not personal allocation instructions.

## What is published

Only the static site and purpose-built public exports are stored here. The existing exporter selects market metrics, research decisions, safe explanatory text, public source links, timestamps, and percentage-based strategy rules. A separately authorized My portfolio page shows purchase costs, share counts, dated position values, estimated unrealized P&L and aggregate account totals/cash/buying power. Account identifiers, deposits, orders, bank records, authentication details, personal recommendation quantities and raw source logs remain outside this repository. Some account-specific sentences are omitted from the public journal.

The new `docs/data/watch.json` feed contains public research and non-sensitive check status only, not raw Finances data or private account values. Its settings timestamp is separate from `last_check`. The latter remains null until an actual watch review is published; this website update is not a new market check. Existing portfolio snapshots and research history are preserved.

The first entry preserves the September 11, 2026 market snapshot. It is not a new scheduled check. The website itself does not query a brokerage, place trades, run a monitor, or guarantee that a scheduled check took place. Displayed timestamps show the latest published evidence; refreshing the page only reloads saved data.

## Development

No JavaScript packages or external assets are needed. Python 3.9 or later is sufficient for export, publication, and tests.

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory docs
```

Open `http://127.0.0.1:8765/` to preview the site. Serve it over HTTP so the browser can fetch its JSON data.

Export saved logs from a private directory outside the repository:

```sh
python3 scripts/export_research.py --logs ../logs --output docs/data/research.json
python3 -m unittest discover -s tests -v
```

Publish a new legacy scanner export after a research check:

```sh
python3 scripts/publish_logs.py --logs ../logs --state ../reports/pages-publish-state.json
```

The publisher verifies the repository and branch, refuses unrelated changes and exports only approved fields. With `--portfolio-source /private/path.json`, it also publishes the authorized latest portfolio and a matching immutable journal snapshot; without that argument, it publishes research data only. It never force-pushes. An unchanged export does not create an empty commit. Failed publication preserves the local research logs and records the error in the private state file. A successful push means deployment is pending, not that the site is already updated.

For the current watch, update only the safe fields in `docs/data/watch.json` after a real review, preserve history and follow [WATCH_PUBLISHING.md](WATCH_PUBLISHING.md). Validate with `python3 -m unittest discover -s tests -p 'test_watch.py' -v` before publication. Do not overwrite the separate scanner export to record a watch check.

## Hosting and updates

GitHub Pages publishes `main` → `/docs`, with `.nojekyll` for plain static files. See [GitHub's publishing-source documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

Older documentation described a separate local/Codex monitor at 08:45, 10:45, 12:45, 14:45 and 15:45 on weekdays. That scheduler is outside this repository and has **not been verified or changed by this website update**. The current ChatGPT watch uses the three-check schedule above. Editing the site does not reschedule an external host. Existing local publishing scripts are retained; any separate monitor requires its host to be available, and missed runs must never be invented.

Research and alerts do not establish a trade, an investment return, or a proven strategy. Stop levels model planned risk; gaps and slippage can produce larger losses.
