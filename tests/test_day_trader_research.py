"""Offline regression tests: no broker connectivity or order side effects."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from research.beethoven_advisory import build_report, safe_targets
from research.read_only_tool import ALLOWED, VENDOR, command, main


def example(weights=None, complete=False):
    log = "PAPER_AUTO_SIGNAL " + json.dumps({
        "date": "2026-10-20", "paper_only": True,
        "targets": weights if weights is not None else {"TQQQ": 0.99}
    })
    if complete:
        log += "\nPAPER_REBALANCE_COMPLETE " + json.dumps({"order_count": 2})
    return log


class PaperResearchIntegrationTests(TestCase):
    def test_report_requires_real_logged_signal(self):
        result = build_report("PAPER_MISSED_WINDOW no trade")
        self.assertEqual(result["status"], "NO_VERIFIED_LOG_SIGNAL")
        self.assertEqual(result["broker_orders_submitted_by_research"], 0)

    def test_signal_not_mistaken_for_fills(self):
        result = build_report(example())
        self.assertEqual(result["status"], "PAPER_LOG_SIGNAL_ONLY")
        self.assertIsNone(result["order_count_reported_by_runner"])
        self.assertFalse(result["completion_logged"])

    def test_completed_paper_marker_not_broker_audit(self):
        result = build_report(example(complete=True))
        self.assertEqual(result["status"], "PAPER_LOG_REBALANCE_COMPLETE")
        self.assertEqual(result["order_count_reported_by_runner"], 2)
        self.assertFalse(result["independent_fill_verification_by_research"])

    def test_warns_on_concentration_and_leverage(self):
        result = build_report(example())
        self.assertEqual(result["known_high_risk_tickers"], ["TQQQ"])
        self.assertEqual(result["max_symbol_weight"], .99)
        self.assertGreater(len(result["review_notes"]), 1)

    def test_rejects_invalid_and_foreign_targets(self):
        for v in ({"NOTETF": .99}, {"TQQQ": 1}, {"TQQQ": .8},
                  {"TQQQ": float("nan")}, {"TQQQ": True}, {}):
            with self.subTest(v=v):
                with self.assertRaises(ValueError):
                    safe_targets(v)

    def test_invalid_log_fails_closed(self):
        self.assertEqual(build_report("PAPER_AUTO_SIGNAL {corrupt")["status"],
                         "INVALID_PAPER_LOG")
        self.assertEqual(build_report(example({"BIL": .99})
                            .replace('"paper_only": true', '"paper_only": false'))
                         ["status"], "INVALID_PAPER_LOG")

    def test_only_manual_public_data_tools_allowed(self):
        self.assertEqual(set(ALLOWED), {"scanner", "news", "analyst", "pelosi"})
        for forbidden in ("broker", "execution", "risk", "orders"):
            with self.assertRaises(ValueError):
                command(forbidden, "TQQQ")
        for injection in ("TQQQ;echo BAD", "../TQQQ", "tqqq", "TQQQ$(id)"):
            with self.assertRaises(ValueError):
                command("scanner", injection)

    def test_research_subprocess_not_given_broker_secrets(self):
        with patch("research.read_only_tool.subprocess.run",
                   return_value=SimpleNamespace(returncode=0)) as run, \
             patch.dict("research.read_only_tool.os.environ", {
                 "WEBULL_PAPER_APP_KEY": "dummy",
                 "ALPACA_SECRET_KEY": "dummy",
                 "MISC_TOKEN": "dummy",
                 "GOOD": "ok"
             }):
            self.assertEqual(main(["--tool", "news", "--symbol", "TQQQ"]), 0)
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["GOOD"], "ok")
            self.assertNotIn("WEBULL_PAPER_APP_KEY", env)
            self.assertNotIn("ALPACA_SECRET_KEY", env)
            self.assertNotIn("MISC_TOKEN", env)

    def test_vendored_eleven_scripts_parse_offline(self):
        modules = [
            "trader-alerts/alerts.py", "trader-analyst/facts.py",
            "trader-broker/ticket.py", "trader-budget/size.py",
            "trader-entry/entry.py", "trader-exit/exit.py",
            "trader-news/news.py", "trader-pelosi/ptr.py",
            "trader-risk/check.py", "trader-scanner/scan.py",
            "trader-timemachine/timemachine.py"
        ]
        self.assertEqual(len(modules), 11)
        for name in modules:
            code = (VENDOR / name).read_text()
            compile(code, name, "exec")
        self.assertIn("MIT License", (VENDOR / "LICENSE").read_text())

    def test_research_workflow_has_no_trading_trigger_or_secrets(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/research-tools.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("live-execute", workflow)
        original = (root / ".github/workflows/webull-auto-execute.yml").read_text()
        self.assertIn("github.event_name == 'schedule'", original)


if __name__ == "__main__":
    import unittest
    unittest.main()
