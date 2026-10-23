# Offline Stonks Performance Audit (SIMULATION ONLY)

This optional research tool **never authenticates with Webull, reads live
account data, calls a model or places an order**. It extends the existing
`backtest.py` close-to-close simulator without modifying trading logic.

## Running a fixed-rule holdout evaluation

Start with an independently sourced, verified adjusted-close CSV
containing a sorted `date` column and the complete signal+execution
symbol universe needed by `strategy_engine.py` (including `SPY`
as a passive benchmark). At least 80 observations are required.
You must decide and record the holdout date **before** viewing results.
You are responsible for verifying delistings, dividends, splits, and
survivorship coverage in the supplied dataset.

```sh
python -m research.performance_audit \
  --prices YOUR_ADJUSTED_CLOSES.csv \
  --start 2024-01-02 \
  --holdout 2025-01-02 \
  --cost-bps 8 \
  --output out/performance-audit.json
```

The tool requires **30 or more trading observations on each side** of
the holdout boundary. Without enough data it refuses to print results.
It labels every result `SIMULATION_ONLY_NOT_REAL_OR_PAPER_BROKER_RETURNS`.

Included: total and annualized hypothetical returns, maximum drawdown,
daily win/loss/flat counts, annualized volatility, daily gains-to-losses
ratio, and annualized zero-risk-free-rate Sharpe when at least 30 valid
observations with nonzero variance exist. All comparison modes use
**identical calendar spans**, with a side-by-side SPY buy-and-hold
benchmark explicitly labeled as excluding initial purchase fees.

Important: `original` and `compliant` are the two existing original
strategy variants in `backtest.run`. This module does **NOT**
backtest ORB intraday entries, seven-agent opinions, or Beethoven's
actual Webull fills. Nor is it a genuine walk-forward optimization
framework: it holds rules fixed and splits results into retrospective
pre-holdout and holdout windows. The underlying model assumes a signal
at the close is filled at that same close, which can be optimistic.

**Do not compare these hypothetical close-to-close returns to brokerage
P&L, paper fills, intraday ORB, or other datasets as if equivalent.**
The tool never claims real dollars earned, real fees paid, or audited
paper results. No realistic fill quality is claimed without actual
timestamped bid/ask quotes and order receipts.

## Evidence and tests

- Python offline tests: `tests/test_performance_audit.py`.
- Existing CI workflow: `.github/workflows/tests.yml`.
- The simulator's input-slice invariant is tested to ensure evaluation
  for signal time `t` only receives bars through `t`.
- The required holdout date is supplied explicitly; the test does not
  imply it was pre-committed for historical research already performed.

## Before claiming strategy improvement

1. Verify third-party adjusted-close source and date coverage.
2. Register the strategy rules and holdout period before comparing.
3. Compare against identical-date baseline and record fees, spread,
   slippage and execution assumptions.
4. Preserve drawdown, turnover and uncertainty with all reported returns.
5. Validate actual sandbox order status and holdings independently
   before describing any simulated trade as filled.
6. Collect real ORB, Beethoven and agent trade logs in isolated,
   nonpublic datasets; never disclose Webull account identifiers.

The operator must separately deploy Cloud Run dashboard updates with
authentication and verify the revision. This backtest utility is not
deployed to Cloud Run.
