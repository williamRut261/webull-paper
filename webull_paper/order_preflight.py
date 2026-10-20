"""GET-only sandbox order-history readiness check; no orders or previews."""
import json
import os
import hashlib
from datetime import datetime

from webull.core.client import ApiClient
from webull.trade.trade_client import TradeClient

from webull_paper.automatic import PAPER_HOST, history_guard
from webull_paper.paper_orders import select_account, verified
from webull_paper.readiness import accounts_from
from webull_paper.signal_dry_run import NY


def main():
    key, secret = os.getenv("WEBULL_PAPER_APP_KEY"), os.getenv("WEBULL_PAPER_APP_SECRET")
    if not key or not secret:
        raise RuntimeError("Webull paper secrets unavailable")
    api = ApiClient(key, secret, "us")
    api.add_endpoint("us", PAPER_HOST)
    trade = TradeClient(api)
    response = verified(trade.account_v2.get_account_list(), "sandbox accounts")
    accounts = accounts_from(response)
    if not accounts or accounts[0].get("account_type") != "CASH":
        raise RuntimeError("The designated Webull SANDBOX index 0 is not CASH")
    account_id = accounts[0]["account_id"]
    account_digest = hashlib.sha256(str(account_id).encode()).hexdigest()
    expected_pin = os.environ.get("WEBULL_PAPER_ACCOUNT_SHA256", "")
    pin_matches = bool(len(expected_pin) == 64 and account_digest == expected_pin)
    print("WEBULL_SANDBOX_ACCOUNT_FINGERPRINT " + json.dumps({
        "account_index": 0, "account_count": len(accounts),
        "account_type": "CASH", "account_pin_matches": pin_matches,
        "orders_submitted": 0
    }, sort_keys=True), flush=True)
    if not pin_matches:
        raise RuntimeError("Webull PAPER account pin missing or mismatched; no orders")
    history_guard(trade.order_v3, account_id, datetime.now(NY).date().isoformat())
    print("WEBULL_SANDBOX_ORDER_READINESS " + json.dumps({
        "sandbox_only": True, "account_count": len(accounts),
        "open_orders": 0, "recent_same_day_bot_orders": 0,
        "order_history_shape_verified": True, "orders_submitted": 0
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
