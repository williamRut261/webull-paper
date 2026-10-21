"""strategy PaperTrade order adapter. Sandbox ONLY; never accesses real accounts.

Default mode --plan makes no broker changes. Actual sandbox orders require
--paper-execute, WEBULL_PAPER_EXECUTE_ENABLED=true, an explicit 0-based
WEBULL_PAPER_ACCOUNT_INDEX and fresh intraday signals within a safe window.
The source Composer JSON and strategy evaluator remain unchanged.
"""
import argparse
import json
import math
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

import pandas as pd
from webull.core.client import ApiClient
from webull.data.data_client import DataClient
from webull.trade.trade_client import TradeClient
from strategy_engine import load_strategy,signal_symbols,Evaluator,original_targets,ORIGINAL_EXECUTION_ASSETS
from webull_paper.signal_dry_run import SANDBOX,NY,assemble_history
from webull_paper.readiness import accounts_from
from webull_paper.audit_quotes import quote_time
from webull_paper.sessions import regular_session, completed_sessions

MAX_EXPOSURE=0.99
MIN_ORDER_USD=5.
STATE_DIR=Path("state/webull-paper")


def verified(response,task):
    if int(response.status_code)!=200:
        raise RuntimeError(task+" rejected, HTTP "+str(response.status_code))
    return response.json()


def money(value,name):
    if isinstance(value,dict):
        value=value.get("amount",value.get("value"))
    result=float(value)
    if not math.isfinite(result) or result<0:
        raise RuntimeError("Invalid nonnegative "+name)
    return result


def floor(value,places):
    return float(Decimal(str(value)).quantize(Decimal(10)**(-places),rounding=ROUND_DOWN))


def session_guard(now):
    """Conservative regular-session trading window; skip early closes and holidays."""
    if now.tzinfo is None:
        raise RuntimeError("Paper trading time must be timezone-aware")
    now = now.astimezone(NY)
    if not regular_session(now) or not (now.hour==15 and 48<=now.minute<55):
        raise RuntimeError("Paper trading is restricted to 15:48–15:55 ET weekdays")
    return True


class SnapshotPrices(dict):
    """Prices retain source trade times; request/response time never refreshes them."""
    def __init__(self):
        super().__init__()
        self.trade_times = {}
        self.required = set()

    def validate(self, symbols, now):
        for symbol in set(symbols) | self.required:
            stamp = self.trade_times.get(symbol)
            if symbol not in self or stamp is None:
                raise RuntimeError("No verified Webull paper quote for: " + symbol)
            age = (now - stamp).total_seconds()
            if stamp.astimezone(NY).date() != now.astimezone(NY).date() or not 0 <= age <= 1200:
                raise RuntimeError("Stale or future required Webull quote before order: " + symbol)


def collect_snapshots(data, symbols, now, require_fresh=True, allow_unused_stale=False, clock=None):
    """Never use stale prices to decide strategy branches or size orders.

    In strategy-evaluation mode, omit unusable snapshots instead of aborting
    on an irrelevant ticker. The evaluator fails on any missing input it
    actually reads; selected holdings must also have a fresh executable price.
    Strict mode retains the original fail-fast behavior.
    """
    prices = SnapshotPrices()
    previous = {}
    rows = []
    diagnostics = {}
    seen = set()
    unusable = {}
    for offset in range(0, len(symbols), 10):
        batch = symbols[offset:offset + 10]
        records = verified(data.market_data.get_snapshot(
            symbols=batch, category="US_STOCK"), "Webull quote snapshot")
        if not isinstance(records, list):
            raise RuntimeError("Unexpected snapshot format")
        rows.extend((batch, row) for row in records)
    # Read the clock AFTER all requests. The caller's signal-start timestamp
    # predates network work and can make newly executed trades look future-dated.
    observed_at = clock() if clock is not None else now
    if observed_at.tzinfo is None:
        raise RuntimeError("Snapshot observation time must be timezone-aware")
    observed_at = observed_at.astimezone(NY)
    for batch, row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Invalid Webull snapshot record")
        symbol = row.get("symbol")
        if symbol not in batch or symbol in seen:
            raise RuntimeError("Unexpected/duplicate Webull symbol in snapshot")
        seen.add(symbol)
        reason, age, stamp = None, None, None
        if require_fresh:
            try:
                stamp = quote_time(row.get("last_trade_time")).astimezone(NY)
                age = (observed_at - stamp).total_seconds()
                if age < 0:
                    reason = "future_timestamp"
                elif stamp.date() != observed_at.date():
                    reason = "other_session"
                elif age > 1200:
                    reason = "stale_over_20m"
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                reason = "invalid_timestamp"
            diagnostics[symbol] = {
                "trade_at": stamp.isoformat() if stamp else None,
                "age_seconds": round(age, 3) if age is not None else None,
                "status": reason or "within_paper_age_limit",
                "age_at_signal_start_seconds": round((now-stamp).total_seconds(), 3) if stamp else None,
            }
            if reason:
                if not allow_unused_stale:
                    raise RuntimeError("Stale or future Webull quote for " + symbol + ": " + reason)
                unusable[symbol] = reason
                continue
        try:
            price = money(row.get("price"), "price")
            prev = money(row.get("pre_close"), "pre_close")
            if price <= 0 or prev <= 0:
                raise RuntimeError("Nonpositive snapshot prices " + symbol)
        except (TypeError, ValueError, RuntimeError, OverflowError):
            if not allow_unused_stale:
                raise
            unusable[symbol] = "invalid_price"
            continue
        prices[symbol] = price
        prices.trade_times[symbol] = stamp
        previous[symbol] = prev
    missing = set(symbols) - seen
    if (missing or unusable) and not allow_unused_stale:
        raise RuntimeError("Webull missing/unusable original signal snapshots: " +
                           ",".join(sorted(missing | set(unusable))))
    if allow_unused_stale:
        print("PAPER_SNAPSHOT_COVERAGE " + json.dumps({
            "universe": len(symbols), "usable": len(prices),
            "observed_at": observed_at.isoformat(), "quotes": diagnostics,
            "max_age_seconds": 1200, "realtime_entitlement_verified": False,
            "unusable": unusable, "missing": sorted(missing)
        }, sort_keys=True), flush=True)
    return prices, previous

class RequiredInputEvaluator(Evaluator):
    """Add Webull diagnostics without changing any Composer evaluation rules."""
    def metric(self, symbol, fn, days):
        try:
            return super().metric(symbol, fn, days)
        except ValueError as exc:
            series = self.closes.get(symbol, pd.Series(dtype=float))
            length = 1001 if fn == "relative-strength-index" else days + 1
            recent = series.loc[series.first_valid_index():].iloc[-length:]
            invalid = recent[~recent.map(lambda x: math.isfinite(x) and x > 0)]
            report = {"symbol": symbol, "metric": fn, "window": days,
                      "available_rows": len(recent),
                      "invalid_dates": [str(d.date()) for d in invalid.index],
                      "history_end": str(series.index[-1]) if len(series) else None}
            print("PAPER_REQUIRED_INPUT_BLOCKED " + json.dumps(report, sort_keys=True), flush=True)
            raise ValueError(str(exc) + "; REQUIRED " + symbol + " " + fn) from exc


def targets_for_now(data,root,now,execute,clock=None):
    symbols=sorted(signal_symbols(root))
    history=assemble_history(data,symbols,now.date(),allow_missing=execute)
    if execute:
        # Make missing sessions explicit, including an absent prior session.
        history = history.reindex(completed_sessions(history.index[0], now.date()))
        # Convert raw timestamp-validated sandbox quote onto previous-session forward-adjusted basis.
        observed = []
        def observation_clock():
            value = (clock or (lambda: datetime.now(NY)))()
            observed.append(value)
            return value
        prices,raw_previous=collect_snapshots(
            data,symbols,now,True,allow_unused_stale=True,
            clock=observation_clock)
        session_guard(observed[-1])
        if observed[-1].astimezone(NY).date() != now.date():
            raise RuntimeError("Signal retrieval crossed trading sessions")
        prev_adj=history.iloc[-1]
        today={}
        for symbol in prices:
            adjusted=float(prev_adj.get(symbol, float("nan")))
            if not math.isfinite(adjusted) or adjusted<=0:
                continue  # Leave NaN; only an active metric needs this history.
            today[symbol]=prices[symbol]*adjusted/raw_previous[symbol]
        # Missing quotes remain NaN on TODAY. A used condition/filter fails
        # closed in Evaluator.metric rather than silently using yesterday.
        history.loc[pd.Timestamp(now.date())]=pd.Series(today)
        evaluator = RequiredInputEvaluator(root,history)
        targets=original_targets(evaluator.evaluate(),MAX_EXPOSURE)
        prices.required = {key[0] for key in evaluator.cache} | set(targets)
        print("PAPER_ACTIVE_INPUTS " + json.dumps(sorted(prices.required)), flush=True)
        # A final selected asset might not appear in a metric call. Never
        # permit a target without a current, validated execution price.
        unpriced=set(targets)-set(prices)
        if unpriced:
            raise RuntimeError("No fresh Webull order quote for selected targets: "+
                               ",".join(sorted(unpriced)))
        return targets,prices
    # Plan mode uses last completed D bar, never claims these are live signals.
    return original_targets(Evaluator(root,history).evaluate(),MAX_EXPOSURE),{}


def select_account(trade,execute):
    accounts=accounts_from(verified(trade.account_v2.get_account_list(),"list accounts"))
    if not accounts:
        raise RuntimeError("No sandbox accounts")
    index=os.getenv("WEBULL_PAPER_ACCOUNT_INDEX","").strip()
    if not index:
        if execute:
            raise RuntimeError("Set explicit WEBULL_PAPER_ACCOUNT_INDEX before paper execution")
        index="0"
    if not index.isdecimal() or int(index)>=len(accounts):
        raise RuntimeError("Invalid WEBULL_PAPER_ACCOUNT_INDEX")
    chosen=accounts[int(index)]
    if chosen.get("account_type")!="CASH":
        raise RuntimeError("This bot requires a sandbox CASH account, not margin/options")
    return chosen["account_id"],int(index)


def portfolio(trade,account_id,allowed_extra=frozenset()):
    balance=verified(trade.account_v2.get_account_balance(account_id),"balance")
    equity=money(balance.get("total_net_liquidation_value"),"sandbox equity")
    cash=money(balance.get("total_cash_balance"),"sandbox cash")
    positions=verified(trade.account_v2.get_account_position(account_id),"positions")
    if not isinstance(positions,list):
        raise RuntimeError("Unexpected position format")
    holdings={}
    for p in positions:
        s=p.get("symbol")
        if s not in (ORIGINAL_EXECUTION_ASSETS | frozenset(allowed_extra)) or p.get("instrument_type")!="EQUITY":
            raise RuntimeError("Unmanaged holdings; refuse to rebalance")
        qty=money(p.get("quantity"),"share quantity")
        price=money(p.get("last_price"),"last_price")
        holdings[s]={"qty":qty,"value":qty*price,"price":price}
    if equity<=0:
        raise RuntimeError("Invalid equity")
    return equity,cash,holdings


def order_payload(symbol,side,amount,price,day,sequence,allowed_extra=frozenset()):
    """Min $5 for fractional shares, never exceed modeled purchase budget."""
    if symbol not in (ORIGINAL_EXECUTION_ASSETS | frozenset(allowed_extra)) or not math.isfinite(price) or price<=0:
        raise RuntimeError("Unknown symbol/price")
    if amount<MIN_ORDER_USD or not math.isfinite(amount):
        raise RuntimeError("Order smaller than $5")
    quantity=floor(amount/price,6)
    if quantity<=0:
        raise RuntimeError("Zero calculated shares")
    if quantity>=1:
        quantity=float(int(quantity))
    elif quantity*price<MIN_ORDER_USD:
        raise RuntimeError("Fractional order falls below Webull $5 minimum")
    cid=f"bt{day.replace('-','')}{side[0]}{sequence:02d}{symbol}"
    if len(cid)>32:
        raise RuntimeError("Order ID too long")
    return {"client_order_id":cid,"combo_type":"NORMAL","symbol":symbol,
            "instrument_type":"EQUITY","market":"US","order_type":"MARKET",
            "quantity":str(int(quantity)) if quantity>=1 else str(quantity),
            "side":side,"time_in_force":"DAY","support_trading_session":"CORE",
            "entrust_type":"QTY"}


def plan_orders(targets,holdings,equity,cash,current_prices,day):
    """Sell excess before buying; always cash-funded; never short."""
    if not targets or abs(sum(targets.values())-MAX_EXPOSURE)>1e-6:
        raise RuntimeError("Invalid original strategy allocation")
    if not set(targets)<=ORIGINAL_EXECUTION_ASSETS:
        raise RuntimeError("Unknown ticker")
    orders=[]
    seq=0
    # Positions must be repriced using fresh snapshots before a live paper order.
    for symbol,p in sorted(holdings.items()):
        target=equity*targets.get(symbol,0)
        excess=p["value"]-target
        if excess<MIN_ORDER_USD:
            continue
        seq+=1
        orders.append(order_payload(symbol,"SELL",min(excess,p["value"]),
                                    p["price"],day,seq))
    # No buys until existing sell orders are confirmed filled in real broker.
    for symbol,weight in sorted(targets.items()):
        held=holdings.get(symbol,{}).get("value",0.)
        shortage=equity*weight-held
        available=min(cash*.99,equity*MAX_EXPOSURE-sum(
                      x["value"] for x in holdings.values()))
        if shortage<MIN_ORDER_USD or available<MIN_ORDER_USD:
            continue
        budget=min(shortage,available)
        if symbol not in current_prices:
            # Plan mode can report targets but cannot fabricate live order pricing.
            continue
        seq+=1
        orders.append(order_payload(symbol,"BUY",budget,current_prices[symbol],day,seq))
        cash-=budget
    return orders


def main(argv=None):
    cli=argparse.ArgumentParser()
    cli.add_argument("--paper-execute",action="store_true")
    args=cli.parse_args(argv)
    execute=args.paper_execute
    if execute and os.getenv("WEBULL_PAPER_EXECUTE_ENABLED")!="true":
        raise RuntimeError("Paper order submission requires owner activation variable")
    now=datetime.now(NY)
    if execute:
        session_guard(now)
    key,secret=os.getenv("WEBULL_PAPER_APP_KEY"),os.getenv("WEBULL_PAPER_APP_SECRET")
    if not key or not secret:
        raise RuntimeError("Missing Webull PaperTrade secrets")
    api=ApiClient(key,secret,"us")
    api.add_endpoint("us",SANDBOX)  # Cannot be changed to production by environment.
    trade=TradeClient(api)
    data=DataClient(api)
    account_id,index=select_account(trade,execute)
    root=load_strategy()
    targets,quotes=targets_for_now(data,root,now,execute)
    equity,cash,holdings=portfolio(trade,account_id)
    print("PAPER_strategy_PLAN "+json.dumps({
        "date":now.date().isoformat(),"cash_account_index":index,
        "mode":"paper-sandbox-trading" if execute else "read-only-history-plan",
        "targets":targets,"equity":round(equity,2),
        "cash":round(cash,2),"positions":sorted(holdings),
        "quotes_fresh":bool(execute),"real_orders_possible":False,
        "submitted_orders":0},sort_keys=True),flush=True)
    if not execute:
        return 0

    day=now.date().isoformat()
    STATE_DIR.mkdir(parents=True,exist_ok=True)
    claimed=STATE_DIR/(day+".json")
    if claimed.exists():
        raise RuntimeError("Already attempted Webull PaperTrade rebalance today")
    opened=verified(trade.order_v3.get_order_open(account_id=account_id),"open orders")
    if isinstance(opened,dict):
        items=opened.get("data")
    else:
        items=opened
    if not isinstance(items,list) or items:
        raise RuntimeError("Unverified or existing paper open orders; abort")
    # Explicitly block any broker orders until order-history duplicate safeguards
    # and Webull fractionable instrument eligibility have been independently checked.
    raise RuntimeError("Execution staged but not activated: verify duplicate-order history, exact broker balances and ticker fractionability")


if __name__=="__main__":
    raise SystemExit(main())
