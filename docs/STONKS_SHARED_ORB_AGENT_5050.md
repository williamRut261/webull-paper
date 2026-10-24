# Webull PAPER: shared-account ORB + seven-agent desk (50/50)

**Status: STAGED in PR, NOT ACTIVE, NO BROKER ORDERS PLACED.** This corrects
the old separate-CASH-account plan. Both strategies use **the existing pinned
Webull OpenAPI SANDBOX CASH account at index 0**, never Webull LIVE or Alpaca.

## Allocation and independent decisions

| Sleeve | Share of total account equity | Maximum invested at cost / target | Decision maker | Order ID prefix | Review and execution log |
| --- | ---: | ---: | --- | --- | --- |
| OG Trader ORB | 50% economic allocation | 49.5% of total account equity | Its own verified 5-minute breakout scan and deterministic risk checks; AI veto does **not** suppress scanning | `tr...` entry, `tc...` close | `trader-morning-<run-id>`, `shared-orb-close.log` |
| Seven-agent AI desk | 50% economic allocation | 49.5% of total account equity | Three agreeing analysts plus Risk Manager, Desk Lead, Trade Reviewer, strict prior-session structured hypothesis, quotes and account checks | `ag...` | `seven-agent-sandbox-<run-id>` |
| Shared minimum cash | — | **1% of total account equity uninvested** | Aggregate account-level invariant | — | Broker balances and positions read-only |

These are **maximum investment allocations**, not instructions to trade on
every session or deploy all 50% even when there are no qualifying signals.
The original stricter ORB stop-loss-distance, limit, cash buffer and minimum
order rules remain. No artificial consensus or signal generation is permitted.

The original **Beethoven 80/19 paper trading behavior is preserved when the
new flag is disabled**, but must **NOT coexist** on this same account after
the 50/50 cutover. In 50/50 mode the existing 15:48 ET workflow calls the
new ORB-only close executor instead of Beethoven. It preserves agent positions,
does not sell or size the seven-agent sleeve, and does not touch live accounts.

## Shared execution routing and guards

- **Webull SANDBOX host only**, `api.sandbox.webull.com`, existing SDK 3.0.3.
- **Exactly account index 0**, CASH, same runtime SHA-256 fingerprint
  as `WEBULL_PAPER_ACCOUNT_SHA256`; never index 1 or an alternate account.
- Same GitHub Actions `webull-paper-order` concurrency group for ORB entry,
  agent desk execution and ORB close. Distinct same-day claim directories and
  strategy order IDs; no automatic retry of uncertain receipts.
- Agent trading allowed only on `SPY/QQQ`; ORB owns only its existing approved
  liquid candidate universe. Tickers must remain disjoint. No shorts, leverage
  by account borrowing, new trading permissions or real-money paths.
- Reject unknown/legacy `bt` holdings, cross-strategy sells, filled-order
  history that cannot establish the relevant strategy's position provenance,
  open orders, truncated order history, broker mismatch, stale prices, or
  increased exposure. **No automatic forced liquidation of existing GDXU or
  other Beethoven positions** as part of this PR.
- Separate order artifact logs and outcome classifications per sleeve. A
  GitHub run or `PAPER_FILLED` log cannot by itself establish a complete
  independently broker-audited fill or P&L. Realized strategy P&L remains
  **UNVERIFIED** until read-only fill/fee/cost-basis reconciliation.
- ORB evaluation may legitimately return zero approved scanner opportunities
  on an active day. Seven-agent decision may legitimately veto with
  `NO_STRUCTURED_CONSENSUS`. They are independent decisions.

## Enabling the reviewed cutover safely

1. Review the PR, inspect all source and passing CI on its exact HEAD.
   **Do not enable the mode just because CI is green**.
2. Using authenticated read-only **Webull SANDBOX** checks, verify index 0
   CASH pin, current open orders, all position quantities, broker fills,
   cash availability and any existing incomplete Beethoven rebalance.
3. Establish a **verified flat starting account / broker-reconciled
   non-legacy holdings** before activation. If it still holds GDXU, GDXD,
   SOXS, or unknown positions, shared mode fails closed. Do not force
   liquidation simply to demonstrate activity.
4. Review the existing 50/50 plan, independence of the ORB scanner and
   agent risk committee, 1% cash buffer and ORB-only EOD flattening behavior.
5. After merge and safe account cutover, explicitly set GitHub Actions
   repository variable `WEBULL_SHARED_5050_ENABLED=true`. Keep existing
   `WEBULL_PAPER_ACCOUNT_SHA256` pin and PAPER-only API credentials.
   Seven-agent execution also requires the existing independent
   `AI_AGENTS_SANDBOX_EXECUTE_ENABLED=true`. Do not enable any live trading.
6. Check first scheduled ORB entry at 10:25 ET, independent agent review and
   potential entry at 11:22 ET, ORB-only close at 15:48 ET. Review
   `PAPER_TRADER_PLAN`, `AI_AGENT_SANDBOX`, `SHARED_ORB_CLOSE_PLAN`,
   order preview, read-only broker order detail/fills and subsequent positions
   **separately**. Do not infer a trade from agent avatar movement.
7. If required market data, provenance, reconciled legacy positions,
   broker-access permissions, or historic orders are missing, record
   **BLOCKED** and leave order authorization disabled until resolved.

## Current blockers

- Prior Oct 23 paper runner reported **63 GDXU** in index-0 account. That is a
  legacy Beethoven symbol excluded from both new strategies. Its **current
  authoritative holdings and transition are not yet verified**.
- The dedicated sandbox broker API cannot be queried using the separate
  personal read-only Webull plugin. It must be validated through the actual
  Webull SANDBOX connection. No new sandbox orders were placed for testing.
- Independent realized P&L attribution requires authenticated order-fill,
  timestamps, prices, fees and broker balance/position records, not just
  public trading predictions or final equity estimates.
- Current default/merged main is **not yet the shared-account architecture**.
  This change must pass regression tests, be reviewed and merged to take effect.
