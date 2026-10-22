"""Offline validation of strict seven-agent Webull SANDBOX order controls."""
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json
import tempfile
import unittest

from research.ai_desk import ROLES
from research.agent_sandbox_executor import (
    ALLOWED, MAX_POSITION_FRACTION, approved_ticket, build_payload,
    check_dedicated_account, claim_day, execute_one, load_report,
    session_guard, verify_order_book, build_sell_payload,
)
from webull_paper.signal_dry_run import NY
from webull_paper.paper_orders import SnapshotPrices


def report(day="2026-10-21",symbol="SPY"):
    return {"schema":1,"status":"RESEARCH_ONLY","provider":"gemini",
            "actual_broker_orders_from_agents":0,"as_of":day,
            "consensus":"HYPOTHESIS_FOR_BACKTEST",
            "hypothesis":{"symbol":symbol,"action":"BUY"},
            "agents":[{"role":role,"symbol":symbol,"action":"BUY","confidence":.8}
                      for role in ROLES]}


class R:
    status_code=200
    def __init__(self, data):self.data=data
    def json(self):return self.data


class Broker:
    def __init__(self):
        self.account_v2=SimpleNamespace(
            get_account_list=lambda:R([
                {"account_id":"original-beethoven","account_type":"CASH"},
                {"account_id":"isolated-agents","account_type":"CASH"}]))
        self.order_v3=SimpleNamespace(
            get_order_open=lambda **kw:R([]),
            get_order_history=lambda *a,**kw:R([]))


class AgentsSandboxTests(unittest.TestCase):
    NOW=datetime(2026,10,22,11,22,tzinfo=NY)

    def test_independent_risk_gate_requires_all_seven_and_reviewer(self):
        self.assertEqual(approved_ticket(report(),self.NOW.date()),{
            "approved":True,"symbol":"SPY","side":"BUY",
            "reason":"SEVEN_AGENT_RISK_APPROVED"})
        for i in (4,5,6):
            packet=report()
            packet["agents"][i]["action"]="HOLD"
            self.assertFalse(approved_ticket(packet,self.NOW.date())["approved"])
        x=report(symbol="GDXD")
        self.assertFalse(approved_ticket(x,self.NOW.date())["approved"])
        x=report()
        x["agents"][2]["action"]="NO_TRADE"
        x["agents"][3]["action"]="NO_TRADE"
        self.assertFalse(approved_ticket(x,self.NOW.date())["approved"])

    def test_seven_agent_sell_can_only_liquidate_own_existing_position(self):
        x=report()
        x["hypothesis"]["action"]="SELL"
        for row in x["agents"]:
            row["action"]="SELL"
        self.assertEqual(approved_ticket(x,self.NOW.date())["side"],"SELL")
        x["agents"][6]["action"]="HOLD"
        self.assertFalse(approved_ticket(x,self.NOW.date())["approved"])
        self.assertEqual(build_sell_payload("SPY",.25,"2026-10-22")["quantity"],"0.250000")
        with self.assertRaises(RuntimeError):
            build_sell_payload("SPY",1.5,"2026-10-22")

    def test_fails_on_stale_or_missing_research(self):
        for d in ("2026-10-22","2026-10-23","2026-10-16"):
            with self.subTest(day=d),self.assertRaises(ValueError):
                approved_ticket(report(day=d),self.NOW.date())
        x=report()
        x["agents"][6]["role"]="Fake"
        with self.assertRaises(ValueError):
            approved_ticket(x,self.NOW.date())

    def test_requires_distinct_pin_and_cash(self):
        broker=Broker()
        pin=hashlib.sha256(b"isolated-agents").hexdigest()
        self.assertEqual(check_dedicated_account(broker,"1",pin),"isolated-agents")
        for idx,fingerprint in [("0",pin),("1","0"*64),("5",pin),("",pin)]:
            with self.subTest(index=idx),self.assertRaises(RuntimeError):
                check_dedicated_account(broker,idx,fingerprint)
        with patch.dict("os.environ",{"WEBULL_PAPER_ACCOUNT_SHA256":pin}):
            with self.assertRaises(RuntimeError):
                check_dedicated_account(broker,"1",pin)

    def test_no_orders_away_from_market_or_after_close(self):
        session_guard(self.NOW)
        for hour,minute in [(8,0),(9,45),(15,40),(20,20)]:
            with self.subTest(hour=hour),self.assertRaises(RuntimeError):
                session_guard(self.NOW.replace(hour=hour,minute=minute))

    def test_one_fifth_of_existing_ten_percent_allocation_is_not_allowed(self):
        ticket=build_payload("SPY",600.,5000.,5000.,"2026-10-22")
        self.assertEqual(ticket["side"],"BUY")
        self.assertEqual(ticket["client_order_id"],"ag20261022BSPY")
        self.assertLessEqual(float(ticket["quantity"])*600,
                             5000*MAX_POSITION_FRACTION)
        self.assertGreaterEqual(float(ticket["quantity"])*600,5.)
        with self.assertRaises(RuntimeError):
            build_payload("GDXD",25.,5000.,5000.,"2026-10-22")
        with self.assertRaises(RuntimeError):
            build_payload("SPY",600.,10.,10.,"2026-10-22")

    def test_history_never_accepts_other_bot_or_repeat_orders(self):
        broker=Broker()
        verify_order_book(broker,"isolated-agents","2026-10-22")
        broker.order_v3.get_order_history=lambda *a,**kw:R([
            {"client_order_id":"bt20261022B01SPY","create_time":"2026-10-22"}])
        with self.assertRaises(RuntimeError):
            verify_order_book(broker,"isolated-agents","2026-10-22")
        broker.order_v3.get_order_history=lambda *a,**kw:R([
            {"client_order_id":"ag20261022BSPY","create_time":"2026-10-22"}])
        with self.assertRaises(RuntimeError):
            verify_order_book(broker,"isolated-agents","2026-10-22")

    def test_dry_run_collects_real_timestamped_quotes_without_broker_write(self):
        broker=Broker()
        quotes=SnapshotPrices()
        quotes["SPY"]=600.
        quotes.trade_times["SPY"]=self.NOW
        with patch("research.agent_sandbox_executor.collect_snapshots",
                   return_value=(quotes,{})), \
             patch("research.agent_sandbox_executor.checked_portfolio",
                   return_value=(5000.,5000.,{})):
            result=execute_one(broker,object(),"isolated-agents",
                               {"symbol":"SPY"},self.NOW,
                               clock=lambda:self.NOW,
                               submit=lambda *_a,**_kw: (_ for _ in ()).throw(
                                   AssertionError("should not submit")))
        self.assertEqual(result["status"],"APPROVED_PLAN_ONLY")
        self.assertEqual(result["orders"],0)

    def test_only_one_real_sandbox_submission_after_claim_and_preview_path(self):
        broker=Broker()
        quotes=SnapshotPrices()
        quotes["SPY"]=600.
        quotes.trade_times["SPY"]=self.NOW
        submitted=[]
        def submit(_trade,_account,payload,**kw):
            submitted.append(payload)
            kw["before_submit"]()
        with tempfile.TemporaryDirectory() as d, \
             patch("research.agent_sandbox_executor.STATE_DIR",Path(d)), \
             patch("research.agent_sandbox_executor.collect_snapshots",
                   return_value=(quotes,{})), \
             patch("research.agent_sandbox_executor.checked_portfolio",
                   return_value=(5000.,5000.,{})), \
             patch("research.agent_sandbox_executor.reconcile_order_fill") as reconciled, \
             patch("research.agent_sandbox_executor.datetime") as clock:
            clock.now.return_value=self.NOW
            result=execute_one(broker,object(),"isolated-agents",
                               {"symbol":"SPY"},self.NOW,dry_run=False,
                               clock=lambda:self.NOW,submit=submit)
            self.assertEqual(result["status"],"BROKER_SANDBOX_FILL_RECONCILED")
            self.assertEqual(len(submitted),1)
            self.assertTrue((Path(d)/"2026-10-22.json").exists())
            reconciled.assert_called_once()
            with self.assertRaises(FileExistsError):
                execute_one(broker,object(),"isolated-agents",
                            {"symbol":"SPY"},self.NOW,dry_run=False,
                            clock=lambda:self.NOW,submit=submit)
        self.assertEqual(len(submitted),1)

    def test_selling_reconciles_existing_position_but_never_short(self):
        broker=Broker()
        quotes=SnapshotPrices()
        quotes["SPY"]=600.
        quotes.trade_times["SPY"]=self.NOW
        holdings={"SPY":{"qty":.25,"price":600.,"value":150.}}
        ticket={"symbol":"SPY","side":"SELL"}
        with patch("research.agent_sandbox_executor.collect_snapshots",
                   return_value=(quotes,{})), \
             patch("research.agent_sandbox_executor.checked_portfolio",
                   return_value=(5000.,4000.,holdings)):
            plan=execute_one(broker,object(),"isolated-agents",ticket,
                             self.NOW,dry_run=True,clock=lambda:self.NOW)
            self.assertEqual(plan["side"],"SELL")
            self.assertEqual(plan["quantity"],"0.250000")
            none=execute_one(broker,object(),"isolated-agents",
                             {"symbol":"QQQ","side":"SELL"},self.NOW,
                             dry_run=True,clock=lambda:self.NOW)
            self.assertEqual(none["orders"],0)
        with patch("research.agent_sandbox_executor.checked_portfolio",
                   return_value=(5000.,4000.,{})):
            flat=execute_one(broker,object(),"isolated-agents",ticket,
                             self.NOW,dry_run=True,clock=lambda:self.NOW)
            self.assertEqual(flat["status"],"NO_POSITION_TO_SELL")

    def test_only_iap_owner_can_discover_separate_cash_accounts(self):
        from dashboard.app import app
        audience="/projects/123/locations/us-central1/services/webull-paper-viewer"
        broker=Broker()
        with patch.dict("os.environ",{"IAP_AUDIENCE":audience,
                                       "DASHBOARD_ALLOWED_EMAIL":"owner@example.com"},
                                       clear=True):
            with app.test_client() as client:
                self.assertEqual(client.get("/office/agent-sandbox-accounts").status_code,403)
            with patch("dashboard.app.id_token.verify_token",return_value={
                    "iss":"https://cloud.google.com/iap","email":"owner@example.com"}), \
                 patch("dashboard.app.sandbox_trade_client",return_value=broker):
                with app.test_client() as client:
                    headers={"X-Goog-Iap-Jwt-Assertion":"signed"}
                    response=client.get("/office/agent-sandbox-accounts",headers=headers)
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.headers["Cache-Control"],"private, no-store")
                    self.assertEqual(response.json["orders_submitted"],0)
                    self.assertEqual(len(response.json["candidates"]),1)
                    self.assertEqual(response.json["candidates"][0]["index"],1)
                    self.assertEqual(response.json["candidates"][0]["type"],"CASH")
                    self.assertNotIn("isolated-agents",response.get_data(as_text=True))
                    self.assertNotIn("original-beethoven",response.get_data(as_text=True))
                    self.assertEqual(client.post("/office/agent-sandbox-accounts",
                                             headers=headers).status_code,405)

    def test_broker_host_pinned_and_auto_execution_default_disabled(self):
        source=(Path(__file__).resolve().parents[1]/
                "research/agent_sandbox_executor.py").read_text()
        self.assertIn('PAPER_HOST!="api.sandbox.webull.com"',source)
        self.assertNotIn("api.webull.com",source)
        self.assertNotIn("alpaca",source.lower())
        workflow=(Path(__file__).resolve().parents[1]/
                  ".github/workflows/seven-agent-sandbox.yml").read_text()
        self.assertIn("vars.AI_AGENTS_SANDBOX_EXECUTE_ENABLED == 'true'",workflow)
        self.assertIn("contents: read",workflow)
        self.assertIn("group: webull-paper-order",workflow)
        self.assertIn("github.event_name == 'schedule'",workflow)


if __name__=="__main__":
    unittest.main()
