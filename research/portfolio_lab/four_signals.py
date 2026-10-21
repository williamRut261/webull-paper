"""Compute FOUR independent, contemporaneous PAPER-RESEARCH signal sleeves.

NO BROKER IMPORTS / NO EXECUTION. Daily long-horizon signals use the last
completed close; ORB uses fresh same-session 5m evidence and quote snapshots.
Inputs are externally supplied. Hashes prove input identity, NOT authenticity.
"""
import argparse
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from .adapters import (RSIState, beethoven_from_closes,
                       rsi_replay, rsi_trend_from_closes)
from .inout import RegimeState, inout_from_closes
from .orb import orb_from_observations
from .portfolio import PortfolioError, combine

SLEEVES = ("beethoven", "inout", "rsi_trend", "claude_orb")
BUDGETS = {key: 0.25 for key in SLEEVES}


def replay_inout(frame):
    """Bootstrap source-like cooldown history; no signal on an unprimed state."""
    if len(frame) < 252:
        raise ValueError("Insufficient market history for In & Out")
    result = None
    state = RegimeState()
    for end in range(252, len(frame) + 1):
        result = inout_from_closes(frame.iloc[:end], state)
        state = result.state
    return result


def four_signals(frame, report, quotes, observed_at, *, prior=None, equity=10000.0):
    """Make a combined paper-*research* target with source-specific attribution.

    Signals are not synchronized intraday decisions: three models use last
    close and ORB uses the next session at ~10:20 ET. Actual broker execution
    needs separate review and a single exclusive account reconciler.
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty or (
            not isinstance(frame.index, pd.DatetimeIndex)):
        raise PortfolioError("A dated, complete historical closes DataFrame is required")
    as_of = frame.index[-1].date().isoformat()
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None or (
            observed_at.date() <= frame.index[-1].date() or
            (observed_at.date() - frame.index[-1].date()).days > 7):
        raise PortfolioError("ORB scan must follow a recent completed-close session")
    if prior is not None:
        if not isinstance(prior, dict) or set(prior) != {"inout", "rsi_trend"}:
            raise PortfolioError("Both previous session states must be provided")
        prior_rsi = RSIState(**prior["rsi_trend"])
        prior_inout = RegimeState(**prior["inout"])
        expected = frame.index[-2].date().isoformat()
        if prior_rsi.as_of != expected or prior_inout.as_of != expected:
            raise PortfolioError("Prior state must match the preceding completed session")
        rsi = rsi_trend_from_closes(frame, prior_rsi)
        inout = inout_from_closes(frame, prior_inout)
    else:
        # Historical warm-up is mandatory to avoid defaulting regime state every day.
        rsi = rsi_replay(frame)
        inout = replay_inout(frame)
    beethoven = beethoven_from_closes(frame, as_of)
    orb = orb_from_observations(report, quotes, observed_at, total_equity=equity)
    signals = {
        "beethoven": beethoven,
        "inout": inout.weights,
        "rsi_trend": rsi.weights,
        "claude_orb": orb.weights,
    }
    plan = combine(BUDGETS, signals, cash_reserve=0,
                   max_symbol_weight=1.0)
    next_state = {"inout": asdict(inout.state),
                  "rsi_trend": asdict(rsi.state)}
    result = {
        **plan.to_dict(),
        "portfolio_mode": "RESEARCH_ONLY_NOT_BROKER_ORDERS",
        "real_money_allowed": False,
        "broker_order_count": 0,
        "independent_sleeve_budgets": BUDGETS,
        "as_of_completed_daily_close": as_of,
        "orb_observation_time": orb.observed_at,
        "data_authenticity": "USER_SUPPLIED_FILES_NOT_INDEPENDENTLY_VERIFIED",
        "sleeve_targets_within_own_capital": signals,
        "rsi_unleveraged_not_published_2x_strategy": True,
        "rsi_weekly_rsi_7": rsi.weekly_rsi_7,
        "rsi_ema200": rsi.ema_200,
        "inout_proxy_shocks": list(inout.triggered),
        "orb_candidates_from_real_report": orb.selected,
        "orb_virtual_plans_NOT_ORDERS": list(orb.planned),
        "source_warning": "Not a recommendation; validates input structure, not market data source. "
                          "Do not route these targets to another broker runner.",
    }
    return result, next_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-csv", required=True, help="dated WIDE adjusted close file")
    parser.add_argument("--orb-report", required=True, help="actual saved OG scanner orb JSON")
    parser.add_argument("--orb-quotes", required=True,
                        help="saved independent quote snapshots {TICKER:{price,trade_at}}")
    parser.add_argument("--observed-at", required=True,
                        help="offset-aware ISO date-time within 10:20-10:40 America/New_York")
    parser.add_argument("--prior-state", help="two prior-date persistent signal states")
    parser.add_argument("--virtual-equity", type=float, default=10000)
    parser.add_argument("--out", required=True, help="research target JSON file")
    parser.add_argument("--next-state-out", required=True,
                        help="read-only file for next completed-close signal")
    args = parser.parse_args()

    prices_file = Path(args.daily_csv)
    report_file = Path(args.orb_report)
    quote_file = Path(args.orb_quotes)
    prices = pd.read_csv(prices_file, parse_dates=["date"]).set_index("date")
    report = json.loads(report_file.read_text())
    quotes = json.loads(quote_file.read_text())
    prior = json.loads(Path(args.prior_state).read_text()) if args.prior_state else None
    output, states = four_signals(
        prices, report, quotes, datetime.fromisoformat(args.observed_at),
        prior=prior, equity=args.virtual_equity)
    output["input_sha256_not_provenance"] = {
        "daily_csv": sha256(prices_file.read_bytes()).hexdigest(),
        "orb_report": sha256(report_file.read_bytes()).hexdigest(),
        "orb_quotes": sha256(quote_file.read_bytes()).hexdigest(),
    }
    # Only write after all four signal adapters and portfolio safety checks pass.
    Path(args.out).write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    Path(args.next_state_out).write_text(json.dumps(states, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
