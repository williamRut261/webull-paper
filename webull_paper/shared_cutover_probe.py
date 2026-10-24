"""Authenticated GET-only Webull SANDBOX cutover check; no order methods.

Reports only redacted paper position symbols/quantities, open-order count,
and index-0 CASH pin match. Never logs credentials/account ID or raw API data.
This does NOT authorize liquidation or set any trading flags.
"""
import hashlib
import hmac
import json
import os
import sys

from webull_paper.paper_orders import SANDBOX, money, verified
from webull_paper.automatic import order_items
from webull_paper.readiness import accounts_from


def run():
    from webull.core.client import ApiClient
    from webull.trade.trade_client import TradeClient

    if SANDBOX != "api.sandbox.webull.com":
        raise RuntimeError("Sandbox host mismatch")
    key = os.getenv("WEBULL_PAPER_APP_KEY")
    secret = os.getenv("WEBULL_PAPER_APP_SECRET")
    expected = os.getenv("WEBULL_PAPER_ACCOUNT_SHA256", "")
    if not key or not secret or len(expected) != 64:
        raise RuntimeError("Required SANDBOX secrets/account fingerprint missing")
    api = ApiClient(key, secret, "us")
    api.add_endpoint("us", SANDBOX)
    trade = TradeClient(api)
    accounts = accounts_from(verified(trade.account_v2.get_account_list(), "sandbox account list"))
    if not accounts:
        raise RuntimeError("No sandbox account index 0")
    acct = accounts[0]
    account = str(acct.get("account_id") or "")
    cash_account = acct.get("account_type") == "CASH"
    pin_match = bool(account) and hmac.compare_digest(
        hashlib.sha256(account.encode()).hexdigest(), expected)
    if not cash_account or not pin_match:
        raise RuntimeError("SANDBOX index-0 CASH account pin/type mismatch")
    balance = verified(trade.account_v2.get_account_balance(account), "sandbox balance")
    equity = money(balance.get("total_net_liquidation_value"), "equity")
    cash = money(balance.get("total_cash_balance"), "cash")
    holdings = verified(trade.account_v2.get_account_position(account), "sandbox positions")
    if not isinstance(holdings, list):
        raise RuntimeError("Malformed sandbox position response")
    rows = []
    for p in holdings:
        if not isinstance(p, dict) or p.get("instrument_type") != "EQUITY":
            raise RuntimeError("Unknown sandbox instrument")
        symbol = str(p.get("symbol") or "")
        qty = money(p.get("quantity"), "sandbox share quantity")
        if not symbol or qty < 0:
            raise RuntimeError("Malformed sandbox position")
        if qty:
            rows.append({"symbol": symbol, "quantity": round(qty, 5)})
    open_orders = order_items(verified(
        trade.order_v3.get_order_open(account_id=account), "sandbox open orders"),
        "sandbox open orders")
    history = order_items(verified(
        trade.order_v3.get_order_history(account, page_size=100), "sandbox history"),
        "sandbox history")
    report = {
        "sandbox_only": True, "account_index": 0, "account_type": "CASH",
        "account_pin_verified": True, "equity": round(equity, 2),
        "cash": round(cash, 2), "positions": sorted(rows, key=lambda p: p["symbol"]),
        "open_order_count": len(open_orders), "history_rows": len(history),
        "history_may_be_truncated": len(history) >= 100,
        "flat_for_shared_cutover": not rows and not open_orders and len(history) < 100,
        "orders_submitted": 0,
    }
    print("WEBULL_SHARED_CUTOVER_READONLY " + json.dumps(report, sort_keys=True), flush=True)
    return 0 if report["flat_for_shared_cutover"] else 3


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as exc:
        print("WEBULL_SHARED_CUTOVER_READONLY_BLOCKED " + json.dumps(
            {"reason_class": type(exc).__name__, "orders_submitted": 0}), flush=True)
        sys.exit(2)
