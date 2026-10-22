"""Offline tests for visual 7-agent office, strict source grounding and IAP."""
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from dashboard.app import (
    app, OFFICE_ROLES, build_office_workers, read_office_run,
    read_office_role_checks,
)


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n):
        return self.data[:n]


def recorded_report():
    return {
        "state": "RESEARCH_ONLY",
        "provider": "gemini",
        "as_of": "2026-10-21",
        "stale": False,
        "consensus": "NO_CONSENSUS",
        "decision": "NO EXECUTABLE AGENT DECISION",
        "virtual_equity": "$10,000.00",
        "virtual_return": "+0.00%",
        "virtual_drawdown": "0.00%",
        "agents": [
            {"role": role[0], "action": "HOLD", "symbol": "SPY",
             "confidence": "50%"} for role in OFFICE_ROLES
        ],
    }


def run_response(status, conclusion=None):
    return {
        "workflow_runs": [{
            "name": "AI Trading Desk (RESEARCH ONLY - NO BROKER ORDERS)",
            "id": 12345, "head_branch": "main", "status": status,
            "conclusion": conclusion, "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }]
    }


class AgentOfficeTests(unittest.TestCase):
    def test_exact_seven_people_use_real_roles_and_reported_opinions(self):
        rows = build_office_workers(recorded_report())
        self.assertEqual(len(rows), 7)
        self.assertEqual([r["title"] for r in rows], [r[0] for r in OFFICE_ROLES])
        self.assertTrue(all(row["vote"]["action"] == "HOLD" for row in rows))
        self.assertEqual(len(build_office_workers(None)), 7)
        self.assertTrue(all(row["vote"] is None for row in build_office_workers(None)))

    def test_public_gh_workflow_metadata_is_scoped_to_known_run_names(self):
        source = run_response("in_progress")
        source["workflow_runs"].insert(0, {
            "name": "Totally different workflow", "id": 999,
            "head_branch": "main", "status": "in_progress"
        })
        def opener(req, timeout):
            self.assertEqual(req.full_url.split("/")[2], "api.github.com")
            self.assertLessEqual(timeout, 3)
            return Response(json.dumps(source).encode("utf-8"))
        status = read_office_run(opener=opener)
        self.assertTrue(status["active"])
        self.assertFalse(status["queued"])
        self.assertIn("/runs/12345", status["run_url"])

    def test_verified_per_role_github_checks_only_enable_actual_worker(self):
        sha = "a" * 40
        checks = {"check_runs": [
            {"name": "CI unrelated", "status": "in_progress", "conclusion": None},
            {"name": "AI Office / Technical Analyst", "status": "in_progress", "conclusion": None},
            {"name": "AI Office / Market Analyst", "status": "completed", "conclusion": "success"},
            {"name": "AI Office / Risk Manager", "status": "completed", "conclusion": "failure"},
            {"name": "AI Office / unknown", "status": "in_progress", "conclusion": None},
        ]}
        def opener(req, timeout):
            self.assertIn("/commits/" + sha + "/check-runs", req.full_url)
            self.assertEqual(req.full_url.split("/")[2], "api.github.com")
            return Response(json.dumps(checks).encode())
        statuses = read_office_role_checks(sha, opener=opener)
        self.assertEqual(statuses, {
            "Technical Analyst": "WORKING", "Market Analyst": "DONE",
            "Risk Manager": "FAILED"})
        workers = build_office_workers(recorded_report(), statuses)
        self.assertEqual(workers[1]["stage"], "WORKING")
        self.assertEqual(workers[0]["stage"], "DONE")
        self.assertIsNone(workers[6]["stage"])
        self.assertEqual(read_office_role_checks(None, opener=opener), {})
        self.assertEqual(read_office_role_checks("../../bad", opener=opener), {})

    def test_research_lookup_is_workflow_scoped_not_displaced_by_ci(self):
        visited = []
        def opener(req, timeout):
            visited.append(req.full_url)
            self.assertIn("/actions/workflows/", req.full_url)
            self.assertIn("per_page=1", req.full_url)
            if "ai-trading-desk.yml" in req.full_url:
                return Response(json.dumps(run_response("completed", "success")).encode())
            other = run_response("completed", "failure")
            other["workflow_runs"][0]["name"] = (
                "One-Time Seven-Agent Provider Verification (NO BROKER)")
            other["workflow_runs"][0]["created_at"] = "2025-01-01T00:00:00Z"
            return Response(json.dumps(other).encode())
        result = read_office_run(opener=opener)
        self.assertEqual(result["conclusion"], "success")
        self.assertEqual(result["run_id"], 12345)
        self.assertEqual(len(visited), 2)

    def test_stale_workflow_never_shows_realtime_working(self):
        old = run_response("in_progress")
        old["workflow_runs"][0]["created_at"] = "2025-01-01T00:00:00Z"
        result = read_office_run(
            opener=lambda req, timeout: Response(json.dumps(old).encode()))
        self.assertTrue(result["expired"])
        self.assertFalse(result["active"])
        self.assertFalse(result["queued"])

    def test_role_checks_require_selected_run_and_stale_incomplete_work(self):
        sha = "b" * 40
        data = {"check_runs": [
            {"id": 99, "name": "AI Office / Market Analyst", "external_id": "11",
             "status": "in_progress", "started_at": "2026-10-22T09:00:00Z"},
            {"id": 12, "name": "AI Office / Market Analyst", "external_id": "12",
             "status": "completed", "conclusion": "success",
             "started_at": "2026-10-22T10:00:00Z"},
            {"id": 13, "name": "AI Office / Technical Analyst", "external_id": "12",
             "status": "in_progress", "started_at": "2026-10-22T10:03:00Z"},
            {"id": 14, "name": "AI Office / Risk Manager", "external_id": "12",
             "status": "completed", "conclusion": "failure",
             "started_at": "2026-10-22T10:04:00Z"},
            {"id": 15, "name": "AI Office / Desk Lead", "status": "in_progress"},
        ]}
        def opener(req, timeout):
            return Response(json.dumps(data).encode())
        states = read_office_role_checks(sha, opener=opener,
                                          run_id=12, run_active=False)
        self.assertEqual(states, {
            "Market Analyst": "DONE", "Technical Analyst": "STALE",
            "Risk Manager": "FAILED"})
        self.assertNotIn("Desk Lead", states)
        self.assertEqual(read_office_role_checks(sha, opener=opener, run_id=-1), {})

    def test_completed_and_queued_are_not_mistaken_for_live_execution(self):
        for state, expected in (("completed", False), ("queued", False), ("in_progress", True)):
            with self.subTest(state=state):
                status = read_office_run(
                    opener=lambda req, timeout: Response(
                        json.dumps(run_response(state, "success" if state == "completed" else None)).encode()))
                self.assertEqual(status["active"], expected)
        with self.assertRaises(ValueError):
            read_office_run(opener=lambda req, timeout: Response(b"{broken"))

    def test_unrelated_jobs_are_not_claimed_as_ai_work(self):
        irrelevant = {"workflow_runs": [{"name": "Webull Paper Auto-Trading (SANDBOX ONLY)",
                                         "head_branch": "main", "id": 111,
                                         "status": "in_progress"}]}
        self.assertIsNone(read_office_run(
            opener=lambda req, timeout: Response(json.dumps(irrelevant).encode())))

    def test_owner_only_visual_office_with_no_broker_endpoints(self):
        audience = "/projects/123/locations/us-central1/services/webull-paper-viewer"
        settings = {"IAP_AUDIENCE": audience, "DASHBOARD_ALLOWED_EMAIL": "owner@example.com"}
        with patch.dict(os.environ, settings, clear=True):
            with app.test_client() as c:
                self.assertEqual(c.get("/office").status_code, 403)
            with patch("dashboard.app.id_token.verify_token", return_value={
                "iss": "https://cloud.google.com/iap", "email": "owner@example.com"
            }), patch("dashboard.app.read_agent_feed", return_value=recorded_report()), \
                 patch("dashboard.app.read_office_run", return_value={
                     "active": True, "queued": False, "state": "in_progress",
                     "type": "Scheduled AI desk", "created": "2026-10-22T23:35:01",
                     "conclusion": "", "run_url":
                     "https://github.com/williamRut261/webull-paper/actions/runs/12345",
                 }):
                with app.test_client() as c:
                    response = c.get("/office", headers={"X-Goog-Iap-Jwt-Assertion": "signed"})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b"The Agent Office", response.data)
                    self.assertIn(b"Market Analyst", response.data)
                    self.assertIn(b"Trade Reviewer", response.data)
                    self.assertIn(b"DESK RUN IN PROGRESS", response.data)
                    self.assertIn(b"Only an active, run-matched GitHub Check", response.data)
                    self.assertEqual(response.data.count(b'class="pod '), 7)
                    self.assertIn(b'id="motion"', response.data)
                    self.assertIn(b"prefers-reduced-motion", response.data)
                    self.assertIn(b"robot", response.data)
                    self.assertIn(b"<details", response.data)
                    self.assertIn(b'<script src="/office/motion.js" defer></script>', response.data)
                    self.assertIn(b"HOLD SPY", response.data)
                    self.assertIn(b"content=\"30\"", response.data)
                    self.assertEqual(response.headers.get("Cache-Control"), "private, no-store")
                    self.assertIn("default-src 'none'", response.headers.get("Content-Security-Policy"))

    def test_animation_is_bundled_and_does_not_load_third_party_assets(self):
        source = (Path(__file__).resolve().parents[1] /
                  "dashboard/templates/office.html").read_text()
        self.assertIn("@keyframes roam", source)
        self.assertIn("@keyframes scan", source)
        self.assertIn("@keyframes type-a", source)
        self.assertIn("prefers-reduced-motion", source)
        self.assertIn("body:has(#motion:not(:checked))", source)
        self.assertNotIn("https://", source)
        self.assertIn('<script src="/office/motion.js" defer></script>', source)
        self.assertEqual(source.count("<script"), 1)
        self.assertIn("data-workflow-active", source)
        self.assertIn("agent-walker", source)
        self.assertIn("@keyframes step-leg", source)
        self.assertIn('aria-label="Animated virtual research office"', source)
        self.assertIn("missing events remain unavailable", source.lower())
        docker = (Path(__file__).resolve().parents[1] /
                  "dashboard/Dockerfile").read_text()
        self.assertIn("COPY templates/ /app/templates/", docker)
        self.assertIn("COPY static/ /app/static/", docker)

    def test_animated_walking_script_is_authenticated_and_broker_isolated(self):
        code = (Path(__file__).resolve().parents[1] /
                "dashboard/static/office-motion.js").read_text()
        self.assertIn("agent-walker", code)
        self.assertIn("is-wandering", code)
        self.assertIn("visibilitychange", code)
        self.assertIn("prefers-reduced-motion", code)
        for forbidden in ("place_order", "fetch(", "XMLHttpRequest", "axios",
                          "Webull", "create_order", "submit_order"):
            self.assertNotIn(forbidden, code)
        audience = "/projects/123/locations/us-central1/services/webull-paper-viewer"
        with patch.dict(os.environ, {"IAP_AUDIENCE": audience,
                                     "DASHBOARD_ALLOWED_EMAIL": "owner@example.com"}, clear=True):
            with app.test_client() as client:
                self.assertEqual(client.get("/office/motion.js").status_code, 403)
            with patch("dashboard.app.id_token.verify_token", return_value={
                "iss": "https://cloud.google.com/iap", "email": "owner@example.com"
            }):
                with app.test_client() as client:
                    response = client.get("/office/motion.js", headers={
                        "X-Goog-Iap-Jwt-Assertion": "signed"})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b"agent-walker", response.data)
                    self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def test_missing_report_stays_unavailable_not_fake_lively_personnel(self):
        audience = "/projects/123/locations/us-central1/services/webull-paper-viewer"
        with patch.dict(os.environ, {"IAP_AUDIENCE": audience,
                                     "DASHBOARD_ALLOWED_EMAIL": "owner@example.com"}, clear=True):
            with patch("dashboard.app.id_token.verify_token", return_value={
                "iss": "https://cloud.google.com/iap", "email": "owner@example.com"
            }), patch("dashboard.app.read_agent_feed", side_effect=RuntimeError("no net")), \
                 patch("dashboard.app.read_office_run", return_value=None):
                with app.test_client() as c:
                    response = c.get("/office", headers={"X-Goog-Iap-Jwt-Assertion": "signed"})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b"No published opinion yet", response.data)
                    self.assertIn(b"LIVE RUN STATUS UNAVAILABLE", response.data)
                    self.assertNotIn(b"DESK RUN IN PROGRESS", response.data)


if __name__ == "__main__":
    unittest.main()
