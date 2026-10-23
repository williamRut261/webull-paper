# STONKS Skill Progress — evidence log

Branch: `feature/stonks-skill-verification-telemetry-20261023`
Base: the existing `main` repository. No portfolio or execution workflow
modifications are intended in this branch.
Date: 2026-10-23 UTC (October 22 in Houston when initiated).

## Recovered Work-session context and limitations

- The previous ChatGPT Work transcript reported investigating premature
  per-agent success and loss of prior successful roles on a later model
  failure; the session ended due to a usage cap without a PR.
- GitHub branch/PR searches showed **no pushed skills-integration branch**
  or completed PR to recover from that interrupted session. Unpushed
  Work-container files are **not accessible** here. This branch
  reproduces and resolves the same narrowly identified issues without
  replacing or overwriting the original repo.
- The previous transcript claimed that an upstream verification skill had
  been installed locally. That local installation **was not independently
  inspectable**. Instead, this branch vendors and attributes its verified
  text-only upstream skill in `.agents/skills/`.

## Verified chronological work

| Stage | Evidence | Result and limitation |
| --- | --- | --- |
| Inspect repository and safeguards | Current GitHub `main` tree and `research/ai_desk.py`, `dashboard/app.py`, `tests/`, workflows | Research-only model code, separate SANDBOX execution engine, role checks, existing JS smoke confirmed in source; production deployment not checked |
| Review third-party skill sources | skills.sh plus upstream `SKILL.md` blobs documented in `docs/STONKS_SKILL_INTEGRATION.md` | Nine exact candidates inspected; no broad external installer run |
| First red regression | [39903265173](https://github.com/williamRut261/webull-paper/actions/runs/39903265173) | **FAIL expected**: 226 tests; new tests exposed false-success, invalid lists and missing partial progress. Changes: `tests/test_ai_desk_role_evidence.py`. Commit `531347a622ddae48e9f491ea3eeb25d4dd3d5a3d` |
| Validate specialist before success | [39903383231](https://github.com/williamRut261/webull-paper/actions/runs/39903383231) | **PASS**; added shared validation, bounded per-role monotonic timings and sanitized error progress; change `research/ai_desk.py`; commit `9fed3976b0505694a35c7d0a8f597ef050c2a3b3` |
| Reject spoofed check origins | [39903476130](https://github.com/williamRut261/webull-paper/actions/runs/39903476130) | **FAIL expected**: stricter creator validation initially invalidated the old mock's missing app; updated tests in the next commit; change `dashboard/app.py` commit `9eb73410850d4af84bce46dc0672e31f47fb7a14` |
| Add creator-aware tests | [39903500455](https://github.com/williamRut261/webull-paper/actions/runs/39903500455) | **PASS**: matched real GitHub Actions `app.slug`, protected same-run metadata; added spoofing regression. Commit `9b414897c968be43c24656ccccc291c58d3ea1c8` |
| Vendor pinned safe skill | [39903582198](https://github.com/williamRut261/webull-paper/actions/runs/39903582198) | **PASS**: 227 Python tests, JS syntax + AgentOffice smoke, research-only smoke and Docker build; upstream MIT skill & license copied in `.agents/skills/verification-before-completion/`; commits `29b9e4b5fa5579aed844b406d2b6d2b1fc18be79`, `9500fb1380ec17eb8b15d27b9eba5ee04291164e` |
| Integration notes | `docs/STONKS_SKILL_INTEGRATION.md` | Nine candidates, installation boundaries, implemented methods, actual verification gates, remaining work; commit `f351e90a5686730056d96d7028b6991805b7e576` |
| Verified failure artifact | [39904075231](https://github.com/williamRut261/webull-paper/actions/runs/39904075231) | **PASS**: CLI MODEL_ERROR artifact retains first verified role and failed second role, with no error message or secret; commit `78ca0a3efb0159ec778b0c55465c9cb78b98bb0e` |
| Human-readable telemetry | [39904097177](https://github.com/williamRut261/webull-paper/actions/runs/39904097177) | **PASS**: role/status/duration evidence table in research report; commit `8e66c9799ffe0c8d4f0f226732e0d8028e9e8112` |
| Seven autonomous conversation roles | [39900971506](https://github.com/williamRut261/webull-paper/actions/runs/39900971506) and persisted `research/office_conversation.json` on `main` | **VERIFIED** 7 distinct roles have published research conversation turns, including Trade Reviewer. This is a separate conversation workflow: NOT proof of seven sequential trading-desk calls or Webull trades |
| Review PR | [PR #30](https://github.com/williamRut261/webull-paper/pull/30) | **OPEN, NOT MERGED**; research/telemetry and documentation review only |
| Progress log | This file | Tracks evidence from actual GitHub CI rather than assuming functionality; future merge/Cloud Run/broker checks remain unverified |

## Explicit no-trade scope

- **No new order execution flags enabled.**
- **No paper/live brokerage order invoked by this work.**
- No changes to Beethoven, ORB, their account pinning, position sizes,
  live trading, schedules or workflows that execute trades.
- `AI Office / ...` GitHub Checks are **research telemetry**, not
  broker acknowledgments. `roles_completed` means fully validated
  model outputs, not profitable trades.
- No brokerage fills inferred from unit tests or green CI.
- This PR does not deploy Cloud Run; deployed dashboard may still use
  older code until an owner-approved release.

## Remaining blockers and next actions

1. **Actual model-run validation:** Check a subsequently scheduled
   `AI Trading Desk` or `Autonomous Seven-Agent Office` workflow
   for role completion/latency and check metadata. New code not in
   `main` until PR review and merge.
2. **Actual application deployment:** Verify the desired commit in
   Google Cloud Run and authenticated dashboard rendering.
3. **Real broker milestones:** Inspect read-only Webull SANDBOX account
   and order details. No separate agent-run fills were proved in
   this task; do not enable flags or trade just to manufacture proof.
4. **A known unrelated Beethoven issue:** The October 22 paper run
   [39839705158](https://github.com/williamRut261/webull-paper/actions/runs/39839705158)
   logged a GDXD sell/reconciled and later HTTP 417 on fractional
   quantity precision; fix separately, verify exact account holdings.
5. **Further skill installations:** Defer unneeded third-party code
   and Playwright/browser dependencies until an authenticated isolated
   test environment and dependency/script review are available.
6. **Backtesting:** Point-in-time datasets, independent fees/spread
   estimates and adequate out-of-sample samples required before
   attributing any gains to seven-agent improvements.

## Completion and evidence summary

The branch now contains a code-level telemetry fix, security
regressions, a pinned MIT skill, progress and integration documents, and
[PR #30](https://github.com/williamRut261/webull-paper/pull/30) for review.
[39904097177](https://github.com/williamRut261/webull-paper/actions/runs/39904097177)
passed after the functional changes. Any later documentation-only commit
still requires fresh CI before claiming that exact head passed.
Newly copied guidance is **not** a Cloud Run deployment, profitable
strategy, independently verified broker fill, or authorization to trade.


## Continuation after earlier review (2026-10-23 UTC)

- **PR #30 merged**: `9c44108e4970f2b7b304d11a2ff619d265a4edfa`.
  Verified [GitHub run 39904270113](https://github.com/williamRut261/webull-paper/actions/runs/39904270113):
  228 Python tests, JS smoke, research smoke and Docker build.
- **PR #31 merged**: `95e849ae56fd6d7f14f5914fda1f68580eea6fde`.
  Verified [GitHub run 39905116899](https://github.com/williamRut261/webull-paper/actions/runs/39905116899):
  229 Python tests, JS smoke and Docker. Original sandbox order
  six-decimal defect fixed without changing trades or risk limits.
  No Webull order was submitted as part of this fix.
- **Fixed-rule simulation and browser E2E**: separate branch
  `feature/stonks-readonly-performance-audit-20261023`.
  Existing strategy close-to-close analysis now supports a labeled
  >=30-observation historical holdout and conservative drawdown and
  daily-risk statistics, when verified adjusted closes are supplied.
  No historical market dataset was provided, so no returns claimed.
- **Chromium E2E red-green debugging**: [39905991264](https://github.com/williamRut261/webull-paper/actions/runs/39905991264)
  found that a 15s test incorrectly expected a status refreshed by the
  real app only after 30s; [39906220954](https://github.com/williamRut261/webull-paper/actions/runs/39906220954)
  then exposed invalid `clock.fastForward("31s")` syntax and a
  test-only assumption about run IDs in a sanitized response. The
  assertions were corrected on the same branch; **do not mark E2E
  completed until its newest GitHub CI run passes**.
- **Private deployment identifier**: the new IAP-only
  `/office/release` endpoint returns sanitized, explicitly
  `source_sha_verified=false` source metadata. It does not prove
  Cloud Run provenance without a separate GCP revision check.
- **Cloud Run remains not deployed by this assistant**:
  no GCP execution connector or authenticated Cloud Shell session
  available. Use `docs/STONKS_CLOUD_RUN_DEPLOYMENT.md` to deploy
  reviewed main with strict IAP and independently verify the
  declared SHA and Cloud Run ready revision.
- The separate Webull seven-agent SANDBOX account's actual
  credentials, API login, order preview and broker fills remain
  unverified; no orders were initiated in this task.


## 2026-10-23 UTC — Continued live-office reliability investigation

Observed user-provided authenticated Cloud Run JSON:
- Cloud Run revision `webull-paper-viewer-00016-4qk` serving 100% of traffic,
  declared commit `a1a48108be957845d666d516629a2068b66a21e9`.
- `/office/status` indicated hourly GitHub workflow
  [39906338272](https://github.com/williamRut261/webull-paper/actions/runs/39906338272),
  research `NO_CONSENSUS`, 23 published conversation turns,
  Technical Analyst DONE, News Researcher FAILED, five UNAVAILABLE,
  `verified_count=2`.
- Direct GitHub job log and Check evidence confirmed:
  `OFFICE_DIALOGUE_ROLE_OK role=Technical Analyst turn=23`;
  `OFFICE_DIALOGUE_ROLE_FAILED role=News Researcher class=ValueError`.
  The exact provider text was not retained; **the underlying source of
  that specific ValueError is unknown**, not independently diagnosable.
  The workflow returned overall success despite the specialist failure.
- The existing office prompt permitted 25–65 words, but
  `validate_response` rejected otherwise valid rationale above
  **300 characters**, which is a reproducible local contradiction.
- Hourly GitHub Actions **attempts only two specialist replies per run**,
  so the other five UNAVAILABLE labels were misleading to viewers:
  their absence of Checks was expected, not a five-agent outage.

Remediation on branch
`fix/stonks-conversation-reliability-20261023`:
1. Shorter 20–40 word and 280-character model instruction. A well-formed
   rationale up to the provider's 1600-character parsing limit is
   sanitized and clipped to 300 characters at a word boundary; missing,
   non-HOLD or wrong-symbol outputs **still fail closed**.
2. Per-run result becomes `ATTEMPTED`, `ATTEMPTED_PARTIAL` or
   `ATTEMPTED_FAILED`. The main workflow now exits nonzero when any
   attempted role fails, while `if: always()` still persists sanitized
   previous successes and the daily no-retry marker. The daily 48-call
   ceiling and maximum two calls/hour are **unchanged**.
3. Sanitized `MODEL_BACKEND`, `RESPONSE_VALIDATION`, or
   `RECORDING` categories identify failure stages without printing
   prompts, provider exception text, account data or credentials.
4. AgentOffice now explicitly displays **NOT RUN** for specialists
   omitted from a successfully verified two-call hourly conversation.
   A failed GitHub Check remains FAILED; unavailable GitHub metadata
   still produces UNAVAILABLE, never invented successes.
5. Add offline regressions for long valid responses, malformed
   nontrading checks, partial and total failures, budget/idempotence,
   dashboard API and HTML semantics, source outages and sensitive
   error-message non-disclosure.

**No live brokerage or SANDBOX order was submitted; no trading flags,
account pins, allocations, risk gates, schedules or model-call caps
changed.** Running new code in the already deployed Cloud Run service
requires an explicit authenticated redeployment of reviewed main.

Verification evidence should be appended as a separate GitHub PR
comment after the latest branch and merged-main CI complete.
