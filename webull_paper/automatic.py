"""Automatic strategy paper rebalancing in the WEBULL SANDBOX ONLY.

No broker URL overrides, no live Webull account, no Alpaca connection.
Requires official Webull SDK, GitHub Actions secrets, and strict checks.
"""
import hashlib
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

from strategy_engine import load_strategy
from webull_paper.signal_dry_run import SANDBOX, NY
from webull_paper.paper_orders import (
    MAX_EXPOSURE, MIN_ORDER_USD, STATE_DIR, floor, money, order_payload,
    portfolio, select_account, session_guard, targets_for_now, verified, SnapshotPrices,
    collect_snapshots,
)

PAPER_HOST = "api.sandbox.webull.com"
# SHA-256 fingerprint of verified $5,000 sandbox CASH account #0.
# Pin prevents silently trading one of the other Webull sandbox accounts.
PINNED_SANDBOX_CASH_SHA256 = os.environ.get("WEBULL_PAPER_ACCOUNT_SHA256", "")
STOP_MINUTE = 55
ORDER_WAIT_SECONDS = 65
BUY_PRICE_BUFFER = 0.02


def selected_account_matches_pin(account_id, accounts, index):
    """Only the originally verified first CASH sandbox account may receive orders."""
    return bool(
        index == 0 and accounts
        and accounts[0].get("account_type") == "CASH"
        and str(accounts[0].get("account_id")) == str(account_id)
        and hashlib.sha256(str(account_id).encode()).hexdigest()
        == PINNED_SANDBOX_CASH_SHA256)


def assert_paper_environment():
    if SANDBOX != PAPER_HOST:
        raise RuntimeError("Webull production endpoint is FORBIDDEN")
    if os.getenv("WEBULL_PAPER_EXECUTE_ENABLED") != "true":
        raise RuntimeError("Owner has not activated Webull PAPER orders")
    if os.getenv("WEBULL_PAPER_ACCOUNT_INDEX") != "0":
        raise RuntimeError("Only the verified sandbox CASH account index 0 is permitted")
    if not os.getenv("WEBULL_PAPER_APP_KEY") or not os.getenv("WEBULL_PAPER_APP_SECRET"):
        raise RuntimeError("Missing sandbox-only Webull GitHub secrets")


def close_window(now):
    session_guard(now)
    if now.minute >= STOP_MINUTE:
        raise RuntimeError("Too late for the pre-close paper trading window")


def order_items(payload, label):
    """Fail closed on an unknown response or truncated order list."""
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        if payload.get("pagination_key") or payload.get("last_client_order_id"):
            raise RuntimeError(label + " pagination cannot be ignored")
        values = next((payload[k] for k in ("data", "orders", "result")
                       if isinstance(payload.get(k), list)), None)
    else:
        values = None
    if not isinstance(values, list) or any(not isinstance(x, dict) for x in values):
        raise RuntimeError("Unexpected " + label + " response")
    return values


def history_guard(order_api, account_id, day):
    """Check order book BEFORE claiming day, refusing unknown or partial history."""
    open_orders = order_items(
        verified(order_api.get_order_open(account_id=account_id), "open orders"),
        "open orders")
    if open_orders:
        raise RuntimeError("Existing paper orders are open; refuse another rebalance")
    history = order_items(
        verified(order_api.get_order_history(account_id, page_size=100),
                 "order history"), "order history")
    if len(history) >= 100:
        raise RuntimeError("Paper order history may be truncated")
    prefix = "bt" + day.replace("-", "")
    if any(str(o.get("client_order_id") or "").startswith(prefix) for o in history):
        raise RuntimeError("Webull already has strategy paper orders today")
    # Unknown histories or orders from other sources are not used to infer balance.


def claim_day(day):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / (day + ".json")
    with path.open("x") as f:
        json.dump({"day": day, "mode": "Webull SANDBOX paper", "status": "claimed"}, f)
        f.flush()
        os.fsync(f.fileno())


def detail_status(payload, client_order_id):
    """Webull SDK generations differ in nesting; never accept ambiguous fills."""
    def candidates(x, depth=0):
        if depth > 4:
            return []
        if isinstance(x, list):
            return [z for e in x for z in candidates(e, depth + 1)]
        if isinstance(x, dict):
            ret = [x] if any(k in x for k in ("order_status", "status", "orderStatus")) else []
            for field in ("data", "orders", "order", "result"):
                if isinstance(x.get(field), (dict, list)):
                    ret.extend(candidates(x[field], depth + 1))
            return ret
        return []
    details = candidates(payload)
    found = [x for x in details if
             x.get("client_order_id") == client_order_id or
             (len(details) == 1 and not x.get("client_order_id"))]
    if len(found) != 1:
        raise RuntimeError("Cannot unambiguously verify Webull paper order")
    row = found[0]
    state = str(row.get("order_status") or row.get("status") or
                row.get("orderStatus") or "").upper()
    if not state:
        raise RuntimeError("Missing Webull paper order state")
    return state, row


def preview_and_place(trade, account_id, payload, before_submit=None, session_check=close_window):
    """Place exactly once. A timeout/uncertain receipt must NEVER be retried."""
    session_check(datetime.now(NY))
    if before_submit is not None:
        before_submit()
    cid = payload["client_order_id"]
    preview = verified(trade.order_v3.preview_order(account_id, [payload]),
                       "paper order preview")
    if not isinstance(preview, (dict, list)) or not preview:
        raise RuntimeError("Empty Webull paper order preview")
    if isinstance(preview, dict) and (
            preview.get("error") or preview.get("error_code") or
            preview.get("success") is False):
        raise RuntimeError("Webull paper order preview rejected its payload")
    session_check(datetime.now(NY))
    if before_submit is not None:
        before_submit()
    response = verified(trade.order_v3.place_order(account_id, [payload]),
                        "Webull SANDBOX order placement")
    if not isinstance(response, (dict, list)) or not response:
        raise RuntimeError("Empty sandbox order response")
    if isinstance(response, dict) and (
            response.get("error") or response.get("error_code") or
            response.get("success") is False):
        raise RuntimeError("Webull sandbox order placement was rejected")
    print("PAPER_SUBMITTED " + json.dumps({
        "client_order_id": cid, "symbol": payload["symbol"],
        "side": payload["side"], "quantity": payload["quantity"]}), flush=True)
    return wait_for_full_fill(trade, account_id, cid, float(payload["quantity"]))


def wait_for_full_fill(trade, account_id, cid, qty):
    """Use detail by client ID (history/open-order lists can lag)."""
    deadline = time.monotonic() + ORDER_WAIT_SECONDS
    while time.monotonic() < deadline:
        response = verified(trade.order_v3.get_order_detail(account_id, cid),
                            "sandbox order detail")
        status, entry = detail_status(response, cid)
        if status in {"FILLED", "FULL_FILLED", "FULLY_FILLED", "EXECUTED"}:
            filled = entry.get("filled_quantity", entry.get("filled_qty"))
            if filled is not None and float(filled) + 1e-5 < qty:
                raise RuntimeError("Webull reports filled status but partial quantity")
            print("PAPER_FILLED " + cid, flush=True)
            return
        if status in {"CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "FAILED",
                      "PARTIALLY_CANCELED", "PARTIALLY_CANCELLED"}:
            raise RuntimeError("Paper order did not fill: " + status)
        if status not in {"PENDING", "NEW", "OPEN", "SUBMITTED", "ACCEPTED",
                          "PARTIALLY_FILLED", "PARTIAL_FILLED", "WORKING"}:
            raise RuntimeError("Unknown Webull paper order status: " + status)
        time.sleep(3)
    raise RuntimeError("Paper order still not fully filled: stop without resubmitting")


def checked_portfolio(trade, account_id, allowed_extra=frozenset()):
    equity, cash, positions = portfolio(trade, account_id, allowed_extra=allowed_extra)
    if equity < 100 or cash < 0:
        raise RuntimeError("Unusable sandbox paper account cash/equity")
    exposure = sum(p["value"] for p in positions.values())
    if exposure > equity * 1.001:
        raise RuntimeError("Invalid sandbox portfolio exposure")
    return equity, cash, positions


def make_orders(trade, account_id, targets, quotes, day, expected_exposure=MAX_EXPOSURE,
                allowed_extra=frozenset()):
    """Recalculate balances after EVERY completed sale and buy."""
    if not targets or not math.isclose(sum(targets.values()), expected_exposure,
                                       abs_tol=1e-6):
        raise RuntimeError("Unexpected strategy weights")
    if not 0 < expected_exposure <= MAX_EXPOSURE:
        raise RuntimeError("Invalid strategy sleeve target")
    from strategy_engine import ORIGINAL_EXECUTION_ASSETS
    if set(targets) - ORIGINAL_EXECUTION_ASSETS:
        raise RuntimeError("Trader symbols cannot enter Beethoven target weights")
    count = 0
    equity, cash, holdings = checked_portfolio(trade, account_id, allowed_extra)
    if not isinstance(quotes, SnapshotPrices):
        raise RuntimeError("No verified timestamped Webull paper quotes")
    required = set(targets) | set(holdings)
    def revalidate():
        close_window(datetime.now(NY))
        quotes.validate(required, datetime.now(NY))
    revalidate()  # All required sell/buy/signal inputs before the first write.
    # A tiny remaining scanner position cannot be silently considered "flat".
    if any(sym in allowed_extra and pos["value"] < MIN_ORDER_USD
           for sym, pos in holdings.items()):
        raise RuntimeError("Unliquidatable scanner position below $5; do not claim a clean exit")
    for symbol, position in sorted(holdings.items()):
        excess = position["value"] - equity * targets.get(symbol, 0)
        tolerance = MIN_ORDER_USD if symbol in allowed_extra else max(
            MIN_ORDER_USD, equity * 0.01)
        if excess < tolerance:
            continue
        close_window(datetime.now(NY))
        if symbol not in quotes or quotes[symbol] <= 0:
            raise RuntimeError("Cannot safely value paper sale: " + symbol)
        # Amount capped at verified owned position.
        count += 1
        payload = order_payload(symbol, "SELL",
                                min(excess, position["value"]), quotes[symbol],
                                day, count, allowed_extra=allowed_extra)
        if float(payload["quantity"]) > position["qty"] + 1e-6:
            raise RuntimeError("Attempted paper sale exceeds owned shares")
        preview_and_place(trade, account_id, payload, before_submit=revalidate)
        equity, cash, holdings = checked_portfolio(trade, account_id, allowed_extra)
    # Sell-before-buy: never proceed if a sale has not fully filled.
    for symbol, weight in sorted(targets.items()):
        equity, cash, holdings = checked_portfolio(trade, account_id, allowed_extra)
        shortage = equity * weight - holdings.get(symbol, {}).get("value", 0)
        if shortage < max(MIN_ORDER_USD, equity * 0.01):
            continue
        close_window(datetime.now(NY))
        if symbol not in quotes or quotes[symbol] <= 0:
            raise RuntimeError("No verified Webull paper quote for buy: " + symbol)
        exposure = sum(p["value"] for p in holdings.values())
        budget = min(shortage, cash * 0.98, equity * MAX_EXPOSURE - exposure)
        amount = floor(budget / (1 + BUY_PRICE_BUFFER), 2)
        if amount < MIN_ORDER_USD:
            continue
        count += 1
        payload = order_payload(symbol, "BUY", amount, quotes[symbol], day, count, allowed_extra=allowed_extra)
        # Quantity * buffered market-data price may not exceed cash or headroom.
        reserved = float(payload["quantity"]) * quotes[symbol] * (1 + BUY_PRICE_BUFFER)
        if reserved > cash + 1e-6 or reserved + exposure > equity * MAX_EXPOSURE + 1e-6:
            raise RuntimeError("Paper order price/exposure guard failed")
        preview_and_place(trade, account_id, payload, before_submit=revalidate)
        equity, cash, holdings = checked_portfolio(trade, account_id, allowed_extra)
    print("PAPER_REBALANCE_COMPLETE " + json.dumps({
        "order_count": count,
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "positions": sorted(holdings.keys())}), flush=True)
    return count



def confirmed_signal(data, root, initial_time):
    """Two distinct Webull snapshot evaluations must select identical holdings.

    Both reads use Webull sandbox data; this is a stability check, NOT an
    independent exchange feed or evidence of real-time market-data access.
    Keep the existing 20-minute freshness checks on inputs actually used,
    and require validated execution quotes on every selected holding.
    """
    first_targets, first_quotes = targets_for_now(
        data, root, initial_time, execute=True)
    close_window(datetime.now(NY))
    time.sleep(3)
    second_time = datetime.now(NY)
    close_window(second_time)
    second_targets, second_quotes = targets_for_now(
        data, root, second_time, execute=True)
    if (first_targets.keys() != second_targets.keys()
            or any(not math.isclose(first_targets[s], second_targets[s],
                                    rel_tol=0, abs_tol=1e-6)
                   for s in first_targets)):
        raise RuntimeError("Webull two-sample signal allocation disagreement: NO PAPER ORDERS")
    for symbol in first_targets:
        old, new = first_quotes.get(symbol), second_quotes.get(symbol)
        if not old or not new or not all(
                math.isfinite(x) and x > 0 for x in (old, new)):
            raise RuntimeError("Missing validated two-sample paper order price: " + symbol)
        if abs(new / old - 1) > 0.10:
            raise RuntimeError("Webull selected target price moved >10% between samples: "
                               + symbol)
    print("PAPER_TWO_SAMPLE_AGREEMENT " + json.dumps({
        "first_at": initial_time.isoformat(),
        "second_at": second_time.isoformat(),
        "targets": second_targets, "sandbox_only": True,
        "independent_feed": False, "orders_submitted": 0
    }, sort_keys=True), flush=True)
    return second_targets, second_quotes


def main():
    assert_paper_environment()
    now = datetime.now(NY)
    if now.weekday() >= 5 or not (13 <= now.hour <= 15) or (
            now.hour == 15 and now.minute > 54):
        # Missed sessions must fail visibly, not show a green no-op.
        raise RuntimeError(
            "PAPER_MISSED_WINDOW: GitHub Actions started outside the "
            "13:00-15:54 ET paper staging/execution window; zero orders")
    # The schedule stages at 13:08 ET, well before the unchanged 15:48 ET
    # Composer signal time. Use hours AND minutes to compute the wait.
    signal_time = now.replace(hour=15, minute=48, second=1, microsecond=0)
    remaining = (signal_time - now).total_seconds()
    if remaining > 0:
        print("PAPER_WAIT_FOR_SIGNAL seconds=" + str(int(remaining)), flush=True)
        time.sleep(remaining)
    now = datetime.now(NY)
    close_window(now)

    from webull.core.client import ApiClient
    from webull.data.data_client import DataClient
    from webull.trade.trade_client import TradeClient
    api = ApiClient(os.environ["WEBULL_PAPER_APP_KEY"],
                    os.environ["WEBULL_PAPER_APP_SECRET"], "us")
    api.add_endpoint("us", PAPER_HOST)
    trade, data = TradeClient(api), DataClient(api)
    account_id, index = select_account(trade, execute=True)
    # Never use a shifted/reordered account index, even another CASH account.
    available = verified(trade.account_v2.get_account_list(), "sandbox accounts")
    from webull_paper.readiness import accounts_from
    accounts = accounts_from(available)
    if not selected_account_matches_pin(account_id, accounts, index):
        raise RuntimeError("Designated Webull paper CASH account changed; NO ORDERS")
    day = now.date().isoformat()
    if (STATE_DIR / (day + ".json")).exists():
        print("PAPER_SKIP already claimed today", flush=True)
        return 0
    history_guard(trade.order_v3, account_id, day)
    targets, quotes = confirmed_signal(data, load_strategy(), now)
    trader_enabled = os.getenv("WEBULL_TRADER_PAPER_ENABLED") == "true"
    allowed_extra = frozenset()
    expected_exposure = MAX_EXPOSURE
    if trader_enabled:
        from trader_combo.universe import CANDIDATES, BEETHOVEN_WEIGHT, TRADER_WEIGHT
        allowed_extra = CANDIDATES
        expected_exposure = BEETHOVEN_WEIGHT
        targets = {symbol: weight * BEETHOVEN_WEIGHT / MAX_EXPOSURE
                   for symbol, weight in targets.items()}
        # Fetch today's fresh Webull trade timestamps for trader positions.
        _, _, existing = checked_portfolio(trade, account_id, allowed_extra)
        extra_held = sorted(set(existing) & allowed_extra)
        if extra_held:
            from trader_combo.provenance import verify_scanner_position_ownership
            verify_scanner_position_ownership(trade.order_v3, account_id, extra_held)
            extra_prices, _ = collect_snapshots(
                data, extra_held, datetime.now(NY), require_fresh=True,
                clock=lambda: datetime.now(NY))
            quotes.update(extra_prices)
            quotes.trade_times.update(extra_prices.trade_times)
            quotes.required.update(extra_held)
        print("PAPER_COMBINED_ALLOCATION " + json.dumps({
            "beethoven_weight": BEETHOVEN_WEIGHT,
            "scanner_weight": TRADER_WEIGHT,
            "scanner_positions_to_close": extra_held,
            "no_overnight_scanner_positions_intended": True
        }, sort_keys=True), flush=True)
    close_window(datetime.now(NY))
    equity, cash, held = checked_portfolio(trade, account_id, allowed_extra)
    print("PAPER_AUTO_SIGNAL " + json.dumps({
        "date": day, "paper_only": True, "cash": round(cash, 2),
        "equity": round(equity, 2), "targets": targets,
        "position_symbols": sorted(held)}), flush=True)
    # Re-check broker state immediately before any write.
    history_guard(trade.order_v3, account_id, day)
    claim_day(day)
    make_orders(trade, account_id, targets, quotes, day,
                expected_exposure=expected_exposure, allowed_extra=allowed_extra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
