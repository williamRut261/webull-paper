"""Read-only Webull PaperTrade API readiness check. Never calls order methods.

Confirms sandbox account permissions and attempts to query SPY, GDXD market
data using the *same* Webull keys. Prints no key, secret, account ID, or
response payload.
"""
import json
import os

from webull.core.client import ApiClient
from webull.trade.trade_client import TradeClient
from webull.data.data_client import DataClient

HOST = "api.sandbox.webull.com"


def accounts_from(payload):
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        values = next((payload[k] for k in ("data", "accounts", "list", "results")
                      if isinstance(payload.get(k), list)), [])
    else:
        values = []
    return [x for x in values if isinstance(x, dict) and x.get("account_id")]


def verdict(client, method, *args, **kwargs):
    try:
        res = method(*args, **kwargs)
        status = int(res.status_code)
        if status != 200:
            code = "unknown"
            try:
                payload = res.json()
                if isinstance(payload, dict):
                    code = str(payload.get("error_code", payload.get("code", "unknown")))[:60]
            except Exception:
                pass
            return {"status": status, "error_code": code}, None
        return {"status": status}, res.json()
    except Exception as exc:
        return {"exception_type": type(exc).__name__}, None


def main():
    key = os.environ.get("WEBULL_PAPER_APP_KEY", "").strip()
    secret = os.environ.get("WEBULL_PAPER_APP_SECRET", "").strip()
    if not key or not secret:
        raise RuntimeError("Missing Webull PaperTrade repository secrets")
    api = ApiClient(key, secret, "us")
    api.add_endpoint("us", HOST)
    trade = TradeClient(api)
    data = DataClient(api)
    report = {"environment": "Webull PaperTrade sandbox", "orders_placed": 0}
    report["accounts"], payload = verdict(trade, trade.account_v2.get_account_list)
    accounts = accounts_from(payload)
    report["account_count_with_id"] = len(accounts)
    report["account_types"] = [str(a.get("account_type", "unknown"))[:30] for a in accounts]
    if accounts:
        account_id = accounts[0]["account_id"]
        report["balance"], balance = verdict(trade, trade.account_v2.get_account_balance, account_id)
        report["balance_field_names"] = sorted(balance.keys())[:35] if isinstance(balance, dict) else (
            ["array"] if isinstance(balance, list) else [])
        report["positions"], positions = verdict(trade, trade.account_v2.get_account_position, account_id)
        report["position_count"] = len(positions) if isinstance(positions, list) else None
    for symbol in ("SPY", "GDXD"):
        key_name = "bars_" + symbol
        status, bars = verdict(data, data.market_data.get_history_bar, symbol=symbol,
            category="US_STOCK", timespan="D", count="3", real_time_required=False)
        report[key_name] = status
        if isinstance(bars, dict):
            report[key_name]["response_fields"] = sorted(bars.keys())[:15]
            entries = bars.get("result")
            report[key_name]["symbol_group_count"] = len(entries) if isinstance(entries,list) else None
            if isinstance(entries,list) and entries and isinstance(entries[0],dict):
                subgroup = entries[0].get("result")
                report[key_name]["history_count"] = len(subgroup) if isinstance(subgroup,list) else None
                if isinstance(subgroup,list) and subgroup:
                    report[key_name]["last_history_time"] = str(subgroup[-1].get("time",""))[:40]
            if isinstance(entries,list) and entries and isinstance(entries[0],dict):
                report[key_name]["sample_bar_fields"] = sorted(entries[0].keys())
                report[key_name]["sample_time"] = str(entries[0].get("time",""))[:40]
        key_name = "snapshot_" + symbol
        status, snapshot = verdict(data, data.market_data.get_snapshot,
            symbols=[symbol], category="US_STOCK")
        report[key_name] = status
        if isinstance(snapshot, (list, dict)):
            report[key_name]["response_kind"] = type(snapshot).__name__
            report[key_name]["records"] = len(snapshot)
            records = snapshot if isinstance(snapshot,list) else snapshot.get("result",[])
            if isinstance(records,list) and records and isinstance(records[0],dict):
                report[key_name]["sample_fields"] = sorted(records[0].keys())[:20]
                report[key_name]["sample_trade_time"] = str(records[0].get("last_trade_time",""))[:35]
    # Probe realistic 1000+ session history needed for the unmodified strategy.
    status, extended = verdict(data, data.market_data.get_history_bar, symbol="SPY",
        category="US_STOCK", timespan="D", count="1200", real_time_required=False)
    report["long_history_SPY"] = status
    if isinstance(extended,dict) and isinstance(extended.get("result"),list) and extended["result"]:
        group = extended["result"][0].get("result")
        report["long_history_SPY"]["bar_count"] = len(group) if isinstance(group,list) else None
    print("WEBULL_SANDBOX_READINESS "+json.dumps(report, sort_keys=True), flush=True)
    if not accounts:
        raise RuntimeError("No verified paper account ID returned")
    # Market-data failures are an actionable blocker, not hidden by a green job.
    if report["bars_SPY"].get("status") != 200:
        raise RuntimeError("Webull OpenAPI sandbox market-data history is not available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
