"""Private, read-only Webull OpenAPI SANDBOX portfolio viewer for Google Cloud Run.

This module has no endpoint, import, or invocation for order placement.
Every request requires a Google-signed IAP assertion with a pinned audience.
Do not deploy with anonymous access or without Cloud Run IAP.
"""
from datetime import datetime, timezone
import hashlib
import hmac
import math
import os
import re

from flask import Flask, abort, make_response, render_template_string, request
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

SANDBOX_HOST = "api.sandbox.webull.com"
PIN_REGEX = re.compile(r"[a-fA-F0-9]{64}\Z")
IAP_AUDIENCE_PATTERN = re.compile(
    r"/projects/[0-9]+/locations/[a-z0-9-]+/services/[a-z0-9-]+\Z"
)
app = Flask(__name__)


def verified(result, name):
    if int(result.status_code) != 200:
        raise RuntimeError(name + " unavailable")
    return result.json()


def records(value, names):
    """Only documented top-level lists or unambiguous wrapper lists."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for name in names:
            child = value.get(name)
            if isinstance(child, list):
                return child
            if isinstance(child, dict):
                for second in names:
                    if isinstance(child.get(second), list):
                        return child[second]
    raise ValueError("Unexpected broker response shape")


def amount(value):
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("amount", value.get("value"))
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def dollars(number):
    return "Unavailable" if number is None else f"\${number:,.2f}"


def choose_account(accounts, index, sha256):
    if not PIN_REGEX.fullmatch(sha256):
        raise ValueError("Missing or invalid account fingerprint")
    rows = records(accounts, ("data", "accounts", "list", "results"))
    if not index.isdecimal() or int(index) >= len(rows):
        raise RuntimeError("Configured paper account index unavailable")
    row = rows[int(index)]
    if not isinstance(row, dict) or row.get("account_type") != "CASH":
        raise RuntimeError("Verified paper CASH account unavailable")
    identifier = row.get("account_id")
    if identifier is None or not hmac.compare_digest(
        hashlib.sha256(str(identifier).encode()).hexdigest(), sha256.lower()
    ):
        raise RuntimeError("Paper sandbox account fingerprint mismatch")
    return identifier


def normalize_positions(raw):
    items = records(raw, ("data", "positions", "list", "results"))
    positions = []
    for entry in items:
        if not isinstance(entry, dict):
            raise RuntimeError("Invalid broker position")
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9.]{1,12}", symbol):
            raise RuntimeError("Unrecognized broker position symbol")
        quantity = amount(entry.get("quantity"))
        last = amount(entry.get("last_price"))
        positions.append({
            "symbol": symbol, "quantity": quantity, "last_price": dollars(last),
            "market_value": dollars(last * quantity)
            if last is not None and quantity is not None else "Unavailable",
        })
    return positions


def normalize_history(raw):
    items = records(raw, ("data", "orders", "list", "results", "items"))
    result = []
    for entry in items[:100]:
        if not isinstance(entry, dict):
            continue
        result.append({
            "date": str(entry.get("create_time") or entry.get("created_time")
                        or entry.get("order_time") or "Unavailable")[:40],
            "symbol": str(entry.get("symbol") or "—")[:12],
            "side": str(entry.get("side") or "—")[:10],
            "status": str(entry.get("order_status") or entry.get("status")
                          or "Unknown")[:30],
            "quantity": str(entry.get("filled_quantity")
                            or entry.get("quantity") or "—")[:20],
            "price": dollars(amount(entry.get("avg_fill_price")
                                     or entry.get("average_filled_price"))),
        })
    return result


def read_snapshot(trade, expected_pin, index="0"):
    """Get-only broker calls against a verified sandbox account."""
    account_id = choose_account(
        verified(trade.account_v2.get_account_list(), "accounts"),
        index, expected_pin,
    )
    balance = verified(trade.account_v2.get_account_balance(account_id), "balance")
    if not isinstance(balance, dict):
        raise RuntimeError("Unexpected balance response")
    equity = amount(balance.get("total_net_liquidation_value"))
    cash = amount(balance.get("total_cash_balance"))
    if equity is None or cash is None:
        raise RuntimeError("Sandbox equity or cash unavailable")
    positions = normalize_positions(
        verified(trade.account_v2.get_account_position(account_id), "positions")
    )
    try:
        history = normalize_history(verified(
            trade.order_v3.get_order_history(account_id, page_size=100), "order history"
        ))
        history_note = "Latest available 100 orders at most; not a full-history guarantee."
    except Exception:
        history, history_note = [], "Order history unavailable; no history is inferred."
    return {
        "equity": dollars(equity), "cash": dollars(cash),
        "positions": positions, "history": history,
        "history_note": history_note,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "source": "Verified Webull OpenAPI SANDBOX (not native paper trading)",
    }


def sandbox_trade_client():
    from webull.core.client import ApiClient
    from webull.trade.trade_client import TradeClient
    key = os.getenv("WEBULL_PAPER_APP_KEY", "").strip()
    secret = os.getenv("WEBULL_PAPER_APP_SECRET", "").strip()
    if not key or not secret:
        raise RuntimeError("Missing sandbox credentials")
    sdk = ApiClient(key, secret, "us")
    sdk.add_endpoint("us", SANDBOX_HOST)
    return TradeClient(sdk)


def authorized_user():
    audience = os.getenv("IAP_AUDIENCE", "")
    jwt_token = request.headers.get("X-Goog-Iap-Jwt-Assertion", "")
    email = os.getenv("DASHBOARD_ALLOWED_EMAIL", "").lower().strip()
    if not IAP_AUDIENCE_PATTERN.fullmatch(audience) or not jwt_token or not email:
        abort(403)
    try:
        decoded = id_token.verify_token(
            jwt_token, GoogleRequest(), audience=audience,
            certs_url="https://www.gstatic.com/iap/verify/public_key",
        )
        if (decoded.get("iss") != "https://cloud.google.com/iap"
                or decoded.get("email", "").lower() != email):
            abort(403)
    except Exception:
        abort(403)
    return email


TEMPLATE = """
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Webull PAPER — Portfolio</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,sans-serif}
body{background:#101522;color:#e9eff8;max-width:1100px;margin:0 auto;padding:28px 18px}
header{display:flex;align-items:center;justify-content:space-between;gap:16px}
h1{font-size:1.65rem;margin:.15em 0}h2{font-size:1.15rem}
a{color:#93c5fd}small,.muted{color:#aab8cc}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:22px 0}
.box{background:#1c2535;padding:18px;border-radius:14px;border:1px solid #364356}
.number{font-size:2rem;font-variant-numeric:tabular-nums;font-weight:700;margin-top:10px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:11px 8px;border-bottom:1px solid #364356}
th{color:#bdcbe0;font-weight:500}td{font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
.btn{border:1px solid #566d8c;border-radius:8px;padding:9px 12px;white-space:nowrap}
</style></head><body>
<header><div><small>WEBULL OPENAPI SANDBOX ONLY</small><h1>Paper Portfolio</h1></div>
<a class="btn" href="/">Refresh</a></header>
<p class="muted">Read-only · {{ snapshot.as_of }} · {{ snapshot.source }}</p>
<div class="stats"><section class="box"><small>Total account equity</small>
<div class="number">{{ snapshot.equity }}</div></section>
<section class="box"><small>Cash balance</small><div class="number">{{ snapshot.cash }}</div></section></div>
<section class="box"><h2>Current positions</h2><div class="scroll"><table>
<tr><th>Symbol</th><th>Quantity</th><th>Last price</th><th>Market value</th></tr>
{% for p in snapshot.positions %}<tr><td>{{p.symbol}}</td><td>{{p.quantity}}</td>
<td>{{p.last_price}}</td><td>{{p.market_value}}</td></tr>
{% else %}<tr><td colspan="4">No positions returned by the broker.</td></tr>{% endfor %}
</table></div></section><div style="height:16px"></div>
<section class="box"><h2>Recent orders</h2><p class="muted">{{ snapshot.history_note }}</p>
<div class="scroll"><table><tr><th>Date</th><th>Symbol</th><th>Side</th>
<th>Status</th><th>Quantity</th><th>Average fill</th></tr>
{% for o in snapshot.history %}<tr><td>{{o.date}}</td><td>{{o.symbol}}</td>
<td>{{o.side}}</td><td>{{o.status}}</td><td>{{o.quantity}}</td>
<td>{{o.price}}</td></tr>
{% else %}<tr><td colspan="6">No order records shown.</td></tr>{% endfor %}</table>
</div></section><p class="muted">Order rows are not necessarily executions.
This page cannot place, cancel or modify trades.</p>
</body></html>
"""


@app.get("/")
def index():
    authorized_user()
    try:
        snapshot = read_snapshot(
            sandbox_trade_client(),
            os.getenv("WEBULL_PAPER_ACCOUNT_SHA256", ""),
            os.getenv("WEBULL_PAPER_ACCOUNT_INDEX", "0"),
        )
    except Exception:
        # Do not disclose broker responses, account identifiers, or secret values.
        abort(502, "Sandbox data unavailable or account verification failed")
    response = make_response(render_template_string(TEMPLATE, snapshot=snapshot))
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    return response
