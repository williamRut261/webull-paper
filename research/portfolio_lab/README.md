# Multi-strategy In & Out portfolio lab — NO TRADING

Isolated research on a **draft branch**. The existing Webull PAPER 80/19
workflow and both Alpaca and Webull LIVE bots remain **completely unchanged**.
This project contains zero brokerage APIs, credentials, execution instructions
or automated runner schedules.

## What it does

The portfolio manager handles target *weights*, NOT actual brokerage orders.
Each strategy gets a virtual capital allocation. Proposed holdings from
Beethoven, Peter Guenther's QuantConnect-style "In & Out", public RSI trend,
and Claude's ORB scanner are combined and netted into one portfolio target.
The EMA9+VWAP slot is disabled until its exact entry/exit rules are obtained.

The example allocates 25% each to Beethoven, In & Out, RSI, and Claude ORB,
with no research-only cash reserve, as a **demonstration only**.
Change the budgets only after matched multi-year tests. Every funded strategy
needs an explicit signal; otherwise **fail closed**. An empty explicit signal
means that sleeve holds cash. Gross exposure and per-symbol concentration are
checked on the *combined*, not individual, targets.

**No strategy may directly send orders.** A possible future real deployment
requires ONE sole executor with a separate authoritative account position
reconciler, market-hours gate, broker acknowledgment, idempotent order IDs,
minimum trade/cash/settlement checks, kill switch, and compliance validation.
If Beethoven LIVE or the Webull PAPER bot continue placing independent orders
in the *same account*, this virtual-book separation does not prevent conflict.
Do not attempt to execute these proposed changes alongside other active bots.

## In & Out adapter

Implements the essential *idea* of the public QuantConnect In & Out example
based on Peter Guenther: last 252 completed daily closes; baseline average
of closes 55–65 trading days ago; bottom-1-percentile shocks in XLI, DBB,
IGE, SHY, UUP and relative pairs (GLD/SLV, XLU/XLI, FXF/FXA); 15-session
risk-off cooldown. If risk-on: 100% of this sleeve in QQQ. If risk-off:
40% TLT, 40% IEF, 20% GLD. Each call consumes ONE new completed daily bar;
the returned InOut state must be persisted for the next new trading session.
Signals are available only *after* the completed daily close; don't trade
using the same bar's earlier prices.

This is an independently written, intentionally **simplified** proxy, **not
a reproduction** of the published +1,534% QC backtest: that example also has
adaptive wait-day logic, its own weekly trading schedule, and historical fill
assumptions. No claim of parity or profitable returns should be made.
Original discussion:
https://www.quantconnect.com/forum/discussion/9597/the-in-amp-out-strategy-continued-from-quantopian/p1
Published example:
https://www.quantconnect.com/terminal/cache/embedded_backtest_7aa1cbe2156acaafffa07ef68cfb67b1.html

The RSI trend and EMA+VWAP adapters are NOT yet implemented: never substitute
example JSON holdings for actual computed trading signals. The existing ORB
scanner and Beethoven evaluator likewise require future safe read-only
adapters with real timestamped market data. Example signals are **synthetic**.

## Run synthetic portfolio test

From the root of this repo (Python 3.11+):

    python -m unittest discover -s tests -p 'test_portfolio_lab.py' -v
    python -m research.portfolio_lab.cli \
      --config research/portfolio_lab/config.example.json \
      --signals research/portfolio_lab/signals.example.json \
      --as-of 2026-10-20

Optional --current accepts an existing holding SYMBOL:weight mapping and
prints NET changes, **not broker order tickets**. Add --inout-daily using a
wide CSV with columns date, QQQ, XLI, DBB, IGE, SHY, UUP, GLD, SLV,
XLU, FXF, FXA, TLT, IEF (only proxies used for signals need full history).
Historical data must be the point-in-time prices actually available and
correctly split/dividend handled at that point. Data errors halt processing.

Before allocating real capital: compare five independent sleeves, portfolio
blend and cash controls on identical histories with walk-forward holdouts,
transaction costs, leverage normalization, overlap/correlation/drawdowns and
disclosures for look-ahead and post-inception assets. The backtester
still needs implementing. This PR does NOT report real performance.


## Equal 25% research capital and daily leaderboard

As requested, **Beethoven, In & Out, RSI trend, and Claude ORB each get
25%** of a *virtual research* account (e.g. $2,500 each of $10,000).
The equal-allocation example uses 0% cash reserve strictly to demonstrate
a 100% research portfolio. It is **not a live trading recommendation**:
a future broker implementation needs explicit reserve/margin/settlement checks.
EMA9+VWAP stays disabled.

The new `daily.py` records one complete exchange session of **four
independently sourced NET returns** in a persistent JSON ledger, and produces
a Markdown leaderboard with daily %, daily virtual $ P&L, independent
cumulative %, virtual equity, a rank, an evidence reference for each,
and the 25%-daily-rebalanced combined portfolio's cumulative return.
This **does not generate signals or market returns**. It refuses missing
sleeves, invalid sources, look-ahead signals, duplicate dates, and
mixed live/paper/backtest results rather than inventing performance.
A net-return input of 0 must be a REAL observed zero, not a placeholder.

Input format is illustrated by
`research/portfolio_lab/observation.EXAMPLE_NOT_REAL.json`.
That example deliberately contains invented numbers and is never run by
any scheduled job or included in a real performance report.

Run after authentic same-mode strategy return observations exist:

    python -m research.portfolio_lab.daily \
      --observation REAL_2026-10-21.json \
      --ledger path/to/private/daily-ledger.json \
      --report path/to/private/report-2026-10-21.md

**Accounting note:** Each independent strategy compounds its own original
25%-funded virtual subaccount. To maintain equal *portfolio weights each day*,
the separate combined-portfolio NAV is rebalanced to 25% of current aggregate
equity in each sleeve after every session. Thus adding four independent
sleeve equities is NOT the same as the daily-rebalanced combined NAV
after the first day. This distinction is intentional. No broker positions
are liquidated by this read-only research system.

No automatic live/paper imports exist for RSI, the combined signal engine,
or intraday ORB yet, so a real four-way leaderboard cannot truthfully be
published until genuine comparable observations are connected. The workflow
runs **offline unit tests only**, not synthetic financial reports and
does not schedule real trades.
