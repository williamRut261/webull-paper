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

An **unleveraged** RSI adapter is now implemented in `adapters.py`. It runs
EMA200, the author's EWM weekly RSI(7) with the one-week shift, 5-session
cooldown and bearish QQQ/GLD buffer. Bull allocation is **100% QQQ**, NOT
the author's published 200%-exposure version. Exact published return parity
is expressly NOT claimed. `adapters.py` also invokes the actual local
Beethoven JSON/evaluator against externally supplied dated closes. `orb.py`
filters original scanner output and timestamped independent quotes into
virtual 25%-sleeve trade ideas with the existing estimated stop-risk logic.
No adapter pulls account balances, submits broker orders, or establishes any
paper trade fill. EMA+VWAP remains disabled. Example signals are **synthetic**.

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

## New four-strategy combined signal plan (OFFLINE; NO BROKER)

`four_signals.py` builds one 25/25/25/25 virtual book from four sources:
Beethoven (existing 501-node evaluator), the existing *simplified* In & Out
proxy (with correctly persisted/replayed regime state), the *unleveraged*
RSI adapter, and genuine intraday ORB scanner hits with independent quote
observations. This is **not the existing scheduled Webull PAPER bot** and
will not run without explicit input files. It makes no network requests and
contains no broker order calls.

For an observation at 10:22 ET on Oct 21, after the Oct 20 completed close:

```sh
python -m research.portfolio_lab.four_signals \\
  --daily-csv path/to/full_wide_daily_adjusted_closes.csv \\
  --orb-report path/to/actual_2026-10-21_ORB_scanner_output.json \\
  --orb-quotes path/to/independently_timestamped_quotes.json \\
  --observed-at '2026-10-21T10:22:00-04:00' \\
  --out path/to/dry-run-plan.json \\
  --next-state-out path/to/next-signal-state.json
```

The daily CSV needs a `date` column and complete histories of the original
Beethoven signal symbols plus In & Out proxies, QQQ and GLD (252+ daily rows,
more if Composer indicators need them). `--orb-report` accepts the unmodified
original OG scanner JSON generated during the same ORB session. Quotes are a
JSON mapping `{ "XLE": { "price": 50.15, "trade_at": "2026-10-21T10:22:00-04:00" } }`
for each selected breakout. Quote timestamps must be within 120 seconds.
The exact latest completed daily bar is evaluated once; never enter future
prices. Pass `--prior-state` on following runs using the previous output,
otherwise the full state is bootstrapped across historical dates. Output
contains SHA-256 of files **only to identify the input version**; this does
NOT independently verify source authenticity or actual filled orders.

The three daily strategies deliberately use **last completed closes** while
ORB uses the **current morning**. No 15:48 current-day Beethoven target or
noon rebalancing is asserted. In particular a research plan is NOT an
executable Webull order set and cannot be safely handed to
`webull_paper.automatic` without a consolidated broker executor and
exclusive account ownership. The older scheduled 80/19 Webull PAPER runner
remains unchanged, and the new adapters must never be mistaken for four
funded/scheduled paper executions.

**Still outstanding:** actual validated shared market-data ingestion, one
exclusive sandbox execution manager, position/fill reconciliation and
sleeve attribution (including ORB day-trade P&L), same-period four-way
backtesting, independent daily return observations, and a verified risk
review prior to activating the change. Never use this signal plan as proof
of strategy profitability.
