"""Research-only multi-strategy capital book and net target planner.

Pure arithmetic. No broker imports, HTTP, secrets, accounts or order submission.
A real account must have ONE separately reviewed order executor.
"""
from collections import defaultdict
from dataclasses import dataclass
import math
import re
from typing import Mapping


class PortfolioError(ValueError):
    pass


def number(value, context):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise PortfolioError(context + " must be numeric")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise PortfolioError(context + " must be nonnegative and finite")
    return value


def weight_map(weights, label):
    if not isinstance(weights, Mapping):
        raise PortfolioError(label + " must be a symbol->weight mapping")
    clean = {}
    for symbol, weight in weights.items():
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,8}", symbol):
            raise PortfolioError(label + " contains an unapproved symbol format")
        value = number(weight, label + "/" + symbol)
        if value > 1:
            raise PortfolioError(label + "/" + symbol + " exceeds 100%")
        if value:
            clean[symbol] = value
    if sum(clean.values()) > 1.0 + 1e-9:
        raise PortfolioError(label + " targets exceed sleeve capital")
    return clean


@dataclass(frozen=True)
class ResearchPlan:
    targets: dict
    sleeve_ledger: dict
    cash_weight: float
    reserve: float
    changes: dict

    def to_dict(self):
        return {
            "research_only": True,
            "target_weights": self.targets,
            "virtual_sleeve_attribution": self.sleeve_ledger,
            "cash_weight": self.cash_weight,
            "cash_reserve_floor": self.reserve,
            "proposed_net_weight_changes_NOT_ORDERS": self.changes,
            "note": "One central executor is REQUIRED before any future live/paper use."
        }


def combine(budgets: Mapping, signals: Mapping, *, cash_reserve=0.01,
            max_symbol_weight=0.99, current_weights=None):
    """Merge sleeves into ONE target book. Every sleeve only owns its budget.

    A missing signal for a funded sleeve FAILS CLOSED, rather than making
    an accidental liquidation or silently reallocating another sleeve.
    An explicitly empty signal means keep that sleeve's money in cash.
    """
    if not isinstance(budgets, Mapping) or not isinstance(signals, Mapping):
        raise PortfolioError("Budgets and signals must be mappings")
    reserve = number(cash_reserve, "cash reserve")
    symbol_cap = number(max_symbol_weight, "per-symbol cap")
    if reserve > 1 or not 0 < symbol_cap <= 1:
        raise PortfolioError("Invalid portfolio safety cap")
    if len(set(budgets)) != len(budgets) or not all(isinstance(k, str) and k for k in budgets):
        raise PortfolioError("Invalid sleeve identifiers")
    clean_budgets = {name: number(x, "budget/"+name) for name, x in budgets.items()}
    if any(x > 1 for x in clean_budgets.values()):
        raise PortfolioError("Sleeve budget exceeds equity")
    if sum(clean_budgets.values()) > 1.0 - reserve + 1e-9:
        raise PortfolioError("Sleeves exceed available equity after cash reserve")
    if any(name not in budgets for name in signals):
        raise PortfolioError("Unfunded or unknown signal source")
    missing = {name for name, cap in clean_budgets.items() if cap > 0 and name not in signals}
    if missing:
        raise PortfolioError("Funded sleeves missing signals: "+", ".join(sorted(missing)))
    targets = defaultdict(float)
    ledger = {}
    for name in sorted(clean_budgets):
        budget = clean_budgets[name]
        holdings = weight_map(signals.get(name, {}), name)
        if budget == 0 and holdings:
            raise PortfolioError("Disabled sleeve must not submit signals: "+name)
        ledger[name] = {}
        for symbol, within in holdings.items():
            contribution = budget * within
            ledger[name][symbol] = round(contribution, 12)
            targets[symbol] += contribution
    for sym, wt in targets.items():
        if wt > symbol_cap + 1e-9:
            raise PortfolioError("Overlapping sleeves breach combined symbol cap: "+sym)
    if sum(targets.values()) > 1 - reserve + 1e-9:
        raise PortfolioError("Gross exposure exceeds cash-reserved equity")
    before = weight_map(current_weights or {}, "current portfolio")
    if sum(before.values()) > 1 + 1e-9:
        raise PortfolioError("Current holdings exceed equity")
    after = {key: round(val, 12) for key, val in sorted(targets.items()) if val > 1e-12}
    changes = {key: round(after.get(key, 0) - before.get(key, 0), 12)
               for key in sorted(set(after) | set(before))
               if abs(after.get(key, 0) - before.get(key, 0)) > 1e-10}
    return ResearchPlan(targets=after, sleeve_ledger=ledger,
                        cash_weight=round(1 - sum(after.values()), 12),
                        reserve=reserve, changes=changes)
