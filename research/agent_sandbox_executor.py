"""Seven-agent consensus -> ONE real Webull SANDBOX PAPER order (never LIVE).

Shared pinned CASH account with ORB, independent 49.5%-of-equity agent sleeve.
Separate order IDs and strategy reports. No research-only chat order authority.
Exclusive 50/50 mode and opt-in required; legacy Beethoven holdings block trade.
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
from trader_combo.shared_sleeves import (
    AGENT_FRACTION, AGENT_SYMBOLS, ORB_SYMBOLS, CASH_RESERVE,
    owned_positions, shared_mode, validate_ownership_history,
)
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
ALLOWED = AGENT_SYMBOLS
MAX_POSITION_FRACTION = AGENT_FRACTION
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
    # The pre-existing gate validates schema, prior-day age and all seven
    # opinions even when it denies permission to BUY an existing ORB signal.
    hypothesis=report.get("hypothesis")
    if report.get("consensus")!="HYPOTHESIS_FOR_BACKTEST" or not isinstance(hypothesis,dict):
        return {"approved":False,"reason":"NO_STRUCTURED_CONSENSUS"}
    symbol=hypothesis.get("symbol")
    side=hypothesis.get("action")
    if symbol not in ALLOWED or side not in ("BUY","SELL"):
        return {"approved":False,"reason":"UNSUPPORTED_SYMBOL_OR_SIDE"}
    votes=report["agents"]
    agrees=lambda row: (row["symbol"]==symbol and row["action"]==side
                         and row["confidence"]>=0.65)
    if (sum(agrees(row) for row in votes[:4])<3
            or not all(agrees(row) for row in votes[4:])):
        return {"approved":False,"reason":"SEVEN_AGENT_VETO"}
    if side=="BUY" and not gate["approved"]:
        return {"approved":False,"reason":gate["reason"]}
    # SELL means reduce an existing owned sandbox position, never short.
    return {"approved":True,"symbol":symbol,"side":side,
            "reason":"SEVEN_AGENT_RISK_APPROVED"}


def check_shared_account(trade, account_index, fingerprint):
    """Pin exactly the same existing CASH account index 0 used by ORB."""
    if account_index != "0":
        raise RuntimeError("Shared ORB/agent PAPER account must use index 0")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint or ""):
        raise RuntimeError("Shared sandbox CASH account fingerprint missing")
    if not hmac.compare_digest(os.getenv("WEBULL_PAPER_ACCOUNT_SHA256", ""), fingerprint):
        raise RuntimeError("Shared account fingerprint must match ORB pin")
    rows = accounts_from(verified(trade.account_v2.get_account_list(),
                                  "sandbox shared account discovery"))
    if not rows or rows[0].get("account_type") != "CASH":
        raise RuntimeError("Shared SANDBOX index 0 is not CASH")
    account_id = str(rows[0].get("account_id") or "")
    if not account_id or not hmac.compare_digest(
            hashlib.sha256(account_id.encode()).hexdigest(), fingerprint):
        raise RuntimeError("Shared CASH account fingerprint mismatch")
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
    # Permit existing ORB orders in the shared account. Refuse same-day
    # non-sleeve orders and any agent retry; do not interpret ORB fills as ours.
    for row in history:
        raw=(str(row.get("create_time") or row.get("created_at") or
                 row.get("place_time_at") or ""))
        cid=str(row.get("client_order_id") or "")
        if cid.startswith(CID_PREFIX+today.replace("-","")):
            raise RuntimeError("Agent order already submitted for trading date")
        if raw.startswith(today) and not cid.startswith(("ag", "tr", "tc")):
            raise RuntimeError("Unmanaged order today blocks shared PAPER execution")


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
    # 50/50 economic sleeves, each capped at 49.5% of total equity.
    # Always reserve >=1% aggregate equity as CASH.
    notional=min(equity*MAX_POSITION_FRACTION,
                 max(0.0, cash-equity*CASH_RESERVE)*0.98)
    qty=Decimal(str(notional))/Decimal(str(price))
    qty=qty.quantize(Decimal("0.00001"),rounding=ROUND_DOWN)
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



def build_sell_payload(symbol, held_qty, day):
    if symbol not in ALLOWED or type(held_qty) not in (int,float) or (
            not math.isfinite(held_qty) or held_qty<=0):
        raise RuntimeError("Invalid sandbox sell position")
    exact=Decimal(str(held_qty))
    q=exact.quantize(Decimal("0.00001"),rounding=ROUND_DOWN)
    if exact!=q:
        raise RuntimeError("Held shares exceed Webull maximum five-decimal precision")
    if q>=1 and q!=q.to_integral_value(rounding=ROUND_DOWN):
        raise RuntimeError("Broker fractional mixed positions require manual reconciliation")
    return {"client_order_id":CID_PREFIX+day.replace("-","")+"S"+symbol,
            "combo_type":"NORMAL","symbol":symbol,
            "instrument_type":"EQUITY","market":"US",
            "order_type":"MARKET","quantity":str(q),"side":"SELL",
            "time_in_force":"DAY","support_trading_session":"CORE",
            "entrust_type":"QTY"}


def execute_one(trade,data,account_id,ticket, now,*, dry_run=True,
                clock=None, submit=preview_and_place):
    session_guard(now)
    today=now.astimezone(NY).date().isoformat()
    verify_order_book(trade,account_id,today)
    equity,cash,positions=checked_portfolio(trade,account_id,
                                            allowed_extra=ALLOWED|ORB_SYMBOLS)
    groups=owned_positions(positions,equity=equity,cash=cash)
    validate_ownership_history(trade, account_id, positions, today)
    agent_positions=groups["agents"]
    symbol=ticket["symbol"]
    side=ticket.get("side","BUY")
    if side not in ("BUY","SELL") or symbol not in ALLOWED:
        raise RuntimeError("Invalid agent order authority")
    if agent_positions and (side=="BUY" or set(agent_positions)!={symbol}):
        return {"status":"NO_TRADE_EXISTING_AGENT_POSITION","orders":0}
    if side=="SELL" and symbol not in agent_positions:
        return {"status":"NO_POSITION_TO_SELL","orders":0}
    observed_clock=clock or (lambda:datetime.now(NY))
    prices,_=collect_snapshots(data,[symbol],now,True,clock=observed_clock)
    observed_at=observed_clock()
    session_guard(observed_at)
    prices.validate({symbol},observed_at)
    if side=="BUY":
        order=build_payload(symbol,prices[symbol],equity,cash,today)
    else:
        qty=agent_positions[symbol]["qty"]
        if qty*prices[symbol]<MIN_NOTIONAL:
            return {"status":"SELL_BELOW_MINIMUM","orders":0}
        order=build_sell_payload(symbol,qty,today)
    if dry_run:
        return {"status":"APPROVED_PLAN_ONLY","orders":0,
                "symbol":symbol,"side":side,"quantity":order["quantity"]}
    # A locally atomic claim guards retry after a broken receipt; the cache
    # persists this claim across workflows when GitHub Actions saves it.
    claim_day(today)
    def before_submit():
        current=datetime.now(NY)
        session_guard(current)
        prices.validate({symbol},current)
        verify_order_book(trade,account_id,today)
        updated_equity,updated_cash,updated_positions=checked_portfolio(
            trade,account_id,allowed_extra=ALLOWED|ORB_SYMBOLS)
        updated_groups=owned_positions(
            updated_positions,equity=updated_equity,cash=updated_cash)
        validate_ownership_history(trade,account_id,updated_positions,today)
        if set(updated_positions)!=set(positions) or any(
                abs(updated_positions[x]["qty"]-positions[x]["qty"])>0.000001
                for x in positions):
            raise RuntimeError("Shared account positions changed since agent plan")
        if side=="BUY":
            cost=float(order["quantity"])*prices[symbol]*1.02
            if updated_groups["agents"] or updated_cash - cost < updated_equity*CASH_RESERVE:
                raise RuntimeError("Agent BUY would breach sleeve or cash reserve")
        elif set(updated_groups["agents"])!={symbol}:
            raise RuntimeError("Agent SELL cannot touch ORB position")
        if updated_equity<=0:
            raise RuntimeError("Invalid paper equity")
    submit(trade,account_id,order,before_submit=before_submit,
           session_check=session_guard)
    reconcile_order_fill(trade,account_id,symbol,side,
                         agent_positions.get(symbol,{}).get("qty",0),
                         float(order["quantity"]),allowed_extra=ALLOWED|ORB_SYMBOLS)
    return {"status":"BROKER_SANDBOX_FILL_RECONCILED","orders":1,
            "symbol":symbol,"side":side,"quantity":order["quantity"]}


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
    if not shared_mode():
        raise RuntimeError("Shared 50/50 PAPER mode disabled; never use isolated account")
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
        raise RuntimeError("Shared sandbox credentials absent")
    api=ApiClient(key,secret,"us")
    api.add_endpoint("us",PAPER_HOST)  # hard-coded sandbox, NEVER production
    trade,data=TradeClient(api),DataClient(api)
    account_id=check_shared_account(
        trade,os.getenv("WEBULL_PAPER_ACCOUNT_INDEX",""),
        os.getenv("WEBULL_PAPER_ACCOUNT_SHA256",""))
    outcome=execute_one(trade,data,account_id,ticket,now,dry_run=not args.execute)
    print("AI_AGENT_SANDBOX "+json.dumps(outcome,sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
