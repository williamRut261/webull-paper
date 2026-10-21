# Beethoven PAPER + Day Trader research toolkit

**Integrated as advisory-only code. There are NO new broker order paths.**
The running Webull PAPER bot uses the original Composer 501-node strategy unchanged.
The additional tools cannot override signals, change 99% allocations, modify broker state,
or provide reliable forecasts of a trade's future outcome.

## Origin and license

Vendored from https://github.com/Jakeschincariol/day-trader-skill
at pinned upstream commit `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd` (Oct 20, 2026).
The original MIT license is included at `vendor/day_trader_skill/LICENSE`.
Python sources and skill instructions are copied unmodified. These are independent
command-line tools, **not** eleven profitable strategies and not brokerage execution.

## Connected workflow

The scheduled Webull PAPER job continues to run its original sandbox execution.
**After** that step, even on failure, a separate read-only advisory builds
`logs/beethoven-research.json` from `logs/webull-paper.log`. This lists
target weights, observed paper completion markers, concentration, and certain
leveraged/inverse ETF exposure warnings. It does not call any broker endpoints.
A completion log marker alone is not an independent brokerage fill audit.
If the signal is absent, the report says so.

There is a manual `Day Trader Research (MANUAL - NO BROKER ORDERS)` workflow
for scanner, news, analyst and Pelosi public data lookups. It has no trading
credentials, no schedule, and cannot call the broker module.
The other original skill scripts can be invoked locally using the original
README under `vendor/day_trader_skill/README.md`.

## The 11 included independent tools

| Module | Use | Beethoven connection |
| --- | --- | --- |
| trader-scanner | Chart setups | Optional independent research, NOT allocation |
| trader-news | Headlines / filings | Optional independent research |
| trader-entry | Intraday trade entry | Not suitable as a direct replacement for Beethoven's close signal |
| trader-exit | Intraday stops / targets | Advisory only; NOT connected to execution |
| trader-timemachine | Monte Carlo day-trade paths | Requires a separate intraday entry/stop/target plan |
| trader-budget | Proposed position sizing | Not wired to Beethoven's 99% sizing |
| trader-risk | Checks discretionary proposals | Does not override existing sandbox risk gates |
| trader-broker | Renders orders and logs approvals | NOT connected to Webull or CI workflows |
| trader-alerts | Research alerts | Not connected to Webull order/cancel logic |
| trader-analyst | SEC financial statements | Optional independent research |
| trader-pelosi | Public congressional filings | Optional independent research; lagged disclosure |

**Important:** The original Time Machine uses roughly 60 days of 5-minute
bars and simulated intraday moves. Beethoven holds and rotates a multi-asset
ETF strategy using a different time horizon. Its odds must not be presented
as the probability Beethoven will profit or as an every-outcome simulation.

## Try research manually (no brokerage credentials required)

Go to Actions > Day Trader Research (MANUAL - NO BROKER ORDERS) > Run workflow.
Select scanner/news/analyst/pelosi and type a ticker. Unofficial Yahoo and
public data providers may rate-limit or return unavailable data.

```bash
python -m research.beethoven_advisory --log logs/webull-paper.log --output logs/beethoven-research.json
python -m research.read_only_tool --tool scanner --symbol TQQQ
python -m research.read_only_tool --tool news --symbol TQQQ
python vendor/day_trader_skill/trader-timemachine/timemachine.py --help
python -m unittest discover -s tests -v
```

For historical Time Machine tests, follow its SKILL.md and provide valid
historical intraday bars, entry, stop and target. Do not run it against
Beethoven's daily closes as if they were five-minute bars.

No changes are made to Alpaca LIVE, Webull LIVE, or old retired paper repository.
