# Seven-Agent Webull SANDBOX Order Execution

## Purpose

This is the seven-agent desk's own optional paper-order path. The existing
autonomous chat is still a **discussion**, not an executable market-data feed.
No model free text is parsed as an order. The executor reads the latest
seven-role **structured research report** from
`research/ai_desk_status.json` and independently validates its date, provider,
all seven votes, and explicit risk approvals.

**It cannot trade real money**, cannot call production Webull hosts, and never
touches Beethoven/ORB's existing sandbox account at index 0. It does not edit
the 80/19/1 strategy, its schedules, or its orders.

## Paper trade specification

- Separate verified **CASH** Webull sandbox account index 1–4, not 0.
- Explicit exact SHA-256 account fingerprint matched to an owner-provided
  GitHub Actions secret.
- BUY or position-reducing SELL **SPY or QQQ only**. No options, leverage,
  inverse ETFs, margin, short sales, or pyramiding.
- Requires the previous day's seven-role Gemini paper research:
  at least three of four analysts agree at >=65% confidence, and Risk
  Manager, Desk Lead and Trade Reviewer **each explicitly agree** at >=65%.
  NO_TRADE/HOLD/missing/stale opinions block orders.
- Executes no more than **one order per New York trading day** on the
  dedicated agent account. A scheduled job starts at **11:22 AM ET** weekdays
  and validates that the exchange is open.
- At most **5% of dedicated account equity per new BUY**, with cash buffer.
  Existing positions prevent new BUYs. SELL requires an exact authorized
  holdings match; it cannot short.
- Official Webull **sandbox** quote with actual last-trade timestamp must be
  within the existing 20-minute timestamp freshness guard. Note this can
  still be a **delayed feed**, not guaranteed live-market-price execution.
- The Webull API **previews** the order, then submits once, checks final order
  detail status and reconciles broker share-count delta. A timeout or an
  uncertain receipt must **never trigger another submission**.
- Checks Webull open orders and the entire recent history before submission.
  Any other bot's client order ID on this dedicated account blocks execution.
  GitHub Actions cache also saves a same-day submission claim, including
  uncertain/failed receipts. Workflow uses existing `webull-paper-order`
  concurrency lock so it cannot race the other Webull paper workflows.
- A successful decision **does not guarantee any order**; current source
  reports HOLD / NO_CONSENSUS, and data, risk and account checks can veto.

## Enrollment (owner only)

**Execution is disabled by default.** To enable after reviewing the tests:

1. Deploy the revised existing owner-IAP-protected Cloud Run dashboard, then
   sign in and open:
   `https://webull-paper-viewer-955692373304.us-central1.run.app/office/agent-sandbox-accounts`
   This **GET-only** endpoint lists separate sandbox account indices, CASH
   type and SHA-256 fingerprints; no raw account IDs, broker orders or secret
   keys are returned. **Do not use index 0.**
2. At GitHub repository > Settings > Secrets and variables > Actions:
   - Create repository **secret** `AI_AGENTS_ACCOUNT_SHA256` with the exact
     SHA-256 fingerprint of a separate CASH sandbox account.
   - Create repository **variable** `AI_AGENTS_ACCOUNT_INDEX` with the
     corresponding integer 1–4.
   - Create repository **variable** `AI_AGENTS_SANDBOX_EXECUTE_ENABLED`
     with value `true` **only after verifying that account has no
     other bot's orders, no unrelated holdings and available test cash**.
   Webull PAPER API credentials already used by the other sandbox bots are
   reused, but orders route to this distinct account ID.
3. The new `Seven-Agent Webull Sandbox Trade` GitHub Actions scheduled
   workflow automatically executes only if enabled and fully approved.
   Manual `workflow_dispatch` is **non-executable**. An unsupported
   account, wrong PIN, stale research, lack of consensus or quotes, or
   account crossover causes no order.
4. Inspect GitHub Actions jobs and saved audit log artifact for
   `AI_AGENT_PAPER_VETO`, `APPROVED_PLAN_ONLY`,
   `PAPER_SUBMITTED`, `PAPER_FILLED`, or
   `BROKER_SANDBOX_FILL_RECONCILED`. Only the latter plus a broker
   detail/position match establishes successful sandbox execution.

## Emergency stop

Set GitHub Actions variable `AI_AGENTS_SANDBOX_EXECUTE_ENABLED=false`
to disable **future scheduled agent-order jobs**. This will not cancel a job
already in progress or reverse an existing sandbox fill; stop a running
GitHub Action separately if necessary.

## Limitations / why broker orders are not live

This is an implementation and offline-tested order path, **not evidence of a
real successful broker order**. A separate real SDK submission/preview and
subsequent order-detail reconciliation must still be verified when all gates
are satisfied. The default public status only shows research, not completed
broker fills. Webull SANDBOX is not the same as live execution quality.
The agent speech transcript is **never** a valid order authorization channel.

No credentials, sandbox account numbers, private position details, or
GitHub secrets are written into the public repository.
