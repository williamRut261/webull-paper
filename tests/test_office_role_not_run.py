"""Distinguish omitted hourly agents from actual failures; never infer work."""
import os
import unittest
from unittest.mock import patch

from dashboard.app import (
    app, _office_status_cache, read_office_status_snapshot, build_office_workers,
)


def sample_run():
    return {"head_sha": "a" * 40, "run_id": 12345,
            "type": "Autonomous research conversation",
            "state": "completed", "active": False, "queued": False,
            "expired": False, "conclusion": "success",
            "run_url": "https://github.com/williamRut261/webull-paper/actions/runs/12345",
            "created": "2026-10-23T05:32:00Z"}


class NotRunTests(unittest.TestCase):
    def setUp(self):
        _office_status_cache["payload"] = None
        _office_status_cache["expires"] = 0

    def tearDown(self):
        _office_status_cache["payload"] = None
        _office_status_cache["expires"] = 0

    def test_valid_hourly_run_sets_only_omitted_roles_to_not_run(self):
        with patch("dashboard.app.read_office_run", return_value=sample_run()), \
             patch("dashboard.app.read_office_role_checks", return_value={
                 "Technical Analyst": "DONE", "News Researcher": "FAILED"
             }), patch("dashboard.app.read_agent_feed", return_value=None), \
             patch("dashboard.app.read_office_conversation", return_value={
                 "available": True, "last_turn": 23, "messages": []}):
            result = read_office_status_snapshot()
        self.assertEqual(result["source"], "VERIFIED")
        self.assertEqual(result["verified_count"], 2)
        self.assertEqual([r["stage"] for r in result["roles"]], [
            "NOT_RUN", "DONE", "FAILED", "NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN"
        ])
        self.assertIn("Autonomous research conversation", result["run"]["type"])

    def test_missing_immutable_run_sha_cannot_invent_not_run_stage(self):
        invalid = sample_run()
        invalid["head_sha"] = None
        with patch("dashboard.app.read_office_run", return_value=invalid), \
             patch("dashboard.app.read_agent_feed", return_value=None), \
             patch("dashboard.app.read_office_conversation", return_value={
                 "available": False, "last_turn": 0, "messages": []}):
            snapshot = read_office_status_snapshot()
        self.assertEqual([r["stage"] for r in snapshot["roles"]],
                         ["UNAVAILABLE"] * 7)
        self.assertEqual(snapshot["verified_count"], 0)

    def test_unreachable_check_api_is_not_mislabeled_not_run(self):
        with patch("dashboard.app.read_office_run", return_value=sample_run()), \
             patch("dashboard.app.read_office_role_checks",
                   side_effect=ConnectionError("private credentials must not appear")), \
             patch("dashboard.app.read_agent_feed", return_value=None), \
             patch("dashboard.app.read_office_conversation", return_value={
                 "available": False, "last_turn": 0, "messages": []}):
            result = read_office_status_snapshot()
        self.assertEqual(result["source"], "PARTIAL")
        self.assertEqual({r["stage"] for r in result["roles"]}, {"UNAVAILABLE"})
        self.assertNotIn("private credentials", str(result))

    def test_only_hourly_dialogue_has_not_run_default(self):
        result = build_office_workers(None, {"Risk Manager": "DONE"}, default_stage="NOT_RUN")
        self.assertEqual(result[0]["stage"], "NOT_RUN")
        self.assertEqual(result[4]["stage"], "DONE")
        standard = build_office_workers(None, {"Risk Manager": "DONE"})
        self.assertIsNone(standard[0]["stage"])

    def test_authenticated_html_clearly_labels_not_attempted_roles(self):
        settings = {
            "IAP_AUDIENCE": "/projects/123/locations/us-central1/services/webull-paper-viewer",
            "DASHBOARD_ALLOWED_EMAIL": "owner@example.com",
        }
        with patch.dict(os.environ, settings, clear=True), \
             patch("dashboard.app.id_token.verify_token", return_value={
                 "iss": "https://cloud.google.com/iap", "email": "owner@example.com"}), \
             patch("dashboard.app.read_office_run", return_value=sample_run()), \
             patch("dashboard.app.read_office_role_checks", return_value={
                 "Technical Analyst": "DONE", "News Researcher": "FAILED"
             }), patch("dashboard.app.read_agent_feed", return_value=None):
            with app.test_client() as client:
                html = client.get("/office",
                      headers={"X-Goog-Iap-Jwt-Assertion": "test-token"})
        self.assertEqual(html.status_code, 200)
        self.assertIn(b'data-stage="NOT_RUN"', html.data)
        self.assertIn(b"Not attempted in this hourly run", html.data)
        self.assertIn(b'data-stage="FAILED"', html.data)
        self.assertNotIn(b"private credentials", html.data)


if __name__ == "__main__":
    unittest.main()
