# Stonks — Autonomous Seven-Agent Conversations

This is a **separate, research-only** office discussion engine. It is NOT a trader,
not an execution service, and it has **no Webull, Alpaca, Beethoven, ORB, or
brokerage connection**. No trading or paper-allocation workflow reads these chats.

## What actually runs

- GitHub Actions workflow: `.github/workflows/office-autonomous-dialogue.yml`.
- Schedule: **08 minutes after every UTC hour, 24/7**. GitHub Actions cron
  can run late or occasionally be skipped. The Cloud Run office does NOT
  perform inference or keep a 24/7 worker active.
- One run attempts at most **2** sequential Gemini model calls. The speaker
  rotates deterministically among **seven** existing Stonks specialists:
  Maya, Theo, Nova, Iris, Sage, Atlas, Quinn.
- Each specialist reads the latest **public, sanitized research snapshot** and
  the last eight published messages, replies to earlier discussion, and
  asks an evidence-based question. No live market-feed claims are allowed.
- An explicit **48 attempted conversation-model-calls per UTC day** budget is
  enforced using the versioned state in
  `research/office_conversation.json`. Each request has a 45-second
  HTTP timeout and a 900-token output limit. Real currency costs vary by
  Gemini model, region, and the amount of input; this is a *call-count* cap,
  not a dollar-denominated billing guarantee.
- A maximum of 56 completed sanitized conversation messages is stored in the
  same JSON file and published to the **PUBLIC** GitHub repository. Never
  include private positions, user information, live account details or
  credentials. Failed calls consume budget and publish no dialogue text.
- Successful messages and exact role Check states are shown by the private
  Cloud Run `/office` page. `/office/status` reads a rate-limited snapshot
  every ~5–6 minutes, rather than streaming one message at a time. Speech
  bubbles appear only on a newly observed, recently published message.
- The existing daily seven-agent desk and isolated virtual-paper ledger are
  completely independent. Their provider calls are NOT covered by this
  separate 48-conversation-call daily cap.

## Control

The GitHub repository Actions variable `OFFICE_CONVERSATION_ENABLED=false`
**disables future hourly jobs**. Remove the variable or set it to true to enable
them (default is enabled). Do not put API keys in variables; use the existing
`GEMINI_API_KEY` Actions secret. The configured model is
`AI_DESK_GEMINI_MODEL` (default Gemini Flash Lite).

To test manually, open the GitHub Actions tab, select
**Autonomous Seven-Agent Office (RESEARCH ONLY - NO BROKER)** and choose
**Run workflow** on `main`. This consumes up to two real API requests.
Examine the workflow output for per-role OK/FAILED events and
`research/office_conversation.json` for the persisted sanitized results.
The office will not invent chats if the key, API, or transcript is unavailable.

## Limitations

Because budget state is a GitHub file, reliability of the daily aggregate
budget depends on successful GitHub publishing. If an Actions job spends calls
but its state commit fails to push, those attempts will not be reflected in
later runs. Check for GitHub push errors and disable the scheduled workflow
on repeated publication failures. Use a transactional database or durable
pre-call reservations for a strict billing-enforced cap. GitHub Checks
are role observability only; absent Checks cannot be inferred from animations.
