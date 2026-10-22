# Claude $20 → Polymarket $4,218 viral reel — research audit

**Claim source:** https://www.instagram.com/reel/DeOO2ZWPFU3/

**Linked third-party wallet:**
https://polymarket.com/@0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82-1772569391020

**Research status:** Part 1 public-wallet forensic check, NOT a strategy
replication, historical trade-by-trade net return backtest, independent
verification of the alleged small-account test, or authorization to trade.

The reel says someone told Claude to look for BTC-specific time windows
with >65% edge, use Kelly bet sizes, skip high volatility, and update
probabilities Bayesianly. None of those four phrases is sufficient to
identify an actual forecasting function, odds entry rule, exact
timestamps, validated training dataset or executable strategy.

**Important discrepancies to test independently:**
- The referenced wallet is a verifiable public Polymarket account, but
  ownership and any causal connection to Claude are NOT established.
- We observed ETH and SOL fills and both Up and Down outcomes acquired
  in the same 5-minute market. This conflicts with a description of a
  simple BTC-only directional strategy.
- Polymarket's public PnL economics separately report realized market
  PnL, trade PnL, fees and maker/taker rebates. Do not conflate any
  one of these with a personal strategy return on $80.
- Public profile Markets Traded counts DISTINCT markets, NOT fills.
  The reel's "13,070 predictions" cannot be blindly compared to fills.
- No verified evidence of the claimed user's $80 deposit and $4,218
  end balance, full order history, financing, sizing or withdrawals.
- No evidence that the wallet's large-market-maker economics could
  be reproduced by an $80 taker with worse fills.

The audit retrieves only:
1. Public v2/user-stats for the pinned wallet.
2. The latest 100 public v2/trades fills from that SAME wallet.
3. A non-random sample breakdown by symbol and any markets with both
   outcomes in sample; never label fill count as independent bets.
4. Breakdown of documented PnL/fee/rebate components when available.

## Reproduce safely

The independent read-only workflow:
https://github.com/williamRut261/webull-paper/actions/workflows/polymarket-wallet-audit.yml

The workflow uses *no* credentials and cannot place orders.

    python -m unittest discover -s tests -p test_polymarket_wallet_audit.py -v
    python -m research.polymarket_wallet_audit

Running the second command downloads a small public Polymarket sample.
The captured report appears in out/polymarket-claude-wallet-audit/.
Public data may be delayed, stale or missing. API errors are surfaced.

## Actual backtesting prerequisites — not yet met

To test independent predictive edge rather than describe an existing
profitable wallet, first define a rules-based entry and exit signal
from timestamped BTC 5m or 15m markets (for example, time-of-day
bins *selected from training data* with a shrinkage-adjusted posterior
win probability). Use the actual market bid/ask and resolved reference
price, trade fees, minimum sizes, queue/depth, settlement specification
and latency. Use continuous time-split walk-forward tests to prevent
look-ahead, report confidence intervals and control for many time bins.
Compare to odds-implied probabilities, a 50/50 baseline and holding
the underlier. Freeze all parameters before the out-of-sample fold.

Bayesian beta-binomial updates may prevent small-sample overconfidence,
but cannot generate an edge from noise. A 65% win rate is not
automatically profitable: payout depends on the entry price and fees.
Kelly's bet fraction must be based on calibrated *net* payoff odds and
reduced drastically or turned off under uncertainty. Test fractional
Kelly only in research, with strict drawdown/risk limits.

We currently have NO independently validated prediction signal,
historical fill/slippage dataset, cost-adjusted equity curve, trades,
Sharpe, max drawdown, capital needs, or reproducible profit.
**Do not add a sixth strategy, change Webull PAPER, copy the wallet,
connect credentials, or enable actual orders.**

## Venue constraints

These markets are on Polymarket International, not Webull. According
to Polymarket's public help materials, US users cannot trade on
polymarket.com; the US product is separate and may not list the same
markets. Public read-only research does not need any trading account.
Do not bypass venue restrictions or assume that the strategy is
executable on Webull, Alpaca, or Polymarket US.
