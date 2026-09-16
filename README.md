# Agentic Trader

A browsable investing research journal: business value guides the approach, technical evidence helps with timing, and dated records show what was known.

**[Open the research dashboard](https://howardwhsrun.github.io/Agentic-Trader/)**

The dashboard has a [My portfolio view](https://howardwhsrun.github.io/Agentic-Trader/portfolio.html), an overview, dated research journal, searchable stock/ETF universe, a separate crypto research view, candidate details, strategy rules, and a learning guide. It uses real saved research snapshots. Baseline archives are labeled as archives; hypothetical price levels are not live quotes or executed trades.

The current coverage is 60 U.S. stocks/ETFs plus spot Bitcoin and Ethereum. Equities use completed exchange sessions and SPY-relative strength; crypto uses completed UTC days and a BTC/USD benchmark. Crypto volume and quotes are specific to the displayed venue, not consolidated market activity or Robinhood execution prices. The scanner retains its recorded position/risk guardrails. Its technical results do not establish fair value or an investment recommendation. Crypto has no executable sizing or qualified alerts until its broker and event checks can be established.

The current Strategy view explains thesis review, bear/base/bull valuation scenarios, cash-flow growth, margin of safety, and technical review zones. The separately published company review presents dated sources and valuation assumptions; the technical scanner itself does not calculate intrinsic value. Earlier swing-era logs and their hypothetical entry/stop/2R scenarios remain historical records; chart resistance is not an automatic current exit instruction.

## What is published

Only the static site and a purpose-built public export are stored here. The exporter selects market metrics, research decisions, safe explanatory text, public source links, timestamps, and percentage-based strategy rules. A separately authorized My portfolio page shows purchase costs, share counts, dated position values, estimated unrealized P&L and aggregate account totals/cash/buying power. Account identifiers, deposits, orders, bank records, authentication details, personal recommendation quantities and raw source logs remain outside this repository. Some account-specific sentences are omitted from the public journal.

The first entry preserves the September 11, 2026 market snapshot. It is not a new scheduled check. Future checks appear when the local monitor successfully records and publishes them. The website itself does not query a brokerage, place trades, run the monitor, or guarantee that a scheduled check took place. The displayed timestamps show the latest published evidence.

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

Publish a new public export after a research check:

```sh
python3 scripts/publish_logs.py --logs ../logs --state ../reports/pages-publish-state.json
```

The publisher verifies the repository and branch, refuses unrelated changes and exports only approved fields. With `--portfolio-source /private/path.json`, it also publishes the authorized latest portfolio and a matching immutable journal snapshot; without that argument, it publishes research data only. It never force-pushes. An unchanged export does not create an empty commit. Failed publication preserves the local research logs and records the error in the private state file. A successful push means deployment is pending, not that the site is already updated.

## Hosting and updates

GitHub Pages publishes `main` → `/docs`, with `.nojekyll` for plain static files. See [GitHub's publishing-source documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

The local monitor is scheduled for five weekday checks in America/Chicago: 08:45, 10:45, 12:45, 14:45, and 15:45. Equity checks follow the actual exchange calendar; crypto uses its own daily calendar within the same weekday schedule. No weekend checks are enabled. The monitor publishes after saving each research log, including quiet checks with no opportunity. Local scheduling requires the host and Codex to be available; missed runs are never invented.

Research and alerts do not establish a trade, an investment return, or a proven strategy. Stop levels model planned risk; gaps and slippage can produce larger losses.
