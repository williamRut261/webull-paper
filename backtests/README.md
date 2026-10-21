# Backtesting Beethoven versus Webull's 80/19 PAPER combo

Research-only branch. Does not alter any LIVE or PAPER order runner.

## What is tested

1. 2024–2026 Beethoven original 501-node tree at 99%, 80%, 75% allocation
   using prior-day daily adjusted CLOSE signals, next-close returns, and a
   conservative per-day proportional transaction cost approximation.
2. The 80/19 combo versus 99% Beethoven only on matched sessions having
   sufficient 5-minute charts for the reviewed Day Trader stock/ETF universe.
   This follows the original scanner's 20% maximum-failed-chart threshold;
   missing tickers are explicitly listed in each matched report row.
   15-minute opening range, first breakout, 10:20 entry proxy, 15:45 exit proxy,
   3 positions max, whole shares, 19% sleeve and 0.3% reference stop-risk cap.

**Critical:** historical five-minute data for the full requested 2024–2026
window is not freely available from Yahoo (typically under 60 days). This
tool never fabricates older bars. If more than 20% of scanner charts are
missing, the 80/19 comparison is **unavailable**, not zero. Days with lesser
missing coverage are flagged and should be interpreted cautiously. The same limitation applies to
tickers that did not yet exist during earlier requested dates.

The existing Backtesting.py library is useful for *single instruments* but
cannot reproduce simultaneous, cash-shared sleeves by itself. This simulator
therefore reuses the original Composer evaluator and multi-asset accounting
instead of inaccurately feeding the portfolio into a single-asset backtest.

These are simulations, not broker fills. Historical daily CLOSE decisions
are not identical to 15:48 ET live decisions, and Yahoo 5-minute bar OPEN
prices are not Webull order confirmations. Scanner failures, delays,
real-time quote entitlements, slippage and settled-cash limits may matter.
Stop references are NOT actual protective stop orders.

Run from repo root with Python 3.11:

    pip install -r requirements.txt "yfinance>=0.2.65" "backtesting>=0.6"
    python -m unittest discover -s tests -p test_comparison_backtest.py -v
    python -m backtests.download --end 2026-10-20 --start 2024-01-01
    python -m backtests.compare --end 2026-10-20 --start 2024-01-01

Output: backtests/results/report.json, long_beethoven.csv, matched_80_19.csv,
orb_trades.csv and backtests/data/coverage.json (unavailable history listed).

Do not merge into a production trading branch without review. Never publish
credentials or account data as GitHub artifacts.

## Interpreting results

`report.json` now lists the actual first/last dates of every return window,
including dates excluded when a strategy symbol did not yet trade. The primary
published performance uses the **longest uninterrupted valid period**. It does
not claim the full 2024–2026 dates if earlier ETFs or stocks did not exist.
Annualizing any small matched period is mathematically possible but **not** a
credible performance forecast. The short-date daily-close model cannot establish
that a real brokerage account would earn the historical paper simulation.

The combined matched return is the sum of the 80% Beethoven contribution and
the scanner sleeve; `scanner_missing` makes any incomplete chart coverage
visible. The scanner's stops/targets remain planning references, not submitted
protective orders. Fees and fills are approximate, never audited live results.
