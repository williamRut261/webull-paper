# Webull Paper

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
