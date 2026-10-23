"""Offline validation of explicitly hypothetical backtest evaluation.

No model calls, data downloads, broker connections or order submissions.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from research.performance_audit import (
    evaluate_fixed_rule_holdout, summarize_returns, validated_prices, main,
)


def prices(n=120):
    dates = pd.bdate_range("2026-01-01", periods=n)
    return pd.DataFrame({
        "SPY": [500.0 + i for i in range(n)],
        "GDXD": [23.0 + i / 10 for i in range(n)],
    }, index=dates)


class SimulationOnlyPerformanceTests(unittest.TestCase):
    def test_metrics_are_bounded_and_no_sharpe_on_tiny_or_constant_sample(self):
        data = summarize_returns([0.1, -0.2, 0.0, 0.1])
        self.assertEqual(data["observations"], 4)
        self.assertEqual(data["positive_days"], 2)
        self.assertEqual(data["negative_days"], 1)
        self.assertEqual(data["flat_days"], 1)
        self.assertEqual(data["max_drawdown_pct"], 20.0)
        self.assertIsNone(data["sharpe_zero_riskfree"])
        self.assertEqual(data["daily_gain_loss_ratio"], 1.0)
        self.assertIsNone(summarize_returns([0.01] * 35)["sharpe_zero_riskfree"])
        self.assertIsNone(summarize_returns([0.01] * 35)["daily_gain_loss_ratio"])

    def test_invalid_price_matrix_fails_closed(self):
        d = prices()
        bad = d.copy()
        bad.iloc[1, 0] = float("nan")
        for entry in (bad, d.iloc[::-1], d.iloc[:4], d.reset_index(drop=True),
                      d.rename(columns={"SPY": ""}), d.iloc[:, [0, 0]]):
            with self.subTest(reason=str(entry.shape)):
                with self.assertRaises(ValueError):
                    validated_prices(entry)

    def test_holdout_produces_same_boundaries_for_original_compliant_and_spy(self):
        matrix = prices(120)
        dates = matrix.index[11:110]
        # Stub the existing pricing strategy replay; this exercises strict
        # summary/holdout accounting without relying on a profitable pattern.
        simulated = pd.DataFrame({
            "date": [str(x.date()) for x in dates],
            "original": [1.0002 ** (i + 1) for i in range(len(dates))],
            "compliant": [1.0001 ** (i + 1) for i in range(len(dates))],
        })
        with patch("research.performance_audit.run", return_value=simulated) as run:
            result = evaluate_fixed_rule_holdout(
                matrix, dates[0], dates[50], cost_bps=8)
        run.assert_called_once()
        self.assertIn("SIMULATION_ONLY", result["status"])
        self.assertEqual(result["train_days"], 50)
        self.assertEqual(result["holdout_days"], len(dates) - 50)
        self.assertEqual(result["cost_bps_per_turnover_unit"], 8.0)
        self.assertFalse(result.get("broker_connected", False))
        for strategy in ("original", "compliant", "SPY_buy_and_hold"):
            score = result["metrics"][strategy]
            self.assertEqual(score["pre_holdout"]["observations"], 50)
            self.assertEqual(score["holdout"]["observations"], len(dates)-50)
        self.assertGreater(result["metrics"]["original"]["holdout"]["cumulative_return_pct"], 0)

    def test_invalid_holdout_and_cost_never_fake_performance(self):
        for count in (35, 65):
            # 35 fails minimum sample in prices; 65 is below min 80.
            with self.assertRaises(ValueError):
                evaluate_fixed_rule_holdout(prices(count), "2026-01-10", "2026-04-01")
        with self.assertRaises(ValueError):
            evaluate_fixed_rule_holdout(prices(), "2026-03-01", "2026-02-01")
        with self.assertRaises(ValueError):
            evaluate_fixed_rule_holdout(prices(), "2026-02-01", "2026-04-01", cost_bps=-0.1)
        with self.assertRaisesRegex(ValueError, "SPY"):
            evaluate_fixed_rule_holdout(
                prices().drop(columns=["SPY"]), "2026-02-01", "2026-04-01")
        for returns in ([], [-1.1, 0.1], [float("nan")]):
            with self.assertRaises(ValueError):
                summarize_returns(returns)

    def test_cli_missing_data_does_not_create_fabricated_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "unavailable.csv")
            output = Path(tmp) / "metrics.json"
            with self.assertRaises(SystemExit):
                main(["--prices", missing, "--start", "2026-02-01",
                      "--holdout", "2026-04-01", "--output", str(output)])
            self.assertFalse(output.exists())

    def test_actual_strategy_replay_never_exposes_future_bars_to_signals(self):
        # Evaluator receives price history only through signal day t.
        # The t-to-t+1 close is used strictly for simulated returns.
        import backtest
        small = prices(5)
        with patch.object(backtest, "load_strategy", return_value="synthetic"), \
             patch.object(backtest, "Evaluator") as evaluator, \
             patch.object(backtest, "compliant_targets", side_effect=lambda x: x):
            evaluator.return_value.evaluate.return_value = {"SPY": 1.0}
            result = backtest.run(small, start=small.index[0], cost_bps=0)
        self.assertEqual(len(result), 4)
        self.assertEqual([len(call.args[1]) for call in evaluator.call_args_list],
                         [1, 2, 3, 4])
        self.assertEqual(result["original"].iloc[-1],
                         small["SPY"].iloc[-1] / small["SPY"].iloc[0])


if __name__ == "__main__":
    unittest.main()
