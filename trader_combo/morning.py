"""OG Trader Skill ORB: independently evaluated Webull SANDBOX PAPER sleeve.

Legacy 80/19 Beethoven mode stays unchanged unless shared 50/50 is enabled.
In 50/50 mode ORB and seven-agent desk share pinned CASH account 0,
with separate 49.5% investable limits, distinct fills/reviews and 1% cash.
Stop/target estimates are NOT live broker stop/target orders.
"""
import hashlib
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

from strategy_engine import ORIGINAL_EXECUTION_ASSETS
from trader_combo.universe import (
    CANDIDATES, BEETHOVEN_WEIGHT, TRADER_WEIGHT, MAX_POSITIONS,
    MAX_TOTAL_EXPOSURE, MAX_STOP_DISTANCE, MIN_STOP_DISTANCE,
    MAX_TRADE_LOSS_FRACTION,
)
from trader_combo.scan import run_scan
from trader_combo.shared_sleeves import (
    AGENT_SYMBOLS, ORB_FRACTION, GROSS_FRACTION, CASH_RESERVE,
    owned_positions, shared_mode, validate_ownership_history,
)
from webull_paper.signal_dry_run import NY, SANDBOX
from webull_paper.sessions import regular_session
from webull_paper.paper_orders import (
    collect_snapshots, order_payload, select_account, verified, floor,
)
from webull_paper.automatic import (
    PAPER_HOST, PINNED_SANDBOX_CASH_SHA256, BUY_PRICE_BUFFER,
    selected_account_matches_pin, checked_portfolio, order_items,
    preview_and_place,
)

STATE_DIR = Path("state/trader-paper")
# Stage before the intended entry and tolerate delayed GitHub cron dispatches.
# Neither staging nor waiting may send an order; morning_guard checks every write.
SCANNER_STAGE_MINUTE = 9 * 60 + 5
SCANNER_ENTRY_MINUTE = 10 * 60 + 25
SCANNER_STOP_MINUTE = 10 * 60 + 40


def morning_wait_seconds(now):
    """Return pre-entry wait on full trading days; reject missed/early starts.

    GitHub scheduled runs may begin tens of minutes late. Fail visibly if the
    entry window has already passed rather than chasing an old ORB setup.
    """
    if now.tzinfo is None:
        raise RuntimeError("Scanner staging time needs timezone")
    local = now.astimezone(NY)
    minutes = local.hour * 60 + local.minute
    if (not regular_session(local) or
            not SCANNER_STAGE_MINUTE <= minutes < SCANNER_STOP_MINUTE):
        raise RuntimeError("TRADER_MISSED_WINDOW: outside 09:05-10:40 ET paper staging/entry window; zero orders")
    signal_time = local.replace(hour=10, minute=25, second=0, microsecond=0)
    return max(0.0, (signal_time - local).total_seconds())


def morning_guard(now):
    if now.tzinfo is None:
        raise RuntimeError("Scanner trade time needs timezone")
    local = now.astimezone(NY)
    minutes = local.hour * 60 + local.minute
    if not regular_session(local) or not (10 * 60 + 20 <= minutes < 10 * 60 + 40):
        raise RuntimeError("Trader sleeve only trades 10:20-10:40 ET on regular market days")
    return True


def assert_sandbox():
    if PAPER_HOST != SANDBOX or SANDBOX != "api.sandbox.webull.com":
        raise RuntimeError("Trader scanner production brokerage FORBIDDEN")
    if os.getenv("WEBULL_PAPER_EXECUTE_ENABLED") != "true" or (
            os.getenv("WEBULL_TRADER_PAPER_ENABLED") != "true"):
        raise RuntimeError("Trader sleeve requires explicit PAPER enablement")
    if os.getenv("WEBULL_PAPER_ACCOUNT_INDEX") != "0":
        raise RuntimeError("Trader sleeve only supports pinned sandbox account index 0")
    if not os.getenv("WEBULL_PAPER_APP_KEY") or not os.getenv("WEBULL_PAPER_APP_SECRET"):
        raise RuntimeError("Missing sandbox-only credentials")
    if not PINNED_SANDBOX_CASH_SHA256:
        raise RuntimeError("Missing sandbox CASH account pin")


def scanner_history_guard(trade, account, day):
    active = order_items(
        verified(trade.order_v3.get_order_open(account_id=account), "open orders"),
        "open orders")
    if active:
        raise RuntimeError("Open sandbox orders: do not run another scanner trade")
    prior = order_items(
        verified(trade.order_v3.get_order_history(account, page_size=100), "order history"),
        "order history")
    if len(prior) >= 100:
        raise RuntimeError("Unbounded order history; cannot confirm scanner dedupe")
    prefix = "tr" + day.replace("-", "")
    if any(str(p.get("client_order_id") or "").startswith(prefix) for p in prior):
        raise RuntimeError("Already placed Trader sleeve orders today")
    return True


def proposed_entries(signals, equity, cash, holdings, fresh_quotes, *, shared=False):
    """Budget/stop sizing, independent from the other strategy's allocation."""
    weight = ORB_FRACTION if shared else TRADER_WEIGHT
    if equity < 100 or cash < 0 or not 0 < weight < 0.50:
        raise RuntimeError("Unusable paper sleeve equity/cash")
    trader_value = sum(x["value"] for s, x in holdings.items() if s in CANDIDATES)
    exposure = sum(x["value"] for x in holdings.values())
    if shared:
        owned_positions(holdings,equity=equity,cash=cash)
        if trader_value > .01:
            raise RuntimeError("ORB overnight or existing scanner shares need reconciliation")
        if exposure > equity * GROSS_FRACTION + .01:
            raise RuntimeError("Shared sandbox already over-allocated")
    else:
        beethoven_value = sum(x["value"] for s, x in holdings.items()
                             if s in ORIGINAL_EXECUTION_ASSETS)
        if trader_value > 0.01 or beethoven_value > equity * (BEETHOVEN_WEIGHT + 0.005):
            raise RuntimeError("Scanner sleeve cannot trade with legacy 99% Beethoven or held scanner positions")
        if exposure > equity * (BEETHOVEN_WEIGHT + 0.005):
            raise RuntimeError("Scanner already over-allocated or has unmanaged holdings")
    if not signals:
        return []
    amount_left = min(equity * weight, max(0, cash - equity * CASH_RESERVE),
                      max(0, equity * MAX_TOTAL_EXPOSURE - exposure))
    budget_per = equity * weight / min(MAX_POSITIONS, len(signals))
    decisions = []
    for candidate in signals[:MAX_POSITIONS]:
        symbol = candidate["symbol"]
        price = fresh_quotes.get(symbol)
        if symbol not in CANDIDATES or not isinstance(price, (float, int)) or not math.isfinite(price) or price <= 0:
            raise RuntimeError("Invalid or unauthorized scanner execution quote")
        if abs(price / candidate["signal_price"] - 1) > 0.01:
            continue  # Gap already moved; never chase Yahoo's stale signal
        stop = (candidate["range_low"] + candidate["range_high"]) / 2
        distance = (price - stop) / price
        if not MIN_STOP_DISTANCE <= distance <= MAX_STOP_DISTANCE:
            continue
        estimated_loss_limit = equity * MAX_TRADE_LOSS_FRACTION
        price_budget = estimated_loss_limit / distance
        cash_budget = min(amount_left, budget_per, price_budget) / (1 + BUY_PRICE_BUFFER)
        amount = floor(cash_budget, 2)
        if amount < 5 or price > amount:
            continue  # No fractional stock shares without verified broker eligibility
        shares = int(amount // price)
        if shares < 1:
            continue
        reserved = shares * price * (1 + BUY_PRICE_BUFFER)
        if reserved + exposure > equity * MAX_TOTAL_EXPOSURE + 1e-8 or reserved > cash - equity * .01:
            continue
        decisions.append({"symbol": symbol, "price": float(price), "shares": shares,
                          "stop_reference": round(stop, 4),
                          "target_reference": round(price + 2 * (price - stop), 4),
                          "estimated_loss_at_stop": round(shares * (price - stop), 2),
                          "gross_reserved": round(reserved, 2)})
        amount_left -= reserved
        if amount_left < 5:
            break
    return decisions


def claim_day(day):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / (day + ".json")).open("x") as handle:
        json.dump({"day": day, "trader": "Webull SANDBOX only", "claimed": True}, handle)


def main():
    assert_sandbox()
    seconds = morning_wait_seconds(datetime.now(NY))
    if seconds > 0:
        print("PAPER_TRADER_WAIT_FOR_SIGNAL seconds=" + str(int(seconds)), flush=True)
        time.sleep(seconds)
    morning_guard(datetime.now(NY))
    now = datetime.now(NY)
    day = now.date().isoformat()
    if (STATE_DIR / (day + ".json")).exists():
        raise RuntimeError("Local scanner session already claimed")
    # Owner can instantly stop all AI-approved morning orders without disabling
    # Beethoven, modifying OAuth/IAP, or changing brokerage credentials.
    if os.getenv("AI_PAPER_BROKER_KILL_SWITCH") == "true":
        print("PAPER_AI_BROKER_KILLED; zero orders", flush=True)
        return 0
    # Agents may approve only the existing 19% ORB sleeve; never submit orders
    # directly, alter Beethoven, or expand the ticker universe.
    if not shared_mode() and os.getenv("AI_DESK_PAPER_GATE_ENABLED") == "true":
        from trader_combo.agent_gate import fetch_agent_gate
        decision = fetch_agent_gate(now.date())
        print("PAPER_AI_DESK_GATE " + json.dumps({
            **decision, "mode": "existing_orb_sleeve_only",
            "additional_allocation": 0, "direct_agent_orders": 0,
        }, sort_keys=True), flush=True)
        if not decision["approved"]:
            return 0
    # Read market setups first. A failure never sends a broker order.
    signals = run_scan(now)
    morning_guard(datetime.now(NY))
    from webull.core.client import ApiClient
    from webull.trade.trade_client import TradeClient
    from webull.data.data_client import DataClient
    api = ApiClient(os.environ["WEBULL_PAPER_APP_KEY"],
                    os.environ["WEBULL_PAPER_APP_SECRET"], "us")
    api.add_endpoint("us", PAPER_HOST)
    trade, data = TradeClient(api), DataClient(api)
    account, index = select_account(trade, execute=True)
    from webull_paper.readiness import accounts_from
    accounts = accounts_from(verified(trade.account_v2.get_account_list(), "sandbox accounts"))
    if not selected_account_matches_pin(account, accounts, index):
        raise RuntimeError("Scanner did not match verified CASH account pin")
    scanner_history_guard(trade, account, day)
    equity, cash, holdings = checked_portfolio(trade, account, CANDIDATES)
    # Fail before any write on unexpected holdings or an unreduced Beethoven allocation.
    shared=shared_mode()
    if shared:
        owned_positions(holdings,equity=equity,cash=cash)
        validate_ownership_history(trade, account, holdings, day)
    elif set(holdings) - (ORIGINAL_EXECUTION_ASSETS | CANDIDATES):
        raise RuntimeError("Unknown holdings")
    fresh = {}
    trade_times = {}
    if signals:
        from webull_paper.paper_orders import collect_snapshots
        fetched, _ = collect_snapshots(
            data, [s["symbol"] for s in signals], datetime.now(NY),
            require_fresh=True, clock=lambda: datetime.now(NY))
        for symbol, price in fetched.items():
            age = (datetime.now(NY) - fetched.trade_times[symbol]).total_seconds()
            if age < 0 or age > 120:
                raise RuntimeError("Trader intraday entry requires <=120s Webull quote freshness")
            fresh[symbol] = price
            trade_times[symbol] = fetched.trade_times[symbol]
    decisions = proposed_entries(signals, equity, cash, holdings, fresh, shared=shared)
    print("PAPER_TRADER_PLAN " + json.dumps({
        "date": day, "mode": "sandbox_only", "source": "OG Trader Skill ORB",
        "beethoven_allocation": 0 if shared else BEETHOVEN_WEIGHT,
        "scanner_allocation": ORB_FRACTION if shared else TRADER_WEIGHT,
        "agent_allocation": ORB_FRACTION if shared else 0,
        "separate_strategy_reports": shared,
        "candidates_checked": len(CANDIDATES), "signals": len(signals),
        "orders_planned": decisions, "stop_orders_submitted": False,
        "exit_plan": ("Same-day 15:48 ET shared ORB-only close (best effort)"
                      if shared else "Same-day 15:48 ET close by Beethoven job (best effort)")
    }, sort_keys=True), flush=True)
    if not decisions:
        return 0
    morning_guard(datetime.now(NY))
    scanner_history_guard(trade, account, day)
    claim_day(day)  # Never retry an uncertain submitted order on this runner.
    for i, d in enumerate(decisions, 1):
        morning_guard(datetime.now(NY))
        equity2, cash2, holdings2 = checked_portfolio(trade, account, CANDIDATES)
        exposure = sum(v["value"] for v in holdings2.values())
        reserved = d["gross_reserved"]
        if shared:
            owned_positions(holdings2,equity=equity2,cash=cash2)
            validate_ownership_history(trade,account,holdings2,day)
        trader_exposure = sum(v["value"] for s, v in holdings2.items()
                              if s in CANDIDATES)
        sleeve_limit = ORB_FRACTION if shared else TRADER_WEIGHT
        if (exposure + reserved > equity2 * MAX_TOTAL_EXPOSURE + 1e-6
                or trader_exposure + reserved > equity2 * sleeve_limit + 1e-6
                or cash2 - reserved < equity2 * CASH_RESERVE):
            raise RuntimeError("Rechecked scanner order would exceed sleeve or cash")
        payload = order_payload(
            d["symbol"], "BUY", d["shares"] * d["price"], d["price"], day, i,
            allowed_extra=CANDIDATES)
        payload["client_order_id"] = "tr" + payload["client_order_id"][2:]
        if float(payload["quantity"]) != d["shares"]:
            raise RuntimeError("Scanner order quantity did not pass exact preflight")
        def check_signal_stamp():
            morning_guard(datetime.now(NY))
            age = (datetime.now(NY) - trade_times[d["symbol"]]).total_seconds()
            if not 0 <= age <= 120:
                raise RuntimeError("Trader quote stale immediately before sandbox order")
        preview_and_place(trade, account, payload,
                          before_submit=check_signal_stamp, session_check=morning_guard)
        print("PAPER_TRADER_FILL_RECORDED " + json.dumps({
            "symbol": d["symbol"], "quantity": d["shares"],
            "paper_only": True, "stop_reference": d["stop_reference"],
            "target_reference": d["target_reference"],
            "stop_order_live": False
        }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
