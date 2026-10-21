"""RESEARCH ONLY: compare original Beethoven with Webull 80/19 ORB.
Daily Beethoven sim fills at daily close: a proxy, NOT exact 15:48 ET fills.
Intraday ORB requires actual 5-minute regular-session candles, no data imputation.
"""
import argparse
import json
from pathlib import Path
import math
import numpy as np
import pandas as pd
from strategy_engine import Evaluator, load_strategy
from trader_combo.universe import CANDIDATES

def read_bars(path):
    if not Path(path).exists():
        return {}
    df = pd.read_csv(path)
    if df.empty:
        return {}
    required = {"datetime","symbol","open","high","low","close","volume"}
    if not required.issubset(df):
        raise ValueError("Missing candle columns: "+str(required-set(df)))
    dt = pd.to_datetime(df.datetime, utc=True).dt.tz_convert("America/New_York")
    df["day"] = dt.dt.strftime("%Y-%m-%d")
    df["clock"] = dt.dt.strftime("%H:%M")
    return {(day,s): f.set_index("clock").sort_index()
            for (day,s),f in df.groupby(["day","symbol"])}

def morning(day, bars, equity, cost_bps=10):
    """Approximate OG scanner at 10:20; missing universe => no comparable result."""
    clock = pd.date_range("2000-01-01 09:30", periods=10, freq="5min").strftime("%H:%M")
    entries=[]
    valid=0
    valid_symbols=set()
    for symbol in sorted(CANDIDATES):
        f=bars.get((day,symbol))
        if f is None or f.index.duplicated().any() or not set(clock).issubset(f.index):
            continue
        q=f.loc[list(clock)]
        if not np.isfinite(q[["open","high","low","close","volume"]].astype(float).to_numpy()).all():
            continue
        valid+=1
        valid_symbols.add(symbol)
        if q.iloc[-1]["close"] < 5 or q["volume"].sum()<100000:
            continue
        high=float(q.iloc[:3]["high"].max())
        low=float(q.iloc[:3]["low"].min())
        if not 0<low<high:
            continue
        for i in range(3,10):
            price=float(q.iloc[i]["close"])
            if price>high:
                pct=100*(price/high-1)
                if .1<=pct<=3 and (9-i)*300<=600:
                    entries.append((i,symbol,price,high,low))
                break
    # Match the OG scanner's maximum 20% failed/unavailable symbol allowance.
    # Report missing symbols: partial coverage can understate opportunities.
    coverage_info={"day":day,"coverage":valid,"required":len(CANDIDATES),
                   "missing_symbols":sorted(CANDIDATES-valid_symbols)}
    if len(CANDIDATES)-valid>len(CANDIDATES)//5:
        return None, [], coverage_info
    entries.sort()
    cash=.19*equity
    pnl=0.
    trades=[]
    for i,s,signal,high,low in entries[:3]:
        q=bars[(day,s)]
        if "10:20" not in q.index or "15:45" not in q.index:
            return None, [], {"day":day,"issue":"missing entry/exit timestamp"}
        buy=float(q.loc["10:20","open"])
        sell=float(q.loc["15:45","open"])
        if not all(math.isfinite(v) and v>0 for v in (buy,sell)):
            continue
        if abs(buy/signal-1)>.01:
            continue
        stop=(high+low)/2.
        stopdist=(buy-stop)/buy
        if not .004<=stopdist<=.035:
            continue
        budget=min(cash,.19*equity/min(len(entries),3),.003*equity/stopdist)/1.01
        shares=int(budget//buy)
        if shares<1:
            continue
        cash-=shares*buy*1.01
        gain=shares*(sell-buy)-(shares*(buy+sell))*cost_bps/10000.
        pnl+=gain
        trades.append({"date":day,"symbol":s,"shares":shares,"entry_price_proxy":buy,
                       "exit_price_proxy":sell,"net_pnl":round(gain,4)})
    return pnl/equity,trades,coverage_info

def choose_segment(segments):
    """Longest uninterrupted valid sample, not an invented stitched return."""
    if not segments:
        return pd.DataFrame(), []
    best = max(segments, key=lambda xs: (len(xs), xs[-1]["date"]))
    return pd.DataFrame(best), [
        {"start": xs[0]["date"], "end": xs[-1]["date"], "days": len(xs)}
        for xs in segments
    ]


def run(daily, bars, start, end, cost_bps=10):
    """Research-only, true-signal-data-required, contiguous market sessions.

    Evaluate ALL requested dates, even if an early asset did not yet exist.
    Report contiguous valid windows, never pretend the sparse results cover
    years that lack historical data. Trade costs use actual target turnover,
    with cash implicit, rather than charging the whole allocation each day.
    """
    if daily.empty or daily.index.has_duplicates or not daily.index.is_monotonic_increasing:
        raise ValueError("Invalid or unsorted daily price index")
    if not 0 <= cost_bps <= 100:
        raise ValueError("Invalid assumed per-dollar trade cost")
    daily = daily.apply(pd.to_numeric, errors="coerce")
    root = load_strategy()
    exposures = {"beethoven_99": .99, "beethoven_80_cash_19": .80,
                 "beethoven_75_cash_25": .75}
    windows, paired_windows, trades = [], [], []
    long_rows, pair_rows = [], []
    issues, skipped = [], 0
    equity = {name: 10000. for name in exposures}
    prev_alloc = {name: {} for name in exposures}
    matched = {"beethoven_99": 10000., "beethoven_80_cash_19": 10000., "webull_80_19": 10000.}
    matched_prior = {"beethoven_99": {}, "beethoven_80_cash_19": {}, "webull_80_19": {}}

    def close_long():
        nonlocal long_rows, equity, prev_alloc
        if long_rows:
            windows.append(long_rows)
        long_rows = []
        equity = {name: 10000. for name in exposures}
        prev_alloc = {name: {} for name in exposures}

    def close_paired():
        nonlocal pair_rows, matched, matched_prior
        if pair_rows:
            paired_windows.append(pair_rows)
        pair_rows = []
        matched = {"beethoven_99": 10000., "beethoven_80_cash_19": 10000., "webull_80_19": 10000.}
        matched_prior = {"beethoven_99": {}, "beethoven_80_cash_19": {}, "webull_80_19": {}}

    def period_return(weights, price_changes, exposure, holdings):
        target = {s: w*exposure for s, w in weights.items()}
        # Notional traded on buys plus sells. This is a simplified model
        # without price impact, broker rejects or intraday borrow.
        turnover = sum(abs(target.get(s, 0)-holdings.get(s, 0))
                       for s in set(target)|set(holdings))
        gross = sum(target[s]*price_changes[s] for s in target)
        net = gross - turnover*cost_bps/10000.
        if 1+net <= 0 or 1+gross <= 0:
            raise ValueError("Portfolio exhausted")
        # End-of-period marked weights before next daily rebalance.
        after = {s: weight*(1+price_changes[s])/(1+gross)
                 for s, weight in target.items()}
        return net, after

    for i in range(1, len(daily)):
        day = daily.index[i].strftime("%Y-%m-%d")
        if day < start or day > end:
            continue
        try:
            weights = Evaluator(root, daily.iloc[:i]).evaluate()
            if not weights or not math.isclose(sum(weights.values()), 1., abs_tol=1e-7):
                raise ValueError("Invalid evaluated weights")
            changes = {}
            for symbol in weights:
                p0, p1 = daily[symbol].iloc[i-1], daily[symbol].iloc[i]
                if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0 and p1 > 0):
                    raise ValueError("Missing selected holding price: "+symbol)
                changes[symbol] = p1/p0-1
        except (KeyError, ValueError, IndexError, TypeError) as exc:
            skipped += 1
            if len(issues) < 20:
                issues.append({"date": day, "reason": str(exc)[:160]})
            close_long()
            close_paired()
            continue

        growth = {}
        for key, exposure in exposures.items():
            ret, next_holdings = period_return(weights, changes, exposure, prev_alloc[key])
            equity[key] *= 1+ret
            prev_alloc[key] = next_holdings
            growth[key] = equity[key]
        long_rows.append({"date": day, **growth,
                          "original_asset_return": sum(weights[s]*changes[s]
                                                       for s in weights)})

        if bars:
            scanner_return, new_trades, detail = morning(day, bars,
                                                 matched["webull_80_19"], cost_bps)
            if scanner_return is None:
                close_paired()
                if len(issues) < 20:
                    issues.append({"date": day, "reason": "Incomplete intraday scanner data",
                                   "coverage": detail.get("coverage"),
                                   "required": detail.get("required")})
                continue
            r99, w99 = period_return(weights, changes, .99,
                                      matched_prior["beethoven_99"])
            r80, w80 = period_return(weights, changes, .80,
                                      matched_prior["webull_80_19"])
            r80_cash, w80_cash = period_return(weights, changes, .80,
                                                matched_prior["beethoven_80_cash_19"])
            matched_prior["beethoven_99"] = w99
            matched_prior["beethoven_80_cash_19"] = w80_cash
            matched_prior["webull_80_19"] = w80
            matched["beethoven_99"] *= (1+r99)
            matched["beethoven_80_cash_19"] *= (1+r80_cash)
            matched["webull_80_19"] *= (1+r80+scanner_return)
            pair_rows.append({"date": day, **matched,
                              "orb_return_contribution": scanner_return,
                              "orb_trades": len(new_trades),
                              "scanner_coverage": detail["coverage"],
                              "scanner_required": detail["required"],
                              "scanner_missing": ",".join(detail["missing_symbols"])})
            trades.extend(new_trades)
    close_long()
    close_paired()
    long, long_periods = choose_segment(windows)
    paired, matched_periods = choose_segment(paired_windows)
    report_coverage = {"requested_start": start, "requested_end": end,
                       "valid_daily_windows": long_periods,
                       "valid_matched_windows": matched_periods,
                       "daily_skipped_sessions": skipped,
                       "first_issues": issues,
                       "note": ("Only the longest uninterrupted valid sample is compared; "
                                "no short window is labeled a three-year backtest. "
                                "Missing scanner charts are disclosed; up to 20% missing is allowed "
                                "as in the actual OG scanner gate. Historical listings cause gaps.")}
    matched_days = set(paired.date) if not paired.empty else set()
    chosen_trades = pd.DataFrame([x for x in trades if x["date"] in matched_days])
    return long, paired, chosen_trades, report_coverage


def stats(frame, column):
    if frame.empty:
        return None
    x = frame[column].astype(float)
    first, last = frame.date.iloc[0], frame.date.iloc[-1]
    n = len(x)
    if (x <= 0).any():
        raise ValueError("Invalid equity curve")
    # Include original $10k equity as the starting peak for drawdown.
    values = pd.concat([pd.Series([10000.]), x], ignore_index=True)
    dd = (values/values.cummax()-1).min()
    return {"start": first, "end": last, "days": n,
            "total_pct": round((x.iloc[-1]/10000-1)*100, 3),
            "equivalent_daily_pct": round(((x.iloc[-1]/10000)**(1/n)-1)*100, 4),
            "annualized_pct": round(((x.iloc[-1]/10000)**(252/n)-1)*100, 3),
            "max_drawdown_pct": round(dd*100, 3)}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--daily",default="backtests/data/daily.csv")
    p.add_argument("--intraday",default="backtests/data/intraday.csv")
    p.add_argument("--out",default="backtests/results")
    p.add_argument("--start",default="2024-01-01")
    p.add_argument("--end",default="2026-10-20")
    p.add_argument("--cost-bps",type=float,default=10)
    a=p.parse_args()
    if not 0<=a.cost_bps<=100: raise ValueError("invalid costs")
    daily=pd.read_csv(a.daily,index_col=0,parse_dates=True)
    long,match,trades,coverage=run(daily,read_bars(a.intraday),a.start,a.end,a.cost_bps)
    dest=Path(a.out);dest.mkdir(parents=True,exist_ok=True)
    long.to_csv(dest/"long_beethoven.csv",index=False)
    match.to_csv(dest/"matched_80_19.csv",index=False)
    trades.to_csv(dest/"orb_trades.csv",index=False)
    report={"daily_period":([long.iloc[0]["date"],long.iloc[-1]["date"]] if not long.empty else None),
            "matched_period":([match.iloc[0]["date"],match.iloc[-1]["date"]] if not match.empty else None),
            "long":{k:stats(long,k) for k in
                     ("beethoven_99","beethoven_80_cash_19","beethoven_75_cash_25")},
            "matched":{k:stats(match,k) for k in ("beethoven_99","beethoven_80_cash_19","webull_80_19")},
            "matched_days":len(match),"orb_trades":len(trades),
            "orb_winning_trades":int((trades.net_pnl>0).sum()) if not trades.empty else 0,
            "orb_total_net_pnl_dollars":round(float(trades.net_pnl.sum()),2) if not trades.empty else 0.,
            "coverage":coverage,
            "LIMITATION":"Indicative daily-close Beethoven simulation with estimated actual turnover; ORB 5m bar-open fills. "
            "Not exact live 15:48 ET or broker execution; no complete 2024-2026 "
            "5m history from Yahoo. Missing data is never treated as zero returns."}
    (dest/"report.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps(report,indent=2))
    if long.empty: raise SystemExit("NO VALID DAILY HISTORY; DO NOT REPORT RETURNS")
    if match.empty: print("NO VALID MATCHED ORB HISTORY; DO NOT REPORT MERGED RETURNS")

if __name__=="__main__":
    main()
