"""Fail-closed seven-agent approval for existing Webull SANDBOX ORB sleeve.

The seven analysts never receive Webull credentials. They can jointly veto
or approve the pre-existing, broker-verified ORB scanner; they NEVER choose a
new ticker, order size, account or broker endpoint. No additional allocation.
"""
from datetime import date
import json
import math
from urllib.request import Request, urlopen

from research.ai_desk import ROLES

PUBLIC_STATUS = (
    "https://raw.githubusercontent.com/williamRut261/webull-paper/"
    "main/research/ai_desk_status.json"
)
# Limit approval to positive broad equity-market opinions: NEVER treat BUY
# of an inverse hedge or risk-off asset as permission to buy breakout stocks.
RISK_ON = frozenset(("SPY", "QQQ"))
MIN_CONFIDENCE = 0.65
MAX_REPORT_AGE_DAYS = 4


def evaluate_agent_gate(report, trading_date):
    """Validate independent agent opinions and return a documented decision.

    BUY means permission to consider existing ORB signals, NOT permission to
    purchase the agents' indicated risk-on index. Any other result is NO_TRADE.
    Missing/stale/contradictory data fails closed instead of bypassing model.
    """
    if not isinstance(report, dict):
        raise ValueError("Missing AI desk publication")
    if (report.get("schema") != 1 or report.get("status") != "RESEARCH_ONLY"
            or report.get("provider") != "gemini"
            or report.get("actual_broker_orders_from_agents") != 0):
        raise ValueError("Unverified AI desk research")
    if not isinstance(trading_date, date):
        raise ValueError("Invalid order session")
    stamp = report.get("as_of")
    try:
        research_day = date.fromisoformat(stamp)
    except (TypeError, ValueError) as exc:
        raise ValueError("Missing AI research trading date") from exc
    age = (trading_date - research_day).days
    if not 1 <= age <= MAX_REPORT_AGE_DAYS:
        raise ValueError("AI opinion is stale or not from a prior session")
    roles = report.get("agents")
    if (not isinstance(roles, list) or len(roles) != 7
            or any(not isinstance(v, dict) for v in roles)
            or tuple(v.get("role") for v in roles) != ROLES):
        raise ValueError("Incomplete or reordered AI specialist report")
    opinions = []
    for v in roles:
        confidence = v.get("confidence")
        if (type(confidence) not in (int, float)
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
                or v.get("action") not in ("BUY", "SELL", "HOLD", "NO_TRADE")
                or v.get("symbol") not in
                ("SPY", "QQQ", "GDXD", "GDXU", "TQQQ", "GLD", "TLT", "BIL", "NONE")):
            raise ValueError("Invalid AI specialist opinion")
        opinions.append(v)

    hypo = report.get("hypothesis")
    approved = False
    if report.get("consensus") == "HYPOTHESIS_FOR_BACKTEST":
        if not isinstance(hypo, dict) or hypo.get("symbol") not in RISK_ON or hypo.get("action") != "BUY":
            return {"approved": False, "reason": "NO_RISK_ON_BUY"}
        # Conservative validation independently of the consensus label.
        ticker = hypo["symbol"]
        analyst_votes = sum(
            v["action"] == "BUY" and v["symbol"] == ticker
            and v["confidence"] >= MIN_CONFIDENCE for v in opinions[:4])
        approvers = opinions[4:6]
        reviewer = opinions[6]
        approved = (analyst_votes >= 3
                    and all(v["action"] == "BUY" and v["symbol"] == ticker
                            and v["confidence"] >= MIN_CONFIDENCE for v in approvers)
                    and reviewer["action"] not in ("SELL", "NO_TRADE")
                    and (reviewer["action"] != "BUY" or reviewer["symbol"] == ticker))
    return {"approved": approved,
            "reason": "AI_RISK_ON_APPROVED" if approved else "NO_AGENT_APPROVAL"}


def fetch_agent_gate(trading_date, opener=urlopen):
    """Bounded download of sanitized public data; no brokerage access."""
    req = Request(PUBLIC_STATUS, headers={"User-Agent": "sandbox-paper-ai-orb-gate"})
    with opener(req, timeout=8) as response:
        raw = response.read(12001)
    if len(raw) > 12000:
        raise ValueError("AI desk publication oversized")
    return evaluate_agent_gate(json.loads(raw), trading_date)
