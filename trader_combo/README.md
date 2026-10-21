# Combined Beethoven + original Day Trader Skill (Webull SANDBOX)

This is a **two-sleeve automatic paper-trading strategy** in the same pinned
Webull sandbox CASH account, not a brokerage live bot:

- Beethoven: **80%** of account equity target at the existing ~15:48 ET signal,
  preserving every relative weight and the unmodified 501-node Composer JSON.
- OG Trader: **at most 19%** for 1–3 intraday confirmed opening-range-breakout
  stock/ETF positions. Target cash buffer: **at least 1%**.
- Trader positions are automatically targeted for liquidation in Beethoven's
  scheduled 15:48 ET sell-before-buy runner. If GitHub skips a scheduled run,
  a delayed quote or broker rejection can leave overnight positions: this is
  **not a guaranteed flatten**, and no protective stop-loss is placed.
- Original stock-scanner scripts are reused **unmodified** from the pinned MIT
  day-trader-skill under vendor/. This dedicated pre-reviewed stock AND ETF
  universe is intentionally limited to the symbols in trader_combo/universe.py,
  excludes all Beethoven signal/eligible holding tickers and excludes unreviewed
  products. It is NOT a whole-market thousands-of-assets continuous scan.
- Scanner candle data is unofficial Yahoo 5-minute bars, but it **never prices
  a submitted order**. The selected ticker requires a session-dated Webull
  quote whose last trade is at most 120 seconds old, and whose execution price
  differs by at most 1% from the observed breakout.
- Breakout stop reference = opening-range midpoint, estimated target = +2R.
  The reference stop is a **risk filter only**; it is *not* an actual protective
  stop order. Size uses a 0.3% of equity estimated stop loss cap and 19%
  gross exposure cap. A gap can exceed this expected loss.
- No shorts, margin, options, live endpoints, or automated adaptation of
  Beethoven's original holdings beyond scaling their allocation to 80%.
- The two workflows share one GitHub Actions concurrency group and distinct
  order IDs (bt* for Beethoven, tr* for scanner).
- Morning entry: 10:20–10:40 ET regular trading session, then full Webull
  order preview/placement/fill verification. Missed runs and stale quotes
  skip/fail instead of trading blind.
- EOD: 15:48–15:55 ET. Sell intraday trader symbols then perform original
  Beethoven rebalance to its 80% target, preserving 1% spare cash.
- Starts only after the first successful 80% Beethoven rebalance: the morning
  bot refuses to trade with an existing 99%-invested Beethoven account.
- Sandbox CASH account #0 must match WEBULL_PAPER_ACCOUNT_SHA256 and secrets.
  Automatic buy/sell only on GitHub schedule, never manual dispatch.

## Research vs live automation

Vendored OG's other ten tools (News, Entry, Exit, Time Machine, Risk,
Budget, Analyst, Alerts, Broker, Pelosi) remain available as **research**
tools. The live paper order logic uses *the scanner's* opening-range breakout
signals and conservative risk/reference exit formula; it is not a claim that
all eleven tools provide automated brokerage execution or profitable trades.

## Testing

Run `python -m unittest discover -s tests -v` on every PR. Mock-only CI
does not establish broker connection, execution fills, market data freshness,
or profitability. Inspect the logs of actual GitHub Actions sandbox sessions.

**Only Webull PAPER repo changed**. Alpaca LIVE, Webull LIVE and the retired
original paper repository remain untouched.
