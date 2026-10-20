"""Offline-only tests for Webull sandbox timestamp audit; no SDK or orders."""
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from webull_paper.audit_quotes import summarize, quote_time, normalized_rows

NY = ZoneInfo("America/New_York")


class ReadOnlySnapshotAuditTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 13, 15, 47, tzinfo=NY)

    def row(self, symbol, mins_ago):
        ms = int((self.now - timedelta(minutes=mins_ago)).timestamp() * 1000)
        return {"symbol": symbol, "last_trade_time": ms}

    def test_webull_delayed_quotes_are_reported_but_not_mislabeled_as_realtime(self):
        rows = [self.row("SPY", 16), self.row("GDXD", 1)]
        result = summarize(rows, {"SPY", "GDXD", "CRWG"}, self.now)
        self.assertEqual(result["within_3m"], ["GDXD"])
        self.assertEqual(result["between_3m_and_20m"], ["SPY"])
        self.assertEqual(result["missing_symbols"], ["CRWG"])

    def test_stale_quotes_cannot_be_reported_as_eligible(self):
        rows = [self.row("SPY", 70), self.row("GDXD", -1)]
        result = summarize(rows, {"SPY", "GDXD"}, self.now)
        self.assertEqual(result["stale_or_other_day"], ["SPY"])
        self.assertEqual(result["invalid_timestamp"], ["GDXD"])

    def test_duplicate_and_unexpected_symbols_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "Unexpected or duplicate"):
            summarize([self.row("SPY", 15), self.row("SPY", 16)], {"SPY"}, self.now)
        with self.assertRaisesRegex(RuntimeError, "Unexpected or duplicate"):
            summarize([self.row("OTHER", 15)], {"SPY"}, self.now)

    def test_non_json_snapshot_or_naive_timestamp_is_not_accepted(self):
        with self.assertRaisesRegex(RuntimeError, "response shape"):
            normalized_rows({"bad": []})
        with self.assertRaises(ValueError):
            quote_time("2026-10-13T15:35:00")

    def test_iso_and_epoch_timestamp_are_timezone_aware(self):
        self.assertEqual(quote_time("2026-10-13T19:30:00Z"),
                         datetime(2026, 10, 13, 19, 30, tzinfo=timezone.utc))
        now_ms = int(self.now.timestamp() * 1000)
        self.assertEqual(quote_time(now_ms), self.now.astimezone(timezone.utc))


if __name__ == "__main__":
    unittest.main()
