"""Read-only unofficial Yahoo Finance historical download; no broker secrets."""
import argparse
import json
import time
from pathlib import Path
import pandas as pd
import yfinance as yf
from strategy_engine import load_strategy, signal_symbols, walk
from trader_combo.universe import CANDIDATES

def get(symbol,start,end,interval):
    x=yf.Ticker(symbol).history(start=start,end=end,interval=interval,
                                auto_adjust=True,actions=False,raise_errors=True)
    if x.empty: raise ValueError("empty Yahoo response")
    return x

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--end",default="2026-10-20")
    p.add_argument("--start",default="2024-01-01")
    p.add_argument("--days",type=int,default=25)
    p.add_argument("--out",default="backtests/data")
    a=p.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    root=load_strategy()
    universe=signal_symbols(root)|{n["ticker"] for n in walk(root) if n["step"]=="asset"}
    allsyms=sorted(universe|CANDIDATES|{"SPY","QQQ"})
    end=(pd.Timestamp(a.end)+pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    recent=max(pd.Timestamp(a.start),pd.Timestamp(a.end)-pd.Timedelta(days=a.days)).strftime("%Y-%m-%d")
    daily={};bars=[];errors={}
    for index,s in enumerate(allsyms,1):
        try:
            f=get(s,"2021-01-01",end,"1d")
            z=f["Close"]
            daily[s]=pd.Series(z.to_numpy(),index=z.index.tz_localize(None),name=s)
        except Exception as e: errors.setdefault(s,{})["daily"]=str(e)[:130]
        if s in CANDIDATES:
            try:
                f=get(s,recent,end,"5m")
                for ts,row in f.iterrows():
                    local=ts.tz_convert("America/New_York")
                    if not (9<=local.hour<=15): continue
                    bars.append({"datetime":ts.isoformat(),"symbol":s,
                                 "open":float(row["Open"]),"high":float(row["High"]),
                                 "low":float(row["Low"]),"close":float(row["Close"]),
                                 "volume":float(row["Volume"])})
            except Exception as e: errors.setdefault(s,{})["intraday"]=str(e)[:130]
        if index%30==0:
            print("Downloaded",index,"of",len(allsyms),flush=True)
            time.sleep(1)
    if daily:pd.DataFrame(daily).sort_index().to_csv(out/"daily.csv",index_label="Date")
    pd.DataFrame(bars,columns=["datetime","symbol","open","high","low","close","volume"]).to_csv(out/"intraday.csv",index=False)
    coverage={"requested":len(allsyms),"daily_symbols":len(daily),
              "intraday_symbols":len({x["symbol"] for x in bars}),
              "scanner_required":len(CANDIDATES),"recent_start":recent,
              "source":"Yahoo Finance unofficial","errors":errors}
    (out/"coverage.json").write_text(json.dumps(coverage,indent=2)+"\n")
    print(json.dumps({k:v for k,v in coverage.items() if k!="errors"},indent=2))
    if len(daily)<30: raise SystemExit("Missing most daily data - no results")

if __name__=="__main__":main()
