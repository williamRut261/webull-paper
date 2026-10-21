"""Webull SANDBOX four-sleeve *cutover preflight* (NEVER places orders).

The legacy Webull PAPER bot currently owns the sandbox account's 80/19 book.
Do not run a second order executor beside it. This module only checks a
potential 25/25/25/25 cutover and builds conservative draft target weights.
"""
from dataclasses import dataclass
from datetime import datetime
import math
from zoneinfo import ZoneInfo

from research.portfolio_lab.portfolio import PortfolioError, combine
from strategy_engine import ORIGINAL_EXECUTION_ASSETS
from trader_combo.universe import CANDIDATES

NY = ZoneInfo("America/New_York")
BUDGETS = {"beethoven": .25, "inout": .25, "rsi_trend": .25, "claude_orb": .25}
# No arbitrary symbols: only existing Beethoven assets + three research
# strategy universes, including its explicit cash/defensive proxies.
ALLOWED = ORIGINAL_EXECUTION_ASSETS | CANDIDATES | {"QQQ", "TLT", "IEF", "GLD"}
PAPER_GROSS_LIMIT = .99


@dataclass(frozen=True)
class CutoverPreflight:
    sandbox_draft_targets: dict
    deployment_allowed: bool
    reserve_floor: float
    max_gross_exposure: float
    blockers: tuple


def validate_market_snapshot(quotes, symbols, observed_at):
    """Require actual timestamped observation for EVERY proposed position."""
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise PortfolioError("Time must be timezone-aware")
    if not isinstance(quotes, dict):
        raise PortfolioError("Market snapshots must be a mapping")
    for symbol in symbols:
        row = quotes.get(symbol)
        if not isinstance(row, dict):
            raise PortfolioError("Missing Webull snapshot for " + symbol)
        price, stamp = row.get("price"), row.get("trade_at")
        if (isinstance(price, bool) or not isinstance(price, (float, int))
                or not math.isfinite(price) or price <= 0):
            raise PortfolioError("Invalid price for " + symbol)
        try:
            trade_at = datetime.fromisoformat(stamp)
        except (TypeError, ValueError) as exc:
            raise PortfolioError("Invalid Webull quote time for " + symbol) from exc
        if trade_at.tzinfo is None:
            raise PortfolioError("Quote time requires timezone for " + symbol)
        age = (observed_at - trade_at).total_seconds()
        if trade_at.astimezone(NY).date() != observed_at.astimezone(NY).date() or not 0 <= age <= 120:
            raise PortfolioError("Stale, future, or wrong-day Webull quote: " + symbol)


def stage_cutover(research_plan, quotes, observed_at, *,
                  legacy_runner_disabled=False, scanner_runner_disabled=False,
                  pinned_cash_account_verified=False,
                  broker_flat_verified=False, no_open_orders_verified=False):
    """Draft targets with 1% extra cash: equal sleeve CAPITAL not gross exposure.

    Blocks actual cutover until the old schedules are disabled AND an
    exclusive broker reconciler is independently implemented and reviewed.
    The callable has no brokerage SDK, no order side effects and does not
    transition deployment_allowed to True under any input.
    """
    if not isinstance(research_plan, dict) or (
            research_plan.get("portfolio_mode") != "RESEARCH_ONLY_NOT_BROKER_ORDERS"):
        raise PortfolioError("Use validated research four-signal plan only")
    if research_plan.get("independent_sleeve_budgets") != BUDGETS:
        raise PortfolioError("Exactly four 25 percent virtual sleeves required")
    sleeves = research_plan.get("sleeve_targets_within_own_capital")
    if not isinstance(sleeves, dict) or set(sleeves) != set(BUDGETS):
        raise PortfolioError("All four source signals must be present")
    for name, mapping in sleeves.items():
        if set(mapping) - ALLOWED:
            raise PortfolioError("Unreviewed Webull PAPER symbol: " + name)
    pure = combine(BUDGETS, sleeves, cash_reserve=0, max_symbol_weight=1)
    if pure.targets != research_plan.get("target_weights"):
        raise PortfolioError("Research input target weights were modified")
    # A sleeve owns 25% of virtual capital but not every dollar must be
    # invested: reserve 0.25% of total equity within EACH 25%-owned sleeve.
    deployed_budgets = {name: cap * PAPER_GROSS_LIMIT for name, cap in BUDGETS.items()}
    reduced = combine(deployed_budgets, sleeves, cash_reserve=.01, max_symbol_weight=.99)
    validate_market_snapshot(quotes, reduced.targets, observed_at)
    blockers = ["Missing completed, reviewed exclusive Webull SANDBOX execution and "
                "per-strategy fill/cash reconciler"]
    if not legacy_runner_disabled:
        blockers.append("Legacy Beethoven 80/19 close runner still enabled")
    if not scanner_runner_disabled:
        blockers.append("Legacy ORB morning runner still enabled")
    if not pinned_cash_account_verified:
        blockers.append("Pinned sandbox CASH account has not been revalidated")
    if not broker_flat_verified:
        blockers.append("Legacy positions not proved flat and reconciled")
    if not no_open_orders_verified:
        blockers.append("Open/pending orders not proved absent")
    return CutoverPreflight(
        sandbox_draft_targets=reduced.targets,
        deployment_allowed=False,
        reserve_floor=.01,
        max_gross_exposure=PAPER_GROSS_LIMIT,
        blockers=tuple(blockers))
