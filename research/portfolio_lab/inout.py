"""Original-style Guenther/QuantConnect In & Out market-regime RESEARCH adapter.

Independent implementation of the public algorithm's key signal ideas:
252 daily closes; 11-session mean baseline 55..65 days back; five
economic proxy signals and three relative safe-haven pairs; bottom 1% shock
trigger; QQQ risk-on, TLT/IEF/GLD risk-off; fixed 15-session cooldown.

Not a bit-for-bit reproduction of the published backtest. In particular,
the linked historical code uses additional adaptive waiting logic and its
own trading calendar/fill assumptions. No trading API is imported here.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

REQUIRED = ("QQQ", "XLI", "DBB", "IGE", "SHY", "UUP",
            "GLD", "SLV", "XLU", "FXF", "FXA")
RISK_ON = {"QQQ": 1.0}
RISK_OFF = {"TLT": 0.40, "IEF": 0.40, "GLD": 0.20}


@dataclass(frozen=True)
class RegimeState:
    is_in: bool = True
    days_since_exit: int = 999
    as_of: str = ""


@dataclass(frozen=True)
class RegimeResult:
    weights: dict
    state: RegimeState
    triggered: tuple


def inout_from_closes(closes: pd.DataFrame, state=RegimeState()) -> RegimeResult:
    """Process ONE new *completed* daily close; execution is a later session.

    Caller must persist returned state and never replay the same session as a
    new update. Does not support evaluating earlier dates in a later window.
    """
    if not isinstance(closes, pd.DataFrame) or len(closes) < 252:
        raise ValueError("In & Out requires 252 historical daily sessions")
    if not isinstance(closes.index, pd.DatetimeIndex) or (
            closes.index.has_duplicates or not closes.index.is_monotonic_increasing):
        raise ValueError("Daily dates must be unique, sorted DatetimeIndex")
    if any(s not in closes for s in REQUIRED):
        raise ValueError("Missing signal proxy price history")
    f = closes.loc[:, list(REQUIRED)].iloc[-252:].astype(float)
    if not np.isfinite(f.to_numpy()).all() or (f <= 0).any().any():
        raise ValueError("Incomplete or invalid price history")
    as_of = f.index[-1].date().isoformat()
    if state.as_of and state.as_of >= as_of:
        raise ValueError("Cannot reuse or reverse a processed market session")
    baseline = sum(f.shift(n) for n in range(55, 66)) / 11.0
    sample = f / baseline - 1.0
    sample["UUP"] *= -1
    sample["G_S"] = -(sample["GLD"] - sample["SLV"])
    sample["U_I"] = -(sample["XLU"] - sample["XLI"])
    sample["C_A"] = -(sample["FXF"] - sample["FXA"])
    columns = ["XLI", "DBB", "IGE", "SHY", "UUP", "G_S", "U_I", "C_A"]
    recent = sample.loc[:, columns].dropna()
    if len(recent) < 100:
        raise ValueError("Insufficient historical regime observations")
    # Threshold computed ONLY from past sessions; never from future.
    cutoff = recent.iloc[:-1].quantile(.01)
    shock = recent.iloc[-1] < (cutoff - 1e-9)
    triggered = tuple(sorted(shock.index[shock].tolist()))
    if triggered:
        next_state = RegimeState(is_in=False, days_since_exit=0, as_of=as_of)
    elif state.is_in:
        next_state = RegimeState(is_in=True, days_since_exit=state.days_since_exit + 1,
                                 as_of=as_of)
    else:
        elapsed = state.days_since_exit + 1
        next_state = RegimeState(is_in=elapsed >= 15, days_since_exit=elapsed, as_of=as_of)
    return RegimeResult(weights=dict(RISK_ON if next_state.is_in else RISK_OFF),
                        state=next_state, triggered=triggered)
