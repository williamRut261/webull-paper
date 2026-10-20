"""strategy 6.6 decision tree with a cash-funded, paper-only execution boundary."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
import fcntl
import json
import math
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest, GetCalendarRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed, Adjustment

from strategy_engine import (load_strategy, signal_symbols, Evaluator, original_targets,
                             ORIGINAL_EXECUTION_ASSETS)

PAPER = True
MAX_EXPOSURE = 0.99
MIN_TRADE_DOLLARS = 25.0
REBALANCE_TOLERANCE = 0.01
ORDER_FILL_TIMEOUT = 90
CENTRAL = ZoneInfo('America/Chicago')
MARKET_TZ = ZoneInfo('America/New_York')
ALLOWED_ASSETS = ORIGINAL_EXECUTION_ASSETS
FORBIDDEN_ASSETS = frozenset()
STATE_DIR = Path('state')
trading_client = None
data_client = None


def log(message=''):
    print(f"[{datetime.now(CENTRAL):%Y-%m-%d %H:%M:%S %Z}] {message}", flush=True)


def today_tag():
    return datetime.now(MARKET_TZ).strftime('%Y%m%d')


def finite(value, label, minimum=0):
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise RuntimeError(f'Invalid {label}: must be finite and >= {minimum}')
    return number


def floor_amount(value, places):
    return float(Decimal(str(value)).quantize(Decimal(10) ** -places, rounding=ROUND_DOWN))


def connect():
    global trading_client, data_client
    if PAPER is not True:
        raise RuntimeError('LIVE TRADING IS BLOCKED')
    key, secret = os.environ.get('ALPACA_API_KEY'), os.environ.get('ALPACA_SECRET_KEY')
    if not key or not secret:
        raise RuntimeError('Missing ALPACA_API_KEY / ALPACA_SECRET_KEY')
    # No URL override or live-mode option is accepted.
    trading_client = TradingClient(key, secret, paper=True)
    data_client = StockHistoricalDataClient(key, secret)


def validate_symbol(symbol):
    if symbol not in ALLOWED_ASSETS or symbol in FORBIDDEN_ASSETS:
        raise RuntimeError('BLOCKED execution symbol: ' + symbol)


def validate_targets(targets):
    if not targets:
        raise RuntimeError('Empty targets')
    for s, w in targets.items():
        validate_symbol(s)
        finite(w, 'target weight')
    if sum(targets.values()) > MAX_EXPOSURE + 1e-9:
        raise RuntimeError('BLOCKED target exposure exceeds 99%')


def market_is_open():
    clock = trading_client.get_clock()
    log(f'Market open={clock.is_open}; next_close={clock.next_close}')
    return bool(clock.is_open)


def get_open_orders():
    return trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))


def already_ran_today():
    start = datetime.now(MARKET_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    orders = trading_client.get_orders(filter=GetOrdersRequest(
        status=QueryOrderStatus.ALL, after=start, limit=500))
    # A truncated history must never permit a duplicate run.
    if len(orders) >= 500:
        raise RuntimeError('Daily order history may be truncated; refusing execution')
    prefix = f'flowstate-{today_tag()}-'
    return any((o.client_order_id or '').startswith(prefix) for o in orders)


@contextmanager
def execution_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / 'execution.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another local execution is active') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def claim_day(day):
    # Exclusive creation, BEFORE any order attempt. Also persists no-op days.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f'{day}.json'
    with path.open('x') as handle:
        json.dump({'day': day, 'status': 'claimed', 'paper': True}, handle)
        handle.flush()
        os.fsync(handle.fileno())


def get_price_data(symbols):
    today = datetime.now(MARKET_TZ).date()
    start = today - timedelta(days=1700)
    calendar = trading_client.get_calendar(filters=GetCalendarRequest(start=start, end=today - timedelta(days=1)))
    sessions = pd.DatetimeIndex([pd.Timestamp(c.date).normalize() for c in calendar])
    if sessions.empty:
        raise RuntimeError('No completed market sessions')
    # Use completed, split/dividend-adjusted sessions only, never partial today.
    end = datetime.combine(today, datetime.min.time(), tzinfo=MARKET_TZ)
    result = pd.DataFrame(index=sessions)
    symbols = sorted(symbols)
    for offset in range(0, len(symbols), 15):
        request = StockBarsRequest(symbol_or_symbols=symbols[offset:offset+15],
            timeframe=TimeFrame.Day, start=datetime.combine(start, datetime.min.time(), tzinfo=MARKET_TZ),
            end=end, feed=DataFeed.IEX, adjustment=Adjustment.ALL)
        bars = data_client.get_stock_bars(request).df
        if bars is None or bars.empty:
            continue
        for s in symbols[offset:offset+15]:
            if s not in bars.index.get_level_values('symbol'):
                continue
            series = bars.xs(s, level='symbol')['close'].sort_index()
            series.index = pd.DatetimeIndex(series.index).tz_convert(MARKET_TZ).tz_localize(None).normalize()
            if series.index.duplicated().any():
                raise RuntimeError('Duplicate daily bars: ' + s)
            result[s] = series.reindex(sessions)
    log(f'Signal date={sessions[-1].date()}; adjusted IEX data; {len(result.columns)} symbols')
    return result


def build_targets(closes, root=None):
    root = load_strategy() if root is None else root
    raw = Evaluator(root, closes, log).evaluate()
    log('SOURCE ALLOCATION ' + json.dumps(raw, sort_keys=True))
    targets = original_targets(raw, MAX_EXPOSURE)
    validate_targets(targets)
    log('ORIGINAL HOLDING TARGETS ' + json.dumps(targets, sort_keys=True))
    return targets


def get_account():
    account = trading_client.get_account()
    equity = finite(account.equity, 'equity')
    if equity <= 0 or getattr(account, 'trading_blocked', False) or getattr(account, 'account_blocked', False):
        raise RuntimeError('Account is blocked or has no positive equity')
    finite(account.cash, 'cash')
    return account


def get_positions():
    positions = {}
    for p in trading_client.get_all_positions():
        qty = finite(p.qty, 'position quantity')
        mv = finite(p.market_value, 'position value')
        if str(getattr(p, 'side', '')).split('.')[-1].lower() == 'short':
            raise RuntimeError('SHORT POSITION DETECTED')
        if qty == 0 and mv != 0:
            raise RuntimeError('Inconsistent position')
        positions[p.symbol] = {'qty': qty, 'market_value': mv}
    return positions


def preflight_assets(targets, positions):
    for symbol in set(targets) | (set(positions) & ALLOWED_ASSETS):
        validate_symbol(symbol)
        asset = trading_client.get_asset(symbol)
        if not asset.tradable or not asset.fractionable or str(asset.status).split('.')[-1].lower() != 'active':
            raise RuntimeError('Asset unavailable for fractional trading: ' + symbol)


def wait_for_order(order_id):
    deadline = time.monotonic() + ORDER_FILL_TIMEOUT
    while True:
        order = trading_client.get_order_by_id(order_id)
        status = str(order.status).split('.')[-1].lower()
        if status == 'filled':
            log(f'FILLED {order.symbol}: qty={order.filled_qty}; price={order.filled_avg_price}')
            return order
        if status in {'canceled', 'expired', 'rejected', 'done_for_day', 'replaced', 'stopped', 'suspended'}:
            raise RuntimeError(f'Order ended without full fill: {status}')
        if time.monotonic() >= deadline:
            # No retry/resubmission. Open-order and day guards block later runs.
            raise RuntimeError('Order fill timeout; stopping before further orders')
        time.sleep(3)


def submit_market_order(symbol, side, day, *, qty=None, notional=None):
    validate_symbol(symbol)
    if PAPER is not True or day != today_tag():
        raise RuntimeError('Paper lock or trading date guard failed')
    if not market_is_open() or get_open_orders():
        raise RuntimeError('Market closed or open orders appeared')
    account, positions = get_account(), get_positions()
    if side == OrderSide.BUY:
        if qty is not None or notional is None:
            raise RuntimeError('Buys must specify a cash amount')
        requested = finite(notional, 'buy notional')
        gross = sum(p['market_value'] for p in positions.values())
        budget = max(0, min(float(account.cash) * 0.995,
                           float(account.equity) * MAX_EXPOSURE - gross))
        amount = floor_amount(min(requested, budget), 2)
        if amount < MIN_TRADE_DOLLARS:
            log('Insufficient cash/exposure headroom; skipping ' + symbol)
            return None
        fields = {'notional': amount}
    elif side == OrderSide.SELL:
        if qty is None or notional is not None:
            raise RuntimeError('Sells must specify owned quantity')
        amount = floor_amount(min(finite(qty, 'sell quantity'), positions.get(symbol, {}).get('qty', 0)), 6)
        if amount <= 0:
            return None
        fields = {'qty': amount}
    else:
        raise RuntimeError('Unsupported order side')
    cid = f'flowstate-{day}-{side.value.lower()}-{symbol}'
    request = MarketOrderRequest(symbol=symbol, side=side, time_in_force=TimeInForce.DAY,
                                 client_order_id=cid, **fields)
    log(f'SUBMIT PAPER {side.value} {symbol} {fields} cid={cid}')
    return wait_for_order(trading_client.submit_order(order_data=request).id)


def rebalance(targets, day):
    validate_targets(targets)
    account, positions = get_account(), get_positions()
    preflight_assets(targets, positions)
    equity = float(account.equity)
    log(f'Equity=${equity:,.2f}; cash=${float(account.cash):,.2f}')
    for symbol, p in positions.items():
        if symbol not in ALLOWED_ASSETS:
            log('Unmanaged position counted in gross exposure: ' + symbol)
            continue
        excess = p['market_value'] - equity * targets.get(symbol, 0)
        if excess <= max(MIN_TRADE_DOLLARS, equity * REBALANCE_TOLERANCE):
            continue
        if p['market_value'] <= 0:
            raise RuntimeError('Cannot size sale from zero position value')
        qty = p['qty'] if symbol not in targets else p['qty'] * min(1, excess / p['market_value'])
        submit_market_order(symbol, OrderSide.SELL, day, qty=qty)
    for symbol, weight in targets.items():
        account, positions = get_account(), get_positions()
        equity = float(account.equity)
        shortage = equity * weight - positions.get(symbol, {}).get('market_value', 0)
        if shortage > max(MIN_TRADE_DOLLARS, equity * REBALANCE_TOLERANCE):
            submit_market_order(symbol, OrderSide.BUY, day, notional=shortage)
    account, positions = get_account(), get_positions()
    gross = sum(p['market_value'] for p in positions.values()) / float(account.equity)
    log(f'Final gross exposure={gross:.4%}; positions={positions}')
    if gross > 1 + 1e-9:
        raise RuntimeError('Gross exposure exceeds 100%; review account before next execution')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--paper-execute', action='store_true', help='Enable paper orders only')
    modes.add_argument('--dry-run', action='store_true', help='Calculate targets without orders (default)')
    parser.add_argument('--prices-csv', help='Offline adjusted close matrix: date column and original symbol columns')
    args = parser.parse_args(argv)
    if args.prices_csv and args.paper_execute:
        parser.error('Offline prices cannot be used to execute orders')
    root = load_strategy()
    if args.prices_csv:
        closes = pd.read_csv(args.prices_csv, index_col=0, parse_dates=True)
        if closes.empty or not closes.index.is_monotonic_increasing or closes.index.has_duplicates:
            raise RuntimeError('Offline dates must be unique and sorted')
        build_targets(closes, root)
        return 0
    connect()
    with execution_lock():
        day = today_tag()
        if not market_is_open():
            log('Market closed; no execution')
            return 0
        if get_open_orders():
            log('Existing open orders; no execution')
            return 0
        if args.paper_execute and ((STATE_DIR / f'{day}.json').exists() or already_ran_today()):
            log('Day already claimed or broker order found; duplicate run skipped')
            return 0
        closes = get_price_data(signal_symbols(root))
        targets = build_targets(closes, root)
        if not args.paper_execute:
            log('DRY RUN: no orders submitted')
            return 0
        # All signal validation finishes before any order attempt.
        if day != today_tag() or not market_is_open() or get_open_orders() or already_ran_today():
            raise RuntimeError('Execution preconditions changed')
        claim_day(day)
        rebalance(targets, day)
    log('Run complete')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        log(f'FATAL {type(exc).__name__}: {exc}')
        raise
