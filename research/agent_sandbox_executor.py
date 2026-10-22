"""Seven-agent consensus -> ONE real Webull SANDBOX order (never LIVE).

Separate broker account from Beethoven/ORB PAPER. Disabled until an owner
pins a distinct CASH sandbox account and explicitly enables this workflow.
Research dialogue text is deliberately NEVER interpreted as order authority.
"""
import argparse
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen

from research.ai_desk import ROLES
from trader_combo.agent_gate import evaluate_agent_gate
from webull_paper.signal_dry_run import NY
from webull_paper.sessions import regular_session
from webull_paper.automatic import (
    PAPER_HOST, checked_portfolio, order_items, preview_and_place,
    reconcile_order_fill,
)
from webull_paper.paper_orders import collect_snapshots, verified
from webull_paper.readiness import accounts_from

STATUS_URL = ("https://raw.githubusercontent.com/williamRut261/webull-paper/"
              "main/research/ai_desk_status.json")
ALLOWED = frozenset(("SPY", "QQQ"))
MAX_POSITION_FRACTION = 0.05
MIN_NOTIONAL = 5.0
CID_PREFIX = "ag"
STATE_DIR = Path("state/agent-sandbox")


def session_guard(now):
    if now.tzinfo is None:
        raise RuntimeError("Timezone required")
    now = now.astimezone(NY)
    # Exclude opening auction, late close, weekends and exchange holidays.
    if not regular_session(now) or not ((now.hour == 11) or
                                         (12 <= now.hour <= 14) or
                                         (now.hour == 15 and now.minute <= 20)):
        raise RuntimeError("Outside supported 11:00–15:20 ET sandbox session")


def load_report(opener=urlopen):
    req = Request(STATUS_URL, headers={"User-Agent":"stonks-agents-sandbox-only",
                                        "Accept":"application/json"})
    with opener(req,timeout=8) as response:
        raw=response.read(16001)
    if len(raw)>16000:
        raise ValueError("Research report oversized")
    result=json.loads(raw)
    if not isinstance(result,dict):
        raise ValueError("Invalid research report")
    return result


def approved_ticket(report, trade_day):
    """Require seven coherent, prior-session votes. Neither chat nor AI alone
    can bypass this independent deterministic allowlist/risk check.
    """
    # Existing gate independently checks all seven ordered roles, age, vetoes,
    # provider, non-executable research flag and risk-on BUY consensus.
    gate=evaluate_agent_gate(report,trade_day)
    if not gate["approved"]:
        return {"approved":False,"reason":gate["reason"]}
    symbol=report["hypothesis"]["symbol"]
    if symbol not in ALLOWED:
        return {"approved":False,"reason":"UNSUPPORTED_SYMBOL"}
    # An extra independent Trade Reviewer BUY approval avoids the older
    # advisory gate's allowance for a reviewer HOLD.
    reviewer=report["agents"][6]
    if (reviewer["action"]!="BUY" or reviewer["symbol"]!=symbol
            or reviewer["confidence"]<0.65):
        return {"approved":False,"reason":"REVIEWER_NOT_EXPLICIT"}
    return {"approved":True,"symbol":symbol,"side":"BUY",
            "reason":"SEVEN_AGENT_RISK_APPROVED"}


def check_dedicated_account(trade, account_index, fingerprint):
    if account_index not in ("1","2","3","4"):
        raise RuntimeError("Requires a dedicated non-Beethoven sandbox index 1–4")
    if not re.fullmatch(r"[0-9a-f]{64}",fingerprint):
        raise RuntimeError("Dedicated sandbox account fingerprint missing")
    rows=accounts_from(verified(trade.account_v2.get_account_list(),
                                 "sandbox account discovery"))
    idx=int(account_index)
    if idx>=len(rows):
        raise RuntimeError("Dedicated sandbox account index unavailable")
    row=rows[idx]
    if row.get("account_type")!="CASH":
        raise RuntimeError("Dedicated agent account must be CASH")
    account_id=str(row.get("account_id") or "")
    if not account_id or not hmac.compare_digest(
            hashlib.sha256(account_id.encode()).hexdigest(),fingerprint):
        raise RuntimeError("Dedicated account fingerprint mismatch")
    other=os.getenv("WEBULL_PAPER_ACCOUNT_SHA256","")
    if other and hmac.compare_digest(other,fingerprint):
        raise RuntimeError("Agents cannot share Beethoven / ORB sandbox account")
    return account_id


def verify_order_book(trade, account_id, today):
    open_rows=order_items(verified(
        trade.order_v3.get_order_open(account_id=account_id),"open orders"),
        "open orders")
    if open_rows:
        raise RuntimeError("Unknown outstanding paper orders: abort")
    history=order_items(verified(
        trade.order_v3.get_order_history(account_id,page_size=100),
        "paper order history"),"paper order history")
    if len(history)>=100:
        raise RuntimeError("Order history may be truncated")
    # Refuse ANY order on this dedicated account today, even one created
    # outside our workflow, to prevent duplicates/cross-bot interference.
    for row in history:
        raw=(str(row.get("create_time") or row.get("created_at") or
                 row.get("place_time_at") or ""))
        cid=str(row.get("client_order_id") or "")
        if cid.startswith(CID_PREFIX+today.replace("-","")):
            raise RuntimeError("Agent order already submitted for trading date")
        if raw.startswith(today):
            raise RuntimeError("Dedicated paper account already traded today")


def claim_day(day):
    STATE_DIR.mkdir(parents=True,exist_ok=True)
    path=STATE_DIR/(day+".json")
    with path.open("x") as file:
        json.dump({"day":day,"mode":"Webull SANDBOX only",
                   "status":"submission_reserved_no_retry"},file)
        file.flush()
        os.fsync(file.fileno())


def build_payload(symbol, price, equity, cash, day):
    if symbol not in ALLOWED or type(price) not in (int,float) or (
            not math.isfinite(price) or price<=0):
        raise RuntimeError("Unapproved ticker or invalid quote")
    if not all(type(v) in (int,float) and math.isfinite(v) and v>=0
               for v in (equity,cash)):
        raise RuntimeError("Invalid account equity or cash")
    # Limit to 5% of this dedicated sandbox equity. Leave 95% uninvested.
    notional=min(equity*MAX_POSITION_FRACTION,cash*0.98)
    qty=Decimal(str(notional))/Decimal(str(price))
    qty=qty.quantize(Decimal("0.000001"),rounding=ROUND_DOWN)
    if qty>=1:
        qty=qty.to_integral_value(rounding=ROUND_DOWN)
    if notional<MIN_NOTIONAL or qty*Decimal(str(price))<Decimal(str(MIN_NOTIONAL)):
        raise RuntimeError("Ticket below Webull sandbox minimum")
    return {"client_order_id":CID_PREFIX+day.replace("-","")+"B"+symbol,
            "combo_type":"NORMAL","symbol":symbol,
            "instrument_type":"EQUITY","market":"US",
            "order_type":"MARKET","quantity":str(qty),"side":"BUY",
            "time_in_force":"DAY","support_trading_session":"CORE",
            "entrust_type":"QTY"}


def execute_one(trade,data,account_id,ticket, now,*, dry_run=True,
                clock=None, submit=preview_and_place):
    session_guard(now)
    today=now.astimezone(NY).date().isoformat()
    verify_order_book(trade,account_id,today)
    equity,cash,positions=checked_portfolio(trade,account_id,
                                            allowed_extra=ALLOWED)
    if positions:
        # No automatic liquidation of unrecognized/existing inventory;
        # exit logic requires explicit separate design and testing.
        return {"status":"NO_TRADE_EXISTING_POSITION","orders":0}
    symbol=ticket["symbol"]
    observed_clock=clock or (lambda:datetime.now(NY))
    prices,_=collect_snapshots(data,[symbol],now,True,clock=observed_clock)
    observed_at=observed_clock()
    session_guard(observed_at)
    prices.validate({symbol},observed_at)
    order=build_payload(symbol,prices[symbol],equity,cash,today)
    if dry_run:
        return {"status":"APPROVED_PLAN_ONLY","orders":0,
                "symbol":symbol,"side":"BUY","quantity":order["quantity"]}
    # A locally atomic claim guards retry after a broken receipt; the cache
    # persists this claim across workflows when GitHub Actions saves it.
    claim_day(today)
    def before_submit():
        current=datetime.now(NY)
        session_guard(current)
        prices.validate({symbol},current)
        verify_order_book(trade,account_id,today)
        updated_equity,updated_cash,updated_positions=checked_portfolio(
            trade,account_id,allowed_extra=ALLOWED)
        if updated_positions or updated_cash < float(order["quantity"])*prices[symbol]*1.02:
            raise RuntimeError("Cash/position changed since order plan")
        if updated_equity<=0:
            raise RuntimeError("Invalid paper equity")
    submit(trade,account_id,order,before_submit=before_submit,
           session_check=session_guard)
    reconcile_order_fill(trade,account_id,symbol,"BUY",0,
                         float(order["quantity"]),allowed_extra=ALLOWED)
    return {"status":"BROKER_SANDBOX_FILL_RECONCILED","orders":1,
            "symbol":symbol,"side":"BUY","quantity":order["quantity"]}


def main(argv=None):
    cli=argparse.ArgumentParser()
    cli.add_argument("--execute",action="store_true")
    args=cli.parse_args(argv)
    if args.execute and (
            os.getenv("AI_AGENTS_SANDBOX_EXECUTE_ENABLED")!="true" or
            os.getenv("GITHUB_EVENT_NAME")!="schedule"):
        raise RuntimeError("Sandbox execution disabled unless owner enables scheduled mode")
    if PAPER_HOST!="api.sandbox.webull.com":
        raise RuntimeError("Production Webull host forbidden")
    now=datetime.now(NY)
    session_guard(now)
    report=load_report()
    ticket=approved_ticket(report,now.date())
    if not ticket["approved"]:
        print("AI_AGENT_PAPER_VETO "+ticket["reason"]+" orders=0",flush=True)
        return 0
    from webull.core.client import ApiClient
    from webull.data.data_client import DataClient
    from webull.trade.trade_client import TradeClient
    key,secret=os.getenv("WEBULL_PAPER_APP_KEY"),os.getenv("WEBULL_PAPER_APP_SECRET")
    if not key or not secret:
        raise RuntimeError("Dedicated sandbox credentials absent")
    api=ApiClient(key,secret,"us")
    api.add_endpoint("us",PAPER_HOST)  # hard-coded sandbox, NEVER production
    trade,data=TradeClient(api),DataClient(api)
    account_id=check_dedicated_account(
        trade,os.getenv("AI_AGENTS_ACCOUNT_INDEX",""),
        os.getenv("AI_AGENTS_ACCOUNT_SHA256",""))
    outcome=execute_one(trade,data,account_id,ticket,now,dry_run=not args.execute)
    print("AI_AGENT_SANDBOX "+json.dumps(outcome,sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
