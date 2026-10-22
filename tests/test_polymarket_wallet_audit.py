"""Offline regression tests. Never touch the network or broker credentials."""
import json
import unittest
from research.polymarket_wallet_audit import (
    WALLET, get_public, audit, summarise_recent,
)


def row(symbol, outcome, market, ts=1790263841):
    return {
        "proxy_wallet": WALLET, "slug": symbol + "-updown-5m-" + str(ts),
        "condition_id": market, "timestamp": ts, "outcome": outcome,
        "side": "BUY", "size": 1, "price": .5,
    }


def stats():
    return {"data": {"proxy_wallet": WALLET, "trades": 100510,
                     "biggest_win": 7048.934291,
                     "all_time_pnl": {"trade_pnl": 809704.4,
                                      "realized_market_pnl": 487434.36,
                                      "maker_rebate": 660986.35,
                                      "taker_rebate": 44267.21,
                                      "fees_paid": -322522.33}}}


class Response:
    def __init__(self, value):
        self.content = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n=-1):
        return self.content[:n]


class WalletAuditTests(unittest.TestCase):
    def test_multiasset_both_sides_is_detected(self):
        inputs = [
            row("btc", "Up", "A"), row("btc", "Down", "A"),
            row("eth", "Down", "B"), row("sol", "Up", "C"),
        ]
        result = summarise_recent(inputs)
        self.assertEqual(result["sample_assets"], {"BTC": 2, "ETH": 1, "SOL": 1})
        self.assertEqual(result["markets_with_both_up_and_down_bought"], 1)
        self.assertEqual(result["distinct_markets_in_sample"], 3)
        self.assertEqual(result["sample_count"], 4)

    def test_full_wallet_claim_not_inferred(self):
        report = audit(stats(), {"data": [row("eth", "Down", "B")]})
        self.assertEqual(report["status"], "PUBLIC_WALLET_AUDIT_NOT_STRATEGY_BACKTEST")
        self.assertEqual(report["public_trade_pnl_usdc"], 809704.4)
        self.assertEqual(report["public_maker_rebate_usdc"], 660986.35)
        self.assertEqual(report["order_count"], 0)
        self.assertFalse(report["broker_connected"])
        self.assertFalse(report["live_trading_enabled"])
        self.assertFalse(report["paper_trading_enabled"])
        self.assertEqual(report["original_reel_claims_UNVERIFIED"]["personal_small_account_end_usd"], 4218)

    def test_wrong_wallet_rejected(self):
        entry = row("btc", "Up", "A")
        entry["proxy_wallet"] = "0x0000000000000000000000000000000000000000"
        with self.assertRaises(ValueError):
            summarise_recent([entry])

    def test_missing_stats_rejected(self):
        with self.assertRaises(ValueError):
            audit({"data": None}, {"data": [row("btc", "Up", "A")]})

    def test_empty_samples_not_misreported_as_zero(self):
        with self.assertRaises(ValueError):
            summarise_recent([])

    def test_only_preapproved_gets_with_public_fixed_host(self):
        captured = []
        def fake(req, timeout):
            captured.append((req.full_url, req.get_method(), timeout))
            return Response({"data": stats()["data"]})
        result = get_public("user-stats", {"user": WALLET}, opener=fake)
        self.assertIn("data", result)
        self.assertEqual(len(captured), 1)
        self.assertTrue(captured[0][0].startswith(
            "https://data-api.polymarket.com/v2/user-stats?"))
        self.assertEqual(captured[0][1], "GET")
        self.assertEqual(captured[0][2], 20)
        with self.assertRaises(ValueError):
            get_public("trade/execute", {"user": WALLET}, opener=fake)
        with self.assertRaises(ValueError):
            get_public("trades", {"user": WALLET, "limit": 100000},
                       opener=fake)
        self.assertEqual(len(captured), 1)


if __name__ == "__main__":
    unittest.main()
