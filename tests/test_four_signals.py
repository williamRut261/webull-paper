"""Completely offline checks for four-strategy research adapters."""
from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from strategy_engine import load_strategy, signal_symbols
from trader_combo.universe import CANDIDATES
from research.portfolio_lab.adapters import (RSIState, beethoven_from_closes,
    rsi_replay, rsi_trend_from_closes)
from research.portfolio_lab.four_signals import four_signals
from research.portfolio_lab.inout import RegimeState, REQUIRED
from research.portfolio_lab.orb import orb_from_observations

NY = ZoneInfo("America/New_York")


def fake_history(length=300):
    """Synthetic indicator fixture, NEVER actual market performance data."""
    root = load_strategy()
    symbols = signal_symbols(root) | set(REQUIRED) | {"QQQ", "GLD"}
    dates = pd.bdate_range(end="2026-10-20", periods=length)
    frame = pd.DataFrame(index=dates)
    for k, sym in enumerate(sorted(symbols)):
        frame[sym] = np.linspace(80.0 + k, 100.0 + k, length)
    return frame


def scan_report():
    return {"mode": "orb", "source": "yahoo", "unconfirmed": 0,
            "universe": len(CANDIDATES), "failed": 0,
            "hits": [{"symbol": "XLE", "at": "10:20 AM", "pct_over": .7,
                      "or_low": 49.2, "or_high": 49.8,
                      "price": 50.15, "close_date": "2026-10-21"}]}


class FourStrategyAdapterTests(unittest.TestCase):
    def test_original_composer_tree_is_read_only_and_normalized(self):
        frame = fake_history(1100)
        result = beethoven_from_closes(frame, "2026-10-20")
        self.assertAlmostEqual(sum(result.values()), 1.0)
        self.assertTrue(result)
        with self.assertRaisesRegex(ValueError, "exact completed"):
            beethoven_from_closes(frame, "2026-10-21")

    def test_unlevered_rsi_signal_and_one_week_lag(self):
        frame = fake_history()
        r = rsi_trend_from_closes(frame)
        self.assertAlmostEqual(sum(r.weights.values()), 1.0)
        self.assertLessEqual(r.weights.get("QQQ", 0), 1)
        self.assertEqual(r.state.as_of, "2026-10-20")
        self.assertTrue(r.bull)
        self.assertEqual(r.weights, {"QQQ": 1})
        with self.assertRaisesRegex(ValueError, "reused"):
            rsi_trend_from_closes(frame, r.state)
        with self.assertRaisesRegex(ValueError, "Unleveraged"):
            rsi_trend_from_closes(frame, bull_qqq=2)
        # One week-lag means changing an unfinished current week's RSI cannot
        # make the last *previously completed week's* RSI use future prices.
        prior = frame.iloc[:-1]
        old = rsi_trend_from_closes(prior).weekly_rsi_7
        changed = frame.copy()
        changed.loc[frame.index[-1], "QQQ"] *= .70
        newer = rsi_trend_from_closes(changed).weekly_rsi_7
        self.assertEqual(old, newer)

    def test_rsi_state_persistence_and_replay(self):
        frame = fake_history()
        replayed = rsi_replay(frame)
        self.assertEqual(replayed.state.as_of, "2026-10-20")
        with self.assertRaisesRegex(ValueError, "immediately preceding"):
            rsi_trend_from_closes(frame, RSIState(active_qqq=.75,
                                                   as_of="2026-10-15"))
        prev = rsi_replay(frame.iloc[:-1])
        one = rsi_trend_from_closes(frame, prev.state)
        self.assertEqual(one.state, replayed.state)

    def test_orb_25pct_and_stale_quote_fail_closed(self):
        report = scan_report()
        now = datetime(2026, 10, 21, 10, 22, tzinfo=NY)
        quotes = {"XLE": {"price": 50.15, "trade_at": now.isoformat()}}
        plan = orb_from_observations(report, quotes, now)
        self.assertLessEqual(sum(plan.weights.values()), 1)
        self.assertGreater(plan.weights["XLE"], 0)
        self.assertEqual(plan.selected, 1)
        self.assertLessEqual(plan.planned[0]["estimated_loss_at_stop"], 30.01)
        with self.assertRaisesRegex(ValueError, "stale"):
            bad = {"XLE": {"price": 50.15,
                           "trade_at": (now - timedelta(minutes=10)).isoformat()}}
            orb_from_observations(report, bad, now)
        with self.assertRaisesRegex(ValueError, "Missing independently"):
            orb_from_observations(report, {}, now)
        with self.assertRaisesRegex(RuntimeError, "Incomplete"):
            orb_from_observations({**report, "unconfirmed": 1}, quotes, now)

    def test_consolidates_all_four_sleeves_without_broker(self):
        frame = fake_history(300)
        now = datetime(2026, 10, 21, 10, 22, tzinfo=NY)
        prior = {"rsi_trend": {"active_qqq": 1.0, "cooldown": 0,
                               "dip_active": False, "as_of": "2026-10-19"},
                 "inout": {"is_in": True, "days_since_exit": 999,
                           "as_of": "2026-10-19"}}
        quotes = {"XLE": {"price": 50.15, "trade_at": now.isoformat()}}
        plan, states = four_signals(frame, scan_report(), quotes, now, prior=prior)
        self.assertEqual(set(plan["independent_sleeve_budgets"]),
                         {"beethoven", "inout", "rsi_trend", "claude_orb"})
        self.assertTrue(all(v == .25 for v in plan["independent_sleeve_budgets"].values()))
        self.assertLessEqual(sum(plan["target_weights"].values()), 1 + 1e-9)
        self.assertEqual(plan["broker_order_count"], 0)
        self.assertFalse(plan["real_money_allowed"])
        self.assertEqual(states["inout"]["as_of"], "2026-10-20")
        self.assertEqual(states["rsi_trend"]["as_of"], "2026-10-20")
        self.assertGreater(plan["sleeve_targets_within_own_capital"]["claude_orb"]["XLE"], 0)
        bad = {**prior, "rsi_trend": {**prior["rsi_trend"], "as_of": "2026-10-20"}}
        with self.assertRaisesRegex(ValueError, "preceding"):
            four_signals(frame, scan_report(), quotes, now, prior=bad)

if __name__ == "__main__":
    unittest.main()
