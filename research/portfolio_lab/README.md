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

The example allocates 60% Beethoven, 20% In & Out, 10% RSI, 9% ORB, and 1%
cash, as a **demonstration only**, not an optimized or recommended allocation.
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
