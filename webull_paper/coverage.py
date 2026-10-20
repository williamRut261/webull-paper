"""Check whether the Webull sandbox can supply ALL 69 strategy indicators.

Market-data API only. NEVER places, previews, or cancels orders.
"""
import json
import os
from collections import Counter

from webull.core.client import ApiClient
from webull.data.data_client import DataClient
from strategy_engine import load_strategy, signal_symbols

HOST = "api.sandbox.webull.com"


def main():
    api = ApiClient(os.environ["WEBULL_PAPER_APP_KEY"],
                    os.environ["WEBULL_PAPER_APP_SECRET"],"us")
    api.add_endpoint("us", HOST)
    data = DataClient(api)
    symbols=sorted(signal_symbols(load_strategy()))
    statuses=[]
    coverage={}
    for start in range(0,len(symbols),10):
        batch=symbols[start:start+10]
        try:
            res=data.market_data.get_batch_history_bar(symbols=batch, category="US_STOCK",
                timespan="D", count="1200", real_time_required=False)
            statuses.append(int(res.status_code))
            if res.status_code!=200:
                print("WEBULL_BATCH_ERROR",start,"HTTP",res.status_code,flush=True)
                continue
            body=res.json()
            entries=body if isinstance(body,list) else (body.get("result",[]) if isinstance(body,dict) else [])
            if isinstance(entries,dict):
                entries=[entries]
            for item in entries:
                if not isinstance(item,dict):continue
                name=item.get("symbol")
                seq=item.get("result",[])
                if name in symbols and isinstance(seq,list):
                    coverage[name]=len(seq)
        except Exception as ex:
            print("WEBULL_BATCH_ERROR",start,type(ex).__name__,flush=True)
            statuses.append("exception")
    report={"universe":len(symbols),"http_statuses":statuses,
            "symbols_with_bars":len(coverage),
            "symbols_with_1000plus_bars":sum(n>=1000 for n in coverage.values()),
            "symbols_missing":[s for s in symbols if s not in coverage],
            "symbols_short_history":[s for s,n in coverage.items() if n<1000],
            "orders_placed":0}
    print("WEBULL_69_SYMBOL_COVERAGE "+json.dumps(report,sort_keys=True),flush=True)
    if len(coverage)<len(symbols):
        raise RuntimeError("Not all original strategy symbols available from Webull API")
    if min(coverage.values())<3:
        raise RuntimeError("A strategy symbol has insufficient daily history")
if __name__=="__main__":
    main()
