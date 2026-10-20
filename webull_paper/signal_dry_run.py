"""strategy 6.6 original strategy on actual Webull sandbox historical bars.

GET market/account data only. Does NOT submit, preview, cancel or modify orders.
Webull daily bars are forward-adjusted, not the same all-adjustment scheme as
Composer or Alpaca: selections can differ. No source ticker substitutions.
"""
import json
import math
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from webull.core.client import ApiClient
from webull.data.data_client import DataClient
from webull.trade.trade_client import TradeClient

from strategy_engine import load_strategy,signal_symbols,Evaluator,original_targets

SANDBOX="api.sandbox.webull.com"
NY=ZoneInfo("America/New_York")


def unwrap_bars(payload):
    """Validate the nested official SDK batch daily-bar response."""
    groups=payload if isinstance(payload,list) else payload.get("result",[])
    if not isinstance(groups,list):
        raise RuntimeError("Malformed Webull daily-bar response")
    parsed={}
    for item in groups:
        sym=item.get("symbol")
        entries=item.get("result")
        if not sym or not isinstance(entries,list):
            raise RuntimeError("Missing symbol/history in Webull bar result")
        dates={}
        for row in entries:
            price=float(row["close"])
            ts=pd.Timestamp(row["time"])
            if not math.isfinite(price) or price<=0 or ts.tzinfo is None:
                raise RuntimeError("Malformed Webull price or time")
            day=ts.tz_convert(NY).date()
            if day in dates:
                raise RuntimeError("Duplicate Webull price date: "+sym)
            dates[day]=price
        if sym in parsed:
            raise RuntimeError("Duplicate Webull history symbol: "+sym)
        parsed[sym]=dates
    return parsed


def assemble_history(client, symbols, today, allow_missing=False):
    prices={}
    for offset in range(0,len(symbols),10):
        batch=symbols[offset:offset+10]
        for attempt in range(4):
            try:
                response=client.market_data.get_batch_history_bar(
                    symbols=batch,category="US_STOCK",timespan="D",
                    count="1200",real_time_required=False)
                break
            except Exception as exc:
                if attempt>=3 or not ("429" in str(exc) or "TOO_MANY_REQUESTS" in str(exc)):
                    raise
                time.sleep(20*(attempt+1))
        if response.status_code!=200:
            raise RuntimeError("Webull historical data unavailable: HTTP "+str(response.status_code))
        chunk=unwrap_bars(response.json())
        if set(chunk)-set(batch):
            raise RuntimeError("Unexpected Webull history symbols")
        if not allow_missing and set(chunk)!=set(batch):
            raise RuntimeError("Webull missing required tickers: "+",".join(sorted(set(batch)-set(chunk))))
        for ticker,history in chunk.items():
            # Exclude today's potentially incomplete session. Prevent lookahead.
            prices[ticker]=pd.Series({pd.Timestamp(d):v for d,v in history.items() if d<today},dtype=float)
    matrix=pd.DataFrame(prices).sort_index().reindex(columns=symbols)
    if matrix.empty or len(matrix)<40 or matrix.index.has_duplicates:
        raise RuntimeError("Insufficient valid Webull completed-session history")
    if not matrix.index.is_monotonic_increasing:
        raise RuntimeError("History dates not chronological")
    return matrix


def main():
    key=os.environ.get("WEBULL_PAPER_APP_KEY","")
    secret=os.environ.get("WEBULL_PAPER_APP_SECRET","")
    if not key or not secret:
        raise RuntimeError("Missing Webull paper credentials")
    api=ApiClient(key,secret,"us")
    api.add_endpoint("us",SANDBOX)
    client=DataClient(api)
    root=load_strategy()
    syms=sorted(signal_symbols(root))
    history=assemble_history(client,syms,datetime.now(NY).date())
    selection=Evaluator(root,history).evaluate()
    targets=original_targets(selection,0.99)
    report={"provider":"Webull PaperTrade sandbox",
        "market_data":"forward-adjusted Webull daily history; NOT full real-time intraday signals",
        "history_end":str(history.index[-1].date()),
        "history_sessions":len(history),
        "signal_symbols":len(syms),
        "original_allocation":selection,
        "paper_target_weights":targets,
        "orders_submitted":0}
    print("WEBULL_strategy_DRY_RUN "+json.dumps(report,sort_keys=True,default=str),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
