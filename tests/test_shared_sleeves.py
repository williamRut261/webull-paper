"""Offline fail-closed shared account and separate-strategy ownership checks."""
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from trader_combo.shared_sleeves import (
    ORB_FRACTION, AGENT_FRACTION, CASH_RESERVE, GROSS_FRACTION,
    owned_positions, validate_ownership_history, shared_mode,
)
from trader_combo.morning import proposed_entries
from webull_paper.signal_dry_run import NY


class Response:
    status_code = 200
    def __init__(self, data):
        self.data = data
    def json(self):
        return self.data


class SharedSleevesTests(unittest.TestCase):
    def setUp(self):
        self.agent = {"SPY": {"qty": 2, "value": 1200.0, "price": 600.}}
        self.orb = {"XLE": {"qty": 10, "value": 500.0, "price": 50.}}

    def test_equal_reserved_equity_and_disjoint_sleeves(self):
        self.assertEqual(ORB_FRACTION, .495)
        self.assertEqual(AGENT_FRACTION, .495)
        self.assertEqual(CASH_RESERVE, .01)
        self.assertEqual(GROSS_FRACTION, .99)
        self.assertFalse(shared_mode())
        with patch.dict(os.environ, {"WEBULL_SHARED_5050_ENABLED": "true"}):
            self.assertTrue(shared_mode())
        sections = owned_positions({**self.agent, **self.orb},
                                    equity=10000.0, cash=8300.0)
        self.assertEqual(set(sections["agents"]), {"SPY"})
        self.assertEqual(set(sections["orb"]), {"XLE"})

    def test_legacy_or_unknown_holdings_block_cutover(self):
        for holding in ("GDXU", "GDXD", "SOXS", "ZZNOTLISTED"):
            with self.subTest(holding=holding), self.assertRaisesRegex(
                    RuntimeError, "Legacy or unmanaged"):
                owned_positions({holding: {"qty": 1, "value": 50.}},
                                 equity=10000., cash=9950.)

    def test_sleeves_cannot_borrow_each_others_budget(self):
        for positions in (
                {"SPY": {"qty": 20, "value": 5000.}},
                {"XLE": {"qty": 100, "value": 5000.}}):
            with self.assertRaisesRegex(RuntimeError, "sleeve exceeds"):
                owned_positions(positions, equity=10000., cash=5000.)
        # P&L is intentionally not derived from prices or these valuations.

    def test_shared_history_requires_filled_symbol_provenance(self):
        orders = [
            {"client_order_id": "tr20261023B01XLE", "symbol": "XLE",
             "order_status": "FILLED", "create_time": "2026-10-23"},
            {"client_order_id": "ag20261022BSPY", "symbol": "SPY",
             "order_status": "FILLED", "create_time": "2026-10-22"},
        ]
        broker=SimpleNamespace(order_v3=SimpleNamespace(
            get_order_history=lambda *a, **kw: Response(orders)))
        self.assertTrue(validate_ownership_history(
            broker, "shared", {**self.agent, **self.orb}, "2026-10-23"))
        original=orders[0]
        orders[0] = {**original, "client_order_id": "bt20261023B01XLE"}
        with self.assertRaisesRegex(RuntimeError, "Non-sleeve"):
            validate_ownership_history(
                broker, "shared", {**self.agent, **self.orb}, "2026-10-23")
        orders[0] = {**original, "order_status": "REJECTED"}
        with self.assertRaisesRegex(RuntimeError, "provenance"):
            validate_ownership_history(
                broker, "shared", {**self.agent, **self.orb}, "2026-10-23")

    def test_orb_sizing_does_not_spend_agent_budget(self):
        # A risk-approved breakout cannot exceed its own half of the account.
        signal = {"symbol":"XLE", "signal_price":50., "range_low":49.5,
                  "range_high":49.8}
        with patch("trader_combo.morning.MAX_TRADE_LOSS_FRACTION", .003):
            plan=proposed_entries(
                [signal], 10000., 8300., {**self.agent},
                {"XLE":50.}, shared=True)
        self.assertLessEqual(sum(p["gross_reserved"] for p in plan), 4950.)
        self.assertLessEqual(
            sum(p["gross_reserved"] for p in plan), 8300.-100.)
        with self.assertRaisesRegex(RuntimeError, "Legacy or unmanaged"):
            proposed_entries(
                [signal], 10000., 9900., {"GDXU":{"qty":1,"value":100.}},
                {"XLE":50.}, shared=True)

    def test_workflow_exclusivity_and_no_live_trading(self):
        root=Path(__file__).resolve().parents[1]
        agent=(root/".github/workflows/seven-agent-sandbox.yml").read_text()
        close=(root/".github/workflows/webull-auto-execute.yml").read_text()
        orb=(root/".github/workflows/trader-paper-automatic.yml").read_text()
        self.assertIn("group: webull-paper-order",agent)
        self.assertIn("group: webull-paper-order",orb)
        self.assertIn("group: webull-paper-order",close)
        self.assertIn("vars.WEBULL_SHARED_5050_ENABLED == 'true'",agent)
        self.assertIn("env.WEBULL_SHARED_5050_ENABLED != 'true'",close)
        self.assertIn("python -m trader_combo.shared_close",close)
        from webull_paper.automatic import assert_paper_environment
        with patch.dict(os.environ, {"WEBULL_SHARED_5050_ENABLED":"true"}):
            with self.assertRaisesRegex(RuntimeError, "Legacy Beethoven"):
                assert_paper_environment()
        self.assertNotIn("api.webull.com",(
            root/"trader_combo/shared_close.py").read_text())

    def test_agent_dry_run_with_unrelated_orb_holding(self):
        from research.agent_sandbox_executor import execute_one
        from webull_paper.paper_orders import SnapshotPrices
        moment=datetime(2026,10,22,11,22,tzinfo=NY)
        quotes=SnapshotPrices()
        quotes["SPY"]=600.
        quotes.trade_times["SPY"]=moment
        orders=[{"client_order_id":"tr20261022B01XLE", "symbol":"XLE",
                 "order_status":"FILLED","create_time":"2026-10-22"}]
        broker=SimpleNamespace(order_v3=SimpleNamespace(
            get_order_open=lambda **kw: Response([]),
            get_order_history=lambda *a, **kw: Response(orders)))
        with patch("research.agent_sandbox_executor.checked_portfolio",
                   return_value=(10000.,9000.,self.orb)), \
             patch("research.agent_sandbox_executor.collect_snapshots",
                   return_value=(quotes, {})):
            plan=execute_one(broker,object(),"shared",{"symbol":"SPY"},
                             moment,dry_run=True,clock=lambda:moment)
        self.assertEqual(plan["status"],"APPROVED_PLAN_ONLY")
        self.assertEqual(plan["side"],"BUY")
        self.assertLessEqual(float(plan["quantity"])*600.,4950.)


if __name__=="__main__":
    unittest.main()
