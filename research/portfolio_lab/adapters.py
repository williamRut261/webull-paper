"""Deterministic, read-only completed-close strategy adapters.

Do not call these functions from any brokerage execution path. Signals are for
the *next* regular session, not a trade at the same close.
"""
from dataclasses import dataclass, asdict
from typing import Mapping
import math

import numpy as np
import pandas as pd

from strategy_engine import Evaluator, load_strategy, original_targets


@dataclass(frozen=True)
class RSIState:
    """State of the unleveraged RSI variant (NOT the author's 2x backtest)."""
    active_qqq: float | None = None
    cooldown: int = 0
    dip_active: bool = False
    as_of: str = ""


@dataclass(frozen=True)
class RSIResult:
    weights: dict
    state: RSIState
    weekly_rsi_7: float | None
    ema_200: float
    bull: bool


def _history(frame, needed, minimum):
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("Historical closes must use a pandas DatetimeIndex")
    if frame.index.tz is not None or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Historical close dates must be unique, increasing, timezone-naive")
    if len(frame) < minimum or any(symbol not in frame for symbol in needed):
        raise ValueError("Missing required symbols or completed lookback sessions")
    if any(day.normalize() != day for day in frame.index):
        raise ValueError("Historical index must be exchange dates at midnight")
    columns = frame.loc[:, list(needed)].astype(float)
    if not np.isfinite(columns.to_numpy()).all() or (columns <= 0).any().any():
        raise ValueError("Daily close history contains missing, invalid or nonpositive values")
    return columns


def beethoven_from_closes(closes: pd.DataFrame, as_of: str, root=None):
    """Run actual existing 501-node tree using only point-in-time supplied bars.

    Does not substitute any asset or query the brokerage. The caller must supply
    original signal-symbol history; the evaluator fails if any *used* input is
    incomplete. A one-day signal is not proof of Composer mathematical parity.
    """
    if not isinstance(closes, pd.DataFrame) or not isinstance(closes.index, pd.DatetimeIndex):
        raise ValueError("Beethoven needs dated daily closes")
    if closes.index.has_duplicates or not closes.index.is_monotonic_increasing or (
            closes.index.tz is not None):
        raise ValueError("Unsorted/duplicated/tz-aware Beethoven history")
    if not len(closes) or closes.index[-1].date().isoformat() != as_of:
        raise ValueError("Beethoven signal requires exact completed as-of close")
    # Evaluator validates active-path data and the JSON decision tree.
    raw = Evaluator(root or load_strategy(), closes).evaluate()
    return original_targets(raw, exposure=1.0)


def _weekly_rsi_from_author(prices, window=7):
    """Match HakuYuri's EWM RSI, with a ONE-WEEK shift against look-ahead."""
    delta = prices.diff()
    up = delta.where(delta > 0, 0).ewm(alpha=1 / window, adjust=False).mean()
    down = (-delta.where(delta < 0, 0)).ewm(alpha=1 / window, adjust=False).mean()
    ratio = up / down
    return 100 - 100 / (1 + ratio)


def rsi_trend_from_closes(closes: pd.DataFrame, state=RSIState(), *,
                          bull_qqq=1.0, bear_qqq=0.75, dip_qqq=1.0,
                          rsi_dip_threshold=15, cooldown_days=5):
    """Research variant: EMA200 + prior-week RSI7, QQQ/GLD, max 100% holdings.

    The source author's bull target is 200% QQQ. This deliberately clips
    bull exposure to 100% (without borrowing) and cannot claim published
    24.25% CAGR. Dip state and cooldown MUST persist between sessions.
    """
    if not isinstance(state, RSIState):
        raise ValueError("Invalid RSI state")
    for value in (bull_qqq, bear_qqq, dip_qqq):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (
                not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("Unleveraged QQQ exposure must be between 0 and 1")
    if isinstance(cooldown_days, bool) or not isinstance(cooldown_days, int) or (
            cooldown_days < 0 or cooldown_days > 60):
        raise ValueError("Invalid cooldown")
    if not isinstance(rsi_dip_threshold, (int, float)) or (
            not 0 < rsi_dip_threshold < 100):
        raise ValueError("Invalid weekly RSI threshold")
    frame = _history(closes, ("QQQ", "GLD"), 252)
    day = frame.index[-1].date().isoformat()
    if state.as_of and state.as_of >= day:
        raise ValueError("RSI state reused or out of order")
    # A previous state is only safe with exactly the next observed session.
    if state.as_of and state.as_of != frame.index[-2].date().isoformat():
        raise ValueError("RSI state must belong to immediately preceding session")
    qqq = frame["QQQ"]
    ema = float(qqq.ewm(span=200, adjust=False).mean().iloc[-1])
    # The author's weekly indicator is shifted one full W-FRI period before
    # being forward-filled to daily observations.
    shifted = _weekly_rsi_from_author(qqq.resample("W-FRI").last()).shift(1)
    weekly = shifted.reindex(frame.index, method="ffill").iloc[-1]
    w_rsi = float(weekly) if pd.notna(weekly) else None
    price = float(qqq.iloc[-1])
    bull = price > ema

    if state.active_qqq is None:
        dip = bool(not bull and w_rsi is not None and w_rsi < rsi_dip_threshold)
        active = bull_qqq if bull else (dip_qqq if dip else bear_qqq)
        cooldown = 0
    elif state.cooldown:
        active = state.active_qqq
        dip = state.dip_active
        cooldown = state.cooldown - 1
    else:
        dip = False if bull else (state.dip_active or
                                   (w_rsi is not None and w_rsi < rsi_dip_threshold))
        proposed = bull_qqq if bull else (dip_qqq if dip else bear_qqq)
        active = proposed
        cooldown = cooldown_days if not math.isclose(active, state.active_qqq) else 0
    next_state = RSIState(active_qqq=float(active), cooldown=cooldown,
                          dip_active=bool(dip), as_of=day)
    weights = {"QQQ": float(active)}
    if active < 1:
        weights["GLD"] = round(1.0 - active, 12)
    return RSIResult(weights={s: w for s, w in weights.items() if w > 0},
                     state=next_state, weekly_rsi_7=w_rsi, ema_200=ema,
                     bull=bull)


def rsi_replay(closes: pd.DataFrame):
    """Initialize persistent RSI state WITHOUT retroactive 'day zero' shortcuts."""
    _history(closes, ("QQQ", "GLD"), 252)
    state = RSIState()
    result = None
    for idx in range(252, len(closes) + 1):
        result = rsi_trend_from_closes(closes.iloc[:idx], state)
        state = result.state
    return result


def json_state(result):
    return asdict(result.state)
