# Webull Paper

Webull OpenAPI sandbox-only trading research and paper execution.

**No real-money trading.** The scheduled paper workflow stays disabled until the repository's required sandbox secrets and account pin have been configured, and the previous scheduler has been retired.

## Setup
Store these GitHub Actions secrets (never commit them):
- `WEBULL_PAPER_APP_KEY`
- `WEBULL_PAPER_APP_SECRET`
- `WEBULL_PAPER_ACCOUNT_SHA256` — SHA-256 hexadecimal digest of the verified sandbox CASH account identifier

The paper execution workflow also requires the repository variable `WEBULL_PAPER_ACTIVE` set to exactly `true`, after the preceding scheduler is disabled.

The strategy rules and historical data approximations may differ from a broker's calculations. Automation checks prevent duplicate orders and require verified market timestamps.
