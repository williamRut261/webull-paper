"""Strict, read-only out-of-sample accounting for the existing backtest.

This module NEVER calls models, market-data services or brokers, and never
turns research opinions into executable orders. All metrics are explicitly
hypothetical and require a supplied historical prices CSV.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import mean, stdev

import pandas as pd

from backtest import run


MIN_SHARPE_OBSERVATIONS = 30
TRADING_SESSIONS_YEAR = 252


def validated_prices(prices):
    """Require actual date index, enough past observations and finite prices."""
    if (not isinstance(prices, pd.DataFrame) or prices.empty
            or not isinstance(prices.index, pd.DatetimeIndex)
            or prices.index.has_duplicates or not prices.index.is_monotonic_increasing
            or not prices.index.is_unique
            or prices.columns.has_duplicates):
        raise ValueError("Expected a sorted unique dated price matrix")
    if len(prices) < 80:
        raise ValueError("At least 80 observed bars are required for this audit")
    if not all(isinstance(s, str) and s.strip() for s in prices.columns):
        raise ValueError("Invalid column labels")
    if not prices.index.notna().all():
        raise ValueError("Missing date in price data")
    for col in prices:
        values = pd.to_numeric(prices[col], errors="coerce")
        if values.isna().any() or not values.map(
                lambda x: math.isfinite(float(x)) and float(x) > 0).all():
            raise ValueError("Missing, future-filled, nonfinite or nonpositive price: " + col)
    if (prices.index.to_series().diff().dropna() <= pd.Timedelta(0)).any():
        raise ValueError("Duplicated or nonincreasing timestamps")
    return prices


def summarize_returns(returns):
    """Risk accounting based on daily simple returns, with zero risk-free rate.

    No Sharpe is reported for fewer than 30 daily observations or zero
    observed variance. A zero losing-days denominator yields no profit
    factor, not misleading infinite performance.
    """
    if not returns:
        raise ValueError("No simulated returns")
    values = [float(x) for x in returns]
    if (any(not math.isfinite(x) or x <= -1 for x in values)
            or len(values) > 100000):
        raise ValueError("Invalid simulated returns")
    equity, peak, deepest = 1.0, 1.0, 0.0
    for daily in values:
        equity *= 1 + daily
        peak = max(peak, equity)
        deepest = min(deepest, equity / peak - 1)
    wins = [x for x in values if x > 0]
    losses = [x for x in values if x < 0]
    flat = len(values) - len(wins) - len(losses)
    vol = stdev(values) if len(values) > 1 else 0
    sharpe = (math.sqrt(TRADING_SESSIONS_YEAR) * mean(values) / vol
              if len(values) >= MIN_SHARPE_OBSERVATIONS and vol > 0 else None)
    # These statistics are descriptive, never predictions of future returns.
    return {
        "observations": len(values),
        "cumulative_return_pct": round(100 * (equity - 1), 4),
        "annualized_return_pct": round(100 * (equity ** (TRADING_SESSIONS_YEAR / len(values)) - 1), 4),
        "max_drawdown_pct": round(100 * -deepest, 4),
        "daily_win_rate_pct": round(100 * len(wins) / len(values), 2),
        "positive_days": len(wins), "negative_days": len(losses), "flat_days": flat,
        "daily_gain_loss_ratio": round(sum(wins) / -sum(losses), 4) if losses else None,
        "annualized_volatility_pct": round(100 * vol * math.sqrt(TRADING_SESSIONS_YEAR), 4),
        "sharpe_zero_riskfree": round(sharpe, 4) if sharpe is not None else None,
        "sharpe_eligible": sharpe is not None,
    }


def daily_returns_from_equity(series):
    """First day uses an explicit 1.0 initial NAV, unlike pct_change()."""
    past = 1.0
    rows = []
    for amount in series:
        current = float(amount)
        if not math.isfinite(current) or current <= 0:
            raise ValueError("Invalid simulation NAV")
        rows.append(current / past - 1.0)
        past = current
    return rows


def evaluate_fixed_rule_holdout(prices, start, holdout, cost_bps=5.0):
    """Replay existing fixed strategy with historical closes and a dated holdout.

    Not a walk-forward hyperparameter optimizer; no parameters are fitted.
    The simulator explicitly uses close-t signals to earn close-t-to-t+1
    returns, so it cannot replicate intraday or opening Webull fills.
    """
    prices = validated_prices(prices)
    if (type(cost_bps) not in (int, float)
            or not math.isfinite(cost_bps) or not 0 <= cost_bps <= 1000):
        raise ValueError("Costs must be 0..1000 bps")
    try:
        start_day = pd.Timestamp(start).normalize()
        holdout_day = pd.Timestamp(holdout).normalize()
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid start/holdout date") from error
    if start_day >= holdout_day or prices.index.tz is not None:
        raise ValueError("Expected ordered dates and naive historical session dates")

    # The historical pricing matrix must supply the passive SPY benchmark.
    if "SPY" not in prices:
        raise ValueError("SPY benchmark adjusted closes are required")
    results = run(prices, start=start_day, cost_bps=cost_bps)
    if ("date" not in results or "original" not in results or "compliant" not in results
            or len(results) != len(set(results["date"]))):
        raise ValueError("Backtest output lacks dated original/compliant strategies")
    dates = pd.to_datetime(results["date"])
    if (dates.hasnans or not dates.is_monotonic_increasing
            or len(dates) == 0
            or dates[0] < start_day):
        raise ValueError("Invalid simulated evaluation dates")
    train_mask = [dt < holdout_day for dt in dates]
    pre = sum(train_mask)
    if pre < MIN_SHARPE_OBSERVATIONS or len(dates) - pre < MIN_SHARPE_OBSERVATIONS:
        raise ValueError("Need at least 30 pre-holdout and 30 holdout daily observations")

    # Because the simulator returns one NAV per next-session date,
    # benchmark returns span the same [previous-session, session] intervals.
    benchmark = []
    for dt in dates:
        loc = prices.index.get_indexer([dt])[0]
        if loc < 1:
            raise ValueError("Benchmark has no previous session")
        benchmark.append(float(prices["SPY"].iloc[loc] / prices["SPY"].iloc[loc-1] - 1))
    by_strategy = {
        "original": daily_returns_from_equity(results["original"]),
        "compliant": daily_returns_from_equity(results["compliant"]),
        "SPY_buy_and_hold": benchmark,
    }
    scores = {}
    for label, daily in by_strategy.items():
        scores[label] = {
            "pre_holdout": summarize_returns(daily[:pre]),
            "holdout": summarize_returns(daily[pre:]),
        }
    return {
        "status": "SIMULATION_ONLY_NOT_REAL_OR_PAPER_BROKER_RETURNS",
        "strategy_scope": "existing original vs compliant; excludes ORB and seven-agent strategy",
        "input_source": "user_supplied_historical_close_matrix_not_cryptographically_verified",
        "execution_assumption": "signal close t, fill same close t, earn t-to-t+1; no actual orders",
        "lookahead_note": "rules evaluate only past and current bars; closing fill model is optimistic",
        "cost_bps_per_turnover_unit": float(cost_bps),
        "benchmark_cost_bps": 0.0,
        "benchmark_cost_note": "SPY buy-and-hold benchmark excludes initial purchase costs; not an exact matched-cost portfolio",
        "start": str(start_day.date()),
        "holdout_start": str(holdout_day.date()),
        "train_days": pre, "holdout_days": len(dates)-pre,
        "metrics": scores,
        "limitations": [
            "Historical data may omit delisted securities and corporate actions",
            "Not genuine out-of-sample unless holdout date fixed before inspecting results",
            "No intraday bids/asks, real spreads, partial fills or market-impact model",
            "No broker order/fill or strategy profits verified",
            "No independent seven-agent/ORB intraday trade history available for comparison",
        ],
    }


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--prices", required=True, help="CSV with date index and adjusted closes")
    cli.add_argument("--start", required=True, help="First replay session YYYY-MM-DD")
    cli.add_argument("--holdout", required=True, help="Pre-committed holdout boundary YYYY-MM-DD")
    cli.add_argument("--cost-bps", default=5.0, type=float)
    cli.add_argument("--output", required=True, help="JSON report path")
    args = cli.parse_args(argv)
    file = Path(args.prices)
    if not file.is_file():
        cli.error("Price CSV does not exist")
    prices = pd.read_csv(file, index_col=0, parse_dates=True)
    report = evaluate_fixed_rule_holdout(prices, args.start, args.holdout, args.cost_bps)
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print("STONKS_SIMULATION_ONLY", json.dumps({
        "output": str(dest), "train_days": report["train_days"],
        "holdout_days": report["holdout_days"], "broker_orders": 0
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
