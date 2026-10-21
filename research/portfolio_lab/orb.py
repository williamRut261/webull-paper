"""Read-only 25%-sleeve allocation of authentic OG ORB scanner evidence.

This wraps the existing scanner's exact setup filtering, but converts eligible
setups to *virtual* whole-share weights. Quotes must be supplied independently
from timestamped sandbox data; never use Yahoo signals as execution prices.
This module cannot submit orders and does not claim protective stops exist.
"""
from dataclasses import dataclass
from datetime import datetime
import math

from trader_combo.scan import select_recent_signals
from trader_combo.universe import MAX_POSITIONS, MAX_STOP_DISTANCE, MIN_STOP_DISTANCE
from webull_paper.signal_dry_run import NY


@dataclass(frozen=True)
class ORBPlan:
    weights: dict
    planned: tuple
    selected: int
    observed_at: str
    evidence_source: str = "OG Yahoo 5m ORB + separately supplied quote snapshots"


def orb_from_observations(scanner_report, quote_snapshots, observed_at,
                          *, total_equity=10000.0, sleeve_weight=0.25,
                          max_account_loss_per_trade=0.003):
    """Plan whole-share intraday scanner exposures, never orders or fills.

    Requires a FRESH session report plus execution-price observations with
    timestamp and positive price. This virtual plan does not assert that Webull
    will accept any symbol or quantity.
    """
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise ValueError("A timezone-aware scanner observation time is required")
    now = observed_at.astimezone(NY)
    if now.weekday() >= 5 or not (10 * 60 + 20 <= now.hour * 60 + now.minute < 10 * 60 + 40):
        raise ValueError("ORB snapshots require the 10:20-10:40 ET entry window")
    if not isinstance(scanner_report, dict) or not isinstance(quote_snapshots, dict):
        raise ValueError("Scanner and Webull snapshots must be mappings")
    for n in (total_equity, sleeve_weight, max_account_loss_per_trade):
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0:
            raise ValueError("Invalid virtual capital or risk fraction")
    if sleeve_weight > 1 or max_account_loss_per_trade > sleeve_weight:
        raise ValueError("Invalid ORB sleeve allocation")
    signals = select_recent_signals(scanner_report, now)
    # Do not claim zero hits if the upstream scan did not provide coverage.
    remaining = float(total_equity) * sleeve_weight
    chosen = []
    amounts = {}
    for item in signals[:MAX_POSITIONS]:
        symbol = item["symbol"]
        quote = quote_snapshots.get(symbol)
        if not isinstance(quote, dict):
            raise ValueError("Missing independently timestamped ORB quote: " + symbol)
        price = quote.get("price")
        at = quote.get("trade_at")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or (
                not math.isfinite(price) or price <= 0):
            raise ValueError("Invalid ORB execution reference price")
        try:
            stamp = datetime.fromisoformat(at)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid quote timestamp") from exc
        if stamp.tzinfo is None:
            raise ValueError("ORB quote needs timezone")
        age = (now - stamp.astimezone(NY)).total_seconds()
        if stamp.astimezone(NY).date() != now.date() or not 0 <= age <= 120:
            raise ValueError("ORB reference quote is stale, future, or wrong session")
        if abs(price / item["signal_price"] - 1) > .01:
            continue  # Do not chase the unofficial Yahoo breakout price.
        stop = (item["range_low"] + item["range_high"]) / 2
        distance = (price - stop) / price
        if not MIN_STOP_DISTANCE <= distance <= MAX_STOP_DISTANCE:
            continue
        permitted = min(remaining, total_equity * sleeve_weight / len(signals),
                        total_equity * max_account_loss_per_trade / distance)
        # Explicit 2% price-buffer budgeting. Virtual actual spend is still at
        # the given quote and can be strictly less than 25% of account.
        shares = int(permitted / (price * 1.02))
        if shares < 1:
            continue
        value = shares * price
        if value > remaining + 1e-8:
            raise ValueError("ORB virtual risk/capital budget violation")
        remaining -= value
        amounts[symbol] = value / (total_equity * sleeve_weight)
        chosen.append({"symbol": symbol, "shares": shares, "quote": float(price),
                       "stop_reference_not_an_order": float(stop),
                       "estimated_loss_at_stop": shares * (price - stop),
                       "quote_at": stamp.isoformat()})
    if sum(amounts.values()) > 1 + 1e-9:
        raise ValueError("ORB budget exceeds 25% sleeve")
    return ORBPlan(weights=amounts, planned=tuple(chosen), selected=len(signals),
                   observed_at=now.isoformat())
