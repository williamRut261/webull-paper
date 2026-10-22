"""Offline tests for private read-only Cloud Run dashboard; no broker or GCP calls."""
import hashlib
import os
import unittest
from unittest.mock import patch
from dashboard.app import (
    SANDBOX_HOST, app, choose_account, dollars, normalize_history,
    normalize_positions, read_snapshot, records,
)

ACCOUNT_ID = "synthetic-secret-sandbox-account"
PIN = hashlib.sha256(ACCOUNT_ID.encode()).hexdigest()
AUD = "/projects/123456789/locations/us-central1/services/webull-paper-viewer"


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class Account:
    def __init__(self):
        self.calls = []

    def get_account_list(self):
        self.calls.append("GET_ACCOUNTS")
        return Response([{"account_id": ACCOUNT_ID, "account_type": "CASH"}])

    def get_account_balance(self, account_id):
        assert account_id == ACCOUNT_ID
        self.calls.append("GET_BALANCE")
        return Response({"total_net_liquidation_value": 5321.10,
                         "total_cash_balance": 999.17})

    def get_account_position(self, account_id):
        assert account_id == ACCOUNT_ID
        self.calls.append("GET_POSITIONS")
        return Response([{"symbol": "GDXD", "quantity": 10,
                          "last_price": 23.45, "instrument_type": "EQUITY"}])


class Orders:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def get_order_history(self, account_id, page_size=None):
        assert account_id == ACCOUNT_ID
        assert page_size == 100
        self.calls.append("GET_HISTORY")
        if self.fail:
            raise ConnectionError("secret account exception")
        return Response([{"symbol": "GDXD", "side": "SELL",
                          "quantity": 4, "order_status": "FILLED",
                          "avg_fill_price": 21.50}])


class FakeTrade:
    def __init__(self, fail_history=False):
        self.account_v2 = Account()
        self.order_v3 = Orders(fail_history)


class CloudDashboardSafetyTests(unittest.TestCase):
    def test_sandbox_hostname_is_fixed(self):
        self.assertEqual(SANDBOX_HOST, "api.sandbox.webull.com")

    def test_pinned_account_is_required_and_not_guessable(self):
        accounts = [{"account_id": ACCOUNT_ID, "account_type": "CASH"}]
        self.assertEqual(choose_account(accounts, "0", PIN), ACCOUNT_ID)
        for idx, pin in (("0", "a"*64), ("1", PIN), ("ABC", PIN), ("0", "n/a")):
            with self.subTest(idx=idx, pin=pin), self.assertRaises((RuntimeError, ValueError)):
                choose_account(accounts, idx, pin)

    def test_cash_only(self):
        with self.assertRaises(RuntimeError):
            choose_account([{"account_id": ACCOUNT_ID,
                             "account_type": "MARGIN"}], "0", PIN)

    def test_read_only_account_calls_no_order_writes(self):
        broker = FakeTrade()
        snap = read_snapshot(broker, PIN)
        self.assertEqual(snap["equity"], "$5,321.10")
        self.assertEqual(snap["cash"], "$999.17")
        self.assertEqual(snap["positions"][0]["symbol"], "GDXD")
        self.assertEqual(snap["history"][0]["status"], "FILLED")
        self.assertEqual(broker.account_v2.calls,
                         ["GET_ACCOUNTS", "GET_BALANCE", "GET_POSITIONS"])
        self.assertEqual(broker.order_v3.calls, ["GET_HISTORY"])
        self.assertNotIn(ACCOUNT_ID, str(snap))

    def test_history_unavailable_is_not_silently_empty_or_logged_with_details(self):
        with self.assertLogs("dashboard.app", level="WARNING") as captured:
            snap = read_snapshot(FakeTrade(True), PIN)
        self.assertIn("unavailable", snap["history_note"].lower())
        self.assertEqual(snap["history"], [])
        output = "\\n".join(captured.output)
        self.assertIn("stage=order_history", output)
        self.assertIn("exception_type=ConnectionError", output)
        self.assertNotIn("secret account exception", output)
        self.assertNotIn(ACCOUNT_ID, output)

    def test_required_read_failure_logs_stage_and_type_only(self):
        broker = FakeTrade()
        failure_text = "private account id and broker response"
        with patch.object(
            broker.account_v2, "get_account_list",
            side_effect=RuntimeError(failure_text),
        ):
            with self.assertLogs("dashboard.app", level="ERROR") as captured:
                with self.assertRaises(RuntimeError):
                    read_snapshot(broker, PIN)
        output = "\\n".join(captured.output)
        self.assertIn("stage=account_list", output)
        self.assertIn("exception_type=RuntimeError", output)
        self.assertNotIn(failure_text, output)
        self.assertNotIn(ACCOUNT_ID, output)

    def test_report_amounts_do_not_fabricate(self):
        self.assertEqual(dollars(None), "Unavailable")
        self.assertEqual(normalize_positions([{
            "symbol": "SOXS", "quantity": 4, "last_price": None
        }])[0]["market_value"], "Unavailable")

    def test_unknown_history_shape_fails(self):
        with self.assertRaises(ValueError):
            records({"nonsense": 1}, ("orders",))
        with self.assertRaises(ValueError):
            normalize_history({"nonsense": 1})

    def test_no_anonymous_access_even_for_missing_config(self):
        with patch.dict(os.environ, {}, clear=True):
            with app.test_client() as client:
                response = client.get("/")
        self.assertEqual(response.status_code, 403)

    def test_signed_header_cannot_override_user_allowlist(self):
        settings = {"IAP_AUDIENCE": AUD, "DASHBOARD_ALLOWED_EMAIL": "owner@example.com"}
        with patch.dict(os.environ, settings, clear=True):
            with patch("dashboard.app.id_token.verify_token",
                       return_value={"iss": "https://cloud.google.com/iap",
                                     "email": "attacker@example.com"}):
                with app.test_client() as client:
                    response = client.get("/", headers={"X-Goog-Iap-Jwt-Assertion": "test"})
        self.assertEqual(response.status_code, 403)

    def test_signed_user_receives_private_live_broker_snapshot(self):
        settings = {"IAP_AUDIENCE": AUD, "DASHBOARD_ALLOWED_EMAIL": "owner@example.com",
                    "WEBULL_PAPER_ACCOUNT_SHA256": PIN}
        with patch.dict(os.environ, settings, clear=True):
            with patch("dashboard.app.id_token.verify_token",
                       return_value={"iss": "https://cloud.google.com/iap",
                                     "email": "owner@example.com"}):
                with patch("dashboard.app.sandbox_trade_client", return_value=FakeTrade()):
                    with app.test_client() as client:
                        response = client.get("/", headers={
                            "X-Goog-Iap-Jwt-Assertion": "test-signed"
                        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"$5,321.10", response.data)
        self.assertNotIn(ACCOUNT_ID.encode(), response.data)
        self.assertEqual(response.headers.get("Cache-Control"), "private, no-store")
        self.assertIn("default-src 'none'", response.headers.get("Content-Security-Policy"))

    def test_invalid_signature_rejected(self):
        settings = {"IAP_AUDIENCE": AUD, "DASHBOARD_ALLOWED_EMAIL": "owner@example.com"}
        with patch.dict(os.environ, settings, clear=True):
            with patch("dashboard.app.id_token.verify_token", side_effect=ValueError("bad jwt")):
                with app.test_client() as client:
                    response = client.get("/", headers={"X-Goog-Iap-Jwt-Assertion": "fake"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
