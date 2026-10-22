"""Offline test: paper cutover is blocked without an exclusive reconciler."""
from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

from research.portfolio_lab.portfolio import PortfolioError, combine
from webull_paper.four_strategy_cutover import stage_cutover, BUDGETS

NY = ZoneInfo("America/New_York")


def example_plan():
    inputs = {"beethoven": {"QQQ": .6, "TLT": .4},
              "inout": {"QQQ": 1.},
              "rsi_trend": {"QQQ": .75, "GLD": .25},
              "claude_orb": {"XLE": .5}}
    result = combine(BUDGETS, inputs, cash_reserve=0,
                     max_symbol_weight=1).to_dict()
    result["portfolio_mode"] = "RESEARCH_ONLY_NOT_BROKER_ORDERS"
    result["independent_sleeve_budgets"] = BUDGETS
    result["sleeve_targets_within_own_capital"] = inputs
    return result


class PaperCutoverTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 21, 10, 22, tzinfo=NY)
        self.plan = example_plan()
        self.quotes = {k: {"price": 50.0, "trade_at": self.now.isoformat()}
                       for k in self.plan["target_weights"]}

    def test_cash_floor_and_independent_25pct_cap(self):
        result = stage_cutover(self.plan, self.quotes, self.now)
        self.assertEqual(result.reserve_floor, .01)
        self.assertLessEqual(sum(result.sandbox_draft_targets.values()), .99 + 1e-9)
        self.assertAlmostEqual(result.sandbox_draft_targets["XLE"], .12375)
        self.assertFalse(result.deployment_allowed)
        self.assertTrue(any("Legacy" in x for x in result.blockers))

    def test_no_false_activation_even_with_all_flags(self):
        proposed = stage_cutover(self.plan, self.quotes, self.now,
                                 legacy_runner_disabled=True,
                                 scanner_runner_disabled=True,
                                 pinned_cash_account_verified=True,
                                 broker_flat_verified=True,
                                 no_open_orders_verified=True)
        self.assertFalse(proposed.deployment_allowed)
        self.assertTrue(any("reconciler" in x for x in proposed.blockers))

    def test_missing_quote_and_mismatched_sleeve_fail_closed(self):
        with self.assertRaisesRegex(PortfolioError, "Missing Webull snapshot"):
            stage_cutover(self.plan, {}, self.now)
        old = self.plan["independent_sleeve_budgets"]
        self.plan["independent_sleeve_budgets"] = {**old, "beethoven": .8}
        with self.assertRaisesRegex(PortfolioError, "four 25"):
            stage_cutover(self.plan, self.quotes, self.now)

    def test_stale_quote_and_unknown_symbol_fail_closed(self):
        broken = dict(self.quotes)
        broken["QQQ"] = {"price": 50.0,
                         "trade_at": (self.now - timedelta(minutes=3)).isoformat()}
        with self.assertRaisesRegex(PortfolioError, "Stale"):
            stage_cutover(self.plan, broken, self.now)
        bad = example_plan()
        bad["sleeve_targets_within_own_capital"]["rsi_trend"] = {"BADSYMB0":1}
        with self.assertRaisesRegex(PortfolioError, "Unreviewed"):
            stage_cutover(bad, self.quotes, self.now)


if __name__ == "__main__":
    unittest.main()
