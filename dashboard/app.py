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
OFFICE_RUNS_API = (
    "https://api.github.com/repos/williamRut261/webull-paper/"
    "actions/runs?per_page=35"
)
OFFICE_ROLES = (
    ("Market Analyst", "Maya", "Studies market regime", "Market breadth · trend", "#73b7fb", "a"),
    ("Technical Analyst", "Theo", "Checks price indicators", "RSI · SMA · momentum", "#a58cf1", "b"),
    ("News Researcher", "Nova", "Assesses missing news context", "News feed not connected", "#e2aa70", "c"),
    ("Strategy Analyst", "Iris", "Tests trading hypotheses", "Signals · costs", "#83d4b6", "d"),
    ("Risk Manager", "Sage", "Evaluates limits and vetoes", "Exposure · risk checks", "#e88893", "e"),
    ("Desk Lead", "Atlas", "Synthesizes specialist views", "Consensus · disagreement", "#e4bb78", "f"),
    ("Trade Reviewer", "Quinn", "Challenges the trade idea", "Independent review", "#91c6cb", "g"),
)


def read_office_run(opener=urlopen):
    """Retrieve public GitHub Actions state, never infer agent-level progress."""
    req = UrlRequest(
        OFFICE_RUNS_API, headers={
            "User-Agent": "webull-paper-agent-office",
            "Accept": "application/vnd.github+json",
        })
    with opener(req, timeout=3) as response:
        raw = response.read(80001)
    if len(raw) > 80000:
        raise ValueError("Actions metadata oversized")
    data = json.loads(raw)
    runs = data.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("Malformed Actions metadata")
    relevant = [r for r in runs if isinstance(r, dict) and r.get("name") in (
        "AI Trading Desk (RESEARCH ONLY - NO BROKER ORDERS)",
        "One-Time Seven-Agent Provider Verification (NO BROKER)",
    ) and r.get("head_branch") == "main"]
    if not relevant:
        return None
    latest = relevant[0]
    state = str(latest.get("status", ""))[:24]
    conclusion = str(latest.get("conclusion") or "")[:24]
    if state not in ("queued", "waiting", "pending", "in_progress", "completed", "requested"):
        raise ValueError("Unexpected workflow run state")
    run_id = latest.get("id")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("Missing run ID")
    return {
        "state": state, "conclusion": conclusion,
        "active": state == "in_progress",
        "queued": state in ("queued", "waiting", "pending", "requested"),
        "run_url": (
            "https://github.com/williamRut261/webull-paper/actions/runs/" + str(run_id)
        ),
        "created": str(latest.get("created_at") or "")[:20],
        "type": "Scheduled AI desk" if latest.get("name", "").startswith("AI Trading") else "Provider verification",
    }


OFFICE_TEMPLATE = """
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{% if run and (run.active or run.queued) %}
<meta http-equiv="refresh" content="30">
{% endif %}
<title>Agent Office · Webull PAPER</title>
<style>
:root{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;color-scheme:dark;
 --txt:#edf3ff;--muted:#9eb1cb;--border:#2b4057;--glass:#172438}
*{box-sizing:border-box}
body{margin:0;background:#0a111f;color:var(--txt)}
a{color:#92d1ff;text-decoration:none}a:hover{text-decoration:underline}
.page{max-width:1360px;margin:0 auto;padding:22px 22px 60px}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:26px;flex-wrap:wrap}
.brand{font-size:.86rem;letter-spacing:.18em;font-weight:750;color:#adc7e5}
.links{display:flex;align-items:center;gap:15px;flex-wrap:wrap}
.links a{padding:9px 13px;border:1px solid #415878;border-radius:12px}
.hero{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap;margin-bottom:20px}
h1{margin:0 0 9px;font-size:clamp(2rem,4vw,3.3rem);letter-spacing:-.055em}
h2{font-size:1.15rem;letter-spacing:-.02em}
.muted{color:var(--muted)}
.intro{max-width:720px;margin:0;font-size:.95rem;line-height:1.5}
.state{display:flex;gap:9px;align-items:center;border:1px solid #34506a;background:#17273b;border-radius:99px;padding:12px 17px;font-size:.84rem}
.light{width:11px;height:11px;background:#8494ab;border-radius:50%;box-shadow:0 0 0 5px #8494ab18}
.state.active .light{background:#47d7a7;box-shadow:0 0 14px #47d7a777;animation:pulse 1.2s ease-in-out infinite}
.state.fail .light{background:#ef9c91}
.state.ok .light{background:#47d7a7}
@keyframes pulse{50%{opacity:.42;transform:scale(.8)}}
.scene{padding:18px;border:1px solid #38506e;border-radius:25px;
 background:radial-gradient(circle at 18% 0%,#25435c 0%,transparent 37%),
 radial-gradient(circle at 96% 65%,#192d54 0%,transparent 42%),#101c2c;
 box-shadow:inset 0 0 45px #08111e88}
.scene-heading{display:flex;justify-content:space-between;gap:16px;align-items:baseline;flex-wrap:wrap;margin-bottom:18px}
.scene-heading strong{font-size:.96rem}
.legend{font-size:.79rem;color:#a8bcd6}
.floor{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px}
.station{position:relative;background:linear-gradient(180deg,#243449 0%,#19273c 100%);
 border:1px solid #4a607b;border-radius:19px;min-height:278px;overflow:hidden;padding:13px;
 display:flex;flex-direction:column;justify-content:space-between}
.station:before{content:"";position:absolute;left:0;right:0;bottom:0;height:79px;background:#263b46;
 border-top:2px solid #466073;opacity:.52}
.station-title{position:relative;z-index:2;display:flex;justify-content:space-between;gap:5px;align-items:start}
.agent-name{font-weight:780;font-size:.97rem}
.agent-role{font-size:.76rem;color:#b1c3dd;margin-top:2px}
.activity{text-align:right;font-size:.67rem;letter-spacing:.045em;color:#b8c9dc;background:#122136;
 border-radius:99px;padding:5px 8px;white-space:nowrap}
.activity.lit{color:#b7ffe8;background:#1b4f4d}
.office-art{position:relative;height:111px;z-index:1;margin-top:5px}
.person{position:absolute;left:25px;top:8px;width:65px;height:99px}
.hair{position:absolute;z-index:3;top:0;left:14px;width:37px;height:24px;border-radius:55% 50% 25% 20%;
 background:#314054}
.face{position:absolute;z-index:4;top:10px;left:17px;width:32px;height:37px;border-radius:39% 39% 45% 45%;background:#deb48c}
.eye{position:absolute;top:15px;height:3px;width:3px;border-radius:50%;background:#263346}
.eye.one{left:8px}.eye.two{right:8px}
.body{position:absolute;z-index:3;left:5px;top:45px;width:55px;height:51px;border-radius:21px 21px 4px 4px;background:var(--shirt)}
.body:after{content:"";position:absolute;left:22px;top:0;width:9px;height:21px;border-radius:0 0 10px 10px;background:#13243c55}
.arm{position:absolute;z-index:5;width:12px;height:36px;top:52px;border-radius:12px;background:#deae87}
.arm.left{left:0;transform:rotate(-26deg)}.arm.right{right:0;transform:rotate(26deg)}
.station.is-active .arm.left{animation:key1 .65s ease-in-out infinite alternate}
.station.is-active .arm.right{animation:key2 .7s ease-in-out infinite alternate}
@keyframes key1{to{transform:rotate(-35deg) translateY(3px)}}
@keyframes key2{to{transform:rotate(35deg) translateY(3px)}}
.monitor{position:absolute;right:8px;top:5px;width:108px;height:75px;border:8px solid #0c182a;
 border-radius:9px;background:linear-gradient(140deg,#123d53,#12283d);box-shadow:2px 4px 10px #08111e}
.monitor:after{content:"";position:absolute;left:42px;bottom:-24px;width:12px;height:17px;background:#0c182a}
.mon-line{margin:6px;height:4px;border-radius:4px;background:#7cc8cd;opacity:.75}
.mon-line.b{width:70%;background:#d1a2d6}.mon-line.c{width:50%;background:#89cbe3}
.desk{position:absolute;bottom:4px;left:2px;right:2px;height:25px;border:2px solid #97745b;
 border-radius:8px;background:linear-gradient(#bd9675,#84664e);z-index:6}
.desk:before{content:"";position:absolute;top:-10px;left:50%;width:52px;height:8px;
 background:#11243a;border-radius:5px;transform:translateX(-50%)}
.desk:after{content:"";position:absolute;top:7px;right:12px;width:9px;height:9px;background:#d3d8df;border-radius:50%}
.station.is-active .monitor{box-shadow:0 0 15px #66e5ce55}
.agent-detail{z-index:2;position:relative;border-radius:11px;background:#101e2dcc;
 border:1px solid #40566e;padding:10px;margin-top:8px}
.task{font-size:.78rem;color:#dbe6f7;min-height:32px;line-height:1.35}
.result{margin-top:7px;font-size:.72rem;color:#aabdd5}
.bridge{grid-column:span 2;background:linear-gradient(140deg,#1b3746,#1c2b46);
 border:1px solid #537087;border-radius:19px;padding:22px;display:flex;flex-direction:column;justify-content:center;gap:14px}
.bridge .big{font-size:1.55rem;font-weight:760;letter-spacing:-.05em}
.branch{border-top:1px solid #57718a;padding-top:12px;font-size:.82rem;color:#b9cee4}
.bottom{margin-top:17px;display:grid;grid-template-columns:1fr 1fr;gap:14px}
.panel{background:var(--glass);border:1px solid var(--border);border-radius:18px;padding:19px}
.panel p{font-size:.85rem;line-height:1.6}
.row{display:flex;justify-content:space-between;gap:10px;border-top:1px solid #39506a;padding:9px 0;font-size:.84rem}
.tag{font-size:.75rem;border-radius:7px;background:#283d52;padding:5px 8px}
.notice{font-size:.76rem;line-height:1.6;color:#b5c7de}
@media(max-width:1100px){.floor{grid-template-columns:repeat(3,minmax(0,1fr))}.bridge{grid-column:span 2}}
@media(max-width:750px){.floor{grid-template-columns:repeat(2,minmax(0,1fr))}.bottom{grid-template-columns:1fr}}
@media(max-width:460px){.page{padding:16px 12px 40px}.scene{padding:10px}.floor{grid-template-columns:1fr}
.station{min-height:252px}.bridge{grid-column:span 1}.hero{gap:14px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important}}
</style></head><body><div class="page">
<div class="topbar"><div class="brand">WEBULL PAPER <span class="muted">/ AI MISSION CONTROL</span></div>
<nav class="links"><a href="/">Portfolio</a><a href="/office">Refresh office</a></nav></div>
<div class="hero"><div><h1>The Agent Office</h1>
<p class="intro muted">Seven specialist characters, one coordinated research desk.
See their assigned stations and the latest verified decisions. Animated movement is illustrative;
actual run state comes from GitHub Actions.</p></div>
<div class="state {% if run and run.active %}active{% elif run and run.conclusion == 'success' %}ok{% elif run and run.conclusion == 'failure' %}fail{% endif %}">
<span class="light"></span>
{% if run and run.active %}DESK RUN IN PROGRESS
{% elif run and run.queued %}RUN QUEUED
{% elif run and run.conclusion == 'success' %}LAST RUN COMPLETED
{% elif run and run.conclusion == 'failure' %}LAST RUN FAILED
{% else %}LIVE RUN STATUS UNAVAILABLE{% endif %}
</div></div>
<section class="scene" aria-label="Virtual agent office">
<div class="scene-heading"><strong>THE RESEARCH FLOOR</strong>
<div class="legend">
{% if run %}{{run.type}} · {{run.created}} UTC · <a href="{{run.run_url}}">See verified workflow →</a>
{% else %}GitHub run details unavailable{% endif %}
</div></div>
<div class="floor">
{% for role in workers %}
<div class="station {% if run and run.active %}is-active{% endif %}" style="--shirt:{{role.color}}">
<div class="station-title"><div><div class="agent-name">{{role.name}}</div>
<div class="agent-role">{{role.title}}</div></div>
<div class="activity {% if run and run.active %}lit{% endif %}">
{% if run and run.active %}DESK ACTIVE{% elif role.vote %}REPORTED{% else %}AWAITING DATA{% endif %}</div></div>
<div class="office-art" aria-hidden="true">
<div class="person"><div class="hair"></div>
<div class="face"><span class="eye one"></span><span class="eye two"></span></div>
<div class="body"></div><span class="arm left"></span><span class="arm right"></span></div>
<div class="monitor"><div class="mon-line"></div><div class="mon-line b"></div>
<div class="mon-line c"></div><div class="mon-line"></div></div><div class="desk"></div></div>
<div class="agent-detail"><div class="task">{{role.task}}</div>
<div class="result">
{% if role.vote %}Last published: <strong>{{role.vote.action}} {{role.vote.symbol}}</strong>
· {{role.vote.confidence}} confidence
{% else %}No published opinion yet{% endif %}
</div></div></div>
{% endfor %}
<div class="bridge">
<div class="tag">DECISION HUB</div>
<div class="big">{% if agent %}{{agent.consensus}}{% else %}AWAITING REPORT{% endif %}</div>
<p class="muted">{% if agent %}Latest dataset {{agent.as_of}} · {{agent.provider}}
{% if agent.stale %}· STALE{% endif %}{% else %}No verified research report found.{% endif %}</p>
<div class="branch">Morning PAPER orders still require the independent ORB scanner,
sandbox validation and agent risk-on approval. The avatars themselves never place orders.</div>
</div>
</div></section>
<div class="bottom">
<section class="panel"><h2>Desk Activity</h2>
{% if run %}<div class="row"><span>GitHub Actions</span><strong>{{run.state}}{% if run.conclusion %} · {{run.conclusion}}{% endif %}</strong></div>
<div class="row"><span>Started / created</span><span>{{run.created}} UTC</span></div>
{% else %}<p class="muted">Could not retrieve GitHub Actions run state.</p>{% endif %}
<div class="row"><span>Agent progress</span><span>Per-agent live step not available</span></div>
<div class="row"><span>Last published agent report</span><span>{% if agent %}{{agent.as_of}}{% else %}Unavailable{% endif %}</span></div>
<p class="notice">Seven research roles are called sequentially. Their specific live stage is
not published, so characters are not claimed to be executing individual tasks in real time.
{% if run and (run.active or run.queued) %}This page updates every 30 seconds while the run is active or queued.{% endif %}</p>
</section>
<section class="panel"><h2>Paper Orders &amp; Performance</h2>
{% if agent %}
<div class="row"><span>Independent virtual equity</span><strong>{{agent.virtual_equity}}</strong></div>
<div class="row"><span>Virtual simulated return</span><strong>{{agent.virtual_return}}</strong></div>
<div class="row"><span>Virtual observed drawdown</span><strong>{{agent.virtual_drawdown}}</strong></div>
<div class="row"><span>Latest research decision</span><strong>{{agent.decision}}</strong></div>
{% else %}<p class="muted">No verified virtual-paper results available.</p>{% endif %}
<p class="notice">These values describe a separate $10,000 hypothetical ledger.
Actual Webull OpenAPI sandbox holdings and recent broker orders remain on the <a href="/">Portfolio</a> page.</p>
</section></div>
</div></body></html>
"""


def build_office_workers(agent):
    """Join exact seven known roles to last published sanitized opinions."""
    opinions = {
        x["role"]: x for x in agent["agents"]
    } if agent and isinstance(agent.get("agents"), list) else {}
    return [
        {"title": title, "name": name, "task": task, "detail": detail,
         "color": color, "tag": tag, "vote": opinions.get(title)}
        for title, name, task, detail, color, tag in OFFICE_ROLES
    ]


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
    response = make_response(render_template_string(
        OFFICE_TEMPLATE, workers=build_office_workers(agent), agent=agent, run=run))
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'")
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
