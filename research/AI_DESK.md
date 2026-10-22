# AI Trading Desk — Seven-agent, read-only research

This OpenAI Agents SDK prototype imitates a trading-floor discussion:
Market Analyst, Technical Analyst, News Researcher, Strategy Analyst,
Risk Manager, Desk Lead, and independent Trade Reviewer. Each specialist
reads a single validated daily-market snapshot and earlier opinions.
No literal ChatGPT group chat exists; GitHub coordinates the agents.

The deterministic opinion gate needs at least three of the first four
analysts to agree, and both the risk manager and desk lead to agree.
Even unanimous agreement is ONLY a hypothesis for backtesting. No orders
are possible: this project has no broker SDK or broker credentials.

## Open the deployed workflow and results

1. Navigate to the repository Actions tab.
2. Select AI Trading Desk (RESEARCH ONLY - NO BROKER ORDERS).
3. Choose Run workflow, then your focus ticker.
4. Open its Summary to read each agent's opinion.
5. Download the ai-desk-research artifact for JSON details and data provenance.

## One-time setup (required for actual AI responses)

Create an Actions secret named OPENAI_API_KEY. Use your own OpenAI API
key, never a Webull secret. OpenAI API billing is separate from ChatGPT.
Do not paste any API key into chat.

To explicitly enable after-close weekday research, create repository
variable AI_DESK_ENABLED=true. Recurring calls incur API charges, so
the scheduled job is disabled until this variable is set.
Optional AI_DESK_MODEL defaults to gpt-5-mini.

The market feed is unofficial Yahoo historical DAILY bars. Incomplete
or stale bars cause a visible failure, not a guessed signal. No news
feed is connected; the news agent must state this. Quotes are not
suitable for order execution, and GitHub schedules are best-effort.

## Test

    python -m unittest discover -s tests -p test_ai_desk.py -v
    python -m research.ai_desk --smoke --out /tmp/desk-smoke

## Not included or activated

No five-strategy capital allocation, five-way Webull executor, trade
orders, account P&L attribution, autonomous intraday trading or tested
returns. Webull PAPER stays on the current 80/19 setup. PR #4 (4x25)
remains separate. Alpaca LIVE and Webull LIVE are untouched.
Integrating five sleeves requires a distinct safe cutover after
portfolio and data validation, loss controls, and paper-fill tests.
