# Seven-agent desk operations — October 22, 2026

## System boundaries

The deployed Webull PAPER **Cloud Run dashboard** is a read-only IAP application.
The live Webull OpenAPI SANDBOX trading sleeves remain **80% Beethoven / up to
19% ORB / at least 1% spare cash**. They DO NOT consume AI-desk recommendations.
Alpaca LIVE and Webull LIVE are entirely outside this repository.

The separate seven-agent desk runs **research only**:
1. Market Analyst — broad market regime.
2. Technical Analyst — RSI, SMA20, SMA50, 20-session return.
3. News Researcher — reports **news NOT CONNECTED** (does not invent headlines).
4. Strategy Analyst — testable ideas and cost caveats.
5. Risk Manager — veto if weak evidence.
6. Desk Lead — reconcile prior analyst views.
7. Trade Reviewer — independent critical review.

The model provider is selected for all seven sequential calls: scheduled
Gemini by default, manual Gemini/OpenAI/Claude/Grok/compare.
Providers do NOT each run an agent in parallel and do not control broker trades.
The daily market source is public unofficial Yahoo daily candles, not broker
realtime execution quotes. Any invalid/missing input fails visibly.

## Auto schedule / disable / costs

GitHub workflow: .github/workflows/ai-trading-desk.yml.
- Weekdays 23:35 UTC (18:35 Houston daylight time, 17:35 standard time).
- Default scheduled state: ENABLED except if repository Actions variable
  AI_DESK_ENABLED equals **false**. Manual runs remain possible.
- Requires repository *secret* GEMINI_API_KEY for 7 paid/credit-consuming
  model calls per scheduled day. Other provider secrets optional:
  OPENAI_API_KEY, ANTHROPIC_API_KEY, XAI_API_KEY.
- Gemini model is configurable via Actions variable AI_DESK_GEMINI_MODEL.
  The configured model must be available to the connected key/provider.
- Set AI_DESK_ENABLED=false to STOP automatic AI-model calls. It does not
  turn off the existing Beethoven or ORB schedule.
- No API key is bundled in the repo, dashboard, virtual ledger or report.
  Do not paste secrets into chat or workflow logs.
- GitHub scheduled jobs can be delayed or skipped; successful code tests
  do not establish that a real model API call has completed.

## Separate VIRTUAL PAPER shadow execution

The bridge research/agent_paper.py has NO broker SDK or network/order calls.
It processes only complete, validated 7-agent RESEARCH_ONLY consensus
hypotheses, and queues a virtual order for the **NEXT session's daily close**
to avoid filling at a close already known to the research agent.

Risk controls:
- Independent synthetic starting equity $10,000; no shared Webull cash.
- A single long position with maximum 5% gross equity exposure.
- Maximum estimated 0.1% account loss per candidate assuming a hypothetical
  2% stop distance. **This is not a protective stop order.**
- 0.1% assumed transaction cost per virtual transaction.
- No shorts, leverage, fractional shares, realtime fills, retries of a
  given day, or broker calls.
- Repository Actions variable AI_PAPER_KILL_SWITCH=true cancels pending
  virtual intents and stops new virtual orders while preserving account
  marks. If unset, simulated entries/exits may be queued.
- Virtual performance is **not** strategy proof and cannot be compared
  to real execution. Daily-close marks cannot model intraday stops, gaps,
  spreads, liquidity or market-impact.

Only these two public-safe JSON files are committed from the scheduled workflow:
research/ai_desk_status.json and research/agent_virtual_ledger.json.
The repo is PUBLIC, so these synthetic research opinions and fictional
performance are PUBLIC. No broker account IDs, holdings, order history,
API keys, raw model responses or personally identifying data are published.
The private dashboard *reads* that sanitized public feed and displays it
separately from actual Webull sandbox positions/order history.

A GitHub Actions workflow token needs contents:write to push these files.
If push fails due to repository rules or token permissions, the workflow
will show failure and dashboard will show stale / unavailable research.
The dashboard never presents unavailable research as a successful trade.

## ORB reliability

Earlier 09:35 ET GitHub staging missed an Oct 21 market window when GitHub
started the runner ~78 minutes late. The new stage is 09:05 ET, waits
until 10:25 ET, and hard-rejects orders after 10:40 ET, with a 115-minute
runner timeout. This improves tolerance; no GitHub cron can guarantee
execution. The **morning 19% sleeve** and existing 15:48 ET Beethoven
exit logic are unchanged. Check the next real *scheduled* execution log.

## Verify/rollout (do not assume automatic deployment)

- Confirm CI for PR #16 and review the virtual-only code.
- Merge only if tests pass; GitHub workflow schedules apply after merge.
- Confirm GEMINI_API_KEY is configured; run AI Desk manually and verify
  7 real specialist results in report.json. A CI smoke test is NOT this.
- Look for a successfully published research/ai_desk_status.json and new
  virtual ledger day after the next scheduled run.
- **Cloud Run does NOT redeploy from GitHub automatically.** Deploy the
  reviewed dashboard directory to existing webull-paper-viewer only,
  retaining existing private IAP, service account and Secret Manager
  bindings. Verify signed-in access, signed-out denial and no broker
  order-call changes.
- Compare repo/CI status and UI agent date, and inspect paper order
  history separately. Do not attribute Webull fills to AI agents.

Real Webull PAPER agent execution is NOT authorized by these changes:
a separate capital allocation / exclusive broker manager / reconciliation,
fill-ownership, kill switch and explicit approval would be required before
connecting an AI strategy to the brokerage sandbox.
