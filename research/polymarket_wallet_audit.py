"""Read-only audit of a viral Polymarket wallet claim. NO ORDERS, EVER.

Only GETs public v2 Polymarket wallet statistics and at most the newest 100
fills. A recent sample is not an estimate of full lifetime strategy returns.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://data-api.polymarket.com/v2/"
WALLET = "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82"
MAX_FILLS = 100


def get_public(route, params, *, opener=urlopen):
    if route not in ("user-stats", "trades"):
        raise ValueError("Non-allowlisted read-only endpoint")
    if params.get("user") != WALLET:
        raise ValueError("Unexpected wallet")
    if route == "trades" and params.get("limit") != MAX_FILLS:
        raise ValueError("Unbounded or changed sample")
    url = API + route + "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "stonks-readonly-research/1.0",
                                "Accept": "application/json"}, method="GET")
    with opener(req, timeout=20) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Oversized API payload")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError("Unexpected API response")
    return payload


def finite_or_none(value):
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError, OverflowError):
        return None


def summarise_recent(trades):
    if not isinstance(trades, list) or len(trades) > MAX_FILLS:
        raise ValueError("Malformed or oversized trade sample")
    if not trades:
        raise ValueError("No public trade sample; no evidence")
    assets = Counter()
    sides = Counter()
    markets = defaultdict(set)
    names = {}
    last, earliest = 0, 9_999_999_999
    for item in trades:
        if not isinstance(item, dict) or item.get("proxy_wallet", "").lower() != WALLET:
            raise ValueError("Trade belongs to another wallet")
        slug = item.get("slug", "")
        if not isinstance(slug, str) or not slug:
            raise ValueError("Missing market identifier")
        symbol = slug.split("-")[0].upper()
        if symbol not in ("BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "HYPE"):
            symbol = "OTHER"
        timestamp = item.get("timestamp")
        if type(timestamp) is not int or timestamp < 1700000000:
            raise ValueError("Invalid trade timestamp")
        last, earliest = max(last, timestamp), min(earliest, timestamp)
        assets[symbol] += 1
        market = item.get("condition_id") or slug
        outcome = str(item.get("outcome") or "UNKNOWN").upper()
        markets[market].add(outcome)
        names[market] = slug
        sides[str(item.get("side") or "UNKNOWN").upper()] += 1
    opposing = [
        names[k] for k, v in markets.items()
        if ("UP" in v and "DOWN" in v)
    ]
    return {
        "sample_count": len(trades),
        "sample_type": "MOST_RECENT_FILLS_NOT_RANDOM_NOT_FULL_HISTORY",
        "sample_newest_utc": datetime.fromtimestamp(last, timezone.utc).isoformat(),
        "sample_oldest_utc": datetime.fromtimestamp(earliest, timezone.utc).isoformat(),
        "sample_assets": dict(sorted(assets.items())),
        "sample_sides": dict(sorted(sides.items())),
        "distinct_markets_in_sample": len(markets),
        "markets_with_both_up_and_down_bought": len(opposing),
        "examples_both_outcomes": sorted(opposing)[:8],
        "sample_does_not_establish": [
            "Historical profitable time windows",
            "Net ROI or net per-fill profit",
            "Wallet ownership or Claude involvement",
            "Backtest fills, win rate, Kelly parameters or Bayesian update rules",
        ],
    }


def audit(stats, trades):
    if not isinstance(stats, dict) or not isinstance(stats.get("data"), dict):
        raise ValueError("Missing wallet stats")
    card = stats["data"]
    if str(card.get("proxy_wallet", "")).lower() != WALLET:
        raise ValueError("Stats for wrong wallet")
    pnl = card.get("all_time_pnl") or {}
    if not isinstance(pnl, dict):
        raise ValueError("Invalid PnL record")
    sample = summarise_recent(trades.get("data"))
    result = {
        "status": "PUBLIC_WALLET_AUDIT_NOT_STRATEGY_BACKTEST",
        "wallet": WALLET,
        "reel": "https://www.instagram.com/reel/DeOO2ZWPFU3/",
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "profile_markets_traded": card.get("trades"),
        "profile_biggest_win_usdc": finite_or_none(card.get("biggest_win")),
        "public_trade_pnl_usdc": finite_or_none(pnl.get("trade_pnl")),
        "public_realized_market_pnl_usdc": finite_or_none(pnl.get("realized_market_pnl")),
        "public_maker_rebate_usdc": finite_or_none(pnl.get("maker_rebate")),
        "public_taker_rebate_usdc": finite_or_none(pnl.get("taker_rebate")),
        "public_fees_paid_usdc": finite_or_none(pnl.get("fees_paid")),
        "sample": sample,
        "lifetime_stats_as_of_utc": (
            datetime.fromtimestamp(pnl["timestamp"], timezone.utc).isoformat()
            if type(pnl.get("timestamp")) is int else None
        ),
        "original_reel_claims_UNVERIFIED": {
            "wallet_profit_usd": 384858,
            "predictions": 13070,
            "biggest_win_usd": 18500,
            "personal_small_account_start_usd": 80,
            "personal_small_account_end_usd": 4218,
        },
        "research_verdict": (
            "The wallet exists and has substantial documented activity, "
            "but this sample is not exclusively Bitcoin and includes "
            "both directions in some markets. No executable strategy "
            "specification or independently reproducible $80-to-$4218 "
            "result was provided. Do not copy-trade or activate."
        ),
        "order_count": 0, "broker_connected": False,
        "live_trading_enabled": False, "paper_trading_enabled": False,
        "US_access_note": (
            "Global polymarket.com cannot be used to trade from the US; "
            "this script only accesses public historical information."
        ),
    }
    return result


def main():
    stats = get_public("user-stats", {"user": WALLET})
    fills = get_public("trades", {"user": WALLET, "limit": MAX_FILLS})
    report = audit(stats, fills)
    directory = Path("out/polymarket-claude-wallet-audit")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    x = report["sample"]
    message = [
        "# Viral Claude Polymarket reel: PUBLIC WALLET AUDIT",
        "",
        "**This is not a backtest and places zero trades.**",
        "",
        "Source wallet: " + report["wallet"],
        "",
        "Trades sampled: " + str(x["sample_count"]) + " (latest, NOT random)",
        "",
        "Sample fill assets: " + json.dumps(x["sample_assets"]),
        "",
        "Distinct markets in sample: " + str(x["distinct_markets_in_sample"]),
        "",
        "Markets where BOTH Up and Down appear in sample: " +
        str(x["markets_with_both_up_and_down_bought"]),
        "",
        "Public stats markets traded: " + str(report["profile_markets_traded"]),
        "",
        "Public trade PnL USDC: " + str(report["public_trade_pnl_usdc"]),
        "",
        "Public maker rebate USDC: " + str(report["public_maker_rebate_usdc"]),
        "",
        "The reported personal $80-to-$4218 result is NOT VERIFIED.",
        "",
        "No identified 65%-edge BTC time window, forecast model, settlement "
        "attribution, exact trading rules or independent execution-cost backtest.",
        "",
        "DO NOT CONNECT TO WEBULL, ALPACA OR POLYMARKET EXECUTION.",
    ]
    (directory / "summary.md").write_text("\n".join(message) + "\n")
    print("PUBLIC_POLYMARKET_AUDIT_DONE ORDERS=0 " +
          json.dumps({"fills": x["sample_count"], "assets": x["sample_assets"],
                      "both_directions_markets": x["markets_with_both_up_and_down_bought"],
                      "markets_traded_lifetime": report["profile_markets_traded"]}),
          flush=True)


if __name__ == "__main__":
    main()
