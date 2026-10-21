# Webull Paper

## Beethoven + Trader Skill: automated stock/ETF PAPER sleeves

This repository now contains an optional combined automatic Webull **sandbox
paper-trading** strategy (no real brokerage API endpoints):

- The original Beethoven 501-node signal decision tree is unchanged, but its
  allocation is scaled proportionally from 99% to **80% of account equity**.
- The original Day Trader Skill opening-range-breakout scanner searches a
  separate, explicit stock **and ETF** candidate universe and may automatically
  **buy** up to **19% of equity** at 10:20-10:40 AM New York time.
- At about 3:48 PM New York time, the original Beethoven paper runner verifies
  scanner holdings from filled bot order history and attempts to **sell them**
  before rebalancing the Beethoven 80% allocation. The combined maximum target
  is 99% of equity, with 1% intended spare cash.
- Early-entry and close workflows are best-effort GitHub Actions; delayed
  schedules, Yahoo data failures, delayed broker quotes, unavailable products,
  order rejections or cash restrictions can cause skipped orders or overnight
  positions. The original skill's example stop/target levels are currently
  **advisory sizing inputs, not protective orders**.
- Only the scanner's breakout and conservative sizing logic is wired to
  autonomous sandbox execution. Other Trader Skill modules (Time Machine,
  News, Analyst, Pelosi, Alerts, etc.) remain independent research tools and
  are NOT automated trading gates. No profitability has been demonstrated.

See [combined strategy operation](trader_combo/README.md) and the
[original research toolkit](research/README.md). The change is restricted
to this Webull PAPER repo; it does not alter Alpaca LIVE or Webull LIVE.


Scheduled Webull OpenAPI **sandbox-only** paper-trading bot. This repository is public; its GitHub-hosted standard runner does not consume the private-repository Actions minute allowance.

## Activation status

- **Automatic sandbox orders:** enabled for scheduled weekday GitHub Actions runs only.
- **Schedule:** 2:58 PM New York / 1:58 PM Houston; evaluate at 3:48 PM New York / 2:48 PM Houston.
- **Manual workflow dispatch:** never places orders (the trading job is skipped).
- **Old private scheduler:** retired with its schedule removed and job hard-disabled.
- **Real-money trading:** not supported by this repository; fixed SDK host `api.sandbox.webull.com`.

Previous read-only production-like sandbox checks confirmed HTTP 200 authentication, the designated CASH account's SHA-256 pin, and readable order history. **Actual first post-cutover sandbox fills and within-session market-data freshness remain unverified.** The bot aborts instead of trading on stale/invalid required quotes, mismatched account, incomplete order history, incorrect signal timing, or unsafe order responses. GitHub scheduled jobs are best-effort and may run late.

## Required GitHub Actions secrets

Keep these as repository **secrets**, not variables or code:

- `WEBULL_PAPER_APP_KEY` — sandbox key only
- `WEBULL_PAPER_APP_SECRET` — sandbox secret only
- `WEBULL_PAPER_ACCOUNT_SHA256` — verified CASH account-ID SHA-256

The scheduling gate is maintained in `.github/workflows/webull-auto-execute.yml`: `github.event_name == 'schedule'`. No additional repository activation variable is needed.

## Read-only checks

- `.github/workflows/webull-paper-connection.yml`: sandbox authentication and GET-only access.
- `.github/workflows/webull-readiness.yml`: allocation, quote coverage, pinned cash account, and order history; **never submits an order**.
- `.github/workflows/tests.yml`: mocked offline regression tests, no account access.

Strategy timing, fill sequencing, duplicate-order checks, and 99% maximum intended allocation are preserved from the previous private sandbox bot. Market-data differences from other brokers can produce different allocations.

## Optional independent trading research (Oct. 20, 2026)

The 11 MIT-licensed Day Trader Skill Python modules are vendored under
`vendor/day_trader_skill/` and connected through an **advisory-only**
log report. The existing scheduled Webull sandbox orders and all strategy
indicators remain exactly as before. `Day Trader Research (MANUAL - NO BROKER
ORDERS)` runs public-data scanner/news/SEC research without broker secrets.
The existing Webull paper workflow attaches `logs/beethoven-research.json`
when available. See `research/README.md`. The Time Machine needs a separate
intraday plan and does NOT predict Beethoven's multi-ETF future returns.
