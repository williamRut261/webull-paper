"""Combined Beethoven + Trader Webull PAPER safety regressions (offline)."""
import json
import os
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from strategy_engine import ORIGINAL_EXECUTION_ASSETS
from trader_combo.universe import (
    CANDIDATES, EXCLUDED, BEETHOVEN_WEIGHT, TRADER_WEIGHT, MAX_TOTAL_EXPOSURE
)
from trader_combo.scan import select_recent_signals
from trader_combo.morning import (
    morning_guard, assert_sandbox, proposed_entries, scanner_history_guard
)
from webull_paper.paper_orders import order_payload, portfolio
from research.beethoven_advisory import build_report

NY = ZoneInfo("America/New_York")


class CombinedPaperTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 10, 21, tzinfo=NY)

    def scanner_doc(self, **kwargs):
        base = {"mode": "orb", "source": "yahoo", "unconfirmed": 0,
                "universe": len(CANDIDATES), "failed": 0,
                "hits": [{"symbol": "XLE", "at": "10:20 AM",
                          "pct_over": 0.7, "or_low": 49.2,
                          "or_high": 49.8, "price": 50.15}]}
        base.update(kwargs)
        return base

    def test_scanner_covers_other_stocks_and_etfs_but_not_beethoven(self):
        self.assertGreater(len(CANDIDATES), 70)
        self.assertIn("XLE", CANDIDATES)  # energy ETF
        self.assertIn("ADBE", CANDIDATES)  # stock
        self.assertFalse(CANDIDATES & EXCLUDED)
        self.assertFalse(CANDIDATES & ORIGINAL_EXECUTION_ASSETS)
        self.assertAlmostEqual(BEETHOVEN_WEIGHT + TRADER_WEIGHT, MAX_TOTAL_EXPOSURE)

    def test_original_scanner_result_must_be_recent_and_confirmed(self):
        result = select_recent_signals(self.scanner_doc(), self.now)
        self.assertEqual(result[0]["symbol"], "XLE")
        self.assertEqual(len(result), 1)
        for report in (self.scanner_doc(unconfirmed=1),
                       self.scanner_doc(source="unknown"),
                       self.scanner_doc(universe=1)):
            with self.subTest(report=report):
                with self.assertRaises(RuntimeError):
                    select_recent_signals(report, self.now)
        future = self.scanner_doc(hits=[dict(self.scanner_doc()["hits"][0], at="10:30 AM")])
        self.assertEqual(select_recent_signals(future, self.now), [])

    def test_no_old_opening_range_signal_will_execute(self):
        old = self.scanner_doc(hits=[dict(self.scanner_doc()["hits"][0], at="9:50 AM")])
        self.assertEqual(select_recent_signals(old, self.now), [])

    def test_morning_regular_session_gate(self):
        self.assertTrue(morning_guard(self.now))
        for hour, minute in ((10, 19), (10, 40), (15, 48)):
            with self.subTest(hour=hour, minute=minute):
                with self.assertRaises(RuntimeError):
                    morning_guard(self.now.replace(hour=hour, minute=minute))
        with self.assertRaises(RuntimeError):
            morning_guard(self.now + timedelta(days=4))  # Saturday

    def test_sandbox_gate_never_allows_other_account_or_unenabled(self):
        good = {"WEBULL_PAPER_EXECUTE_ENABLED": "true",
                "WEBULL_TRADER_PAPER_ENABLED": "true",
                "WEBULL_PAPER_ACCOUNT_INDEX": "0",
                "WEBULL_PAPER_APP_KEY": "synthetic-paper-key",
                "WEBULL_PAPER_APP_SECRET": "synthetic-paper-secret"}
        with patch("trader_combo.morning.PINNED_SANDBOX_CASH_SHA256", "fake-pin"):
            with patch.dict(os.environ, good, clear=True):
                assert_sandbox()
                os.environ["WEBULL_PAPER_ACCOUNT_INDEX"] = "1"
                with self.assertRaises(RuntimeError):
                    assert_sandbox()
                os.environ["WEBULL_PAPER_ACCOUNT_INDEX"] = "0"
                os.environ["WEBULL_TRADER_PAPER_ENABLED"] = "false"
                with self.assertRaises(RuntimeError):
                    assert_sandbox()

    def test_cannot_start_scanner_while_beethoven_at_99pct(self):
        holding = {"GDXD": {"value": 4950, "qty": 100}}
        signal = self.scanner_doc()["hits"][0]
        input_signal = {"symbol": signal["symbol"], "signal_price": signal["price"],
                        "range_low": signal["or_low"], "range_high": signal["or_high"]}
        with self.assertRaisesRegex(RuntimeError, "legacy 99%"):
            proposed_entries([input_signal], 5000, 50, holding, {"XLE": 50.15})

    def test_scanner_buys_at_most_19pct_and_caps_risk(self):
        input_signal = {"symbol": "XLE", "signal_price": 50.15,
                        "range_low": 49.2, "range_high": 49.8}
        holding = {"GDXD": {"value": 4000, "qty": 100}}
        result = proposed_entries([input_signal], 5000, 1000, holding, {"XLE": 50.15})
        self.assertEqual(len(result), 1)
        self.assertLessEqual(result[0]["gross_reserved"], 950)
        self.assertLessEqual(result[0]["estimated_loss_at_stop"], 15)
        self.assertGreater(result[0]["shares"], 0)
        self.assertLess(result[0]["stop_reference"], result[0]["price"])
        self.assertGreater(result[0]["target_reference"], result[0]["price"])

    def test_missing_or_invalid_execution_quote_is_rejected(self):
        s = {"symbol": "XLE", "signal_price": 50.15,
             "range_low": 49.2, "range_high": 49.8}
        h = {"GDXD": {"value": 4000, "qty": 100}}
        with self.assertRaisesRegex(RuntimeError, "execution quote"):
            proposed_entries([s], 5000, 1000, h, {})
        self.assertEqual(proposed_entries([s], 5000, 1000, h, {"XLE": 53.}), [])

    def test_base_order_payload_rejects_scanner_without_explicit_allowlist(self):
        with self.assertRaises(RuntimeError):
            order_payload("XLE", "BUY", 200, 50, "2026-10-20", 1)
        entry = order_payload("XLE", "BUY", 200, 50, "2026-10-20", 1,
                              allowed_extra=CANDIDATES)
        self.assertEqual(entry["quantity"], "4")
        self.assertEqual(entry["symbol"], "XLE")

    def test_combined_advisory_identifies_eighty_percent_sleeve(self):
        log = 'PAPER_COMBINED_ALLOCATION ' + json.dumps({
            "beethoven_weight": .80, "scanner_weight": .19}) + "\n"
        log += 'PAPER_AUTO_SIGNAL ' + json.dumps({
            "paper_only": True, "date": "2026-10-20",
            "targets": {"GDXD": .80}})
        report = build_report(log)
        self.assertEqual(report["status"], "PAPER_LOG_SIGNAL_ONLY")
        self.assertEqual(report["beethoven_allocation"], 0.80)
        self.assertEqual(report["trader_allocation"], 0.19)

    def test_workflows_are_sandbox_only_not_manual_execution(self):
        from pathlib import Path
        base = Path(__file__).resolve().parents[1] / ".github/workflows"
        open_workflow = (base / "trader-paper-automatic.yml").read_text()
        close_workflow = (base / "webull-auto-execute.yml").read_text()
        self.assertIn("github.event_name == 'schedule'", open_workflow)
        self.assertIn("api.sandbox.webull.com", __import__("trader_combo.morning", fromlist=["SANDBOX"]).SANDBOX)
        self.assertIn("WEBULL_TRADER_PAPER_ENABLED:", open_workflow)
        self.assertIn("WEBULL_TRADER_PAPER_ENABLED:", close_workflow)
        self.assertIn("group: webull-paper-order", open_workflow)
        self.assertIn("group: webull-paper-order", close_workflow)


if __name__ == "__main__":
    import unittest
    unittest.main()
