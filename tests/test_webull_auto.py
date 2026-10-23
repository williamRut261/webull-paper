"""Mock-only Webull paper-automation tests: NO network or broker orders."""
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pandas as pd
from strategy_engine import load_strategy, signal_symbols
import webull_paper.paper_orders as paper
from zoneinfo import ZoneInfo

import webull_paper.automatic as bot
from webull_paper.paper_orders import collect_snapshots

NY = ZoneInfo("America/New_York")


def ok(data):
    return NS(status_code=200, json=lambda: data)


class PaperAutomationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 13, 15, 49, tzinfo=NY)
        clock_patch = patch.object(paper, "datetime", wraps=datetime)
        self.paper_clock = clock_patch.start()
        self.paper_clock.now.return_value = self.now
        self.addCleanup(clock_patch.stop)

    def test_strict_sandbox_owner_flag_and_account_index(self):
        env = {
            "WEBULL_PAPER_EXECUTE_ENABLED": "true",
            "WEBULL_PAPER_ACCOUNT_INDEX": "0",
            "WEBULL_PAPER_APP_KEY": "test-sandbox-key",
            "WEBULL_PAPER_APP_SECRET": "test-sandbox-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            bot.assert_paper_environment()
            os.environ["WEBULL_PAPER_ACCOUNT_INDEX"] = "1"
            with self.assertRaisesRegex(RuntimeError, "index 0"):
                bot.assert_paper_environment()
            os.environ["WEBULL_PAPER_ACCOUNT_INDEX"] = "0"
            os.environ["WEBULL_PAPER_EXECUTE_ENABLED"] = "false"
            with self.assertRaisesRegex(RuntimeError, "not activated"):
                bot.assert_paper_environment()

    def test_pinned_cash_account_only_among_multiple_sandbox_accounts(self):
        import hashlib
        from unittest.mock import patch
        selected = {"account_id": "sandbox-account-0", "account_type": "CASH"}
        other = {"account_id": "sandbox-account-1", "account_type": "CASH"}
        fingerprint = hashlib.sha256(b"sandbox-account-0").hexdigest()
        with patch.object(bot, "PINNED_SANDBOX_CASH_SHA256", fingerprint):
            self.assertTrue(bot.selected_account_matches_pin(
                "sandbox-account-0", [selected, other], 0))
            self.assertFalse(bot.selected_account_matches_pin(
                "sandbox-account-1", [other, selected], 0))
            self.assertFalse(bot.selected_account_matches_pin(
                "sandbox-account-0", [selected, other], 1))
            self.assertFalse(bot.selected_account_matches_pin(
                "sandbox-account-0", [{"account_id": "sandbox-account-0",
                                       "account_type": "MARGIN"}], 0))

    def test_cannot_place_after_1555(self):
        with patch.object(bot, "datetime") as time_clock:
            time_clock.now.return_value = self.now.replace(minute=55)
            with self.assertRaisesRegex(RuntimeError, "restricted|Too late"):
                bot.close_window(time_clock.now())

    def test_history_guard_blocks_existing_open_orders(self):
        api = Mock()
        api.get_order_open.return_value = ok({"data": [{"client_order_id": "other"}]})
        with self.assertRaisesRegex(RuntimeError, "Existing paper orders"):
            bot.history_guard(api, "paper-test-account", "2026-10-13")
        api.get_order_history.assert_not_called()

    def test_history_guard_blocks_duplicate_broker_orders(self):
        api = Mock()
        api.get_order_open.return_value = ok({"data": []})
        api.get_order_history.return_value = ok({"data": [
            {"client_order_id": "bt20261013B01GDXD"}]})
        with self.assertRaisesRegex(RuntimeError, "already has strategy"):
            bot.history_guard(api, "paper-test-account", "2026-10-13")

    def test_history_guard_refuses_paginated_or_unknown_records(self):
        api = Mock()
        api.get_order_open.return_value = ok({"data": []})
        api.get_order_history.return_value = ok({
            "data": [], "pagination_key": "next-page"})
        with self.assertRaisesRegex(RuntimeError, "pagination"):
            bot.history_guard(api, "paper-test-account", "2026-10-13")
        api.get_order_history.return_value = ok({"ok": True})
        with self.assertRaisesRegex(RuntimeError, "Unexpected"):
            bot.history_guard(api, "paper-test-account", "2026-10-13")

    def test_delayed_sandbox_quotes_accepted_but_old_quotes_rejected(self):
        data = Mock()
        row = {
            "symbol": "GDXD", "price": 20.0, "pre_close": 19.0,
            "last_trade_time": int((self.now - timedelta(minutes=16)).timestamp() * 1000),
        }
        data.market_data.get_snapshot.return_value = ok([row])
        prices, previous = collect_snapshots(data, ["GDXD"], self.now, True)
        self.assertEqual(prices["GDXD"], 20.)
        self.assertEqual(previous["GDXD"], 19.)
        row["last_trade_time"] = int(
            (self.now - timedelta(minutes=25)).timestamp() * 1000)
        with self.assertRaisesRegex(RuntimeError, "Stale"):
            collect_snapshots(data, ["GDXD"], self.now, True)

    def synthetic_signal_quotes(self, stale_symbols=(), omitted_symbols=()):
        """Full strategy tree; GDXU rises and selects GDXD; no network."""
        root = load_strategy()
        symbols = sorted(signal_symbols(root))
        dates = paper.completed_sessions(pd.Timestamp("2026-07-01"), self.now.date())[-50:]
        history = pd.DataFrame({
            symbol: [100.0 + i for i in range(len(dates))]
            for symbol in symbols
        }, index=dates)
        data = Mock()
        def get_snapshot(symbols, category):
            records = []
            for symbol in symbols:
                if symbol in omitted_symbols:
                    continue
                age = 35 if symbol in stale_symbols else 16
                records.append({
                    "symbol": symbol, "price": 150.0, "pre_close": 149.0,
                    "last_trade_time": int((
                        self.now - timedelta(minutes=age)).timestamp() * 1000)
                })
            return ok(records)
        data.market_data.get_snapshot.side_effect = get_snapshot
        return root, data, history

    def test_unused_stale_agq_does_not_block_original_strategy_signal(self):
        root, data, history = self.synthetic_signal_quotes(stale_symbols={"AGQ"})
        with patch.object(paper, "assemble_history", return_value=history):
            targets, quotes = paper.targets_for_now(
                data, root, self.now, execute=True)
        self.assertEqual(targets, {"GDXD": .99})
        self.assertNotIn("AGQ", quotes)
        self.assertIn("GDXD", quotes)

    def test_missing_unused_snapshot_does_not_invent_a_price(self):
        root, data, history = self.synthetic_signal_quotes(omitted_symbols={"AGQ"})
        with patch.object(paper, "assemble_history", return_value=history):
            targets, quotes = paper.targets_for_now(
                data, root, self.now, execute=True)
        self.assertEqual(targets, {"GDXD": .99})
        self.assertNotIn("AGQ", quotes)

    def test_stale_required_gdxu_signal_still_aborts(self):
        root, data, history = self.synthetic_signal_quotes(stale_symbols={"GDXU"})
        with patch.object(paper, "assemble_history", return_value=history):
            with self.assertRaisesRegex(ValueError, "missing or invalid price"):
                paper.targets_for_now(data, root, self.now, execute=True)

    def test_stale_selected_gdxd_order_quote_still_aborts(self):
        root, data, history = self.synthetic_signal_quotes(stale_symbols={"GDXD"})
        with patch.object(paper, "assemble_history", return_value=history):
            with self.assertRaisesRegex(RuntimeError, "No fresh Webull order quote"):
                paper.targets_for_now(data, root, self.now, execute=True)

    def test_stale_rejected_in_default_strict_mode(self):
        data = Mock()
        data.market_data.get_snapshot.return_value = ok([{
            "symbol": "AGQ", "price": 12.0, "pre_close": 11.0,
            "last_trade_time": int((self.now - timedelta(minutes=35)).timestamp() * 1000),
        }])
        with self.assertRaisesRegex(RuntimeError, "Stale"):
            collect_snapshots(data, ["AGQ"], self.now, True)

    def test_duplicates_still_fail_even_if_first_record_stale(self):
        data = Mock()
        data.market_data.get_snapshot.return_value = ok([
            {"symbol": "AGQ", "price": 12.0, "pre_close": 11.0,
             "last_trade_time": int((
                 self.now - timedelta(minutes=35)).timestamp() * 1000)},
            {"symbol": "AGQ", "price": 12.0, "pre_close": 11.0,
             "last_trade_time": int((
                 self.now - timedelta(minutes=16)).timestamp() * 1000)},
        ])
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            collect_snapshots(
                data, ["AGQ"], self.now, True, allow_unused_stale=True)


    def test_two_webull_samples_must_agree_before_any_paper_orders(self):
        samples = [
            ({"GDXD": .99}, {"GDXD": 20.}),
            ({"GDXU": .99}, {"GDXU": 85.}),
        ]
        with patch.object(bot, "targets_for_now", side_effect=samples) as evaluate, \
             patch.object(bot, "datetime") as clock, \
             patch.object(bot.time, "sleep") as sleep, \
             patch.object(bot, "make_orders") as submit:
            clock.now.return_value = self.now
            with self.assertRaisesRegex(RuntimeError, "allocation disagreement"):
                bot.confirmed_signal(Mock(), Mock(), self.now)
        self.assertEqual(evaluate.call_count, 2)
        sleep.assert_called_once_with(3)
        submit.assert_not_called()

    def test_agreeing_webull_samples_keep_second_validated_prices(self):
        samples = [
            ({"GDXU": .99}, {"GDXU": 85.}),
            ({"GDXU": .99}, {"GDXU": 86.}),
        ]
        with patch.object(bot, "targets_for_now", side_effect=samples), \
             patch.object(bot, "datetime") as clock, \
             patch.object(bot.time, "sleep") as sleep:
            clock.now.return_value = self.now
            targets, quotes = bot.confirmed_signal(Mock(), Mock(), self.now)
        self.assertEqual(targets, {"GDXU": .99})
        self.assertEqual(quotes, {"GDXU": 86.})
        sleep.assert_called_once_with(3)

    def test_unsafe_second_sample_price_fails_closed(self):
        samples = [
            ({"GDXD": .99}, {"GDXD": 20.}),
            ({"GDXD": .99}, {"GDXD": 24.}),
        ]
        with patch.object(bot, "targets_for_now", side_effect=samples), \
             patch.object(bot, "datetime") as clock, \
             patch.object(bot.time, "sleep"):
            clock.now.return_value = self.now
            with self.assertRaisesRegex(RuntimeError, "moved >10%"):
                bot.confirmed_signal(Mock(), Mock(), self.now)

    def test_two_sample_stops_if_window_closes_between_snapshots(self):
        samples = [
            ({"GDXU": .99}, {"GDXU": 85.}),
            ({"GDXU": .99}, {"GDXU": 86.}),
        ]
        with patch.object(bot, "targets_for_now", side_effect=samples) as evaluate, \
             patch.object(bot, "datetime") as clock, \
             patch.object(bot.time, "sleep"):
            clock.now.side_effect = [self.now, self.now.replace(minute=55)]
            with self.assertRaisesRegex(RuntimeError, "restricted|Too late"):
                bot.confirmed_signal(Mock(), Mock(), self.now)
        evaluate.assert_called_once()

    def test_fill_waits_for_verified_detail_and_rejects_partial(self):
        api = Mock()
        api.order_v3.get_order_detail.return_value = ok({
            "orders": [{"client_order_id": "paperid",
                        "status": "FILLED", "filled_quantity": "1.0"}]})
        bot.wait_for_full_fill(api, "sandbox", "paperid", 1.)
        api.order_v3.get_order_detail.return_value = ok({
            "orders": [{"client_order_id": "paperid",
                        "status": "FILLED", "filled_quantity": "0.1"}]})
        with self.assertRaisesRegex(RuntimeError, "partial"):
            bot.wait_for_full_fill(api, "sandbox", "paperid", 1.)

    def test_rejected_preview_never_places_order(self):
        trade = Mock()
        trade.order_v3.preview_order.return_value = ok({"error": "unsupported"})
        # Valid HTTP 200 is necessary but not enough: unknown nested errors fail.
        # A HTTP 417 will reliably block placement.
        trade.order_v3.preview_order.return_value = NS(status_code=417, json=lambda: {})
        with patch.object(bot, "datetime") as clock:
            clock.now.return_value = self.now
            with self.assertRaisesRegex(RuntimeError, "preview"):
                bot.preview_and_place(trade, "sandbox", {
                    "client_order_id": "paperid", "symbol": "GDXD",
                    "side": "BUY", "quantity": "1"})
        trade.order_v3.place_order.assert_not_called()

    def test_webull_sandbox_fractional_orders_never_exceed_five_digits(self):
        """Webull returned HTTP 417 OPENAPI_FRACT_QTY_SCALE_LESS_5 in
        original Beethoven paper workflow on Oct 22, 2026.
        """
        from decimal import Decimal
        for side in ("BUY", "SELL"):
            payload = paper.order_payload(
                "GDXD", side, 12.345678, 100., "2026-10-23", 1)
            quantity = payload["quantity"]
            self.assertEqual(quantity, "0.12345")
            self.assertLessEqual(-Decimal(quantity).as_tuple().exponent, 5)
            self.assertLessEqual(Decimal(quantity) * Decimal(100), Decimal("12.345678"))
            self.assertEqual(payload["entrust_type"], "QTY")
        # Whole-share orders must remain whole numbers with no decimal dot.
        self.assertEqual(
            paper.order_payload("GDXD", "BUY", 235.85, 100., "2026-10-23", 2)["quantity"],
            "2")
        # A fractional order that rounds below Webull's $5 minimum must
        # fail closed rather than silently submit an under-minimum ticket.
        with self.assertRaisesRegex(RuntimeError, "below Webull"):
            paper.order_payload("GDXD", "BUY", 5.00001, 9999., "2026-10-23", 3)

    def test_buy_sizing_preserves_cash_and_broker_limit(self):
        trade = Mock()
        snapshot = (5000.0, 5000.0, {})
        quotes = paper.SnapshotPrices()
        quotes["GDXD"] = 20.
        quotes.trade_times["GDXD"] = self.now
        with patch.object(bot, "checked_portfolio", return_value=snapshot), \
             patch.object(bot, "preview_and_place") as submit, \
             patch.object(bot, "reconcile_order_fill", return_value=snapshot), \
             patch.object(bot, "datetime") as clock:
            clock.now.return_value = self.now
            count = bot.make_orders(trade, "sandbox", {"GDXD": .99},
                                    quotes, "2026-10-13")
        self.assertEqual(count, 1)
        payload = submit.call_args.args[2]
        self.assertEqual(payload["symbol"], "GDXD")
        self.assertEqual(payload["side"], "BUY")
        self.assertLessEqual(float(payload["quantity"]) * 20. * 1.02, 4950.)

    def test_no_buy_without_verified_quote(self):
        trade = Mock()
        with patch.object(bot, "checked_portfolio",
                          return_value=(5000.0, 5000.0, {})), \
             patch.object(bot, "preview_and_place") as submit, \
             patch.object(bot, "datetime") as clock:
            clock.now.return_value = self.now
            with self.assertRaisesRegex(RuntimeError, "No verified"):
                bot.make_orders(trade, "sandbox", {"GDXD": .99},
                                {}, "2026-10-13")
        submit.assert_not_called()

    def test_claim_is_exclusive(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(bot, "STATE_DIR", Path(tmp)):
            bot.claim_day("2026-10-13")
            with self.assertRaises(FileExistsError):
                bot.claim_day("2026-10-13")
            self.assertTrue((Path(tmp) / "2026-10-13.json").exists())

    def test_schedule_is_exclusively_paper(self):
        data = Path(".github/workflows/webull-auto-execute.yml").read_text()
        self.assertIn("WEBULL_PAPER_EXECUTE_ENABLED: \"true\"", data)
        self.assertIn("webull_paper.automatic", data)
        self.assertNotIn("ALPACA_LIVE", data)
        self.assertIn("webull-public-paper-v1", data)
        # Stage 50 minutes early, preserving the near-close decision.
        self.assertIn('cron: "58 14 * * 1-5"', data)
        self.assertIn('timeout-minutes: 120', data)
        self.assertIn("if: github.event_name == 'schedule'", data)
        self.assertIn('api.sandbox.webull.com', Path('webull_paper/automatic.py').read_text())
        self.assertNotIn('api.webull.com', Path('webull_paper/automatic.py').read_text())

    def test_missed_market_window_is_fatal_not_green_noop(self):
        # Oct. 13 actual 16:08 ET GitHub start used to silently exit 0.
        with patch.object(bot, "assert_paper_environment"), \
             patch.object(bot, "datetime") as clock:
            clock.now.return_value = self.now.replace(hour=16, minute=8)
            with self.assertRaisesRegex(RuntimeError, "PAPER_MISSED_WINDOW"):
                bot.main()

    def test_early_stage_still_defers_until_signal_time(self):
        for hour, minute, expected_seconds in ((13, 8, 9601), (14, 8, 6001), (14, 58, 3001), (15, 8, 2401)):
            with self.subTest(hour=hour), \
                 patch.object(bot, "assert_paper_environment"), \
                 patch.object(bot, "datetime") as clock, \
                 patch.object(bot.time, "sleep",
                              side_effect=RuntimeError("SLEPT")) as sleep:
                clock.now.return_value = self.now.replace(hour=hour, minute=minute)
                with self.assertRaisesRegex(RuntimeError, "SLEPT"):
                    bot.main()
                sleep.assert_called_once()
                # Stage at multiple times (including new 14:58) -> 15:48:01 ET.
                self.assertEqual(sleep.call_args.args[0], expected_seconds)

    def test_start_before_staging_window_rejected(self):
        with patch.object(bot, "assert_paper_environment"), \
             patch.object(bot, "datetime") as clock, \
             patch.object(bot.time, "sleep") as sleep:
            clock.now.return_value = self.now.replace(hour=12, minute=59)
            with self.assertRaisesRegex(RuntimeError, "PAPER_MISSED_WINDOW"):
                bot.main()
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
