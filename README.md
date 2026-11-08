# Agentic Trader

A browsable research journal for long-only swing candidates and longer-term investments, with dated evidence, conditional entry criteria, downside analysis and manual execution.

**[Open the research dashboard](https://howardwhsrun.github.io/Agentic-Trader/)** · **[Current research watch](https://howardwhsrun.github.io/Agentic-Trader/watch.html)**

The dashboard has a [My portfolio view](https://howardwhsrun.github.io/Agentic-Trader/portfolio.html), an overview, dated research journal, searchable stock/ETF universe, a separate crypto archive, candidate details, historical strategy rules, and a learning guide. It uses real saved research snapshots. Baseline archives are labeled as archives; hypothetical price levels are not live quotes or executed trades.

## Current watch — October 21, 2026

The [32-stock scorecard](https://howardwhsrun.github.io/Agentic-Trader/watch.html) shows every fixed-universe ticker, ranked buying-at-reference-price scores, conditional action plans, evidence gaps and primary-source links. This is saved market research, not live quotes or an order system.

Hard reviews publish full assessments alongside text reports. Ten-minute soft checks update a separate timestamp and coverage status without refreshing old scores or prices. Full-day hard-review targets are 07:00, 08:00, 08:30, 09:00, 13:30 and 14:30 America/Chicago, subject to verified holidays and early closes. Existing schedules are maintained externally; this website does not create or change them. See [WATCH_PUBLISHING.md](WATCH_PUBLISHING.md) for the current contract and safe update helper.

No private portfolio information or personalized purchase sizing is included in this scorecard feed. All trades remain manual, with no options, leverage, borrowing or short selling. A score is not a probability of profit or an instruction to buy.

The legacy scanner's published universe contains 60 U.S. stocks/ETFs plus spot Bitcoin and Ethereum. Equities use completed exchange sessions and SPY-relative strength; crypto uses completed UTC days and a BTC/USD benchmark. Crypto volume and quotes are specific to the displayed venue, not consolidated market activity or Robinhood execution prices. These dated scanner results do not establish fair value, an investment recommendation or the active watch's scope. Crypto is not part of the current stock/ETF alert mandate. Earlier strategy examples, their percentage-based rules and their 1–5-session review clock remain historical context, not personal allocation instructions.

## Options intraday scan / 期权盘中扫描

A GitHub Actions workflow (`.github/workflows/options-scan.yml`) scans every 10 minutes during the NYSE regular session (09:30–16:00 ET; 13:00 on early-close days; no runs on weekends or NYSE holidays). It analyses the watch universe plus SPY/QQQ with delayed Yahoo Finance chains and **pushes only important events, each at most once per day**:

- **Big block** (🐋): one contract with ≥2,000 volume, ≥5× open interest and ≥$1M premium traded.
- **IV shock** (⚡): IV30 moves ≥8 vol points *and* ≥25% from the 10:00 ET baseline.
- **Big move** (📈/📉): price move ≥2σ of the one-day implied move and ≥3%.
- **Technical entry candidate** (🎯): `scripts/entry_screen.py` automates the price-derivable buying-score-v2 checks from completed daily bars: close > SMA20 > SMA50, SMA20 rising, 20-session return beating SPY, price within 1 ATR14 of SMA20, a setup within 0.5 ATR (pullback to SMA20 or fresh 20-session-high breakout), a structural invalidation, a 2R path clear of the 120-session high, ≥$20M average dollar volume and no earnings within ~5 sessions. Catalyst, fundamentals, spread and macro-event checks are not automated, so a 🎯 is a candidate to research, not a buy signal.

Quiet days send nothing. Every scan's full report still lands in the run summary and a 7-day artifact. Set the repository variable `OPTIONS_PUSH_DIGEST=true` to also receive one full digest at 10:00 ET. Thresholds are constants at the top of `scripts/options_analysis.py`. GitHub may delay or skip scheduled runs under load. Inspired by the scheduling/notification design of [ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis). This is research output only; it places no orders and does not change the watch's execution rules.

Metrics: IV30 (ATM ~30 DTE), HV20, IV/HV, IV Rank (from IV history kept in the Actions cache, shown after 20 runs), weekly expected move (ATM straddle), 95/105 put–call skew, put/call volume and open-interest ratios, front-expiry max pain, unusual volume (≥3× OI and ≥500 contracts), earnings within 14 days.

Set any of these repository **Secrets** to receive the reminder (Settings → Secrets and variables → Actions):

| Channel | Secrets |
|---|---|
| ntfy (phone push, no account) | `NTFY_TOPIC` (optional `NTFY_TOKEN`; variable `NTFY_SERVER`) |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Discord | `DISCORD_WEBHOOK_URL` |
| Email (Gmail app password) | `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS` (variables `SMTP_SERVER`, `SMTP_PORT`) |

The full Markdown report appears in the run summary and as a 30-day artifact. Scheduled workflows only run from the default branch. Run locally:

```sh
pip install -r requirements-options.txt
python3 scripts/options_analysis.py --symbols SPY,AAPL --force          # one-off report
python3 scripts/options_analysis.py --scan                                # intraday alerts
python3 scripts/trading_calendar.py --date 2026-11-26
```

## What is published

Only the static site and purpose-built public exports are stored here. The existing exporter selects market metrics, research decisions, safe explanatory text, public source links, timestamps, and percentage-based strategy rules. A separately authorized My portfolio page shows purchase costs, share counts, dated position values, estimated unrealized P&L and aggregate account totals/cash/buying power. Account identifiers, deposits, orders, bank records, authentication details, personal recommendation quantities and raw source logs remain outside this repository. Some account-specific sentences are omitted from the public journal.

The new `docs/data/watch.json` feed contains public research and non-sensitive check status only, not raw Finances data or private account values. Its settings timestamp is separate from `last_check`. Separate hard-review and soft-check timestamps now show the actual published checks. Existing portfolio snapshots and research history are preserved.

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

Older documentation described a separate local/Codex monitor at 08:45, 10:45, 12:45, 14:45 and 15:45 on weekdays. That scheduler is outside this repository and has **not been verified or changed by this website update**. The current review and soft-check schedules are described above. Editing the site does not reschedule an external host. Existing local publishing scripts are retained; any separate monitor requires its host to be available, and missed runs must never be invented.

Research and alerts do not establish a trade, an investment return, or a proven strategy. Stop levels model planned risk; gaps and slippage can produce larger losses.
