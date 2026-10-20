"""Read-only Webull PaperTrade sandbox snapshot freshness audit.

Runs near the Composer trading window, without previewing/submitting orders.
Webull's sandbox stock quotes may be at least 15 minutes delayed.
"""
import json
import math
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from strategy_engine import load_strategy, signal_symbols

NY = ZoneInfo("America/New_York")
SANDBOX = "api.sandbox.webull.com"


def normalized_rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for field in ("result", "data", "quotes"):
            if isinstance(payload.get(field), list):
                return payload[field]
    raise RuntimeError("Unexpected Webull snapshot response shape")


def quote_time(value):
    if value is None or isinstance(value, bool):
        raise ValueError("Missing last-trade timestamp")
    if isinstance(value, (int, float)) or str(value).isdigit():
        raw = float(value)
        if not math.isfinite(raw):
            raise ValueError("Nonfinite last-trade timestamp")
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Last-trade timestamp is timezone-naive")
    return stamp.astimezone(timezone.utc)


def summarize(rows, symbols, now):
    """Summarize availability and ages without exposing account data or prices."""
    symbols = set(symbols)
    seen = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Unexpected snapshot record")
        symbol = row.get("symbol")
        if symbol not in symbols or symbol in seen:
            raise RuntimeError("Unexpected or duplicate snapshot symbol")
        try:
            t = quote_time(row.get("last_trade_time"))
            age = (now.astimezone(timezone.utc) - t).total_seconds()
        except (ValueError, OverflowError, TypeError):
            seen[symbol] = ("invalid_timestamp", None)
            continue
        if not 0 <= age:
            seen[symbol] = ("invalid_timestamp", None)
        elif age <= 180 and t.astimezone(NY).date() == now.astimezone(NY).date():
            seen[symbol] = ("within_3m", age)
        elif age <= 20 * 60 and t.astimezone(NY).date() == now.astimezone(NY).date():
            seen[symbol] = ("between_3m_and_20m", age)
        elif age <= 35 * 60 and t.astimezone(NY).date() == now.astimezone(NY).date():
            seen[symbol] = ("between_20m_and_35m", age)
        else:
            seen[symbol] = ("stale_or_other_day", age)
    stats = {}
    for group in ("within_3m", "between_3m_and_20m", "between_20m_and_35m",
                  "stale_or_other_day", "invalid_timestamp"):
        stats[group] = sorted(s for s, (kind, _) in seen.items() if kind == group)
    stats["missing_symbols"] = sorted(symbols - set(seen))
    stats["symbols_reported"] = len(seen)
    stats["symbols_required"] = len(symbols)
    return stats


def main():
    key = os.getenv("WEBULL_PAPER_APP_KEY", "").strip()
    secret = os.getenv("WEBULL_PAPER_APP_SECRET", "").strip()
    if not key or not secret:
        raise RuntimeError("Webull paper API secrets are missing")
    # Import here so unit tests can run with only repo requirements.
    from webull.core.client import ApiClient
    from webull.data.data_client import DataClient

    api = ApiClient(key, secret, "us")
    api.add_endpoint("us", SANDBOX)
    data = DataClient(api)
    symbols = sorted(signal_symbols(load_strategy()))
    rows = []
    for offset in range(0, len(symbols), 10):
        batch = symbols[offset:offset+10]
        response = data.market_data.get_snapshot(symbols=batch, category="US_STOCK")
        if int(response.status_code) != 200:
            raise RuntimeError("Webull snapshot GET failed, HTTP " + str(response.status_code))
        rows.extend(normalized_rows(response.json()))

    now = datetime.now(NY)
    result = summarize(rows, symbols, now)
    result["observed_at"] = now.isoformat()
    result["market_data_source"] = "Webull PaperTrade sandbox (may be delayed 15m)"
    result["orders_submitted"] = 0
    result["ready_for_automatic_paper_orders"] = False
    print("WEBULL_READONLY_QUOTE_COVERAGE " + json.dumps(result, sort_keys=True), flush=True)
    # Audit indicates market data coverage; it never enables orders.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
