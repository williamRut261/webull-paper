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

    def test_consensus_buy_is_capped_fees_are_explicit(self):
        state = virtual_step(report())
        trade = state["trades"][0]
        self.assertEqual(trade["side"], "BUY")
        self.assertLessEqual(trade["shares"] * 25, INITIAL_CASH * MAX_POSITION_FRACTION)
        self.assertGreater(trade["estimated_cost"], 0)
        self.assertEqual(state["positions"], {"GDXD": trade["shares"]})
        self.assertLessEqual(state["cash"] + trade["shares"] * 25, INITIAL_CASH)
        self.assertEqual(public_status(report(), state)["actual_broker_orders_from_agents"], 0)

    def test_retry_does_not_double_execute(self):
        state = virtual_step(report())
        self.assertEqual(virtual_step(report(), state), state)

    def test_kill_switch_blocks_all_new_virtual_orders(self):
        state = virtual_step(report(), killed=True)
        self.assertEqual(state["positions"], {})
        self.assertEqual(state["trades"], [])
        self.assertEqual(public_status(report(), state, killed=True)["virtual_paper"]["status"], "KILLED")

    def test_no_consensus_no_trades(self):
        state = virtual_step(report(consensus=False))
        self.assertEqual(state["trades"], [])
        self.assertEqual(state["cash"], INITIAL_CASH)

    def test_sell_only_existing_position_and_no_short(self):
        self.assertEqual(virtual_step(report(action="SELL"))["trades"], [])
        initial = virtual_step(report())
        later = virtual_step(report(day="2026-10-22", price=27, action="SELL"), initial)
        self.assertEqual(len(later["trades"]), 2)
        self.assertEqual(later["positions"], {})
        self.assertGreater(later["cash"], INITIAL_CASH)
        self.assertEqual(later["last_day"], "2026-10-22")

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
