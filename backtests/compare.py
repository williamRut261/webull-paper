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

def run(daily,bars,start,end,cost_bps=10):
    if daily.empty or daily.index.has_duplicates:
        raise ValueError("Invalid daily data")
    daily=daily.sort_index().apply(pd.to_numeric,errors="coerce")
    root=load_strategy()
    accounts={"beethoven_99":10000.,"beethoven_80_cash_19":10000.,
              "beethoven_75_cash_25":10000.}
    matched={"beethoven_99":10000.,"webull_80_19":10000.}
    curves=[];paired=[];trades=[];errors=[]
    began=False
    for i in range(1,len(daily)):
        day=daily.index[i].strftime("%Y-%m-%d")
        if day<start or day>end:
            continue
        try:
            weights=Evaluator(root,daily.iloc[:i]).evaluate()
            if not math.isclose(sum(weights.values()),1.,abs_tol=1e-7):
                raise ValueError("weights do not sum to one")
            r=0.
            for symbol,w in weights.items():
                p0,p1=daily[symbol].iloc[i-1],daily[symbol].iloc[i]
                if not (np.isfinite(p0) and np.isfinite(p1) and p0>0 and p1>0):
                    raise ValueError("missing price "+symbol)
                r+=w*(p1/p0-1)
        except (KeyError,ValueError,IndexError,TypeError) as exc:
            errors.append({"date":day,"reason":str(exc)[:180]})
            if began:
                # Stop old contiguous sample, then restart after a missing day;
                # cannot carry a fictitious portfolio across unpriced sessions.
                accounts={"beethoven_99":10000.,"beethoven_80_cash_19":10000.,
                          "beethoven_75_cash_25":10000.}
                matched={"beethoven_99":10000.,"webull_80_19":10000.}
                curves=[];paired=[];trades=[]
                began=False
            continue
        began=True
        # Daily rebalance dollar-proportional approximation. Daily cost on all
        # invested capital is intentionally conservative but NOT actual turnover.
        fee=cost_bps/10000.
        for key,exposure in (("beethoven_99",.99),("beethoven_80_cash_19",.80),
                             ("beethoven_75_cash_25",.75)):
            accounts[key]*=1+exposure*(r-fee)
        curves.append({"date":day,**accounts,"asset_return":r})
        if bars:
            if not paired and day not in {d for d,_ in bars}: # before intraday period
                continue
            orb,new,info=morning(day,bars,matched["webull_80_19"],cost_bps)
            if orb is None:
                errors.append({"date":day,"reason":"intraday incomplete","detail":info})
                if paired:
                    matched={"beethoven_99":10000.,"webull_80_19":10000.}
                    paired=[];trades=[] # retain only continuous matched session suffix
                continue
            matched["beethoven_99"]*=1+.99*(r-fee)
            matched["webull_80_19"]*=1+.8*(r-fee)+orb
            paired.append({"date":day,**matched,"orb_return_contribution":orb,
                           "scanner_coverage":info["coverage"],
                           "scanner_required":info["required"],
                           "scanner_missing":",".join(info["missing_symbols"])})
            trades+=new
    return pd.DataFrame(curves),pd.DataFrame(paired),pd.DataFrame(trades),errors

def stats(frame,column):
    if frame.empty: return None
    x=frame[column].astype(float)
    n=len(x)
    dd=(x/x.cummax()-1).min()
    return {"days":n,"total_pct":round((x.iloc[-1]/10000-1)*100,3),
            "equivalent_daily_pct":round(((x.iloc[-1]/10000)**(1/n)-1)*100,4),
            "annualized_pct":round(((x.iloc[-1]/10000)**(252/n)-1)*100,3),
            "max_drawdown_pct":round(dd*100,3)}

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
    long,match,trades,issues=run(daily,read_bars(a.intraday),a.start,a.end,a.cost_bps)
    dest=Path(a.out);dest.mkdir(parents=True,exist_ok=True)
    long.to_csv(dest/"long_beethoven.csv",index=False)
    match.to_csv(dest/"matched_80_19.csv",index=False)
    trades.to_csv(dest/"orb_trades.csv",index=False)
    report={"daily_period":([long.iloc[0]["date"],long.iloc[-1]["date"]] if not long.empty else None),
            "matched_period":([match.iloc[0]["date"],match.iloc[-1]["date"]] if not match.empty else None),
            "long":{k:stats(long,k) for k in
                     ("beethoven_99","beethoven_80_cash_19","beethoven_75_cash_25")},
            "matched":{k:stats(match,k) for k in ("beethoven_99","webull_80_19")},
            "matched_days":len(match),"orb_trades":len(trades),"issues":issues[:40],
            "LIMITATION":"Indicative daily-close Beethoven simulation, ORB 5m bar-open fills. "
            "Not exact live 15:48 ET or broker execution; no complete 2024-2026 "
            "5m history from Yahoo. Missing data is never treated as zero returns."}
    (dest/"report.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps(report,indent=2))
    if long.empty: raise SystemExit("NO VALID DAILY HISTORY; DO NOT REPORT RETURNS")
    if match.empty: print("NO VALID MATCHED ORB HISTORY; DO NOT REPORT MERGED RETURNS")

if __name__=="__main__":
    main()
