"""IAP-protected source-version marker: offline, no broker or live auth."""
import os
import unittest
from unittest.mock import patch

from dashboard.app import app


class ReleaseProofTests(unittest.TestCase):
    def test_marker_requires_google_iap_and_owner(self):
        env = {"IAP_AUDIENCE": "/projects/123/locations/us-central1/services/webull-paper-viewer",
               "DASHBOARD_ALLOWED_EMAIL": "owner@example.com",
               "STONKS_CODE_SHA": "f" * 40, "K_REVISION": "webull-paper-viewer-00005-abc"}
        with patch.dict(os.environ, env, clear=True):
            with app.test_client() as client:
                self.assertEqual(client.get("/office/release").status_code, 403)
            with patch("dashboard.app.id_token.verify_token", return_value={
                    "iss": "https://cloud.google.com/iap",
                    "email": "owner@example.com"}):
                with app.test_client() as client:
                    data = client.get("/office/release", headers={
                        "X-Goog-Iap-Jwt-Assertion": "signed-fixture"})
                    self.assertEqual(data.status_code, 200)
                    self.assertEqual(data.json["declared_source_sha"], "f" * 40)
                    self.assertEqual(data.json["revision"], "webull-paper-viewer-00005-abc")
                    self.assertFalse(data.json["source_sha_verified"])
                    self.assertIn("private, no-store", data.headers["Cache-Control"])
                    self.assertIn("default-src 'none'", data.headers["Content-Security-Policy"])
                    self.assertNotIn("WEBULL", str(data.json))

    def test_absent_or_malformed_marker_is_unverified_not_inferred(self):
        env = {"IAP_AUDIENCE": "/projects/123/locations/us-central1/services/webull-paper-viewer",
               "DASHBOARD_ALLOWED_EMAIL": "owner@example.com",
               "STONKS_CODE_SHA": "injected invalid sha",
               "K_REVISION": "<script>alert(1)</script>"}
        with patch.dict(os.environ, env, clear=True):
            with patch("dashboard.app.id_token.verify_token", return_value={
                    "iss": "https://cloud.google.com/iap",
                    "email": "owner@example.com"}):
                with app.test_client() as client:
                    data = client.get("/office/release", headers={
                        "X-Goog-Iap-Jwt-Assertion": "signed-fixture"})
                    self.assertEqual(data.status_code, 200)
                    self.assertEqual(data.json["declared_source_sha"], "UNVERIFIED")
                    self.assertEqual(data.json["revision"], "UNAVAILABLE")
                    self.assertNotIn("<script>", data.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
