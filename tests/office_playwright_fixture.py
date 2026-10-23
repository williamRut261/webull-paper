"""LOOPBACK-ONLY mocked GitHub research fixture for Playwright integration tests.

This file is intentionally excluded from the dashboard Docker image.
NEVER start it on an externally routable interface or with real credentials.
"""
import importlib
import os

if os.environ.get("STONKS_OFFICE_E2E") != "true":
    raise SystemExit("Only STONKS_OFFICE_E2E=true permits this mock fixture server")

dash = importlib.import_module("dashboard.app")
from dashboard.app import AGENT_ROLES

def read_fake_agent():
    return {
        "state": "RESEARCH_ONLY", "provider": "gemini",
        "as_of": "2026-10-22", "stale": False,
        "consensus": "NO_CONSENSUS",
        "decision": "NO EXECUTABLE AGENT DECISION",
        "virtual_equity": "$10,000.00", "virtual_return": "+0.00%",
        "virtual_drawdown": "0.00%",
        "agents": [{"role": role, "symbol": "SPY", "action": "HOLD",
                    "confidence": "50%"} for role in AGENT_ROLES],
    }


# Patch *this testing interpreter only*. No IAP bypass is added to app.py.
dash.authorized_user = lambda: "test-fixture@example.invalid"
dash.read_agent_feed = read_fake_agent
dash.read_office_run = lambda: {
    "state": "in_progress", "active": True, "queued": False,
    "expired": False, "conclusion": "", "run_id": 12345,
    "head_sha": "a" * 40, "type": "Synthetic testing run",
    "created": "2026-10-23T05:00:00Z",
    "run_url": "https://github.com/williamRut261/webull-paper/actions/runs/12345",
}
dash.read_office_role_checks = lambda *_a, **_k: {
    "Market Analyst": "WORKING", "Technical Analyst": "DONE",
    "Risk Manager": "FAILED",
}
dash.read_office_conversation = lambda: {
    "available": True, "kind": "HOURLY_BUDGETED_RESEARCH_DIALOGUE",
    "updated_at": "2026-10-23T05:00:00+00:00", "last_turn": 1,
    "messages": [{
        "turn": 1, "role": "Market Analyst", "name": "Maya",
        "text": "Offline test-only research message with no broker instructions.",
        "at": "2026-10-23T05:00:00+00:00",
    }],
}
dash.app.run(host="127.0.0.1", port=18765, use_reloader=False, debug=False)
