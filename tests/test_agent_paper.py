"""Offline virtual-paper bridge tests; impossible to submit brokerage orders."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.agent_paper import (empty_ledger, virtual_step, public_status,
                                  INITIAL_CASH, MAX_POSITION_FRACTION, main)
from research.ai_desk import ROLES


def report(day="2026-10-21", price=25, action="BUY", consensus=True):
    agents = [{"role": role, "symbol": "GDXD", "action": action,
               "confidence": 0.9} for role in ROLES]
    return {
        "status": "RESEARCH_ONLY", "broker_connected": False,
        "consensus": "HYPOTHESIS_FOR_BACKTEST" if consensus else "NO_CONSENSUS",
        "hypothesis": {"symbol": "GDXD", "action": action} if consensus else None,
        "agent_opinions": agents, "provider": "gemini",
        "market_data": {"quotes": {
            "GDXD": {"close": price, "as_of": day},
            "SPY": {"close": 500, "as_of": day},
        }}
    }


class VirtualPaperSafetyTests(unittest.TestCase):
    def test_initial_state_and_isolation(self):
        state = empty_ledger()
        self.assertEqual(state["cash"], 10000.0)
        self.assertEqual(state["positions"], {})
        self.assertFalse(state["trades"])

    def test_buy_is_queued_until_next_session_close_and_capped(self):
        intent = virtual_step(report())
        self.assertEqual(intent["trades"], [])
        self.assertEqual(intent["positions"], {})
        self.assertEqual(intent["pending"], {"signal_day": "2026-10-21", "symbol": "GDXD", "action": "BUY"})
        state = virtual_step(report(day="2026-10-22", price=27, consensus=False), intent)
        trade = state["trades"][0]
        self.assertEqual(trade["side"], "BUY")
        self.assertEqual(trade["signal_day"], "2026-10-21")
        self.assertEqual(trade["assumed_close"], 27)
        self.assertLessEqual(trade["shares"] * 27, INITIAL_CASH * MAX_POSITION_FRACTION)
        self.assertGreater(trade["estimated_cost"], 0)
        self.assertEqual(state["positions"], {"GDXD": trade["shares"]})
        self.assertLess(state["cash"] + trade["shares"] * 27, INITIAL_CASH)
        self.assertEqual(public_status(report(), state)["actual_broker_orders_from_agents"], 0)

    def test_retry_does_not_double_execute(self):
        queued = virtual_step(report())
        self.assertEqual(virtual_step(report(), queued), queued)
        filled = virtual_step(report(day="2026-10-22", consensus=False), queued)
        self.assertEqual(virtual_step(report(day="2026-10-22", consensus=False), filled), filled)

    def test_kill_switch_blocks_and_clears_queued_intents(self):
        queued = virtual_step(report())
        state = virtual_step(report(day="2026-10-22", consensus=False), queued, killed=True)
        self.assertEqual(state["positions"], {})
        self.assertEqual(state["pending"], None)
        self.assertEqual(state["trades"], [])
        self.assertEqual(public_status(report(), state, killed=True)["virtual_paper"]["status"], "KILLED")

    def test_no_consensus_no_trades(self):
        state = virtual_step(report(consensus=False))
        self.assertEqual(state["trades"], [])
        self.assertEqual(state["cash"], INITIAL_CASH)
        self.assertIsNone(state["pending"])

    def test_sell_only_existing_position_and_no_short(self):
        self.assertIsNone(virtual_step(report(action="SELL"))["pending"])
        queued = virtual_step(report())
        held = virtual_step(report(day="2026-10-22", consensus=False), queued)
        sell = virtual_step(report(day="2026-10-23", action="SELL"), held)
        self.assertEqual(len(sell["trades"]), 1)
        self.assertEqual(sell["pending"]["action"], "SELL")
        closed = virtual_step(report(day="2026-10-26", price=27, consensus=False), sell)
        self.assertEqual(len(closed["trades"]), 2)
        self.assertEqual(closed["trades"][-1]["side"], "SELL")
        self.assertEqual(closed["positions"], {})
        self.assertGreater(closed["cash"], INITIAL_CASH)
        self.assertEqual(closed["last_day"], "2026-10-26")

    def test_missing_prices_bad_quotes_and_dates_fail_closed(self):
        old = virtual_step(report())
        with self.assertRaises(ValueError):
            virtual_step(report(day="2026-10-20"), old)
        bad = report()
        bad["market_data"]["quotes"]["GDXD"]["close"] = float("nan")
        with self.assertRaises(ValueError):
            virtual_step(bad)
        bad = report()
        bad["market_data"]["quotes"]["SPY"]["as_of"] = "2026-10-20"
        with self.assertRaises(ValueError):
            virtual_step(bad)
        bad = report()
        bad["hypothesis"]["symbol"] = "INVALID"
        with self.assertRaises(ValueError):
            virtual_step(bad)

    def test_missing_agent_or_provider_error_not_a_trade(self):
        bad = report()
        bad["agent_opinions"].pop()
        with self.assertRaises(ValueError):
            virtual_step(bad)
        bad = report()
        bad["broker_connected"] = True
        with self.assertRaises(ValueError):
            virtual_step(bad)
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "report.json").write_text(json.dumps({
                "status": "NOT_CONFIGURED", "consensus": "NO_CONSENSUS"}))
            main(["--report", str(base / "report.json"),
                  "--ledger", str(base / "ledger.json"),
                  "--status", str(base / "status.json")])
            self.assertEqual(json.loads((base / "ledger.json").read_text())["trades"], [])
            self.assertEqual(json.loads((base / "status.json").read_text())["agents"], [])

    def test_duplicate_ordering_rejects_stale_days(self):
        old = virtual_step(report(day="2026-10-22"))
        with self.assertRaisesRegex(ValueError, "Out-of-order"):
            virtual_step(report(day="2026-10-21"), old)

    def test_never_imports_broker_order_implementation(self):
        src = Path(__file__).resolve().parents[1].joinpath("research/agent_paper.py").read_text()
        for prohibited in ("webull_paper.", "preview_and_place", "alpaca.", "TradeClient",
                           "create_order", "submit_order", "api.sandbox.webull.com"):
            self.assertNotIn(prohibited, src)


if __name__ == "__main__":
    unittest.main()
