"""Offline tests for automatic AI authorization of EXISTING sandbox ORB orders.

No model calls, broker calls, or Webull credentials are involved.
"""
from datetime import date
import json
import os
import unittest
from unittest.mock import patch

from research.ai_desk import ROLES
from trader_combo.agent_gate import evaluate_agent_gate, fetch_agent_gate


def packet(day="2026-10-22", symbol="SPY", action="BUY", confidence=.8):
    return {
        "schema": 1, "status": "RESEARCH_ONLY", "provider": "gemini",
        "actual_broker_orders_from_agents": 0,
        "as_of": day, "consensus": "HYPOTHESIS_FOR_BACKTEST",
        "hypothesis": {"symbol": symbol, "action": action},
        "agents": [{"role": role, "symbol": symbol, "action": action,
                    "confidence": confidence} for role in ROLES]
    }


class AgentBrokerGateTests(unittest.TestCase):
    TRADE_DAY = date(2026, 10, 23)

    def test_full_risk_on_consensus_only_approves_existing_orb_scanner(self):
        self.assertEqual(evaluate_agent_gate(packet(), self.TRADE_DAY),
                         {"approved": True, "reason": "AI_RISK_ON_APPROVED"})

    def test_risk_manager_veto_and_independent_reviewer_block(self):
        for i in (4, 5):
            x = packet()
            x["agents"][i]["action"] = "NO_TRADE"
            self.assertFalse(evaluate_agent_gate(x, self.TRADE_DAY)["approved"])
        for action in ("SELL", "NO_TRADE"):
            x = packet()
            x["agents"][6]["action"] = action
            self.assertFalse(evaluate_agent_gate(x, self.TRADE_DAY)["approved"])

    def test_holding_and_inverse_etf_buy_do_not_trigger_order_permission(self):
        for sym, action in (("GDXD", "BUY"), ("GDXU", "BUY"),
                            ("GLD", "BUY"), ("SPY", "HOLD"), ("TLT", "SELL")):
            with self.subTest(sym=sym, action=action):
                x = packet(symbol=sym, action=action)
                self.assertFalse(evaluate_agent_gate(x, self.TRADE_DAY)["approved"])

    def test_consensus_label_alone_is_insufficient(self):
        x = packet()
        x["agents"][0]["action"] = "HOLD"
        x["agents"][1]["action"] = "HOLD"
        self.assertFalse(evaluate_agent_gate(x, self.TRADE_DAY)["approved"])
        x = packet()
        x["agents"][4]["confidence"] = .64
        self.assertFalse(evaluate_agent_gate(x, self.TRADE_DAY)["approved"])

    def test_age_skipped_day_and_future_date_are_rejected(self):
        for stamp in ("2026-10-23", "2026-10-24", "2026-10-18", "garbage", None):
            with self.subTest(stamp=stamp):
                x = packet()
                x["as_of"] = stamp
                with self.assertRaises(ValueError):
                    evaluate_agent_gate(x, self.TRADE_DAY)
        self.assertTrue(evaluate_agent_gate(packet(day="2026-10-20"), self.TRADE_DAY)["approved"])

    def test_missing_role_duplicate_agent_and_injected_fills_rejected(self):
        for update in ("role", "duplicate", "confidence", "status", "provider", "broker"):
            x = packet()
            if update == "role":
                x["agents"].pop()
            elif update == "duplicate":
                x["agents"][1]["role"] = x["agents"][0]["role"]
            elif update == "confidence":
                x["agents"][3]["confidence"] = float("nan")
            elif update == "status":
                x["status"] = "FAILED"
            elif update == "provider":
                x["provider"] = "unknown"
            elif update == "broker":
                x["actual_broker_orders_from_agents"] = 1
            with self.subTest(case=update), self.assertRaises(ValueError):
                evaluate_agent_gate(x, self.TRADE_DAY)

    def test_bounded_read_and_invalid_json_fail_closed(self):
        class Response:
            def __init__(self, raw):
                self.raw = raw
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, maximum):
                return self.raw[:maximum]
        def opener(req, timeout):
            self.assertEqual(req.full_url.split("/")[2], "raw.githubusercontent.com")
            self.assertLessEqual(timeout, 10)
            return Response(json.dumps(packet()).encode())
        self.assertTrue(fetch_agent_gate(self.TRADE_DAY, opener=opener)["approved"])
        with self.assertRaises(ValueError):
            fetch_agent_gate(self.TRADE_DAY, opener=lambda *_args, **_kwargs: Response(b"*" * 12001))

    def test_disapproval_stops_before_scanner_or_broker_initialization(self):
        from trader_combo.morning import main
        with patch.dict(os.environ, {"AI_DESK_PAPER_GATE_ENABLED": "true"}):
            with patch("trader_combo.morning.assert_sandbox"), \
                 patch("trader_combo.morning.morning_wait_seconds", return_value=0), \
                 patch("trader_combo.morning.morning_guard"), \
                 patch("trader_combo.agent_gate.fetch_agent_gate",
                       return_value={"approved": False, "reason": "NO_AGENT_APPROVAL"}), \
                 patch("trader_combo.morning.run_scan", side_effect=AssertionError("scan should not run")):
                self.assertEqual(main(), 0)

    def test_approval_is_not_direct_authority_to_place_orders(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        source = (root / "trader_combo" / "agent_gate.py").read_text()
        self.assertNotIn("place_order(", source)
        self.assertNotIn("TradeClient(", source)
        workflow = (root / ".github/workflows/trader-paper-automatic.yml").read_text()
        self.assertIn('AI_DESK_PAPER_GATE_ENABLED: "true"', workflow)
        self.assertIn('WEBULL_TRADER_PAPER_ENABLED: "true"', workflow)
        self.assertIn('cron: "5 9 * * 1-5"', workflow)


if __name__ == "__main__":
    unittest.main()
