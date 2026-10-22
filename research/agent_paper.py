"""Seven-agent hypothesis -> isolated VIRTUAL PAPER ledger.

No broker SDK, order APIs, credentials, or imports from trading modules.
Synthetic trades use same-day public DAILY closing prices; these are NOT
Webull fills, executable prices, or evidence of achievable performance.
"""
import argparse
from copy import deepcopy
from datetime import date
import json
import math
from pathlib import Path

from research.ai_desk import ROLES, SYMBOLS

INITIAL_CASH = 10000.0
MAX_POSITION_FRACTION = 0.05
MAX_ESTIMATED_TRADE_RISK = 0.001
ASSUMED_STOP_FRACTION = 0.02
COST_FRACTION = 0.001
MAX_LOG_ROWS = 120


def empty_ledger():
    return {"schema": 1, "cash": INITIAL_CASH, "positions": {},
            "peak_equity": INITIAL_CASH, "last_day": "",
            "trades": [], "daily": []}


def finite_price(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("Missing or invalid daily close")
    return float(value)


def validated_votes(report):
    rows = report.get("agent_opinions")
    if not isinstance(rows, list) or len(rows) != len(ROLES):
        raise ValueError("Missing or incomplete agent opinions")
    if [x.get("role") for x in rows if isinstance(x, dict)] != list(ROLES):
        raise ValueError("Agent roles missing, changed or reordered")
    allowed = set(SYMBOLS)
    result = []
    for row in rows:
        if (row.get("action") not in ("BUY", "SELL", "HOLD", "NO_TRADE")
                or row.get("symbol") not in allowed | {"NONE"}
                or type(row.get("confidence")) not in (int, float)
                or not math.isfinite(row["confidence"])
                or not 0 <= row["confidence"] <= 1):
            raise ValueError("Invalid agent opinion")
        result.append({"role": row["role"], "symbol": row["symbol"],
                       "action": row["action"], "confidence": round(row["confidence"], 3)})
    return result


def daily_prices(report):
    quotes = report.get("market_data", {}).get("quotes")
    if not isinstance(quotes, dict) or not quotes:
        raise ValueError("No market data")
    prices = {}
    day = None
    for symbol, row in quotes.items():
        if symbol not in SYMBOLS or not isinstance(row, dict):
            raise ValueError("Unapproved market symbol")
        try:
            stamp = date.fromisoformat(row["as_of"]).isoformat()
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("Missing daily data date") from exc
        if day is not None and day != stamp:
            raise ValueError("Mixed market dates")
        day = stamp
        prices[symbol] = finite_price(row.get("close"))
    return day, prices


def virtual_step(report, previous=None, *, killed=False):
    """Pure, idempotent next trading-day simulation. No external side effects."""
    state = deepcopy(previous if previous is not None else empty_ledger())
    if state.get("schema") != 1 or not isinstance(state.get("positions"), dict):
        raise ValueError("Invalid virtual ledger")
    if report.get("status") != "RESEARCH_ONLY" or report.get("broker_connected") is not False:
        raise ValueError("Only disconnected research may inform virtual paper trades")
    votes = validated_votes(report)
    day, prices = daily_prices(report)
    if state.get("last_day") == day:
        return state  # A retry cannot duplicate a simulated fill.
    if state.get("last_day") and day < state["last_day"]:
        raise ValueError("Out-of-order daily research")
    holdings = state["positions"]
    if len(holdings) > 1:
        raise ValueError("Overexposed virtual ledger")
    cash = finite_price(state["cash"]) if state["cash"] else 0.0
    for symbol, qty in holdings.items():
        if symbol not in prices or type(qty) is not int or qty <= 0:
            raise ValueError("Cannot value previous virtual position")
    equity = cash + sum(qty * prices[symbol] for symbol, qty in holdings.items())
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError("Invalid virtual equity")
    hypothesis = report.get("hypothesis")
    if report.get("consensus") != "HYPOTHESIS_FOR_BACKTEST":
        hypothesis = None
    if hypothesis is not None and not isinstance(hypothesis, dict):
        raise ValueError("Malformed hypothesis")
    if hypothesis and (hypothesis.get("symbol") not in prices or
                       hypothesis.get("action") not in ("BUY", "SELL")):
        raise ValueError("Unpriced or invalid hypothesis")
    # The agent is not permitted to short, borrow, trade LIVE, or place orders.
    if not killed and hypothesis:
        symbol, action = hypothesis["symbol"], hypothesis["action"]
        price = prices[symbol]
        if action == "SELL" and symbol in holdings:
            qty = holdings.pop(symbol)
            fee = qty * price * COST_FRACTION
            cash += qty * price - fee
            state["trades"].append({"day": day, "symbol": symbol, "side": "SELL",
                                    "shares": qty, "assumed_close": price,
                                    "estimated_cost": round(fee, 2)})
        elif action == "BUY" and not holdings:
            budget = min(
                equity * MAX_POSITION_FRACTION,
                equity * MAX_ESTIMATED_TRADE_RISK / ASSUMED_STOP_FRACTION,
                cash / (1 + COST_FRACTION))
            qty = math.floor(budget / (price * (1 + COST_FRACTION)))
            if qty > 0:
                fee = qty * price * COST_FRACTION
                cash -= qty * price + fee
                holdings[symbol] = qty
                state["trades"].append({"day": day, "symbol": symbol, "side": "BUY",
                                        "shares": qty, "assumed_close": price,
                                        "estimated_cost": round(fee, 2)})
    state["cash"] = round(cash, 8)
    mark = cash + sum(qty * prices[symbol] for symbol, qty in holdings.items())
    if mark <= 0 or not math.isfinite(mark):
        raise ValueError("Invalid virtual mark")
    state["peak_equity"] = max(float(state["peak_equity"]), mark)
    state["last_day"] = day
    state["daily"].append({"day": day, "equity": round(mark, 2),
                           "drawdown_pct": round(100 * (mark / state["peak_equity"] - 1), 3)})
    state["trades"] = state["trades"][-MAX_LOG_ROWS:]
    state["daily"] = state["daily"][-MAX_LOG_ROWS:]
    return state


def public_status(report, ledger, *, killed=False):
    """Only publish allowlisted market research + VIRTUAL metrics; never credentials."""
    status = str(report.get("status", "UNAVAILABLE"))[:40]
    is_valid = status == "RESEARCH_ONLY"
    votes = validated_votes(report) if is_valid else []
    hypotheses = report.get("hypothesis") if is_valid else None
    hypothesis = None
    if isinstance(hypotheses, dict) and hypotheses.get("symbol") in SYMBOLS and hypotheses.get("action") in ("BUY", "SELL"):
        hypothesis = {"symbol": hypotheses["symbol"], "action": hypotheses["action"]}
    last = ledger["daily"][-1] if ledger.get("daily") else None
    return {
        "schema": 1, "status": status,
        "as_of": ledger.get("last_day") or "UNAVAILABLE",
        "provider": str(report.get("provider", "UNAVAILABLE"))[:20],
        "consensus": str(report.get("consensus", "NO_CONSENSUS"))[:40],
        "hypothesis": hypothesis, "agents": votes,
        "virtual_paper": {
            "status": "KILLED" if killed else "ENABLED",
            "starting_equity": INITIAL_CASH,
            "current_equity": last["equity"] if last else None,
            "cumulative_return_pct": round(100 * (last["equity"] / INITIAL_CASH - 1), 3) if last else None,
            "worst_observed_drawdown_pct": min((r["drawdown_pct"] for r in ledger["daily"]), default=None),
            "simulated_trades": len(ledger["trades"]),
            "latest_trades": ledger["trades"][-8:],
        },
        "actual_broker_orders_from_agents": 0,
        "note": "Separate $10,000 virtual ledger, hypothetical daily-close fills only; not Webull orders, live returns or an audited backtest.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--kill", action="store_true")
    args = parser.parse_args(argv)
    report = json.loads(Path(args.report).read_text())
    path = Path(args.ledger)
    old = json.loads(path.read_text()) if path.exists() else empty_ledger()
    # Provider failures do not create positions or silently manufacture opinions.
    if report.get("status") == "RESEARCH_ONLY":
        ledger = virtual_step(report, old, killed=args.kill)
    else:
        ledger = old
    status = public_status(report, ledger, killed=args.kill)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, sort_keys=True, indent=2) + "\n")
    out = Path(args.status)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(status, sort_keys=True, indent=2) + "\n")
    print("AGENT_VIRTUAL_PAPER_ONLY actual_orders=0 status=" + status["status"])


if __name__ == "__main__":
    main()
