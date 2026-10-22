"""Read-only public GitHub-Checks status adapter tests (no real network/API)."""
import json
import os
import unittest
from unittest.mock import patch

from research.agent_check_status import CHECK_PREFIX, ROLES, publish_stage
from research.ai_desk import ROLES as DESK_ROLES, run_agents


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, *_):
        return json.dumps(self.payload).encode("utf-8")


class PerAgentTelemetryTests(unittest.TestCase):
    def test_role_names_exactly_match_the_trading_desk(self):
        self.assertEqual(ROLES, frozenset(DESK_ROLES))
        self.assertEqual(CHECK_PREFIX, "AI Office / ")

    def test_unauthorized_or_invalid_env_never_contacts_api(self):
        def forbidden(*_, **__):
            raise AssertionError("No network permitted")
        with patch.dict(os.environ, {"AI_OFFICE_CHECKS_ENABLED": "false"}, clear=True):
            self.assertIsNone(publish_stage("Market Analyst", "start", opener=forbidden))
        with patch.dict(os.environ, {"AI_OFFICE_CHECKS_ENABLED": "true",
                                      "AI_OFFICE_GITHUB_TOKEN": "not-real",
                                      "GITHUB_SHA": "bad", "GITHUB_REPOSITORY":
                                      "williamRut261/webull-paper"}, clear=True):
            self.assertIsNone(publish_stage("Market Analyst", "start", opener=forbidden))
        self.assertIsNone(publish_stage("Unknown Role", "start", opener=forbidden))

    def test_start_and_finished_calls_send_only_whitelisted_metadata(self):
        calls = []
        def opener(req, timeout):
            self.assertLessEqual(timeout, 4)
            body = json.loads(req.data)
            calls.append((req.get_method(), req.full_url, body))
            return Response({"id": 12042})
        with patch.dict(os.environ, {
            "AI_OFFICE_CHECKS_ENABLED": "true", "AI_OFFICE_GITHUB_TOKEN": "dummy",
            "GITHUB_REPOSITORY": "williamRut261/webull-paper",
            "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "481516"}, clear=True):
            cid = publish_stage("Market Analyst", "start", opener=opener)
            self.assertEqual(cid, 12042)
            self.assertIsNone(publish_stage("Market Analyst", "success", cid, opener=opener))
            self.assertIsNone(publish_stage("Market Analyst", "failure", cid, opener=opener))
        self.assertEqual([x[0] for x in calls], ["POST", "PATCH", "PATCH"])
        self.assertEqual(calls[0][2]["name"], "AI Office / Market Analyst")
        self.assertEqual(calls[0][2]["head_sha"], "a" * 40)
        self.assertEqual(calls[0][2]["external_id"], "481516")
        self.assertEqual(calls[1][2]["conclusion"], "success")
        self.assertEqual(calls[2][2]["conclusion"], "failure")
        for _, _, payload in calls:
            encoded = json.dumps(payload).lower()
            for secret in ("dummy", "account_id", "password", "bearer",
                           "place_order", "webull", "rationale", "prompt"):
                self.assertNotIn(secret, encoded)

    def test_model_opinions_unchanged_and_role_events_always_close(self):
        events = []
        def spy(role, event, check_id=None):
            events.append((role, event))
            return 1 if event == "start" else None
        data = {"quotes": {"SPY": {"close": 500, "as_of": "2026-10-22"}}}
        def good(provider, model, instructions, prompt):
            role = json.loads(prompt)["role"]
            return ({"symbol": "SPY", "action": "HOLD", "confidence": .5,
                     "rationale": role, "evidence": [], "risks": []},
                    {"input_tokens": 1, "output_tokens": 2})
        with patch("research.agent_check_status.publish_stage", side_effect=spy):
            report = run_agents(data, "offline-test-model", requester=good)
        self.assertEqual(len(events), 14)
        self.assertEqual(events[0], ("Market Analyst", "start"))
        self.assertEqual(events[1], ("Market Analyst", "success"))
        self.assertEqual(events[-1], ("Trade Reviewer", "success"))
        self.assertEqual(report["consensus"], "NO_CONSENSUS")
        self.assertFalse(report["broker_connected"])
        self.assertEqual(report["actual_order_count"], 0)

        def broken(*_):
            raise TimeoutError("model down")
        events.clear()
        with patch("research.agent_check_status.publish_stage", side_effect=spy):
            with self.assertRaises(TimeoutError):
                run_agents(data, "offline-test-model", requester=broken)
        self.assertEqual(events, [
            ("Market Analyst", "start"), ("Market Analyst", "failure")])


if __name__ == "__main__":
    unittest.main()
