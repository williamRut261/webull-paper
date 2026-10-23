"""Fail-closed model dialogue regression; no broker or API calls."""
import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.office_conversation import (
    MAX_CALLS_DAY, new_state, run_once, validate_response, main, read_state,
)


def entry(text):
    return {"symbol": "SPY", "action": "HOLD", "confidence": 0.5,
            "rationale": text, "evidence": [], "risks": []}


class DialogueReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.when = datetime(2026, 10, 23, 7, 10, tzinfo=timezone.utc)
        self.state = new_state("2026-10-23")
        self.events = []

    def publish(self, role, event, check_id=None):
        self.events.append((role, event))
        return 123 if event == "start" else None

    def test_long_but_valid_conversational_sentence_is_safely_clipped(self):
        long = ("To the previous specialist: what independent out-of-sample evidence "
                "would show that a robust synthetic risk model has not concealed "
                "the underlying liquidity regime change? ") * 4
        clipped = validate_response(entry(long))
        self.assertGreater(len(long), 300)
        self.assertGreaterEqual(len(clipped), 20)
        self.assertLessEqual(len(clipped), 300)
        self.assertTrue(clipped.startswith("To the previous specialist:"))
        self.assertNotIn("<", clipped)
        self.assertNotIn(">", clipped)

    def test_partially_failed_hour_is_not_falsely_green_and_never_retries(self):
        calls = []
        def requester(provider, model, instruction, prompt):
            role = json.loads(prompt)["speaker"]
            calls.append(role)
            if len(calls) == 2:
                raise ValueError("private user text must not leak")
            return entry("To the prior specialist, which verified source supports the risk threshold?"), {}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = run_once(self.state, {"availability": "UNAVAILABLE"},
                              now=self.when, requester=requester, publish=self.publish)
        self.assertEqual(result, (2, "ATTEMPTED_PARTIAL"))
        self.assertEqual(self.events[-1][1], "failure")
        self.assertEqual(len(self.state["messages"]), 1)
        self.assertEqual(self.state["calls_today"], 2)
        self.assertEqual(self.state["turn_seq"], 2)
        self.assertEqual(self.state["last_hour"], "2026-10-23T07")
        self.assertEqual(run_once(self.state, {}, now=self.when,
                                  requester=requester, publish=self.publish),
                         (0, "HOUR_ALREADY_COMPLETED"))
        self.assertEqual(len(calls), 2)
        self.assertNotIn("private user text", output.getvalue())

    def test_failure_telemetry_classifies_stage_without_raw_provider_content(self):
        for scenario in ("invalid_reply", "backend_error"):
            with self.subTest(scenario=scenario):
                self.state = new_state("2026-10-23")
                def requester(*_args):
                    if scenario == "invalid_reply":
                        return {**entry("This is a research-only question about uncertainty."),
                                "action": "BUY"}, {}
                    raise ValueError("secret response payload must not escape")
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    result = run_once(self.state, {}, now=self.when,
                                      requester=requester, publish=self.publish)
                self.assertEqual(result, (2, "ATTEMPTED_FAILED"))
                expected = ("RESPONSE_VALIDATION" if scenario == "invalid_reply"
                            else "MODEL_BACKEND")
                self.assertIn("category=" + expected, output.getvalue())
                self.assertNotIn("secret response payload", output.getvalue())
                self.assertEqual(len(self.state["messages"]), 0)

    def test_entirely_failed_hour_is_recorded_as_failed_without_extra_calls(self):
        def fail(*_args):
            raise ValueError("do not log secret provider content")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = run_once(self.state, {}, now=self.when, requester=fail,
                              publish=self.publish)
        self.assertEqual(result, (2, "ATTEMPTED_FAILED"))
        self.assertEqual(self.state["calls_today"], 2)
        self.assertEqual(self.state["messages"], [])
        self.assertEqual([x[1] for x in self.events],
                         ["start", "failure", "start", "failure"])
        self.assertNotIn("do not log secret", output.getvalue())

    def test_cli_marks_partial_run_failed_but_persists_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "conversation.json"
            research = Path(tmp) / "public-research.json"
            research.write_text("{}")
            def partially_failed_run(state, public, **kwargs):
                state["day_utc"] = "2026-10-23"
                state["last_hour"] = "2026-10-23T07"
                state["calls_today"] = 2
                state["turn_seq"] = 2
                return 2, "ATTEMPTED_PARTIAL"
            with patch("research.office_conversation.configured", return_value=True), \
                 patch("research.office_conversation.model_for", return_value="model"), \
                 patch("research.office_conversation.run_once", side_effect=partially_failed_run):
                self.assertNotEqual(main(["--state", str(dest), "--research", str(research)]), 0)
            self.assertTrue(dest.exists())
            self.assertEqual(read_state(dest, "2026-10-23")["calls_today"], 2)

    def test_non_hold_or_wrong_symbol_remains_strictly_unusable(self):
        for incorrect in (
            {**entry("Safe research questions are the only allowed output."), "action": "BUY"},
            {**entry("Safe research questions are the only allowed output."), "symbol": "QQQ"},
        ):
            with self.assertRaises(ValueError):
                validate_response(incorrect)


if __name__ == "__main__":
    unittest.main()
