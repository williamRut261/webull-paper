"""Regression: seven-agent completion and runtime evidence must be truthful.

All tests are offline: no model, GitHub, Webull, or Cloud Run traffic.
"""
import json
import math
import unittest
from unittest.mock import patch

from research.ai_desk import ROLES, run_agents, run_comparison, safe_report


def vote(role, *, confidence=0.5, evidence=None):
    return {"symbol": "SPY", "action": "HOLD", "confidence": confidence,
            "rationale": "Offline research from " + role,
            "evidence": ["test-only"] if evidence is None else evidence, "risks": []}


SNAPSHOT = {"quotes": {"SPY": {"close": 500.0, "as_of": "2026-10-22"}}}


class EvidenceTests(unittest.TestCase):
    def test_invalid_confidence_is_a_failed_role_not_a_completed_check(self):
        events = []
        def mark(role, event, check_id=None):
            events.append((role, event))
            return 999 if event == "start" else None
        def malformed(provider, model, instruction, prompt):
            role = json.loads(prompt)["role"]
            return vote(role, confidence=math.nan), {"input_tokens": 1, "output_tokens": 2}
        with patch("research.agent_check_status.publish_stage", side_effect=mark):
            with self.assertRaises(ValueError) as raised:
                run_agents(SNAPSHOT, "offline-test", requester=malformed)
        self.assertEqual(events, [("Market Analyst", "start"),
                                  ("Market Analyst", "failure")])
        progress = raised.exception.agent_progress
        self.assertEqual(progress["failed_role"], "Market Analyst")
        self.assertEqual(progress["completed_roles"], [])
        self.assertEqual(progress["role_execution"][0]["status"], "FAILED")
        self.assertEqual(progress["role_execution"][0]["error_type"], "ValueError")
        self.assertEqual(progress["roles_attempted"], 1)

    def test_partial_successes_are_preserved_when_later_role_fails(self):
        events = []
        def mark(role, event, check_id=None):
            events.append((role, event))
            return 1 if event == "start" else None
        def partial(provider, model, instruction, prompt):
            role = json.loads(prompt)["role"]
            if role == "News Researcher":
                raise TimeoutError("provider key value must never be logged")
            return vote(role), {"input_tokens": 4, "output_tokens": 2}
        with patch("research.agent_check_status.publish_stage", side_effect=mark):
            with self.assertRaises(TimeoutError) as raised:
                run_agents(SNAPSHOT, "offline-test", requester=partial)
        progress = raised.exception.agent_progress
        self.assertEqual(progress["completed_roles"], ["Market Analyst", "Technical Analyst"])
        self.assertEqual(progress["failed_role"], "News Researcher")
        self.assertEqual(progress["roles_attempted"], 3)
        self.assertEqual([x["status"] for x in progress["role_execution"]],
                         ["VERIFIED", "VERIFIED", "FAILED"])
        self.assertEqual(progress["token_usage"], {"input_tokens": 8, "output_tokens": 4})
        self.assertNotIn("provider key value", json.dumps(progress))
        self.assertEqual([e for _, e in events], [
            "start", "success", "start", "success", "start", "failure"])

    def test_successful_seven_agent_run_has_a_bounded_latency_evidence_trail(self):
        def good(provider, model, instruction, prompt):
            role = json.loads(prompt)["role"]
            return vote(role), {"input_tokens": 2, "output_tokens": 1}
        result = run_agents(SNAPSHOT, "offline-test", requester=good)
        rows = result["role_execution"]
        self.assertEqual([r["role"] for r in rows], list(ROLES))
        self.assertTrue(all(r["status"] == "VERIFIED" for r in rows))
        self.assertTrue(all(type(r["duration_ms"]) is int and 0 <= r["duration_ms"] <= 600000
                            for r in rows))
        self.assertEqual(result["roles_attempted"], 7)
        self.assertEqual(result["roles_completed"], 7)
        self.assertEqual(result["actual_order_count"], 0)
        self.assertFalse(result["broker_connected"])

    def test_invalid_lists_are_not_marked_success_or_accepted_in_reports(self):
        invalid = vote("Market Analyst", evidence="synthetic bogus string not list")
        with self.assertRaises(ValueError):
            safe_report(SNAPSHOT, {role: invalid for role in ROLES})
        def model(*args):
            return invalid, {"input_tokens": 1, "output_tokens": 1}
        with self.assertRaises(ValueError):
            run_agents(SNAPSHOT, "offline", requester=model)

    def test_comparison_keeps_partial_failed_provider_progress(self):
        def flaky(provider, model, instruction, prompt):
            role = json.loads(prompt)["role"]
            if role == "Technical Analyst":
                raise ConnectionError("private credentials must not be published")
            return vote(role), {"input_tokens": 1, "output_tokens": 1}
        with patch("research.ai_desk.configured", return_value=True), \
             patch("research.ai_desk.model_for", return_value="fake-model"):
            outcome = run_comparison(SNAPSHOT, requester=flaky)
        for result in outcome["provider_results"].values():
            self.assertEqual(result["status"], "MODEL_ERROR")
            self.assertEqual(result["failed_role"], "Technical Analyst")
            self.assertEqual(result["completed_roles"], ["Market Analyst"])
            self.assertNotIn("private credentials", json.dumps(result))
        self.assertEqual(outcome["actual_order_count"], 0)


if __name__ == "__main__":
    unittest.main()
