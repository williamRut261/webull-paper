"""Private dashboard contract for public, allowlisted agent dialogue."""
import json
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from dashboard.app import (
    app, _office_status_cache, read_office_conversation,
    OFFICE_RUNS_APIS, OFFICE_WORKFLOW_NAMES,
)


class Response:
    def __init__(self, data):
        self.data = data
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, n):
        return self.data[:n]


class DialogueDashboardTests(unittest.TestCase):
    def test_read_public_persisted_transcript_strictly_validates_roles(self):
        data={"schema": 1, "turn_seq": 2, "messages": [
            {"turn": 1,"role": "Market Analyst",
             "text": "We have only the last published opinions, not fresh prices.",
             "at":"2026-10-22T18:00:00+00:00"},
            {"turn": 2,"role": "Technical Analyst",
             "text": "Maya, which indicators would actually change your mind?",
             "at":"2026-10-22T18:00:00+00:00"}]}
        def opener(req, timeout):
            self.assertEqual(req.full_url.split("/")[2], "raw.githubusercontent.com")
            self.assertLessEqual(timeout, 3)
            return Response(json.dumps(data).encode())
        result=read_office_conversation(opener=opener)
        self.assertEqual(result["last_turn"], 2)
        self.assertEqual(len(result["messages"]), 2)
        self.assertEqual(result["messages"][0]["name"], "Maya")
        self.assertEqual(result["messages"][1]["name"], "Theo")
        self.assertNotIn("account", json.dumps(result))
        data["messages"][0]["role"]="New broker agent"
        with self.assertRaises(ValueError):
            read_office_conversation(opener=opener)
        data["messages"][0]["role"]="Market Analyst"
        data["messages"][1]["turn"]=1
        with self.assertRaises(ValueError):
            read_office_conversation(opener=opener)

    def test_new_workflow_is_scoped_for_run_matched_per_role_checks(self):
        self.assertEqual(len(OFFICE_RUNS_APIS), 3)
        self.assertTrue(any("office-autonomous-dialogue.yml" in uri for uri in OFFICE_RUNS_APIS))
        self.assertIn("Autonomous Seven-Agent Office (RESEARCH ONLY - NO BROKER)",
                      OFFICE_WORKFLOW_NAMES)

    def test_owner_only_status_includes_real_persistent_dialogue(self):
        audience = "/projects/123/locations/us-central1/services/webull-paper-viewer"
        fake = {"available":True,"kind":"HOURLY_BUDGETED_RESEARCH_DIALOGUE",
                "last_turn":12,"updated_at":"2026-10-22T18:00:00+00:00",
                "messages":[{"turn":12,"role":"Trade Reviewer","name":"Quinn",
                             "text":"I challenge the existing hypothesis because evidence is missing.",
                             "at":"2026-10-22T18:00:00+00:00"}]}
        _office_status_cache.update({"expires":0.0,"payload":None})
        with patch.dict("os.environ", {"IAP_AUDIENCE":audience,
                                       "DASHBOARD_ALLOWED_EMAIL":"owner@example.com"},clear=True):
            with app.test_client() as c:
                self.assertEqual(c.get("/office/status").status_code,403)
            with patch("dashboard.app.id_token.verify_token",return_value={
                    "iss":"https://cloud.google.com/iap","email":"owner@example.com"}), \
                 patch("dashboard.app.read_office_run",return_value=None), \
                 patch("dashboard.app.read_agent_feed",return_value=None), \
                 patch("dashboard.app.read_office_conversation",return_value=fake):
                with app.test_client() as c:
                    response=c.get("/office/status",headers={"X-Goog-Iap-Jwt-Assertion":"ok"})
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.json["conversation"],fake)
                    self.assertEqual(response.json["conversation"]["messages"][0]["name"],"Quinn")
                    self.assertEqual(response.headers["Cache-Control"],"private, no-store, max-age=0")
        _office_status_cache.update({"expires":0.0,"payload":None})


if __name__=="__main__":
    unittest.main()
