"""Offline safety tests: no model calls, public data requests, or broker access."""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.ai_desk import ROLES, main, make_snapshot, rsi, safe_report, summarise_bars, run_agents


def bars(length=90, days_ago=1):
    start = datetime.now(timezone.utc) - timedelta(days=length + days_ago - 1)
    return [(int((start + timedelta(days=i)).timestamp()), 20+i*.12)
            for i in range(length)]


def opinions():
    return {role: {"symbol": "GDXD", "action": "BUY", "confidence": .9,
                   "rationale": "Synthetic research only", "evidence": ["synthetic"],
                   "risks": ["leveraged instrument"]} for role in ROLES}


class AgentDeskSafetyTests(unittest.TestCase):
    def test_seven_specialists(self):
        self.assertEqual(len(ROLES), 7)
        self.assertEqual(len(set(ROLES)), 7)

    def test_seven_agent_end_to_end_chain_runs_in_order_without_broker(self):
        order = []
        def pretend_model(provider, model, instruction, prompt):
            request = json.loads(prompt)
            role = request["role"]
            self.assertEqual(role, ROLES[len(order)])
            self.assertEqual(len(request["earlier_opinions"]), len(order))
            order.append(role)
            return opinions()[role], {"input_tokens": 10, "output_tokens": 5}
        snapshot = {"quotes": {"GDXD": {"close": 25, "as_of": "2026-10-22"}}}
        result = run_agents(snapshot, "offline-model", requester=pretend_model)
        self.assertEqual(tuple(order), ROLES)
        self.assertEqual(result["status"], "RESEARCH_ONLY")
        self.assertEqual(result["consensus"], "HYPOTHESIS_FOR_BACKTEST")
        self.assertEqual(result["token_usage"]["input_tokens"], 70)
        self.assertEqual(result["actual_order_count"], 0)
        self.assertFalse(result["broker_connected"])

    def test_rsi_bounds_and_flat_line(self):
        self.assertEqual(rsi(list(range(1, 30))), 100.)
        self.assertEqual(rsi([3]*30), 50.)

    def test_daily_bar_indicators(self):
        signal = summarise_bars(bars())
        self.assertGreater(signal["sma20"], 0)
        self.assertTrue(0 <= signal["rsi14"] <= 100)

    def test_stale_or_insufficient_quotes_fail_closed(self):
        for b in (bars(20), bars(90, 12)):
            with self.assertRaises(ValueError):
                summarise_bars(b)

    def test_market_data_error_is_visible_not_fabricated(self):
        def unavailable(_):
            raise TimeoutError("Public provider down")
        snapshot = make_snapshot(symbols=("GDXD",), loader=unavailable)
        self.assertFalse(snapshot["quotes"])
        self.assertEqual(snapshot["errors"], {"GDXD": "TimeoutError"})

    def test_consensus_is_hypothetical_never_executable(self):
        report = safe_report({"quotes": {"GDXD": {"close": 15}}}, opinions())
        self.assertEqual(report["consensus"], "HYPOTHESIS_FOR_BACKTEST")
        self.assertEqual(report["actual_order_count"], 0)
        self.assertFalse(report["paper_execution_enabled"])
        self.assertFalse(report["live_execution_enabled"])
        self.assertFalse(report["broker_connected"])

    def test_risk_manager_veto(self):
        views = opinions()
        views["Risk Manager"].update({"symbol": "NONE", "action": "NO_TRADE"})
        report = safe_report({"quotes": {"GDXD": {}}}, views)
        self.assertEqual(report["consensus"], "NO_CONSENSUS")
        self.assertIsNone(report["hypothesis"])

    def test_malformed_and_unknown_symbol_rejected(self):
        for replacement in ({"symbol": "TSLA"}, {"confidence": math.nan},
                            {"confidence": 3}, {"action": "EXECUTE"},
                            {"symbol": "NONE", "action": "BUY"}):
            views = opinions()
            views["Desk Lead"].update(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                safe_report({"quotes": {"GDXD": {}}}, views)

    def test_missing_agent_fails_closed(self):
        views = opinions()
        del views["Trade Reviewer"]
        with self.assertRaises(ValueError):
            safe_report({"quotes": {"GDXD": {}}}, views)

    def test_smoke_is_clearly_nonlive(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(main(["--out", d, "--smoke"]), 0)
            result = json.loads((Path(d)/"report.json").read_text())
            self.assertEqual(result["status"], "SMOKE_TEST_ONLY")
            self.assertEqual(result["actual_order_count"], 0)

    def test_missing_key_causes_explicit_error(self):
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            self.assertEqual(main(["--out", d]), 2)
            result = json.loads((Path(d)/"report.json").read_text())
            self.assertEqual(result["status"], "NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main()
