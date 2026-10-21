"""Offline regression tests for the Webull PAPER operational repair. No broker calls."""
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import webull_paper.automatic as bot
from webull_paper.paper_orders import SnapshotPrices

NY = ZoneInfo("America/New_York")


class PaperOperationalFixes(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 21, 15, 49, tzinfo=NY)
        self.quotes = SnapshotPrices()
        self.quotes.update({"GDXD": 50., "SOXS": 20.})
        self.quotes.trade_times.update({"GDXD": self.now, "SOXS": self.now})
        self.quotes.required.update({"GDXD", "SOXS"})

    def test_filled_receipt_must_match_new_position_quantity(self):
        unchanged = (5000., 500., {
            "SOXS": {"qty": 36.4, "value": 728., "price": 20.}})
        with (patch.object(bot, "checked_portfolio", return_value=unchanged),
              patch.object(bot.time, "sleep") as sleeper):
            with self.assertRaisesRegex(RuntimeError, "did not reconcile"):
                bot.reconcile_order_fill(
                    Mock(), "paper", "SOXS", "SELL", 36.4, 36.)
        self.assertEqual(sleeper.call_count, 5)

    def test_reported_fill_reconciles_after_broker_position_lag(self):
        previous = (5000., 500., {
            "SOXS": {"qty": 36.4, "value": 728., "price": 20.}})
        changed = (5000., 1220., {
            "SOXS": {"qty": .4, "value": 8., "price": 20.}})
        with (patch.object(bot, "checked_portfolio",
                           side_effect=[previous, changed]),
              patch.object(bot.time, "sleep") as sleeper):
            actual = bot.reconcile_order_fill(
                Mock(), "paper", "SOXS", "SELL", 36.4, 36.)
        self.assertEqual(actual, changed)
        sleeper.assert_called_once_with(2)

    def test_eod_non_target_remainder_sells_whole_then_fraction(self):
        state = {
            "holdings": {
                "GDXD": {"qty": 80., "value": 4000., "price": 50.},
                "SOXS": {"qty": 36.4, "value": 728., "price": 20.},
            }, "cash": 272.,
        }
        placed = []

        def snapshot(*_args, **_kwargs):
            return 5000., state["cash"], {
                sym: dict(p) for sym, p in state["holdings"].items()}

        def simulated_fill(_trade, _account, payload, **_kwargs):
            self.assertEqual(payload["side"], "SELL")
            self.assertEqual(payload["symbol"], "SOXS")
            quantity = float(payload["quantity"])
            placed.append(quantity)
            state["cash"] += quantity * 20.
            holding = state["holdings"]["SOXS"]
            holding["qty"] = round(holding["qty"] - quantity, 6)
            holding["value"] = holding["qty"] * 20.
            if holding["qty"] < 1e-6:
                del state["holdings"]["SOXS"]

        with (patch.object(bot, "checked_portfolio", side_effect=snapshot),
              patch.object(bot, "preview_and_place",
                           side_effect=simulated_fill),
              patch.object(bot, "datetime") as clock):
            clock.now.return_value = self.now
            count = bot.make_orders(
                Mock(), "paper", {"GDXD": .80}, self.quotes,
                "2026-10-21", expected_exposure=.80)
        self.assertEqual(count, 2)
        self.assertEqual(placed, [36., .4])
        self.assertNotIn("SOXS", state["holdings"])

    def test_under_five_dollar_non_target_dust_cannot_be_hidden(self):
        holdings = {
            "GDXD": {"qty": 80., "value": 4000., "price": 50.},
            "SOXS": {"qty": .1, "value": 2., "price": 20.}}
        state = (5000., 998., holdings)
        with (patch.object(bot, "checked_portfolio", return_value=state),
              patch.object(bot, "preview_and_place") as submit,
              patch.object(bot, "datetime") as clock,
              redirect_stdout(StringIO()) as output):
            clock.now.return_value = self.now
            count = bot.make_orders(
                Mock(), "paper", {"GDXD": .80}, self.quotes,
                "2026-10-21", expected_exposure=.80)
        self.assertEqual(count, 0)
        self.assertIn("PAPER_NON_TARGET_RESIDUALS", output.getvalue())
        self.assertIn("SOXS", output.getvalue())
        submit.assert_not_called()

    def test_reconciler_never_treats_wrong_direction_as_fill(self):
        wrong = (5000., 500., {
            "SOXS": {"qty": 37.4, "value": 748., "price": 20.}})
        with (patch.object(bot, "checked_portfolio", return_value=wrong),
              patch.object(bot.time, "sleep")):
            with self.assertRaisesRegex(RuntimeError, "did not reconcile"):
                bot.reconcile_order_fill(
                    Mock(), "paper", "SOXS", "SELL", 36.4, 1.)


if __name__ == "__main__":
    unittest.main()
