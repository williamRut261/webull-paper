# STONKS operational execution audit — 2026-10-22 and 2026-10-23

Audit prepared 2026-10-23 (CDT). All times below **America/Chicago**, with UTC workflow start shown in linked GitHub Actions pages. Scope is the existing `webull-paper` repository and related repos independently identified through the owner's accessible repository list; no trading configuration or broker action was changed by this audit.

## Evidence standard

**A successful GitHub Actions job is not a trade confirmation.** "Workflow-reported broker fill" means the existing trading code logged a FILLED status while using an SDK-connected broker. It is **not** an independent second inquiry into broker-side historical order details. No Alpaca API, dedicated Webull SANDBOX account API, or authenticated Google Cloud Run administration session was accessible in this audit. The connected Webull read-only integration exposes personal production accounts, **not proof of either Webull SANDBOX account**. No account IDs, secrets, or personal balances are published here.

## Execution and outcome matrix

| System | Workflow started? | Signal / evaluation | Broker routed / queried? | Orders submitted? | Broker-fill evidence | Operational classification |
| --- | --- | --- | --- | --- | --- | --- |
| Alpaca LIVE | YES Oct 22,23 | Both days produced GDXU allocation | SDK live execution path and order responses in logs; independent query unavailable | Oct 22 log reports sell GDXD, buy GDXU; Oct 23 no order | Oct 22 log reports both FILLED; independent order-history and portfolio reconciliation UNVERIFIED | Oct 22 OPERATIONAL BUT BROKER RECHECK PENDING; Oct 23 OPERATIONAL BUT NO TRADE |
| Alpaca PAPER (retired replicas) | NO scheduled runs | NOT RUN | NOT RUN | NO | NO | NOT YET VERIFIED AS OPERATING; scheduling retired by design |
| Webull Beethoven SANDBOX | YES Oct 22,23 | GDXU target on both days | Sandbox SDK account/order/position calls made according to existing runner | Oct 22 sale reported, subsequent fractional order rejected; Oct 23 two submitted | Oct 23 both FILLED and quantities reconciled **in run log**, external SANDBOX inquiry UNVERIFIED | Oct 22 FAILED / PARTIAL REBALANCE; Oct 23 OPERATIONAL, BROKER RECHECK PENDING |
| Webull ORB | YES Oct 22,23 | Market scanner **NOT RUN** after veto | NOT RUN, exited before Webull SDK initialization | NO | NO | OPERATIONAL BUT NO TRADE — AI gate denied both mornings |
| Seven-Agent AI Desk | YES Oct 22,23 | Seven specialist research decisions; Oct 23 NO_CONSENSUS | NOT CONNECTED BY DESIGN | NO (research only) | NO | OPERATIONAL BUT NO TRADE |
| Seven-Agent Webull SANDBOX | YES Oct 23 | Read previous structured report; NO_STRUCTURED_CONSENSUS | **NOT RUN**, veto occurs before client/account initialization | NO | NO | OPERATIONAL BUT NO TRADE, dedicated account unverified |
| AgentOffice Gemini conversations | Hourly schedule active; successful model responses observed | Dialogue only, not executable trading signals | NO BROKER CONNECTION BY DESIGN | NO | NO | OPERATIONAL RESEARCH; deployment display UNVERIFIED |
| Cloud Run dashboard | Source present, reported prior deployment | NOT A STRATEGY | Authenticated deployment checks unavailable | NO | NO | NOT YET VERIFIED CURRENTLY DEPLOYED |

## Ten-stage evidence-chain classification

Stages: (1) code, (2) scheduled and started, (3) required credentials/account routing, (4) usable current market data, (5) signal or justified skip, (6) risk decision, (7) authorization/submission, (8) independent broker acknowledgment/rejection, (9) independent broker order final status, (10) independent balance/position reconciliation. `VERIFIED` signifies direct GitHub code/log evidence where appropriate; for stages 8–10 it **requires broker-side corroboration not available from this session**.

| Component/session | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Alpaca LIVE Oct 22 | VERIFIED | VERIFIED | VERIFIED via SDK execution log | VERIFIED with delayed-data limitation | VERIFIED | VERIFIED | VERIFIED workflow-reported submission | UNVERIFIED independently | UNVERIFIED independently | UNVERIFIED |
| Alpaca LIVE Oct 23 | VERIFIED | VERIFIED | VERIFIED via SDK execution log | VERIFIED with missing-data limitation | VERIFIED | VERIFIED | SKIPPED BY DESIGN | NOT RUN | NOT RUN | UNVERIFIED |
| Alpaca PAPER | VERIFIED | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| Webull Beethoven Oct 22 | VERIFIED | VERIFIED | VERIFIED via SDK responses | VERIFIED with entitlement caveat | VERIFIED | VERIFIED | FAILED on subsequent fractional order | VERIFIED rejection logged from Webull API | UNVERIFIED full broker history | UNVERIFIED post-failure portfolio |
| Webull Beethoven Oct 23 | VERIFIED | VERIFIED | VERIFIED via SDK execution log | VERIFIED with entitlement caveat | VERIFIED | VERIFIED | VERIFIED workflow-reported submissions | UNVERIFIED independently | UNVERIFIED independently | UNVERIFIED independently |
| Webull ORB Oct 22,23 | VERIFIED | VERIFIED | NOT RUN due gate | NOT RUN | NOT RUN | VERIFIED veto | SKIPPED BY DESIGN | NOT RUN | NOT RUN | NOT RUN |
| Seven-Agent AI Desk Oct 23 | VERIFIED | VERIFIED | NOT RUN BY DESIGN | VERIFIED unofficial daily source | VERIFIED seven opinions | VERIFIED NO_CONSENSUS | SKIPPED BY DESIGN | NOT RUN | NOT RUN | NOT RUN |
| Seven-Agent SANDBOX Oct 23 | VERIFIED | VERIFIED | NOT RUN due veto | NOT RUN | VERIFIED existing report read | VERIFIED veto | SKIPPED BY DESIGN | NOT RUN | NOT RUN | NOT RUN |
| AgentOffice dialogue | VERIFIED | VERIFIED | VERIFIED model calls, NOT RUN broker | NOT RUN (no execution market feed) | NOT RUN (conversation only) | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| Cloud Run dashboard | VERIFIED source | UNVERIFIED deployed traffic | UNVERIFIED | UNVERIFIED | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |

## Exact session findings

### Alpaca LIVE: `williamRut261/beethoven-replica-review`

- October 22 **11:47:32 CDT**: early-close trigger [39816896575](https://github.com/williamRut261/beethoven-replica-review/actions/runs/39816896575), `Outside session pre-close staging window; no orders`. Expected skip.
- October 22 **2:51:11 CDT**: normal trigger [39843601961](https://github.com/williamRut261/beethoven-replica-review/actions/runs/39843601961); fresh IEX 57/69, delayed SIP fallback 12, zero missing; both evaluations `GDXU=1.0`. **2:51:12 CDT:** code logged `FILLED GDXD: qty=36.158078602; price=26.75`. **2:51:15 CDT:** code logged `FILLED GDXU: qty=12.206902435; price=79.1199`. Broker records and realized P&L not independently retrieved; do not treat log-reported fills as independently broker-confirmed.
- October 23 **11:48:45 CDT**: early-close trigger [39989826601](https://github.com/williamRut261/beethoven-replica-review/actions/runs/39989826601), expected staging-window skip.
- October 23 **2:48:15 CDT**: normal trigger [40014165525](https://github.com/williamRut261/beethoven-replica-review/actions/runs/40014165525); fresh IEX 49/69, delayed SIP fallback 17, symbols AMZZ/URAA/WEBS unavailable, but required strategy evaluation completed with both allocations `GDXU=1.0`. At **2:48:16 CDT**, logged `SKIP SELL` and `SKIP BUY` because the drift was only ~$0.5644 (below minimum).
- Alpaca market data is **not two real-time feeds**: IEX is current and SIP is ~16 minutes behind. Missing non-required symbols did not interrupt Oct 23's completed decision; risk of stale signals remains.
- The separate `alpaca-flow-state` repo has a permanently disabled retired paper job, and `alpaca-beethoven-original-paper` limits the old Alpaca PAPER job to manual dispatch. Neither showed Oct 22–23 scheduled runs. They must not be confused with LIVE.

### Webull Beethoven SANDBOX: `williamRut261/webull-paper`

- October 22 [39839705158](https://github.com/williamRut261/webull-paper/actions/runs/39839705158): 2:48 PM CDT GDXU signal. `PAPER_FILLED` and `PAPER_POSITION_RECONCILED` for **SELL 185 GDXD** in the existing SDK log. Subsequent fractional order returned Webull **HTTP 417 `OPENAPI_FRACT_QTY_SCALE_LESS_5`**, leaving an interrupted rebalance. Not a complete-session success.
- [PR #31](https://github.com/williamRut261/webull-paper/pull/31) corrected `webull_paper/paper_orders.py` from six-decimal to **five-decimal** quantity flooring; added BUY/SELL, whole-share and under-minimum regression. Merge and prior CI passed. This fixes a demonstrated precision mismatch, but it cannot itself reconcile an Oct 22 incomplete portfolio.
- October 23 [40011085776](https://github.com/williamRut261/webull-paper/actions/runs/40011085776): **2:48:16 CDT SELL 1 SOXS** submitted; logged FILLED **2:48:19**, position 1→0. **2:48:19 CDT BUY 63 GDXU** submitted; logged FILLED **2:48:23**, position 0→63. Final log: `PAPER_REBALANCE_COMPLETE order_count=2`, cash **$1,317.68**, equity **$6,018.74**, `positions=[GDXU]`. These are last values **reported by the workflow after sandbox API calls**, not an independent account query or audited P&L.
- The two quote snapshots came from the same source (`independent_feed=false`); `realtime_entitlement_verified=false` appeared in both sessions. Source consistency and short quote age do not prove independently entitled consolidated real-time data.

### Webull ORB SANDBOX

- October 22 [39788912260](https://github.com/williamRut261/webull-paper/actions/runs/39788912260) and October 23 [39962537868](https://github.com/williamRut261/webull-paper/actions/runs/39962537868) started and waited until **9:25 AM CDT / 10:25 AM ET**.
- Both logged `PAPER_AI_DESK_GATE reason=NO_AGENT_APPROVAL approved=false direct_agent_orders=0 additional_allocation=0` and returned successfully. Source `trader_combo/morning.py` returns **before** `run_scan(now)` and broker initialization on this condition. Thus **no independent ORB market scan, entry signal, Webull login, or ORB order was performed** either day. Do not characterize this as zero qualifying breakouts; none were checked. This preserves the configured AI approval requirement but is a functional limitation for any expectation that ORB scans unconditionally.

### Seven-agent research and dedicated Webull SANDBOX

- October 22 [39875073774](https://github.com/williamRut261/webull-paper/actions/runs/39875073774), October 23 [40042415829](https://github.com/williamRut261/webull-paper/actions/runs/40042415829): research-only seven-role execution. Oct 23 each role had a `AI_DESK_ROLE_RESULT ... VERIFIED` log; no orders (`AI_DESK_RESEARCH_ONLY ... ORDERS=0`). Current sanitized `research/ai_desk_status.json`: `consensus=NO_CONSENSUS`, all seven opinions non-trading; virtual ledger stays $10,000, 0 trades. **No broker P&L exists from this ledger**.
- October 23 **10:54 AM CDT** [39982264838](https://github.com/williamRut261/webull-paper/actions/runs/39982264838): opt-in was true, dedicated account index configured as 1, but `AI_AGENT_PAPER_VETO NO_STRUCTURED_CONSENSUS orders=0`. The executor's `approved_ticket` checks status before creating the Webull client, verifying credentials/account or querying balances. Thus distinct CASH account pin, authentication and eligibility remain **UNVERIFIED in this run**, notwithstanding populated environment placeholders.
- Current research status contains no structured hypothesis. The veto is correct, **not proof of a model-to-consensus transport failure**. The research engine requires three agreeing analysts plus risk manager/desk lead and other constraints; do not fabricate votes or loosen gates to force a trade.

### Gemini AgentOffice and Cloud Run

- October 23 **12:32 AM CDT** [39906338272](https://github.com/williamRut261/webull-paper/actions/runs/39906338272): Technical Analyst succeeded, News Researcher failed `ValueError`, but original workflow conclusion was green. [PR #33](https://github.com/williamRut261/webull-paper/pull/33) corrected contradictory response-length constraints, fail-closed workflow exit and `NOT RUN` versus `FAILED` status handling; passed offline tests on merged main.
- At **1:40 AM CDT**, [39912975102](https://github.com/williamRut261/webull-paper/actions/runs/39912975102) logged two successful roles (Strategy Analyst and Risk Manager). The late Oct 23 **8:42 PM CDT** [40050980292](https://github.com/williamRut261/webull-paper/actions/runs/40050980292) logged successful Trade Reviewer/Market Analyst responses, bounded two calls and publication. These logs are stronger evidence than UI animation, but do not prove every hourly attempt succeeded.
- Each hourly dialogue attempts two roles (up to 48 calls per UTC day); five uncalled roles should show `NOT RUN`, not `FAILED`. Avatar movement in `dashboard/static/office-world.js` is explicitly decorative, not a live execution indicator.
- User-confirmed Cloud Run revision `webull-paper-viewer-00017-9nq` and declared SHA `4c80fb82f9c526a3c31a5e82954e312b708bacef` were **not independently checked**. Authenticated `/office/status`, `/office/release`, Cloud Build provenance, IAM/IAP settings and revision traffic could not be fetched. Later main HEAD had `5f7fe188ffe22f06bcb2798d1d7921d8b43b97fd` consisting of research conversation publications. A later GitHub HEAD does not automatically require a dashboard image redeployment, nor does it prove one.

## Corrections, tests and blockers

1. **Previously corrected:** Webull five-decimal precision — PR #31 and its regression. Subsequent Oct 23 run log indicates successful whole-share rebalance. The Oct 22 interrupted rebalance's complete broker-side aftermath remains unverified.
2. **Previously corrected:** Gemini model validation/CI false green and per-role NOT RUN labels — PR #33. The post-merge main [39910975301](https://github.com/williamRut261/webull-paper/actions/runs/39910975301) completed Python unit tests, Node JS smoke, Chromium synthetic-page E2E, research-only smoke and Docker build. No browser session against authenticated Cloud Run was performed.
3. **Not a confirmed bug:** Seven-agent `NO_STRUCTURED_CONSENSUS` and ORB `NO_AGENT_APPROVAL` are fail-closed gates. The latter prevents ORB scanning, which may be a product/strategy choice for separate owner review; no trading logic changed.
4. **Blocker — Alpaca:** obtain authenticated **read-only LIVE** historical orders/fills, accounts/positions, cash, and before/after trade records for Oct 22–23. Match quantities, broker order IDs/status, fees and time. No new live orders authorized.
5. **Blocker — Webull:** authenticated **SANDBOX** read-only accounts 0 and 1, history/open orders, filled quantities and current holdings. Confirm Oct 22 partial rebalance and Oct 23 completion against authoritative broker records. The available Webull personal-account connector is not the dedicated sandbox.
6. **Blocker — Cloud Run:** owner-authenticated `gcloud run services describe`, revisions/traffic, Cloud Build source and IAP policy plus signed-in `/office/status` and `/office/release`. Existing dashboard docs also note an earlier OAuth client secret exposure and unverified rotation; validate rotation privately, do not republish secret.
7. **P&L:** No independently broker-verified P&L or final independent daily balances were obtained; no financial return figure is asserted.
8. **Audit modifications:** documentation only; no strategy, schedule, kill switch, allocation, order gateway, deployment, live/paper broker action, or credential changes. New PR's CI/review must be verified separately; prior green runs do not attest to the audit branch.

**Bottom line:** Research and two bot engines ran. Alpaca LIVE Oct 22 and Webull Beethoven Oct 23 **reported** fills from their SDK sessions; those are **not independently reconciled against fresh broker read-only order history in this audit**. ORB and seven-agent SANDBOX stopped by design before order access. Cloud Run runtime provenance remains inaccessible. Nothing here justifies claiming end-to-end operational certification.
