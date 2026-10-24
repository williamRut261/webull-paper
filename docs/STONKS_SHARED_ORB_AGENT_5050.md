# Webull PAPER: shared-account ORB + seven-agent desk (50/50)

**Status: MERGED to main behind explicit opt-in; NOT ACTIVATED. NO new shared-strategy broker orders placed.** This corrects
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

## 2026-10-23 CDT — Authenticated sandbox cutover probe

- Read-only [GitHub Actions run 40060465466](https://github.com/williamRut261/webull-paper/actions/runs/40060465466) authenticated successfully using the actual Webull SANDBOX credentials, verified index-0 CASH and the account SHA-256 pin.
- The broker returned **63 shares of GDXU** (legacy Beethoven, outside the new two strategy sleeves), **equity $6,002.99**, **cash $1,317.68**, zero open orders, and 12 history entries. The probe placed zero orders and correctly exited nonzero (non-flat cutover BLOCKED).
- PR #35 has been merged as commit `bfcfd9faa8c1629a19031354127c8d6f1ceb5e79` after passing [the corrected-head offline CI](https://github.com/williamRut261/webull-paper/actions/runs/40060330545); shared 50/50 opt-in has NOT been enabled or independently verified. Never treat the code merge as paper activation.
- Before activating, reconcile and close the legacy GDXU PAPER holding via a separately authorized market-hours operation, repeat the authenticated read-only probe to confirm a flat/compatible account and zero open orders, then configure `WEBULL_SHARED_5050_ENABLED=true` and `AI_AGENTS_SANDBOX_EXECUTE_ENABLED=true` in repository Actions variables. No LIVE credentials/orders are part of the cutover.

## Monday 2026-10-26 (Eastern) — owner-authorized, fail-closed automatic cutover

**Implementation pending exact-head CI and merge.** The owner asked to fix the blocked
activation and to allow actual Webull SANDBOX PAPER trading on Monday. The
scheduled ORB runner (09:05 ET staging, first order at 10:25 ET) now reserves
the common broker-order concurrency lock and performs the one-time
`python -m webull_paper.monday_cutover` at 09:35-10:05 ET. On the pinned
index-0 CASH SANDBOX account only, require the broker's filled
`bt20261023B02GDXU` record and **exactly 63 GDXU shares with no other
positions or open orders**. A verified fresh quote permits a single 63-share
MARKET SELL with client ID `mc20261026S01GDXU`. Broker order detail,
then zero remaining GDXU holdings, must reconcile. An immutable daily claim and
broker-order-history duplicate check forbid repeat submission after uncertain
responses. Any other account, quantity, symbol, or order history aborts.

On a verified flat cutover, independently run the original ORB scanner
at 10:25 ET (09:25 Houston). The independent seven-agent executor at
11:22 ET (10:22 Houston) checks prior-session genuine structured consensus
and separately approves any SPY/QQQ entry or exit. Existing AgentOffice
conversations enter the desk only as **untrusted research context**; they
cannot issue or duplicate brokerage orders. At 15:48 ET (14:48 Houston),
the close workflow closes ORB positions only and preserves agents.

The repository's scheduled workflows have an explicit owner-activated
50/50 default, with repository variables `WEBULL_SHARED_5050_ENABLED=false`
or `AI_AGENTS_SANDBOX_EXECUTE_ENABLED=false` available to stop a sleeve.
`AI_PAPER_BROKER_KILL_SWITCH=true` blocks both strategies and the cutover.
The older Beethoven rebalance is retired by a permanent false workflow guard.
**No guaranteed Monday BUY:** a verified paper transition SELL can occur;
ORB and agents place additional orders *only* on fresh approved signals. A
skipped trade or veto does not establish failed implementation.
No LIVE or Alpaca account is accessed by the new workflow.
