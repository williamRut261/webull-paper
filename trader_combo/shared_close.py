"""End-of-day liquidation of ORB-owned positions only, SANDBOX CASH account.

This is the 50/50 successor to the legacy Beethoven close job. It never
liquidates the seven-agent sleeve and fails closed on old Beethoven or
unattributed holdings. Stop/target references do not represent live orders.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

from research.agent_sandbox_executor import check_shared_account
from trader_combo.shared_sleeves import (
    AGENT_SYMBOLS, ORB_SYMBOLS, owned_positions, shared_mode,
    validate_ownership_history,
)
from webull_paper.automatic import (
    PAPER_HOST, checked_portfolio, preview_and_place, reconcile_order_fill,
    order_items,
)
from webull_paper.paper_orders import collect_snapshots, verified, session_guard
from webull_paper.signal_dry_run import NY

STATE_DIR = Path("state/shared-orb-close")


def close_day():
    if not shared_mode() or os.getenv("WEBULL_PAPER_EXECUTE_ENABLED") != "true":
        raise RuntimeError("Shared ORB close requires explicit SANDBOX 50/50 opt-in")
    if PAPER_HOST != "api.sandbox.webull.com":
        raise RuntimeError("Webull production host forbidden")
    if not os.getenv("WEBULL_PAPER_APP_KEY") or not os.getenv("WEBULL_PAPER_APP_SECRET"):
        raise RuntimeError("Missing sandbox credentials")
    now = datetime.now(NY)
    session_guard(now)
    from webull.core.client import ApiClient
    from webull.trade.trade_client import TradeClient
    from webull.data.data_client import DataClient
    api = ApiClient(os.environ["WEBULL_PAPER_APP_KEY"],
                    os.environ["WEBULL_PAPER_APP_SECRET"], "us")
    api.add_endpoint("us", PAPER_HOST)
    trade, data = TradeClient(api), DataClient(api)
    account = check_shared_account(
        trade, os.getenv("WEBULL_PAPER_ACCOUNT_INDEX", ""),
        os.getenv("WEBULL_PAPER_ACCOUNT_SHA256", ""))
    today = now.date().isoformat()
    open_orders = order_items(verified(
        trade.order_v3.get_order_open(account_id=account),
        "shared ORB close open orders"), "shared ORB close open orders")
    if open_orders:
        raise RuntimeError("Outstanding sandbox order blocks shared ORB close")
    equity, cash, positions = checked_portfolio(
        trade, account, allowed_extra=AGENT_SYMBOLS | ORB_SYMBOLS)
    groups = owned_positions(positions, equity=equity, cash=cash)
    validate_ownership_history(trade, account, positions, today)
    exits = groups["orb"]
    print("SHARED_ORB_CLOSE_PLAN " + json.dumps({
        "day": today, "orb_symbols": sorted(exits),
        "agent_symbols_preserved": sorted(groups["agents"]),
        "broker": "SANDBOX", "agent_orders": 0}, sort_keys=True), flush=True)
    if not exits:
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / (today + ".json")).open("x") as f:
        json.dump({"day": today, "status": "reserved_no_retry"}, f)
        f.flush()
        os.fsync(f.fileno())
    for number, (symbol, position) in enumerate(sorted(exits.items()), 1):
        if symbol not in ORB_SYMBOLS:
            raise RuntimeError("ORB close cannot sell seven-agent symbol")
        qty = position.get("qty")
        if type(qty) not in (int, float) or qty <= 0 or qty != int(qty):
            raise RuntimeError("ORB close requires verified whole-share holdings")
        observed = datetime.now(NY)
        session_guard(observed)
        quotes, _ = collect_snapshots(
            data, [symbol], observed, True, clock=lambda: datetime.now(NY))
        quotes.validate({symbol}, datetime.now(NY))
        if qty * quotes[symbol] < 5.0:
            raise RuntimeError("ORB dust below $5: require manual reconciliation")
        payload = {
            "client_order_id": "tc" + today.replace("-", "") + "S" + str(number).zfill(2) + symbol,
            "combo_type": "NORMAL", "symbol": symbol,
            "instrument_type": "EQUITY", "market": "US", "order_type": "MARKET",
            "quantity": str(int(qty)), "side": "SELL", "time_in_force": "DAY",
            "support_trading_session": "CORE", "entrust_type": "QTY"}
        def before_submit():
            session_guard(datetime.now(NY))
            quotes.validate({symbol}, datetime.now(NY))
            outstanding = order_items(verified(
                trade.order_v3.get_order_open(account_id=account),
                "shared close open orders"), "shared close open orders")
            if outstanding:
                raise RuntimeError("New open orders appeared before ORB close")
            eq, ca, pos = checked_portfolio(
                trade, account, allowed_extra=AGENT_SYMBOLS | ORB_SYMBOLS)
            current = owned_positions(pos, equity=eq, cash=ca)
            validate_ownership_history(trade, account, pos, today)
            if set(current["agents"]) != set(groups["agents"]) or any(
                    abs(current["agents"][s]["qty"] - groups["agents"][s]["qty"]) > 0.000001
                    for s in groups["agents"]):
                raise RuntimeError("Agent sleeve changed during ORB exit")
            if symbol not in current["orb"] or current["orb"][symbol]["qty"] != qty:
                raise RuntimeError("ORB position changed before exit")
            prior = order_items(verified(
                trade.order_v3.get_order_history(account, page_size=100),
                "ORB close order history"), "ORB close order history")
            if len(prior) >= 100 or any(
                    str(row.get("client_order_id") or "") == payload["client_order_id"]
                    for row in prior):
                raise RuntimeError("ORB close duplicate/uncertain order")
        preview_and_place(
            trade, account, payload, before_submit=before_submit,
            session_check=session_guard)
        reconcile_order_fill(
            trade, account, symbol, "SELL", qty, qty,
            allowed_extra=AGENT_SYMBOLS | ORB_SYMBOLS)
        print("SHARED_ORB_CLOSED " + json.dumps({
            "symbol": symbol, "quantity": int(qty),
            "agent_sleeve_unmodified": True}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(close_day())
