# STONKS — Vercel Skills Integration and Evidence Policy

Last reviewed: 2026-10-23 UTC. This is an extension of the **existing**
`williamRut261/webull-paper` repository, not a new trading system.

## Installation boundaries and supply-chain decisions

The reviewed upstream Vercel Skills directory is https://skills.sh/.
Third-party markdown is **development guidance**, not a brokerage policy or a
trusted source of executable order instructions. GitHub Actions does not
auto-install community skills or execute `npx skills add`. No new runtime
dependencies, external services, credentials, permissions or postinstall
scripts were added. **Only one reviewed text-only skill was copied into a
supported local-agent directory.** Previous Work-session installation
claims cannot be verified in this workspace and are not counted below.

| Candidate / upstream path | Disposition | Integration rationale |
| --- | --- | --- |
| `obra/superpowers:skills/verification-before-completion/SKILL.md` | **Vendored** at `.agents/skills/verification-before-completion/SKILL.md` | Require fresh passing test/job evidence before describing success |
| `addyosmani/agent-skills:skills/observability-and-instrumentation/SKILL.md` | **Reviewed, applied as a method; not installed** | Bounded per-agent timings, sanitized outcomes, original failures |
| `addyosmani/agent-skills:skills/test-driven-development/SKILL.md` | **Reviewed, applied as a method; not installed** | Red-green regression for false agent success and partial failures |
| `addyosmani/agent-skills:skills/security-and-hardening/SKILL.md` | **Reviewed, applied as a method; not installed** | No secrets in logs; validate GitHub Checks creator and run ID |
| `wshobson/agents:plugins/quantitative-trading/skills/backtesting-frameworks/SKILL.md` | **Reviewed, applied in limited read-only form; not installed** | Fixed-rule holdout replay of original/compliant with user-supplied dates and explicit fill/cost assumptions; no intraday strategy results |
| `addyosmani/agent-skills:skills/ci-cd-and-automation/SKILL.md` | **Reviewed, applied as a method; not installed** | Existing PR CI runs full unit suite, JS smoke, research smoke, Docker build |
| `microsoft/playwright-cli:skills/playwright-cli/SKILL.md` | **Reviewed, applied as testing method; not installed** | Pinned `@playwright/test@1.56.1` runs real Chromium on local synthetic test fixture; no external browser control or credentials |
| `guanyang/open-agent-hub:skills/multi-agent-patterns/SKILL.md` | **Reviewed, deferred** | Existing seven roles and sequential handoffs work; redesign adds risk without demonstrated bottleneck |
| `wshobson/agents:plugins/quantitative-trading/skills/risk-metrics-calculation/SKILL.md` | **Reviewed, applied to clearly simulated results; not installed** | Hypothetical max drawdown, daily volatility and >=30-observation Sharpe; broker statistics still unavailable |

The reviewed `verification-before-completion` skill was sourced from
[obra/superpowers](https://github.com/obra/superpowers), commit
`2ce8aa15d05bd57213e6f746f953aafb7ded7a8b`,
SKILL Git blob `7d45333cc4a49c57a80df6c1fe2fa777a207afbc`.
Its exact Markdown and upstream **MIT LICENSE** are stored together under
`.agents/skills/verification-before-completion/`. It contains
**no bundled executables, scripts, install hooks or secret permissions**.
These files are advisory instructions for compatible coding agents, not
proof that a particular deployed coding agent automatically loaded them.
Every other candidate was inspected by its upstream `SKILL.md` path;
we intentionally did not run an external skills installer blindly.

## Integrated safety and telemetry methods

### Seven-agent research

The seven agents retain their roles and ordering. Every provider JSON reply
is now checked for symbol, action, finite confidence within [0, 1],
rationale type/length and evidence/risks list shape **before**
`AI Office / ROLE` can be completed as successful on GitHub.
A response with NaN confidence or a malformed list is a **failed role**,
not a successful call.

Each role records a bounded monotonic elapsed time and one of:
`VERIFIED` or `FAILED`. A failure retains prior verified role names and
their durations, the failed role, attempted-role count and validated token
counts. The original exception class is preserved. Only allowlisted
role/status/duration/error class are emitted to logs and failure artifacts:
**no provider response bodies, prompts, API keys, prices, account IDs,
broker identities or raw exception messages**.

Normal research JSON gains `role_execution`, `roles_attempted`,
`roles_completed`. Failed `MODEL_ERROR` reports include partial progress
when available. This does not change `safe_report` consensus criteria,
risk gates or executable order permissions. The provider comparison path
also retains per-provider partial progress and still produces **no trades**.

### AgentOffice

For a **specific** GitHub workflow run, the dashboard now requires the
reported Check to have both a matching `external_id` and a GitHub Actions
`app.slug`. Untrusted third-party or creatorless Check names are ignored,
even if they contain a plausible role and run number. `WORKING` remains
valid only for genuinely active non-expired runs, subject to the existing
multi-minute polling cache. Visual avatar movement is **decorative**.

The dashboard's actual version in **Cloud Run is not verified** by Python
tests or a GitHub merge. No Cloud Run deployment was performed in this PR.

### Trading and execution evidence

The following evidence stages are **not interchangeable**:

1. Code and interfaces present.
2. Unit tests pass (offline mocks only).
3. GitHub workflow actually runs.
4. Official Webull SANDBOX authentication and pinned account verified.
5. Broker order preview accepted.
6. Broker accepts order placement.
7. Broker reports an actual sandbox fill.
8. Subsequent position reconciliation verifies quantity change.

A green GitHub Actions check **cannot prove stages 4–8**. The separate
seven-agent executor remains **SANDBOX ONLY**, isolated from Beethoven and
ORB; it requires pre-existing opt-in, pinned account, exact consensus and
risk approval. This PR **does not** enable flags, invoke broker APIs,
alter the 80/19/1 allocation, merge accounts, loosen limits, alter trade
schedules, or authorize LIVE trading.

## Existing verification commands

```sh
python -m pip install -r requirements.txt webull-openapi-python-sdk==3.0.3
python -m pip install -r dashboard/requirements.txt
python -m unittest discover -s tests -v
node --check dashboard/static/office-world.js
node tests/office-world-smoke.cjs
python -m research.ai_desk --smoke --out /tmp/ai-desk-smoke
docker build --file dashboard/Dockerfile --tag paper-viewer-test dashboard
```

These commands are part of the existing read-only GitHub CI pipeline and
do not require broker credentials. A fresh run must be linked before any
test-success claim. For production deployment and actual fill verification,
additional authenticated external checks remain explicitly **unverified**.

## Follow-up work (separate PRs)

1. Verify end-to-end per-role GitHub Checks `app.slug` in an actual model
   workflow run and deployed Cloud Run dashboard.
2. Cross-check agent paper order history and detailed fills directly with
   the *designated* SANDBOX account, without exposing its account ID.
3. Address the existing Beethoven five-decimal order rejection and partial
   rebalance on its own strategy-maintenance branch.
4. Add point-in-time independent backtesting for each strategy with realistic
   fills/fees and walk-forward comparison; do not call synthetic returns profit.
5. Introduce a bounded Playwright browser test only after reviewing its
   dependency permissions and establishing an isolated test browser.

## Source references

- https://skills.sh/obra/superpowers/verification-before-completion
- https://skills.sh/addyosmani/agent-skills/observability-and-instrumentation
- https://skills.sh/addyosmani/agent-skills/test-driven-development
- https://skills.sh/addyosmani/agent-skills/security-and-hardening
- https://skills.sh/wshobson/agents/backtesting-frameworks
- https://skills.sh/addyosmani/agent-skills/ci-cd-and-automation
- https://skills.sh/microsoft/playwright-cli/playwright-cli
- https://skills.sh/guanyang/open-agent-hub/multi-agent-patterns
- https://skills.sh/wshobson/agents/risk-metrics-calculation


## Post-merge hardening extensions (2026-10-23 UTC)

- [PR #30](https://github.com/williamRut261/webull-paper/pull/30) merged as
  `9c44108e4970f2b7b304d11a2ff619d265a4edfa`. Strict seven-agent
  runtime/telemetry validation and dashboard source checks are in main.
- [PR #31](https://github.com/williamRut261/webull-paper/pull/31) merged as
  `95e849ae56fd6d7f14f5914fda1f68580eea6fde`. Original Beethoven
  Webull PAPER fractional quantities now round DOWN to five decimals,
  preventing the known HTTP 417 six-decimal violation; account fills
  still require external confirmation.
- A separate research/UI PR (this branch) adds:
  `research/performance_audit.py`,
  `tests/test_performance_audit.py`,
  `docs/STONKS_BACKTEST_AUDIT.md`,
  `tests/office_playwright_fixture.py`,
  `tests/office.e2e.spec.cjs`, `tests/test_release_proof.py`,
  an IAP-only `/office/release` endpoint,
  `docs/STONKS_CLOUD_RUN_DEPLOYMENT.md` and a pinned Playwright
  CI-only dependency.
- Playwright browser testing requires no Webull credentials: only
  localhost, synthetic statuses and test-process monkeypatching.
  Browser code is **not** part of the deployed Docker image.
- The new fixed-rule backtest is **not an ORB backtest** and cannot
  verify seven-agent profitability; without user-supplied dated market
  data it emits no performance report. No self-evolving trade rules
  or unverified parameter optimization have been introduced.
- No new trade activation, brokerage orders, cloud deployments or
  live-money operations are part of these repository changes.


## 2026-10-23 CDT — Execution evidence integration

The [Oct 22–23 operational audit](STONKS_OCT23_EXECUTION_AUDIT.md) extends the original verification-before-completion policy to cross-repository LIVE and dedicated SANDBOX sessions. New read-only evidence: `beethoven-replica-review` is the owner's actual active Alpaca LIVE repo; legacy `alpaca-flow-state` is retired and `alpaca-beethoven-original-paper` is manual-only. Keep these identities separate from `webull-paper` and from the manual-only Webull production coverage repository.

A `FILLED` string in GitHub Actions logs is stronger than a green run because it comes after broker SDK calls, but remains **workflow-reported** until independently matched to broker order history and balances. The Oct 23 Beethoven SANDBOX runner logged two fills and quantity reconciliation. An available Webull non-trading personal-account connection is **not** equivalent to the dedicated SANDBOX trading credentials. No cross-account equivalence should be inferred.

The ORB AI gate currently exits before `run_scan` when approval is missing; a no-order run cannot establish the existence or absence of ORB breakout signals. The seven-agent executor similarly exits before broker initialization on `NO_STRUCTURED_CONSENSUS`. These are intended fail-closed gates pending owner strategy review, **not** authority to relax criteria.

No execution engine was modified by this documentation audit. Maintain account fingerprints, live opt-in, limits, risk vetoes, exchange windows, isolated caches and IAP. Current deployed revision and credential rotation must still be certified from the owner's authenticated Cloud Run/GCP account.
