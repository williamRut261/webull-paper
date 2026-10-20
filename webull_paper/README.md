**Activation paused until the new repository has sandbox credentials and the old scheduled workflow is disabled.**

# Webull strategy PaperTrade (sandbox only)

This is a separate Webull SANDBOX integration. Its weekday automatic paper order workflow is `.github/workflows/webull-auto-execute.yml`; the original Alpaca paper bot is manual-only and the separate real-money Alpaca repository is untouched.

## Verified with Webull PaperTrade
- API authentication, account list, balances and positions: HTTP 200.
- All 69 strategy signal symbols available via official Webull sandbox market data; 57 had at least 1000 daily bars, 12 had shorter histories.
- Original 501-node strategy with Webull forward-adjusted bars: Oct 9, 2026 -> 100% GDXD source allocation -> 99% sandbox target, 1% cash.
- CASH sandbox account index 0 returned $5,000 simulated equity and cash, no holdings.
- No actual paper order was submitted.

## Safe read-only check
Command: `python -m webull_paper.paper_orders`. Requires repository secrets `WEBULL_PAPER_APP_KEY` and `WEBULL_PAPER_APP_SECRET`, hard-coded endpoint `api.sandbox.webull.com`.
The GitHub Actions workflow `.github/workflows/webull-readiness.yml` runs this read-only check on demand and on relevant pull requests; it is **not** automatically scheduled. It also executes `python -m webull_paper.audit_quotes`, a market-data GET-only freshness audit for all 69 symbols. Neither step submits or previews orders.

## Remaining before automatic sandbox order submission
1. Confirm historical and intraday signal coverage, including the 15-minute sandbox market-data delay. Fresh 3-minute snapshots should not be assumed or required for a delayed-data strategy.
2. Validate actual ticker fractionability and duplicate-order protections.
3. The scheduled Webull SANDBOX runner uses `python -m webull_paper.automatic`. It explicitly activates *only* test-account orders, guards unique client order IDs and open/history checks, previews every order, rechecks portfolio and cash, and verifies each fill before the next order. No live brokerage endpoint is configured.
4. **Actual sandbox order fills are unverified until a valid open-market run.** Unknown order statuses, unexpected response schemas, unavailable symbols, and stale >20-minute quotes abort before further orders; they are not bypassed.
5. Webull's market data is not proven identical to Composer's. The executable strategy JSON and evaluator are preserved; execution uses the designated $5,000 sandbox CASH account (index 0), a 99% max target and a conservative buy-price buffer. There are five sandbox accounts; the selected CASH account at index 0 is pinned using its SHA-256 account-ID fingerprint so account reordering or selection changes stop all orders.

Manual read-only plan: `python -m webull_paper.paper_orders`. Automatic sandbox order driver: `python -m webull_paper.automatic`; it requires verified sandbox credentials, `WEBULL_PAPER_EXECUTE_ENABLED=true`, and `WEBULL_PAPER_ACCOUNT_INDEX=0`. The workflow supplies those two activation settings for scheduled paper-only runs. All trades remain paper/simulated, never real money.

**Schedule reliability:** The paper runner now stages at **1:08 PM Eastern (12:08 PM Houston)** and waits until the **3:48 PM Eastern (2:48 PM Houston)** signal, allowing approximately **160 minutes** of scheduling headroom. GitHub runner timeout is 240 minutes. This may consume thousands of billable GitHub Actions minutes per month on a private repo. Runs arriving after 3:54 PM Eastern fail visibly with `PAPER_MISSED_WINDOW` instead of silently reporting success. This does not bypass quote freshness, account pinning, duplicate-order checks or preview/fill verification.

## Oct 14 market-data failure repair

The Oct 14 automatic run reached the trading window but aborted on an old AGQ snapshot, even when AGQ was not used by the selected strategy branch. The collector now records unusable quotes as missing for that day's signal evaluation (never substitutes previous prices). The existing lazy evaluator refuses a stale/missing ticker if it is referenced by the active condition, filter, or weight, and the selected order targets additionally must have fresh snapshots. Positions requiring sales still require validated execution quotes. Duplicates and malformed broker API structures remain fail-closed. This prevents irrelevant stale tickers from blocking otherwise valid simulated orders; it does not remove quote freshness requirements or guarantee future fills. The next scheduled market session is needed to verify real sandbox order placement.

## Two-timestamp Webull signal consensus (Oct 14)

The scheduled sandbox bot now requests and independently evaluates two Webull quote snapshots separated by 3 seconds. Both allocations must match before claiming the trading day or making paper orders. Selected-symbol execution quotes must remain valid in both readings; a selected price jump over 10% or a session-window timeout fails closed. The second validated snapshot prices are used to size orders. This is **not** independent exchange-level corroboration: both observations use the same Webull sandbox feed, which is **15-minute delayed by default** and may contain old last-trade timestamps for thinly traded assets. It does not remove the underlying delay or imply parity with Alpaca's IEX/SIP dual-feed confirmation. The next market session must still verify actual paper fills.
