"""Private, read-only Webull OpenAPI SANDBOX portfolio viewer for Google Cloud Run.

This module has no endpoint, import, or invocation for order placement.
Every request requires a Google-signed IAP assertion with a pinned audience.
Do not deploy with anonymous access or without Cloud Run IAP.
"""
from datetime import datetime, timezone, date
import json
from urllib.request import Request as UrlRequest, urlopen
import hashlib
import hmac
import logging
import math
import os
import re

from flask import Flask, abort, make_response, render_template, render_template_string, request
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
    if number is None:
        return "Unavailable"
    return f"${(0.0 if abs(number) < 0.005 else number):,.2f}"


def first_value(entry, names):
    """Return the first present field while preserving valid zero values."""
    for name in names:
        value = entry.get(name)
        if value is not None and value != "":
            return value
    return None


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
        position_value = last * quantity if last is not None and quantity is not None else None
        positions.append({
            "symbol": symbol, "quantity": quantity, "last_price": dollars(last),
            "market_value": dollars(position_value),
            "market_value_raw": position_value,
        })
    return positions


def normalize_history(raw):
    items = records(raw, ("data", "orders", "list", "results", "items"))
    result = []
    for group in items:
        if not isinstance(group, dict):
            continue
        nested = group.get("orders")
        entries = nested if isinstance(nested, list) else [group]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # History responses group one or more actual orders under a parent
            # record. Parent fields are used only as fallback metadata.
            order = {**group, **entry}
            filled = first_value(order, ("filled_quantity",))
            total = first_value(order, ("total_quantity", "quantity"))
            quantity = (
                f"{filled} / {total}" if filled is not None and total is not None
                else str(filled if filled is not None else total or "—")
            )
            fill_price = amount(first_value(
                order, ("filled_price", "avg_fill_price", "average_filled_price")
            ))
            if filled is not None and amount(filled) == 0:
                fill_price = None
            result.append({
                "date": str(first_value(order, (
                    "place_time_at", "create_time", "created_time", "order_time",
                    "place_time", "filled_time_at",
                )) or "Unavailable")[:40],
                "symbol": str(first_value(order, ("symbol",)) or "—")[:12],
                "side": str(first_value(order, ("side",)) or "—")[:10],
                "status": str(first_value(order, (
                    "status", "order_status",
                )) or "Unknown")[:30],
                "quantity": quantity[:40],
                "price": dollars(fill_price),
            })
            if len(result) >= 100:
                return result
    return result


def _read_stage(stage, operation, *, optional=False):
    """Log only the stage and exception class; never broker data or exception text."""
    try:
        return operation()
    except Exception as error:
        log = app.logger.warning if optional else app.logger.error
        log(
            "webull_sandbox_dashboard_read_failed stage=%s exception_type=%s",
            stage, type(error).__name__,
        )
        raise


def read_snapshot(trade, expected_pin, index="0"):
    """Get-only broker calls against a verified sandbox account."""
    accounts = _read_stage(
        "account_list",
        lambda: verified(trade.account_v2.get_account_list(), "accounts"),
    )
    account_id = _read_stage(
        "account_verification",
        lambda: choose_account(accounts, index, expected_pin),
    )

    def read_balance():
        balance = verified(
            trade.account_v2.get_account_balance(account_id), "balance"
        )
        if not isinstance(balance, dict):
            raise RuntimeError("Unexpected balance response")
        equity = amount(balance.get("total_net_liquidation_value"))
        cash = amount(balance.get("total_cash_balance"))
        if equity is None or cash is None:
            raise RuntimeError("Sandbox equity or cash unavailable")
        return equity, cash, amount(balance.get("total_market_value"))

    equity, cash, broker_market_value = _read_stage("account_balance", read_balance)
    positions = _read_stage(
        "positions",
        lambda: normalize_positions(verified(
            trade.account_v2.get_account_position(account_id), "positions"
        )),
    )
    try:
        history = _read_stage(
            "order_history",
            lambda: normalize_history(verified(
                trade.order_v3.list_order_history(account_id),
                "order history",
            )),
            optional=True,
        )
        history_note = (
            "Latest available history page; Webull may delay status updates. "
            "Filled / total quantities are shown where available."
        )
    except Exception:
        history, history_note = [], "Order history unavailable; no history is inferred."
    # Last-price x quantity is a client-side estimate and may not equal the
    # broker's authoritative total_market_value. Never silently force a match.
    quoted_total = (
        sum(p["market_value_raw"] for p in positions)
        if all(p["market_value_raw"] is not None for p in positions)
        else None
    )
    broker_vs_quotes = (
        round(broker_market_value - quoted_total, 2)
        if broker_market_value is not None and quoted_total is not None else None
    )
    unallocated_equity = (
        round(equity - cash - broker_market_value, 2)
        if broker_market_value is not None else None
    )
    return {
        "equity": dollars(equity), "cash": dollars(cash),
        "broker_market_value": dollars(broker_market_value),
        "quoted_market_value": dollars(quoted_total),
        "quote_difference": dollars(broker_vs_quotes),
        "equity_residual": dollars(unallocated_equity),
        "balance_note": (
            "Broker-reported holdings and share × last-price estimates may differ "
            "because of pricing timestamps or valuations. The remaining equity "
            "difference is an UNEXPLAINED accounting residual, not trading profit. "
            "Consult detailed Webull balance fields before attributing it."
        ),
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
    # The SDK defaults to writing a log in the read-only /app directory and
    # can include broker exception details. Keep its file output ephemeral and
    # above all normal/error events; dashboard diagnostics remain stage-only.
    sdk.set_file_logger(
        path="/tmp/webull_trade_sdk.log",
        log_level=logging.CRITICAL,
    )
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



# This public JSON contains ONLY sanitized market research and independent
# VIRTUAL paper metrics. It never contains brokerage identifiers or secrets.
AGENT_FEED = (
    "https://raw.githubusercontent.com/williamRut261/webull-paper/"
    "main/research/ai_desk_status.json"
)
AGENT_ROLES = (
    "Market Analyst", "Technical Analyst", "News Researcher",
    "Strategy Analyst", "Risk Manager", "Desk Lead", "Trade Reviewer",
)


def read_agent_feed(opener=urlopen):
    """Best-effort advisory view. It cannot influence any broker decision."""
    req = UrlRequest(AGENT_FEED, headers={"User-Agent": "paper-dashboard-readonly"})
    with opener(req, timeout=3) as response:
        raw = response.read(30001)
    if len(raw) > 30000:
        raise ValueError("Research feed oversized")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("Invalid research feed")
    agents = data.get("agents")
    if not isinstance(agents, list) or len(agents) not in (0, 7):
        raise ValueError("Research roles incomplete")
    if agents and [r.get("role") for r in agents] != list(AGENT_ROLES):
        raise ValueError("Unexpected agent roles")
    safe_rows = []
    for row in agents:
        if (row.get("action") not in ("BUY", "SELL", "HOLD", "NO_TRADE")
                or not re.fullmatch(r"[A-Z0-9]{1,6}", str(row.get("symbol", "")))):
            raise ValueError("Invalid research opinion")
        confidence = amount(row.get("confidence"))
        if confidence is None or confidence < 0 or confidence > 1:
            raise ValueError("Invalid research confidence")
        safe_rows.append({"role": row["role"], "action": row["action"],
                          "symbol": row["symbol"], "confidence": f"{100*confidence:.0f}%"})
    virtual = data.get("virtual_paper") if isinstance(data.get("virtual_paper"), dict) else {}
    history = virtual.get("latest_trades")
    if not isinstance(history, list):
        history = []
    trades = []
    for trade in history[-8:]:
        if not isinstance(trade, dict):
            continue
        if (trade.get("side") not in ("BUY", "SELL")
                or not re.fullmatch(r"[A-Z0-9]{1,6}", str(trade.get("symbol", "")))):
            continue
        trades.append({
            "day": str(trade.get("day", ""))[:10],
            "symbol": trade["symbol"], "side": trade["side"],
            "shares": str(trade.get("shares", ""))[:12],
            "price": dollars(amount(trade.get("assumed_close"))),
        })
    day = str(data.get("as_of", "UNAVAILABLE"))[:10]
    try:
        stale = (datetime.now(timezone.utc).date() - date.fromisoformat(day)).days > 4
    except (ValueError, TypeError):
        stale = True
    hypothesis = data.get("hypothesis")
    decision = "NO EXECUTABLE AGENT DECISION"
    if isinstance(hypothesis, dict) and hypothesis.get("action") in ("BUY", "SELL"):
        if re.fullmatch(r"[A-Z0-9]{1,6}", str(hypothesis.get("symbol", ""))):
            decision = "HYPOTHESIS ONLY: " + hypothesis["action"] + " " + hypothesis["symbol"]
    pct = amount(virtual.get("cumulative_return_pct"))
    dd = amount(virtual.get("worst_observed_drawdown_pct"))
    return {
        "state": str(data.get("status", "UNAVAILABLE"))[:40],
        "provider": str(data.get("provider", "UNAVAILABLE"))[:20],
        "as_of": day, "stale": stale,
        "consensus": str(data.get("consensus", "NO_CONSENSUS"))[:40],
        "decision": decision, "agents": safe_rows,
        "virtual_equity": dollars(amount(virtual.get("current_equity"))),
        "virtual_return": f"{pct:+.2f}%" if pct is not None else "Unavailable",
        "virtual_drawdown": f"{dd:.2f}%" if dd is not None else "Unavailable",
        "virtual_status": str(virtual.get("status", "UNAVAILABLE"))[:20],
        "trades": trades,
    }



# Public read-only workflow metadata, not private credentials or CI logs.
OFFICE_RUNS_APIS = (
    # Workflow-scoped pages are small and cannot be displaced by frequent CI
    # pushes. The former repo-wide 35-run response exceeded its 80 KB cap.
    "https://api.github.com/repos/williamRut261/webull-paper/"
    "actions/workflows/ai-trading-desk.yml/runs?branch=main&per_page=1",
    "https://api.github.com/repos/williamRut261/webull-paper/"
    "actions/workflows/ai-desk-verify.yml/runs?branch=main&per_page=1",
)
OFFICE_WORKFLOW_NAMES = frozenset((
    "AI Trading Desk (RESEARCH ONLY - NO BROKER ORDERS)",
    "One-Time Seven-Agent Provider Verification (NO BROKER)",
))


def read_office_run(opener=urlopen):
    """Read the latest exact research workflow, not unrelated repository CI."""
    candidates, failures = [], []
    for uri in OFFICE_RUNS_APIS:
        req = UrlRequest(uri, headers={
            "User-Agent": "webull-paper-agent-office",
            "Accept": "application/vnd.github+json",
        })
        try:
            with opener(req, timeout=3) as response:
                raw = response.read(80001)
            if len(raw) > 80000:
                raise ValueError("Oversized Actions metadata")
            runs = json.loads(raw).get("workflow_runs")
            if not isinstance(runs, list):
                raise ValueError("Malformed Actions metadata")
            candidates.extend(
                row for row in runs if isinstance(row, dict)
                and row.get("name") in OFFICE_WORKFLOW_NAMES
                and row.get("head_branch") == "main"
            )
        except Exception as error:
            failures.append(error)
    if not candidates:
        if failures:
            raise failures[0]
        return None
    latest = max(candidates, key=lambda r: (
        str(r.get("created_at") or ""), r.get("id") if type(r.get("id")) is int else 0
    ))
    state = str(latest.get("status", ""))[:24]
    conclusion = str(latest.get("conclusion") or "")[:24]
    if state not in ("queued", "waiting", "pending", "in_progress", "completed", "requested"):
        raise ValueError("Unexpected workflow run state")
    run_id = latest.get("id")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("Missing run ID")
    sha = latest.get("head_sha")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        sha = None
    created = str(latest.get("created_at") or "")
    expired = False
    if state != "completed":
        try:
            started = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - started).total_seconds()
            expired = not (0 <= age_seconds <= 30 * 60)
        except (ValueError, TypeError):
            expired = True
    return {
        "state": state, "conclusion": conclusion, "head_sha": sha,
        "run_id": run_id, "expired": expired,
        "active": state == "in_progress" and not expired,
        "queued": state in ("queued", "waiting", "pending", "requested") and not expired,
        "run_url": (
            "https://github.com/williamRut261/webull-paper/actions/runs/" + str(run_id)
        ),
        "created": created[:20],
        "type": ("Scheduled AI desk" if latest.get("name", "").startswith("AI Trading")
                 else "Provider verification"),
    }


def read_office_role_checks(sha, opener=urlopen, run_id=None, run_active=True):
    """Only trusted role checks, attached to the selected workflow run.

    The run ID prevents an old Check on the same SHA being interpreted as
    current. A never-finished Check is not working once its workflow ends.
    Missing/unrecognized events remain unavailable, never invented.
    """
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        return {}
    if run_id is not None and (type(run_id) is not int or run_id <= 0):
        return {}
    uri = ("https://api.github.com/repos/williamRut261/webull-paper/"
           "commits/" + sha + "/check-runs?per_page=100")
    req = UrlRequest(uri, headers={"User-Agent": "webull-paper-agent-office",
                                   "Accept": "application/vnd.github+json"})
    with opener(req, timeout=3) as response:
        raw = response.read(240001)
    if len(raw) > 240000:
        raise ValueError("Oversized role metadata")
    runs = json.loads(raw).get("check_runs")
    if not isinstance(runs, list):
        raise ValueError("Malformed role check states")
    names = set(AGENT_ROLES)
    newest = {}
    for item in runs:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.startswith("AI Office / "):
            continue
        role = name[len("AI Office / "):]
        if role not in names:
            continue
        if run_id is not None and item.get("external_id") != str(run_id):
            continue
        status = item.get("status")
        conclusion = item.get("conclusion")
        if status == "in_progress":
            state = "WORKING" if run_active else "STALE"
        elif status == "completed" and conclusion == "success":
            state = "DONE"
        elif status == "completed" and conclusion in ("failure", "timed_out", "cancelled"):
            state = "FAILED"
        elif status == "queued":
            state = "QUEUED" if run_active else "STALE"
        else:
            continue
        # Choose the newest event on an identical SHA if it was retried.
        sort_key = (str(item.get("started_at") or ""),
                    item.get("id") if type(item.get("id")) is int else 0)
        if role not in newest or sort_key > newest[role][0]:
            newest[role] = (sort_key, state)
    return {role: value[1] for role, value in newest.items()}

# Illustrated office markup is packaged as a standalone Jinja template.


def build_office_workers(agent, checks=None):
    """Join exact seven known roles to last published sanitized opinions."""
    opinions = {
        x["role"]: x for x in agent["agents"]
    } if agent and isinstance(agent.get("agents"), list) else {}
    checks = checks or {}
    return [
        {"title": title, "name": name, "task": task, "detail": detail, "stage": checks.get(title),
         "color": color, "tag": tag, "hair": (
             "#203953", "#503a3f", "#6a4952", "#262838", "#3f3844", "#6a5d43", "#283945"
         )[i], "vote": opinions.get(title)}
        for i, (title, name, task, detail, color, tag) in enumerate(OFFICE_ROLES)
    ]


@app.get("/office/motion.js")
def office_motion():
    """Serve read-only pixel-world animation after the same owner/IAP check."""
    authorized_user()
    response = make_response(app.send_static_file("office-motion.js"))
    response.headers["Cache-Control"] = "private, max-age=60"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/office")
def office():
    authorized_user()
    try:
        agent = read_agent_feed()
    except Exception as error:
        app.logger.warning(
            "office_agent_feed_unavailable exception_type=%s", type(error).__name__)
        agent = None
    try:
        run = read_office_run()
    except Exception as error:
        app.logger.warning(
            "office_action_status_unavailable exception_type=%s", type(error).__name__)
        run = None
    try:
        checks = read_office_role_checks(
            run.get("head_sha"), run_id=run.get("run_id"),
            run_active=run.get("active", False)
        ) if run else {}
    except Exception as error:
        app.logger.warning(
            "office_role_status_unavailable exception_type=%s", type(error).__name__)
        checks = {}
    response = make_response(render_template(
        "office.html", workers=build_office_workers(agent, checks),
        agent=agent, run=run, checks=checks))
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'")
    return response



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
<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><a class="btn" href="/office">Agent Office →</a><a class="btn" href="/">Refresh</a></div></header>
<p class="muted">Read-only · {{ snapshot.as_of }} · {{ snapshot.source }}</p>
<div class="stats"><section class="box"><small>Total account equity</small>
<div class="number">{{ snapshot.equity }}</div></section>
<section class="box"><small>Cash balance</small><div class="number">{{ snapshot.cash }}</div></section></div>
<section class="box"><h2>Account value reconciliation</h2>
<div class="scroll"><table>
<tr><th>Broker-reported holding value</th><td>{{ snapshot.broker_market_value }}</td></tr>
<tr><th>Estimated holdings (shares × last price)</th><td>{{ snapshot.quoted_market_value }}</td></tr>
<tr><th>Broker holdings minus estimated holdings</th><td>{{ snapshot.quote_difference }}</td></tr>
<tr><th>Equity minus cash and broker holdings</th><td>{{ snapshot.equity_residual }}</td></tr>
</table></div><p class="muted">{{ snapshot.balance_note }}</p></section>
<div style="height:16px"></div>

<div style="height:16px"></div>
<section class="box"><h2>Seven-agent AI trading desk (research + virtual paper)</h2>
<p class="muted">Not connected to Webull execution. The seven opinions are advisory,
and $10,000 virtual trades are daily-close assumptions, not broker fills.</p>
{% if agent %}
<p class="muted">Status: {{ agent.state }} · Provider: {{ agent.provider }} ·
Market data: {{ agent.as_of }}{% if agent.stale %} · STALE / UNVERIFIED{% endif %}</p>
<p><strong>Desk outcome:</strong> {{ agent.consensus }} · {{ agent.decision }}</p>
<div class="scroll"><table><tr><th>Specialist</th><th>Opinion</th><th>Symbol</th><th>Confidence</th></tr>
{% for v in agent.agents %}<tr><td>{{ v.role }}</td><td>{{ v.action }}</td><td>{{ v.symbol }}</td>
<td>{{ v.confidence }}</td></tr>
{% else %}<tr><td colspan="4">No verified seven-agent opinions published yet.</td></tr>{% endfor %}
</table></div>
<p class="muted">Independent virtual paper ({{ agent.virtual_status }}) ·
Equity: {{ agent.virtual_equity }} · Simulated return: {{ agent.virtual_return }} ·
Worst observed drawdown: {{ agent.virtual_drawdown }}. No agent orders placed at Webull.</p>
<div class="scroll"><table><tr><th>Virtual day</th><th>Symbol</th><th>Side</th><th>Shares</th><th>Assumed close</th></tr>
{% for t in agent.trades %}<tr><td>{{t.day}}</td><td>{{t.symbol}}</td><td>{{t.side}}</td>
<td>{{t.shares}}</td><td>{{t.price}}</td></tr>
{% else %}<tr><td colspan="5">No simulated trades recorded.</td></tr>{% endfor %}
</table></div>
{% else %}
<p class="muted">Agent report unavailable. No agent decisions or performance are inferred.</p>
{% endif %}
</section>
<section class="box"><h2>Current positions</h2><div class="scroll"><table>
<tr><th>Symbol</th><th>Quantity</th><th>Last price</th><th>Market value</th></tr>
{% for p in snapshot.positions %}<tr><td>{{p.symbol}}</td><td>{{p.quantity}}</td>
<td>{{p.last_price}}</td><td>{{p.market_value}}</td></tr>
{% else %}<tr><td colspan="4">No positions returned by the broker.</td></tr>{% endfor %}
</table></div></section><div style="height:16px"></div>
<section class="box"><h2>Recent orders</h2><p class="muted">{{ snapshot.history_note }}</p>
<div class="scroll"><table><tr><th>Date</th><th>Symbol</th><th>Side</th>
<th>Status</th><th>Filled / total</th><th>Average fill</th></tr>
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
        trade = _read_stage("client_initialization", sandbox_trade_client)
        snapshot = read_snapshot(
            trade,
            os.getenv("WEBULL_PAPER_ACCOUNT_SHA256", ""),
            os.getenv("WEBULL_PAPER_ACCOUNT_INDEX", "0"),
        )
    except Exception:
        # Do not disclose broker responses, account identifiers, or secret values.
        abort(502, "Sandbox data unavailable or account verification failed")
    try:
        agent = read_agent_feed()
    except Exception as error:
        app.logger.warning(
            "agent_public_feed_unavailable exception_type=%s", type(error).__name__)
        agent = None
    response = make_response(render_template_string(TEMPLATE, snapshot=snapshot, agent=agent))
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    return response
