"""Single-use, authenticated Monday GDXU->CASH cutover for Webull SANDBOX.

Never touches LIVE, Alpaca, another account or symbols other than the broker-
verified legacy 63 GDXU. A missing/uncertain receipt is never retried.
The shared strategies remain subject to their own independent signal/risk gates.
"""
import json
import math
import os
from datetime import datetime
from pathlib import Path
import time

from webull_paper.signal_dry_run import NY
from webull_paper.sessions import regular_session
from webull_paper.paper_orders import collect_snapshots, verified
from webull_paper.automatic import (
    PAPER_HOST, checked_portfolio, order_items, detail_status,
    preview_and_place, reconcile_order_fill,
)
from research.agent_sandbox_executor import check_shared_account

MONDAY = "2026-10-26"
LEGACY_SYMBOL = "GDXU"
LEGACY_QUANTITY = 63
LEGACY_BUY_CID = "bt20261023B02GDXU"
CUTOVER_CID = "mc20261026S01GDXU"
STATE_DIR = Path("state/shared-cutover")


def cutover_guard(now):
    if now.tzinfo is None:
        raise RuntimeError("Timezone-aware exchange clock required")
    local = now.astimezone(NY)
    minutes = 60 * local.hour + local.minute
    if (local.date().isoformat() != MONDAY or not regular_session(local)
            or not 9 * 60 + 35 <= minutes < 10 * 60 + 5):
        raise RuntimeError("CUTOVER_BLOCKED: only Monday 09:35-10:05 ET")
    return True


def require_activation():
    if (PAPER_HOST != "api.sandbox.webull.com"
            or os.getenv("WEBULL_SHARED_5050_ENABLED") != "true"
            or os.getenv("WEBULL_PAPER_EXECUTE_ENABLED") != "true"
            or os.getenv("WEBULL_MON_CUTOVER_APPROVED") != "true"
            or os.getenv("AI_PAPER_BROKER_KILL_SWITCH") == "true"
            or os.getenv("GITHUB_EVENT_NAME") != "schedule"
            or os.getenv("WEBULL_PAPER_ACCOUNT_INDEX") != "0"):
        raise RuntimeError("CUTOVER_BLOCKED: no scheduled sandbox-only authorization")
    if not os.getenv("WEBULL_PAPER_APP_KEY") or not os.getenv("WEBULL_PAPER_APP_SECRET"):
        raise RuntimeError("CUTOVER_BLOCKED: missing sandbox credentials")


def inspected_orders(trade, account):
    open_orders = order_items(verified(
        trade.order_v3.get_order_open(account_id=account),
        "cutover open orders"), "cutover open orders")
    history = order_items(verified(
        trade.order_v3.get_order_history(account, page_size=100),
        "cutover order history"), "cutover order history")
    if open_orders or len(history) >= 100:
        raise RuntimeError("CUTOVER_BLOCKED: open orders or incomplete broker history")
    return history


def verify_legacy(trade, account, history):
    if any(str(row.get("client_order_id") or "") == CUTOVER_CID for row in history):
        raise RuntimeError("CUTOVER_BLOCKED: prior cutover order; no retry")
    if any(str(row.get("create_time") or row.get("created_at") or
                   row.get("place_time_at") or "").startswith(MONDAY)
           for row in history):
        raise RuntimeError("CUTOVER_BLOCKED: another Monday broker order already exists")
    detail = verified(
        trade.order_v3.get_order_detail(account, LEGACY_BUY_CID),
        "legacy filled purchase detail")
    status, record = detail_status(detail, LEGACY_BUY_CID)
    if status not in {"FILLED", "FULL_FILLED", "FULLY_FILLED", "EXECUTED"}:
        raise RuntimeError("CUTOVER_BLOCKED: legacy 63-share purchase not FILLED")
    filled = record.get("filled_quantity", record.get("filled_qty"))
    if filled is None or abs(float(filled) - LEGACY_QUANTITY) > 0.00001:
        raise RuntimeError("CUTOVER_BLOCKED: legacy fill quantity mismatch")
    if not any(str(row.get("client_order_id") or "") == LEGACY_BUY_CID
               for row in history):
        raise RuntimeError("CUTOVER_BLOCKED: missing original legacy order in broker history")


def position_check(trade, account):
    equity, cash, positions = checked_portfolio(trade, account)
    if equity < 100 or cash < 0:
        raise RuntimeError("CUTOVER_BLOCKED: invalid brokerage values")
    if not positions:
        return equity, cash, positions
    if set(positions) != {LEGACY_SYMBOL}:
        raise RuntimeError("CUTOVER_BLOCKED: unexpected symbols; no blanket liquidation")
    q = positions[LEGACY_SYMBOL]["qty"]
    if (type(q) not in (float, int) or not math.isfinite(q)
            or abs(q - LEGACY_QUANTITY) > 1e-5):
        raise RuntimeError("CUTOVER_BLOCKED: holding not exactly 63 GDXU shares")
    return equity, cash, positions


def claim():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / (MONDAY + ".json")).open("x") as f:
        json.dump({"day": MONDAY, "order_id": CUTOVER_CID,
                   "status": "reserved_no_retry", "host": "SANDBOX"}, f)
        f.flush()
        os.fsync(f.fileno())


def migrate(trade, data, account, *, now=None, submit=preview_and_place,
            clock=None):
    clock = clock or (lambda: datetime.now(NY))
    cutover_guard(now or clock())
    history = inspected_orders(trade, account)
    equity, cash, holdings = position_check(trade, account)
    if not holdings:
        if any(str(row.get("client_order_id") or "") == CUTOVER_CID
               for row in history):
            print("MONDAY_CUTOVER_ALREADY_FLAT_BROKER_VERIFIED orders=0", flush=True)
        else:
            print("MONDAY_CUTOVER_FLAT_NO_LEGACY_HOLDING orders=0", flush=True)
        return 0
    verify_legacy(trade, account, history)
    observed = clock()
    cutover_guard(observed)
    prices, _ = collect_snapshots(data, [LEGACY_SYMBOL], observed, True, clock=clock)
    prices.validate({LEGACY_SYMBOL}, clock())
    last = prices[LEGACY_SYMBOL]
    age = (clock() - prices.trade_times[LEGACY_SYMBOL]).total_seconds()
    if not 0 <= age <= 120 or last <= 0:
        raise RuntimeError("CUTOVER_BLOCKED: legacy exit quote stale")
    order = {"client_order_id": CUTOVER_CID, "combo_type": "NORMAL",
             "symbol": LEGACY_SYMBOL, "instrument_type": "EQUITY",
             "market": "US", "order_type": "MARKET",
             "quantity": str(LEGACY_QUANTITY), "side": "SELL",
             "time_in_force": "DAY", "support_trading_session": "CORE",
             "entrust_type": "QTY"}
    print("MONDAY_CUTOVER_PLAN " + json.dumps({
        "paper_only": True, "symbol": LEGACY_SYMBOL,
        "quantity": LEGACY_QUANTITY, "mode": "legacy_exit_only",
        "price_reference": round(last, 3), "new_buys": 0}, sort_keys=True), flush=True)
    claim()
    def before_submit():
        cutover_guard(clock())
        prices.validate({LEGACY_SYMBOL}, clock())
        if (clock() - prices.trade_times[LEGACY_SYMBOL]).total_seconds() > 120:
            raise RuntimeError("CUTOVER_BLOCKED: quote became stale")
        verify_legacy(trade, account, inspected_orders(trade, account))
        _, _, current = position_check(trade, account)
        if set(current) != {LEGACY_SYMBOL}:
            raise RuntimeError("CUTOVER_BLOCKED: shares changed before submit")
    submit(trade, account, order, before_submit=before_submit,
           session_check=cutover_guard)
    _, _, updated = reconcile_order_fill(
        trade, account, LEGACY_SYMBOL, "SELL", LEGACY_QUANTITY,
        LEGACY_QUANTITY)
    if updated:
        raise RuntimeError("CUTOVER_BLOCKED: account not flat after legacy sale")
    print("MONDAY_CUTOVER_BROKER_RECONCILED " + json.dumps({
        "symbol": LEGACY_SYMBOL, "sold": LEGACY_QUANTITY,
        "remaining_legacy_positions": 0, "sandbox_only": True,
        "new_buys": 0}, sort_keys=True), flush=True)
    return 0


def main():
    require_activation()
    current = datetime.now(NY)
    if current.date().isoformat() != MONDAY or not regular_session(current):
        raise RuntimeError("CUTOVER_BLOCKED: not Monday regular trading session")
    starts = current.replace(hour=9, minute=35, second=0, microsecond=0)
    if current < starts:
        print("MONDAY_CUTOVER_WAIT seconds=" + str(int((starts - current).total_seconds())), flush=True)
        time.sleep((starts - current).total_seconds())
    cutover_guard(datetime.now(NY))
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
    return migrate(trade, data, account)


if __name__ == "__main__":
    raise SystemExit(main())
