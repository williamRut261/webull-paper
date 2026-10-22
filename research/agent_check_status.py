"""Optional GitHub Checks telemetry for the visual office, never brokerage.

Only seven fixed role names and start/completion states leave the runner.
No prompts, model outputs, portfolios, symbols, account identifiers or tokens
are published. All telemetry errors are non-fatal to existing research logic.
"""
from datetime import datetime, timezone
import json
import os
import re
from urllib.request import Request, urlopen

ROLES = frozenset((
    "Market Analyst", "Technical Analyst", "News Researcher",
    "Strategy Analyst", "Risk Manager", "Desk Lead", "Trade Reviewer",
))
REPOSITORY = "williamRut261/webull-paper"
CHECK_PREFIX = "AI Office / "


def publish_stage(role, event, check_id=None, opener=urlopen):
    """Return check_id on start. Never raise or affect the strategy engine."""
    if (os.environ.get("AI_OFFICE_CHECKS_ENABLED") != "true"
            or role not in ROLES or event not in ("start", "success", "failure")):
        return None
    token = os.environ.get("AI_OFFICE_GITHUB_TOKEN", "")
    sha = os.environ.get("GITHUB_SHA", "")
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or not token
            or not re.fullmatch(r"[0-9a-f]{40}", sha)):
        return None
    if event != "start" and (type(check_id) is not int or check_id <= 0):
        return None
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if event == "start":
        uri = "https://api.github.com/repos/" + REPOSITORY + "/check-runs"
        method = "POST"
        payload = {"name": CHECK_PREFIX + role, "head_sha": sha,
                   "status": "in_progress", "started_at": now,
                   "output": {"title": "Research role running",
                              "summary": "Model call started; no trading permissions."}}
    else:
        uri = ("https://api.github.com/repos/" + REPOSITORY +
               "/check-runs/" + str(check_id))
        method = "PATCH"
        payload = {"status": "completed",
                   "conclusion": "success" if event == "success" else "failure",
                   "completed_at": now,
                   "output": {"title": "Research role " + event,
                              "summary": "No prompts, trades or account data published."}}
    req = Request(uri, data=json.dumps(payload).encode("utf-8"),
                  method=method,
                  headers={"Authorization": "Bearer " + token,
                           "Accept": "application/vnd.github+json",
                           "Content-Type": "application/json",
                           "User-Agent": "stonks-agent-office"})
    try:
        with opener(req, timeout=4) as response:
            result = json.load(response)
        if event == "start" and type(result.get("id")) is int and result["id"] > 0:
            return result["id"]
    except Exception as error:
        # Do not print exceptions: auth headers and URLs might appear in messages.
        print("AI_OFFICE_TELEMETRY_UNAVAILABLE event=" + event +
              " class=" + type(error).__name__, flush=True)
    return None
