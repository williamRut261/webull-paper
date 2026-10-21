"""Identify scanner-owned holdings from Webull's actual sandbox order history.

A matching approved ticker alone is not proof that the automation owns a manual
sandbox holding. Fail closed rather than liquidating a user-created position.
"""
import re

from trader_combo.universe import CANDIDATES
from webull_paper.automatic import order_items
from webull_paper.paper_orders import verified

SCANNER_BUY_ID = re.compile(r"^tr[0-9]{8}B[0-9]{2}([A-Z][A-Z0-9]{0,9})$")


def verify_scanner_position_ownership(order_api, account_id, symbols):
    held = frozenset(symbols)
    if not held:
        return True
    if held - CANDIDATES:
        raise RuntimeError("Unapproved scanner holding cannot be liquidated")
    payload = verified(order_api.get_order_history(account_id, page_size=100),
                       "scanner position order history")
    orders = order_items(payload, "scanner position order history")
    if len(orders) >= 100:
        raise RuntimeError("Scanner ownership order history incomplete; no liquidation")
    known = set()
    for row in orders:
        cid = str(row.get("client_order_id") or "")
        match = SCANNER_BUY_ID.fullmatch(cid)
        if not match:
            continue
        ticker = match.group(1)
        # The ID must agree with the broker's ticker when populated.
        if row.get("symbol") not in (None, "", ticker):
            raise RuntimeError("Scanner order history symbol mismatch")
        state = str(row.get("order_status") or row.get("status") or "").upper()
        # A recognized prior filled trade is evidence, never an unfilled order.
        if state in {"FILLED", "FULL_FILLED", "FULLY_FILLED", "EXECUTED"}:
            known.add(ticker)
    if held - known:
        raise RuntimeError("Scanner-held symbols lack filled bot-buy provenance: " +
                           ",".join(sorted(held - known)))
    return True
