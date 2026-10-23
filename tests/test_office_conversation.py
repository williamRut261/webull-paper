"""Offline tests: persistent autonomous agent dialogue never executes trading."""
from datetime import datetime, timezone, timedelta
import json
import tempfile
from pathlib import Path
import unittest

from research.office_conversation import (
    MAX_CALLS_DAY, MAX_MESSAGES, ROLES, new_state, read_public_research,
    read_state, run_once, validate_response, write_state,
)


def reply(provider, model, instruction, prompt):
    assert provider == "gemini"
    assert "No live quotes" in instruction
    data = json.loads(prompt)
    assert data["purpose"].endswith("NO TRADING")
    prev = data["previous_conversation_untrusted_data"]
    name = data["speaker"]
    msg = ("I hear the earlier specialist's concern. As " + name +
           ", I want to challenge the assumption that old data proves current conditions. "
           "Which missing evidence would change our view?")
    if prev:
        msg = "To " + prev[-1]["role"] + ": " + msg
    return ({"symbol": "SPY", "action": "HOLD", "confidence": .5,
             "rationale": msg, "evidence": [], "risks": []},
            {"input_tokens": 200, "output_tokens": 90})


class OfficeConversationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
        self.state = new_state(self.now.date().isoformat())
        self.events = []

    def publish(self, role, event, check_id=None):
        self.events.append((role, event))
        return 8 if event == "start" else None

    def session(self, when=None, requester=reply):
        return run_once(self.state, {"availability": "UNAVAILABLE"},
                        now=when or self.now, requester=requester,
                        publish=self.publish, model="gemini-3.5-flash-lite")

    def test_two_autonomous_replies_in_each_hour_rotate_seven_roles(self):
        self.assertEqual(self.session(), (2, "ATTEMPTED"))
        self.assertEqual(self.state["calls_today"], 2)
        self.assertEqual([m["role"] for m in self.state["messages"]], list(ROLES[:2]))
        self.assertIn("To Market Analyst", self.state["messages"][1]["text"])
        self.assertEqual(self.session(), (0, "HOUR_ALREADY_COMPLETED"))
        self.assertEqual(self.state["calls_today"], 2)
        self.assertEqual(self.session(self.now + timedelta(hours=1)), (2, "ATTEMPTED"))
        self.assertEqual([m["role"] for m in self.state["messages"]], list(ROLES[:4]))
        for hour in range(2, 4):
            self.session(self.now + timedelta(hours=hour))
        self.assertEqual(self.state["messages"][6]["role"], ROLES[6])
        self.assertEqual(self.state["messages"][7]["role"], ROLES[0])
        self.assertEqual(len(self.events), 16)
        self.assertEqual(self.state["turn_seq"], 8)

    def test_daily_hard_cap_and_start_failures_count_as_attempts(self):
        self.state["calls_today"] = MAX_CALLS_DAY - 1
        def failure(*args):
            raise RuntimeError("private-provider-error")
        self.assertEqual(self.session(requester=failure), (1, "ATTEMPTED_FAILED"))
        self.assertEqual(self.state["calls_today"], MAX_CALLS_DAY)
        self.assertEqual(self.state["messages"], [])
        self.assertEqual(self.events, [(ROLES[0], "start"), (ROLES[0], "failure")])
        self.assertEqual(self.session(self.now + timedelta(hours=1)), (0, "DAILY_CALL_LIMIT"))

    def test_day_resets_usage_but_preserves_memory(self):
        self.session()
        tomorrow = self.now + timedelta(days=1)
        self.assertEqual(self.session(tomorrow), (2, "ATTEMPTED"))
        self.assertEqual(self.state["calls_today"], 2)
        self.assertEqual(len(self.state["messages"]), 4)
        self.assertEqual(self.state["messages"][2]["role"], ROLES[2])

    def test_memory_trim_is_bounded(self):
        start = self.now.replace(hour=0)
        for h in range(24):
            self.session(start + timedelta(hours=h))
        self.assertEqual(self.state["calls_today"], 48)
        self.assertEqual(len(self.state["messages"]), 48)
        self.session(start + timedelta(days=1))
        self.assertEqual(len(self.state["messages"]), 50)
        self.state["messages"] = self.state["messages"][-MAX_MESSAGES:]
        self.assertLessEqual(len(self.state["messages"]), MAX_MESSAGES)

    def test_persistence_round_trip_and_invalid_replies_fail_closed(self):
        self.session()
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "office.json"
            write_state(file, self.state)
            saved = read_state(file, "2026-10-22")
            self.assertEqual(saved, self.state)
            saved = read_state(file, "2026-10-23")
            self.assertEqual(saved["calls_today"], 0)
            self.assertEqual(len(saved["messages"]), 2)
            file.write_text('{"schema":1,"messages":[{"role":"Injected order"}]}')
            with self.assertRaises(ValueError):
                read_state(file, "2026-10-23")
        for candidate in (None, {}, {"symbol": "SPY", "action": "BUY", "rationale": "x"*50},
                          {"symbol": "SPY", "action": "HOLD", "rationale": "x"},
                          {"symbol": "QQQ", "action": "HOLD", "rationale": "x"*50}):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                validate_response(candidate)

    def test_public_context_does_not_include_private_broker_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "feed.json"
            file.write_text(json.dumps({
                "as_of": "2026-10-21", "consensus": "NO_CONSENSUS",
                "account_id": "SECRET_ACCOUNT", "api_key": "SECRET_KEY",
                "agents": [{"role": ROLES[0], "action": "HOLD", "symbol": "SPY"}]
            }))
            public = read_public_research(file)
            self.assertNotIn("SECRET", json.dumps(public))
            self.assertEqual(public["availability"], "LAST_PUBLISHED_ONLY")
            self.assertEqual(public["agent_opinions"][0]["symbol"], "SPY")

    def test_no_broker_dependency_or_execution_api(self):
        source = (Path(__file__).resolve().parents[1] /
                  "research/office_conversation.py").read_text()
        self.assertNotIn("webull_paper", source)
        self.assertNotIn("trader_combo", source)
        self.assertNotIn("place_order(", source)
        self.assertNotIn("execute_order(", source)
        self.assertIn("MAX_CALLS_DAY = 48", source)
        self.assertIn("MAX_CALLS_SESSION = 2", source)
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/office-autonomous-dialogue.yml").read_text()
        self.assertIn('8 * * * *', workflow)
        self.assertIn("OFFICE_CONVERSATION_ENABLED", workflow)
        self.assertNotIn("WEBULL", workflow)
        self.assertNotIn("ALPACA", workflow)
        self.assertNotIn("broker", workflow.lower().split("permissions:", 1)[-1].split("jobs:", 1)[0])


if __name__ == "__main__":
    unittest.main()
