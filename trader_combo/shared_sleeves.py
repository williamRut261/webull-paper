"""Shared Webull SANDBOX CASH account: independently attributed 49.5% sleeves.

One brokerage account, two strategy owners: OG ORB (tr/tc IDs), and seven-agent
desk (ag IDs).  Each owns 50% of the 99% investable equity, with 1% cash
reserved. Never infer ownership from ticker alone or trade legacy holdings.
No order submission or broker imports in this module.
"""
import os
from trader_combo.universe import CANDIDATES

SHARED_FLAG = "WEBULL_SHARED_5050_ENABLED"
AGENT_SYMBOLS = frozenset(("SPY", "QQQ"))
ORB_SYMBOLS = CANDIDATES
ORB_FRACTION = 0.495
AGENT_FRACTION = 0.495
CASH_RESERVE = 0.01
GROSS_FRACTION = ORB_FRACTION + AGENT_FRACTION
ORB_PREFIXES = ("tr", "tc")
AGENT_PREFIX = "ag"

if AGENT_SYMBOLS & ORB_SYMBOLS:
    raise RuntimeError("Agent and ORB order ownership universes overlap")
if abs(GROSS_FRACTION + CASH_RESERVE - 1.0) > 1e-9:
    raise RuntimeError("Shared sandbox allocation does not total 100%")


def shared_mode():
    return os.getenv(SHARED_FLAG) == "true"


def owned_positions(positions, *, equity=None, cash=None):
    """Reject all unknown/legacy holdings before any shared sleeve order."""
    if not isinstance(positions, dict):
        raise RuntimeError("Unverified sandbox holdings")
    if set(positions) - (AGENT_SYMBOLS | ORB_SYMBOLS):
        raise RuntimeError("Legacy or unmanaged holding blocks shared 50/50 cutover")
    groups = {"orb": {}, "agents": {}}
    for symbol, position in positions.items():
        if not isinstance(position, dict) or not isinstance(position.get("value"), (int, float)):
            raise RuntimeError("Unverified sandbox position valuation")
        if position["value"] < 0:
            raise RuntimeError("Invalid sandbox position value")
        groups["agents" if symbol in AGENT_SYMBOLS else "orb"][symbol] = position
    if equity is not None or cash is not None:
        if not isinstance(equity, (int, float)) or not isinstance(cash, (int, float)) or equity < 100 or cash < 0:
            raise RuntimeError("Invalid shared sandbox equity/cash")
        if sum(p["value"] for p in groups["orb"].values()) > equity * ORB_FRACTION + .01:
            raise RuntimeError("ORB sleeve exceeds its 49.5% limit")
        if sum(p["value"] for p in groups["agents"].values()) > equity * AGENT_FRACTION + .01:
            raise RuntimeError("Seven-agent sleeve exceeds its 49.5% limit")
        if sum(p["value"] for p in positions.values()) > equity * GROSS_FRACTION + .01:
            raise RuntimeError("Combined sandbox positions exceed 99%")
    return groups


def permitted_monday_cutover_order(row, trading_day):
    """Only the one broker-verified 63-GDXU migration SELL can coexist with sleeves.

    This exception is bounded to Monday and the known exact order identity.
    Unknown or pending cutover orders remain fail-closed.
    """
    return (
        trading_day == "2026-10-26"
        and str(row.get("client_order_id") or "") == "mc20261026S01GDXU"
        and row.get("symbol") == "GDXU"
        and str(row.get("side") or "").upper() == "SELL"
        and str(row.get("order_status") or row.get("status") or row.get("orderStatus") or "").upper()
            in {"FILLED", "FULL_FILLED", "FULLY_FILLED", "EXECUTED"}
        and str(row.get("create_time") or row.get("created_at") or row.get("place_time_at") or "").startswith("2026-10-26")
    )


def validate_ownership_history(trade, account_id, positions, trading_day):
    """Require actual FILLED strategy orders for every held symbol.

    Brokerage history may be incomplete. In that case reject rather than
    silently claiming ownership or trying to liquidate another strategy.
    """
    from webull_paper.automatic import order_items
    from webull_paper.paper_orders import verified
    rows = order_items(verified(
        trade.order_v3.get_order_history(account_id, page_size=100),
        "shared sandbox order history"), "shared sandbox order history")
    if len(rows) >= 100:
        raise RuntimeError("Shared account order history may be truncated")
    owners = {}
    for row in rows:
        symbol = row.get("symbol")
        cid = str(row.get("client_order_id") or "")
        status = str(row.get("order_status") or row.get("status") or row.get("orderStatus") or "").upper()
        day = str(row.get("create_time") or row.get("created_at") or row.get("place_time_at") or "")
        if day.startswith(trading_day) and not (cid.startswith(("tr", "tc", "ag")) or permitted_monday_cutover_order(row, trading_day)):
            raise RuntimeError("Non-sleeve broker order today blocks shared account")
        if symbol not in positions:
            continue
        expected = AGENT_PREFIX if symbol in AGENT_SYMBOLS else ORB_PREFIXES
        if not cid.startswith(expected):
            raise RuntimeError("Held shares lack matching strategy provenance")
        if status in {"FILLED", "FULL_FILLED", "FULLY_FILLED", "EXECUTED"}:
            owners[symbol] = True
    if set(owners) != set(positions):
        raise RuntimeError("Cannot establish filled-order provenance of shared holdings")
    return True
