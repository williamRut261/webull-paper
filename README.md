# Webull Paper

Webull OpenAPI sandbox-only trading research and paper execution.

**No real-money trading.** The previous private-repository scheduler was retired on October 19, 2026. This public repository's scheduled paper job remains inactive until its sandbox secrets, cash-account pin, and activation flag are configured and independently verified.

## Setup
Store these GitHub Actions secrets (never commit them):
- `WEBULL_PAPER_APP_KEY`
- `WEBULL_PAPER_APP_SECRET`
- `WEBULL_PAPER_ACCOUNT_SHA256` — SHA-256 hexadecimal digest of the verified sandbox CASH account identifier

The paper execution workflow also requires the repository variable `WEBULL_PAPER_ACTIVE` set to exactly `true`. Leave it unset/false until the read-only sandbox connection and account-pin match have passed. Never add these secrets as ordinary repository variables or source files. The previous scheduler is already retired.

The strategy rules and historical data approximations may differ from a broker's calculations. Automation checks prevent duplicate orders and require verified market timestamps.

## Cutover checks

1. Set the three GitHub Actions **repository secrets** listed above via Settings > Secrets and variables > Actions.
2. Run the read-only Webull PaperTrade API Connection workflow and Webull PaperTrade Allocation Plan workflow. Confirm API access and `account_pin_matches: true` in the GET-only order-preflight output.
3. Only after checking the two read-only runs, set the GitHub Actions **repository variable** `WEBULL_PAPER_ACTIVE` to `true`. This activates only the sandbox job; never a real-money endpoint.
4. Check the first scheduled paper session for a successful real sandbox order and verify no duplicate order history.
