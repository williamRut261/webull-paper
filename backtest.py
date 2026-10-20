"""Offline close-to-close research comparison; no broker access or order submission."""
import argparse
import json
import math
from pathlib import Path
import pandas as pd
from strategy_engine import Evaluator, compliant_targets, load_strategy


def run(closes, start, cost_bps=0):
    if closes.empty or closes.index.has_duplicates or not closes.index.is_monotonic_increasing:
        raise ValueError('Prices must have unique sorted dates')
    if not math.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError('Cost must be nonnegative')
    root = load_strategy()
    values = {'original':1., 'compliant':1.}
    previous = {'original':{}, 'compliant':{}}
    rows = []
    # Signal at close t; holdings earn return from t to t+1. No future signal data.
    # Returns here model daily close fills, not the scheduled next-morning bot.
    for i in range(len(closes)-1):
        if closes.index[i] < pd.Timestamp(start):
            continue
        raw = Evaluator(root, closes.iloc[:i+1]).evaluate()
        portfolios = {'original':raw, 'compliant':compliant_targets(raw)}
        for mode, weights in portfolios.items():
            turnover = sum(abs(weights.get(s,0)-previous[mode].get(s,0)) for s in set(weights)|set(previous[mode]))
            pnl = 0.
            realized = {}
            for s,w in weights.items():
                if s not in closes:
                    raise ValueError('Missing execution price: '+s)
                p0,p1 = float(closes[s].iloc[i]),float(closes[s].iloc[i+1])
                if not all(math.isfinite(p) and p>0 for p in (p0,p1)):
                    raise ValueError('Invalid execution price: '+s)
                realized[s]=p1/p0
                pnl += w*(realized[s]-1)
            net=1+pnl-turnover*cost_bps/10000
            if net<=0:
                raise ValueError('Nonpositive portfolio value')
            values[mode] *= net
            previous[mode] = {s:w*realized[s]/net for s,w in weights.items()}
        rows.append({'date':str(closes.index[i+1].date()), **values})
    if not rows:
        raise ValueError('No evaluation dates; supply sufficient warmup and a valid start')
    return pd.DataFrame(rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prices_csv',help='Adjusted close matrix with date index; include original signals AND mapped holdings')
    parser.add_argument('--start',required=True)
    parser.add_argument('--cost-bps',type=float,default=0)
    parser.add_argument('--output',default='comparison.csv')
    args=parser.parse_args()
    prices=pd.read_csv(args.prices_csv,index_col=0,parse_dates=True)
    result=run(prices,args.start,args.cost_bps)
    result.to_csv(args.output,index=False)
    print(json.dumps({'observations':len(result),'output':args.output,
        'assumptions':'Close-to-close, daily rebalance, zero cash interest; excludes real opening fills and broker tolerances.'}))
