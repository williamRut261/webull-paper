"""Evaluate the supplied Composer tree; never submit orders from this module."""
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

STRATEGY_PATH = Path(__file__).parent / 'strategy' / 'paper_strategy.json'
# Signals always use original symbols. Only final holdings pass through this map.
SUBSTITUTIONS = {
    'AAPX': 'AAPL', 'AGQ': 'SLV', 'AMDL': 'AMD', 'AMZU': 'AMZN',
    'AMZZ': 'AMZN', 'BITX': 'IBIT', 'CONL': 'COIN', 'CRWG': 'CRWV',
    'FAS': 'XLF', 'FBL': 'META', 'GDXU': 'GDX', 'GGLL': 'GOOGL',
    'NVDL': 'NVDA', 'OKLL': 'OKLO', 'QLD': 'QQQ', 'SPXL': 'SPY',
    'TECL': 'XLK', 'TMF': 'TLT', 'TQQQ': 'QQQ', 'TSLR': 'TSLA',
    'UPRO': 'SPY', 'URAA': 'URA',
    **{s: 'BIL' for s in ('GDXD', 'FAZ', 'PSQ', 'SOXS', 'SQQQ',
                          'SRTY', 'TECS', 'UVXY', 'WEBS', 'BTAL')},
}
# Explicit allowlist: new source assets cannot silently become executable.
UNCHANGED = set('AVGO BABA BAM BIL BN BX CRWV CVX HOOD IBKR KKR LITE MA MU '
                'PLTR QQQ SCCO SCHW SOFI TLT V VTR WELL'.split())
EXECUTION_ASSETS = frozenset(UNCHANGED | set(SUBSTITUTIONS.values()))
BLOCKED_ASSETS = frozenset(SUBSTITUTIONS) | {'SH', 'SPXU', 'SOXL', 'SSO'}
FUNCTIONS = {'relative-strength-index', 'current-price', 'moving-average-price',
             'moving-average-return', 'cumulative-return', 'standard-deviation-return'}
STEPS = {'root', 'group', 'asset', 'if', 'if-child', 'wt-cash-equal',
         'wt-cash-specified', 'wt-inverse-vol', 'filter'}


def walk(node):
    yield node
    for child in node.get('children', []):
        yield from walk(child)


def window(node, prefix):
    value = node.get(prefix + '-fn-params', {}).get('window',
             node.get(prefix + '-window-days'))
    if value is None and node.get(prefix + '-fn') == 'current-price':
        return 1
    result = int(value)
    if result < 1 or result > 1000 or float(value) != result:
        raise ValueError('Invalid indicator window')
    return result


def specified_weights(children):
    result = [float(c['weight']['num']) / float(c['weight']['den']) for c in children]
    if any(not math.isfinite(w) or w < 0 for w in result) or not math.isclose(sum(result), 1):
        raise ValueError('Specified weights must be finite, nonnegative and sum to one')
    return result


def validate_tree(root):
    ids = set()
    for n in walk(root):
        step, children = n['step'], n.get('children', [])
        if step not in STEPS or n['id'] in ids:
            raise ValueError('Unsupported node or duplicate node ID')
        ids.add(n['id'])
        if step == 'asset':
            if n['ticker'] not in UNCHANGED | set(SUBSTITUTIONS) or children:
                raise ValueError('Unreviewed asset or malformed leaf: ' + n['ticker'])
        elif not children:
            raise ValueError('Empty block: ' + n['id'])
        if step == 'if':
            if (any(c['step'] != 'if-child' for c in children)
                    or not children[-1].get('is-else-condition?')
                    or any(c.get('is-else-condition?') for c in children[:-1])):
                raise ValueError('Malformed conditional')
        if step == 'if-child' and not n.get('is-else-condition?'):
            if n['comparator'] not in ('gt', 'lt'):
                raise ValueError('Unsupported comparator')
            for side in ('lhs', 'rhs'):
                if side == 'rhs' and n.get('rhs-fixed-value?'):
                    if not math.isfinite(float(n['rhs-val'])):
                        raise ValueError('Invalid threshold')
                    continue
                if n[side + '-fn'] not in FUNCTIONS:
                    raise ValueError('Unsupported indicator')
                window(n, side)
        if step == 'filter':
            if (n['sort-by-fn'] not in FUNCTIONS or n['select-fn'] not in ('top', 'bottom')
                    or int(n['select-n']) < 1):
                raise ValueError('Unsupported filter')
            window(n, 'sort-by')
        if step == 'wt-cash-specified':
            specified_weights(children)
        if step == 'wt-inverse-vol':
            if int(n['window-days']) < 2 or any(c['step'] != 'asset' for c in children):
                raise ValueError('Unsupported inverse-volatility block')


def load_strategy(path=STRATEGY_PATH):
    root = json.loads(Path(path).read_text())
    validate_tree(root)
    return root


def signal_symbols(root):
    symbols = set()
    for n in walk(root):
        if n['step'] == 'asset':
            symbols.add(n['ticker'])
        if n['step'] == 'if-child' and not n.get('is-else-condition?'):
            symbols.add(n['lhs-val'])
            if not n.get('rhs-fixed-value?'):
                symbols.add(n['rhs-val'])
    return symbols


def indicator(prices, fn, days):
    """Percent metrics use percentage points, as do the source thresholds.

    Wilder RSI: initial simple average, then alpha=1/N smoothing, at most
    1000 prior sessions. Composer does not publish its exact RSI initializer.
    """
    p = np.asarray(prices, dtype=float)
    need = 1 if fn == 'current-price' else days if fn == 'moving-average-price' else days + 1
    if len(p) < need or not np.isfinite(p).all() or (p <= 0).any():
        raise ValueError('Insufficient, missing or invalid price history')
    if fn == 'current-price':
        return float(p[-1])
    if fn == 'moving-average-price':
        return float(p[-days:].mean())
    if fn == 'relative-strength-index':
        delta = np.diff(p[-1001:])
        gains, losses = np.maximum(delta, 0), np.maximum(-delta, 0)
        g, l = gains[:days].mean(), losses[:days].mean()
        for up, down in zip(gains[days:], losses[days:]):
            g, l = (g * (days - 1) + up) / days, (l * (days - 1) + down) / days
        return 50.0 if g == l == 0 else 100.0 if l == 0 else float(100 - 100 / (1 + g / l))
    returns = p[-days:] / p[-days-1:-1] - 1
    if fn == 'cumulative-return':
        return float(100 * (p[-1] / p[-days-1] - 1))
    if fn == 'moving-average-return':
        return float(100 * returns.mean())
    if fn == 'standard-deviation-return':
        if days < 2:
            raise ValueError('Volatility needs at least two returns')
        return float(100 * returns.std(ddof=1))
    raise ValueError('Unsupported indicator: ' + fn)


class Evaluator:
    def __init__(self, root, closes, log=lambda message: None):
        validate_tree(root)
        self.root, self.closes, self.log = root, closes, log
        self.cache = {}

    def metric(self, symbol, fn, days):
        key = symbol, fn, days
        if key not in self.cache:
            if symbol not in self.closes or self.closes[symbol].empty:
                raise ValueError('Missing signal history: ' + symbol)
            series = self.closes[symbol]
            # Leading missing rows before inception are allowed; internal gaps are not.
            first = series.first_valid_index()
            if first is None:
                raise ValueError('Missing signal history: ' + symbol)
            series = series.loc[first:]
            # Restrict non-RSI checks to the lookback actually requested.
            length = 1001 if fn == 'relative-strength-index' else days + 1
            self.cache[key] = indicator(series.iloc[-length:], fn, days)
        return self.cache[key]

    def condition(self, n):
        lhs = self.metric(n['lhs-val'], n['lhs-fn'], window(n, 'lhs'))
        rhs = float(n['rhs-val']) if n.get('rhs-fixed-value?') else self.metric(
            n['rhs-val'], n['rhs-fn'], window(n, 'rhs'))
        result = lhs > rhs if n['comparator'] == 'gt' else lhs < rhs
        self.log(f"CONDITION {n['id']}: {lhs:.6f} {n['comparator']} {rhs:.6f} -> {result}")
        return result

    def combine(self, children, weights):
        result = defaultdict(float)
        for child, weight in zip(children, weights):
            if weight == 0:
                continue
            for symbol, fraction in self.evaluate(child).items():
                result[symbol] += weight * fraction
        return dict(result)

    def evaluate(self, n=None):
        n = self.root if n is None else n
        step, children = n['step'], n.get('children', [])
        if step == 'asset':
            return {n['ticker']: 1.0}
        if step == 'if':
            for child in children:
                if child.get('is-else-condition?') or self.condition(child):
                    self.log('BRANCH ' + child['id'])
                    return self.evaluate(child)
            raise ValueError('No conditional branch selected')
        if step == 'filter':
            # Resolve conditional candidates at the evaluation date, then rank
            # distinct eligible original tickers. Do not rank substituted assets.
            candidates = dict.fromkeys(s for c in children for s in self.evaluate(c))
            scores = {s: self.metric(s, n['sort-by-fn'], window(n, 'sort-by')) for s in candidates}
            ranked = sorted(candidates, key=lambda s: scores[s], reverse=n['select-fn'] == 'top')
            selected = ranked[:int(n['select-n'])]
            if not selected:
                raise ValueError('Empty ranking')
            self.log(f"FILTER {n['id']}: scores={scores}; selected={selected}")
            return {s: 1 / len(selected) for s in selected}
        if step == 'wt-cash-specified':
            weights = specified_weights(children)
        elif step == 'wt-inverse-vol':
            vols = [self.metric(c['ticker'], 'standard-deviation-return', int(n['window-days'])) for c in children]
            zeros = [i for i, v in enumerate(vols) if v == 0]
            if zeros:
                weights = [1 / len(zeros) if i in zeros else 0 for i in range(len(vols))]
            else:
                inverse = [1 / v for v in vols]
                weights = [v / sum(inverse) for v in inverse]
            self.log(f"INVERSE_VOL {n['id']}: weights={weights}")
        else:
            # Root, group, active if-child and equal-weight blocks distribute
            # equally; child weight annotations matter only under specified weight.
            weights = [1 / len(children)] * len(children)
        return self.combine(children, weights)


def compliant_targets(raw, exposure=0.99):
    if not math.isfinite(exposure) or not 0 <= exposure <= 1:
        raise ValueError('Invalid exposure')
    if not math.isclose(sum(raw.values()), 1) or any(not math.isfinite(w) or w < 0 for w in raw.values()):
        raise ValueError('Invalid source weights')
    targets = defaultdict(float)
    for symbol, weight in raw.items():
        if symbol not in UNCHANGED | set(SUBSTITUTIONS):
            raise ValueError('Unreviewed source holding: ' + symbol)
        target = SUBSTITUTIONS.get(symbol, symbol)
        if target not in EXECUTION_ASSETS or target in BLOCKED_ASSETS:
            raise ValueError('Forbidden execution asset: ' + target)
        targets[target] += weight * exposure
    return dict(targets)


# Original source holdings are bought long, including inverse/leveraged funds.
ORIGINAL_EXECUTION_ASSETS = frozenset(UNCHANGED | set(SUBSTITUTIONS))

def original_targets(raw, exposure=0.99):
    if not math.isfinite(exposure) or not 0 <= exposure <= 1:
        raise ValueError('Invalid exposure')
    if not math.isclose(sum(raw.values()), 1) or any(not math.isfinite(w) or w < 0 for w in raw.values()):
        raise ValueError('Invalid source weights')
    if not set(raw).issubset(ORIGINAL_EXECUTION_ASSETS):
        raise ValueError('Unreviewed source holding')
    return {symbol: weight * exposure for symbol, weight in raw.items()}
