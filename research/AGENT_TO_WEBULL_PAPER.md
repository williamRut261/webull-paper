# Automatic seven-agent approval of Webull SANDBOX PAPER ORB orders

**Scope:** Existing first Webull OpenAPI **SANDBOX** CASH account, not native
Webull app Paper Trading and NEVER Webull LIVE or Alpaca LIVE.

The previously running paper system targeted **80% Beethoven, up to 19% ORB,
at least 1% cash**. This integration adds **zero new strategy allocation**.
It changes the morning 19% ORB sleeve to require a seven-agent overnight
risk-on approval before its existing breakout signals can result in
sandbox orders. The Beethoven 80% logic, EOD exit, Webull endpoint,
price freshness, account SHA pin, open-order/history check, per-trade
risk limits, order-preview, fill reconciliation, and cash protections
remain in the existing code paths.

This is an *agent-approved ORB scanner*, NOT seven models each placing
orders, NOT trading the agents' proposed SPY/GDXD/QQQ ticker, and not
a separate multi-agent 5% portfolio. One existing exclusive sandbox
order runner is the only trade executor; agents collectively approve
or veto use of the original ORB scanner. It is also not proof of profit.

## Daily operation

1. Weekday evening 23:35 UTC, the existing seven-agent desk gathers
   public daily candles and asks all seven Gemini specialist roles.
   The research job publishes a sanitized structured opinion on main.
2. Next market morning, the ORB job stages at 09:05 ET; after
   10:25 ET it checks the AI report. It REFUSES missing, malformed,
   unsupported, same-day, future, >4-day-old, or non-Gemini reports.
3. A valid approval requires a consensus BUY **SPY or QQQ**
   (risk-on only), at least 3/4 early specialist votes at 65%+
   confidence, Risk Manager and Desk Lead both agreeing at 65%+,
   and Trade Reviewer not vetoing. Current HOLD opinions
   mean no new morning paper trades.
4. The existing original scanner independently looks for confirmed,
   fresh ORB breakouts and allocates ≤19% equity among up to 3 eligible
   candidates, always reserving at least 1% cash and checking Beethoven
   ownership. Model recommendations cannot inject unapproved tickers,
   bypass market-time checks, or submit independent brokerage orders.
5. The Beethoven close runner retains its 15:48 ET responsibility
   to liquidate identified ORB-owned positions and rebalance 80%.
   GitHub Actions cron is best-effort; delayed or skipped jobs may miss
   entries or exits, and market prices can move sharply.

A trade can be placed on a scheduled day only if **BOTH** the seven-agent
risk-on approval and original ORB scanner/sandbox broker validation pass.
No guaranteed daily trades.

## Kill switch / controls

In GitHub repo Settings > Secrets and variables > Actions > Variables,
set `AI_PAPER_BROKER_KILL_SWITCH` to `true` to block the morning
ORB/agent order runner at entry. This does NOT disable Beethoven's
end-of-day account management. Set `AI_DESK_ENABLED=false` to stop
scheduled paid Gemini research separately. GitHub job runs already
started may not observe variable changes, so disable the workflow or
cancel running jobs if immediate suspension is required.

The existing Webull API credentials must remain repository *secrets*.
Do not put OAuth client secrets or any brokerage key into variables,
code, logs, issue comments, or this chat.

## Deployment / verification

- Review merged PR and CI. Changes only go live after a merge to main.
- The next successful scheduled **evening** research must publish
  last-session seven-agent outputs (today's 7× HOLD SPY would block buys).
- Verify the next scheduled **morning** ORB log shows
  `PAPER_AI_DESK_GATE` with `approved` and `reason`. If approved,
  watch for `PAPER_TRADER_PLAN` and verified actual sandbox
  orders; if blocked, there should be no ORB order attempt.
- Verify Webull sandbox order history directly; GitHub green tests and
  AI confidence do not independently prove fills.
- Cloud Run dashboard redeployment is **NOT REQUIRED** for the actual
  agent-gated order runner; dashboard only shows read-only research and
  broker activities.
- Do not assume a red Cloud billing-card validation screen is related
  to Webull SANDBOX GitHub Actions. That screen is a Google billing issue.

## Limitation

A fully independent portfolio in which the AI desk itself selects and
owns symbols requires separately budgeted capital or a replacement
decision for the existing ORB sleeve. It also needs additional
reconciliation and close-outs so the Beethoven executor doesn't treat
AI-owned positions as manual or unknown positions. This change
deliberately avoids that conflict.
