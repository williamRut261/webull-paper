# Provider-independent AI Trading Desk (research only)

This seven-specialist research system runs through GitHub Actions, **not a
literal group chat**. It now uses a fixed-endpoint provider adapter instead
of requiring the OpenAI Agents SDK. Supported model providers:

| Workflow selection | Actions secret | Default model | Cost |
| --- | --- | --- | --- |
| gemini (default) | GEMINI_API_KEY | gemini-3.5-flash-lite | May qualify for Google's limited free tier |
| openai | OPENAI_API_KEY | gpt-5-mini | API billed separately from ChatGPT |
| claude | ANTHROPIC_API_KEY | claude-haiku-4-5 | API billing applies |
| grok | XAI_API_KEY | grok-4.7 | API billing applies |
| compare | All configured secrets | Each provider's default | May make up to 28 billable requests |

Each full run has **seven** sequential specialist calls: Market Analyst,
Technical Analyst, News Researcher, Strategy Analyst, Risk Manager,
Desk Lead, independent Trade Reviewer. Later agents read earlier
opinions. The logic requires at least three of four analysts plus
risk-manager and desk-lead agreement for a **hypothesis for backtesting**.
That is not a trading instruction and does not demonstrate profit.

## Usage

1. Visit GitHub repository Settings > Secrets and variables > Actions.
2. Add a secret for the provider you actually want. To start with a
   potentially free provider, visit https://aistudio.google.com/apikey
   and create GEMINI_API_KEY. **Never paste it in chat or source files.**
3. Open Actions > AI Trading Desk (RESEARCH ONLY - NO BROKER ORDERS) >
   Run workflow. Select provider (gemini, openai, claude, grok, compare)
   and focus symbol (default GDXD).
4. Open the run Summary or download its ai-desk-research artifact for
   the JSON evidence, separate specialist opinions and token usage.
5. For recurring Gemini-only research, add GitHub Actions repository
   variable AI_DESK_ENABLED with value true. The scheduled job is
   disabled until you do so. Scheduled runs always use Gemini, not
   paid Claude/Grok/OpenAI or compare mode.
6. Optionally set repository variables AI_DESK_GEMINI_MODEL,
   AI_DESK_OPENAI_MODEL, AI_DESK_CLAUDE_MODEL, AI_DESK_GROK_MODEL to
   override model IDs. These are provider-specific and never change
   the endpoint host. Confirm the chosen model exists and your account
   can access it.

**Billing note:** Model provider free quotas and availability can change,
and free-tier Gemini input may be used by Google to improve products.
A Gemini API key associated with a billed Google project may produce
charges. The workflow does not guarantee a $0 bill. Manual compare mode
explicitly makes provider calls for every configured credential and may
incur charges; its cost is not enforced in code. Keep billing budgets
and limits at each provider. If a key is missing, the job reports
NOT_CONFIGURED rather than silently switching to a paid provider.

The market snapshot uses unofficial Yahoo historical daily closes,
not official exchange live quotes. It refuses missing/stale inputs and
does not claim to have verified news (no news feed is connected).
Research comparisons use identical price snapshots for every model,
but past or forward trade performance is not tested. This is not a
proof of AI model superiority or a portfolio management recommendation.

**Security:** Fixed HTTPS provider endpoints, bounded response sizes,
basic JSON output checks, read-only GitHub permissions, no Webull or
Alpaca keys in workflow, and no broker/order imports in the desk.
No buy/sell order can be sent by this workflow. Never trust model
opinions as executable signals.

## Offline regression/smoke

    python -m unittest discover -s tests -v
    python -m research.ai_desk --smoke --out /tmp/desk-smoke

The smoke test never contacts a model, market-data service or broker.

## Not activated

Webull PAPER remains Beethoven 80% / ORB 19% / ~1% cash. Separate draft
PR #4 remains a non-executing 4x25 research prototype. No five-way
allocation, per-sleeve real performance ledger, intraday Grok execution,
or live broker integration is implemented. Alpaca LIVE and Webull LIVE
are unchanged. Any trading cutover requires independent verification
and separate controls; it is explicitly out of scope here.
