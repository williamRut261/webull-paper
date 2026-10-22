"""Provider-format tests with fake HTTPS responses; zero paid API calls."""
import json
import os
import unittest
from unittest.mock import patch
from research.model_backends import (
    PROVIDERS, configured, model_for, parse_opinion, request_opinion,
)
from research.ai_desk import ROLES, run_agents, run_comparison


OPINION = {
    "symbol": "GDXD", "action": "BUY", "confidence": .9,
    "rationale": "Synthetic test", "evidence": ["unit test"], "risks": ["leverage"],
}


class Response:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, n=-1):
        return self.data[:n]


class ProviderAdapterTests(unittest.TestCase):
    def test_every_provider_is_fixed_https_host(self):
        self.assertEqual(set(PROVIDERS), {"gemini", "openai", "claude", "grok"})
        for provider, entry in PROVIDERS.items():
            self.assertTrue(entry["url"].startswith("https://"))
            self.assertTrue(entry["env"].endswith("API_KEY"))

    def test_model_overrides_validate(self):
        for provider in PROVIDERS:
            self.assertTrue(model_for(provider))
            with self.assertRaises(ValueError):
                model_for(provider, {"AI_DESK_" + provider.upper() + "_MODEL":
                                    "https://evil.example/steal-key"})

    def test_configured_independent_provider_keys(self):
        self.assertTrue(configured("gemini", {"GEMINI_API_KEY": "dummy"}))
        self.assertFalse(configured("claude", {"GEMINI_API_KEY": "dummy"}))

    def test_chat_api_payloads(self):
        for provider in ("gemini", "openai", "grok"):
            captured = {}
            def fake_opener(req, timeout):
                captured["url"] = req.full_url
                captured["body"] = json.loads(req.data)
                captured["headers"] = dict(req.header_items())
                captured["timeout"] = timeout
                return Response({"choices": [{"message": {
                    "content": json.dumps(OPINION)}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
            opinion, counts = request_opinion(
                provider, model_for(provider), "role", "snapshot",
                opener=fake_opener, env={PROVIDERS[provider]["env"]: "test-key"})
            with self.subTest(provider=provider):
                self.assertEqual(opinion, OPINION)
                self.assertEqual(counts["input_tokens"], 100)
                self.assertEqual(captured["body"]["messages"][0]["role"], "system")
                self.assertEqual(captured["url"], PROVIDERS[provider]["url"])
                self.assertLessEqual(captured["timeout"], 45)
                self.assertNotIn("test-key", json.dumps(captured["body"]))
                self.assertIn("Authorization", captured["headers"])

    def test_claude_message_schema(self):
        captured = {}
        def opener(req, timeout):
            captured["body"] = json.loads(req.data)
            captured["headers"] = dict(req.header_items())
            return Response({"content": [{"type": "text", "text": json.dumps(OPINION)}],
                             "usage": {"input_tokens": 82, "output_tokens": 33}})
        data, usage = request_opinion(
            "claude", model_for("claude"), "role", "snapshot",
            opener=opener, env={"ANTHROPIC_API_KEY": "test-key"})
        self.assertEqual(data, OPINION)
        self.assertEqual(usage, {"input_tokens": 82, "output_tokens": 33})
        self.assertEqual(captured["body"]["system"], "role")
        self.assertEqual(captured["body"]["max_tokens"], 900)
        self.assertIn("X-api-key", captured["headers"])

    def test_malformed_outputs_fail_closed(self):
        for payload in ('{"action":"BUY"}', "not json", "[]"):
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                parse_opinion(payload)

    def test_no_key_fails_before_network(self):
        def no_network(req, timeout):
            raise AssertionError("Network must not be called")
        with self.assertRaises(ValueError):
            request_opinion("gemini", "gemini-3.5-flash-lite", "", "",
                            opener=no_network, env={})

    def test_provider_switch_without_strategy_change(self):
        seen = []
        def fake(provider, model, instruction, prompt):
            role = json.loads(prompt)["role"]
            seen.append((provider, role, json.loads(prompt)["source_snapshot"]))
            return dict(OPINION), {"input_tokens": 100, "output_tokens": 30}
        snapshot = {"quotes": {"GDXD": {"close": 10}}}
        for provider in PROVIDERS:
            report = run_agents(snapshot, model_for(provider), provider, requester=fake)
            self.assertEqual(report["actual_order_count"], 0)
            self.assertEqual(report["provider"], provider)
            self.assertEqual(report["token_usage"]["input_tokens"], 700)
            self.assertEqual(report["consensus"], "HYPOTHESIS_FOR_BACKTEST")
        self.assertEqual(len(seen), 28)
        self.assertEqual(set(x[1] for x in seen), set(ROLES))
        self.assertEqual({json.dumps(x[2], sort_keys=True) for x in seen},
                         {json.dumps(snapshot, sort_keys=True)})

    def test_compare_only_configured_providers(self):
        with patch("research.ai_desk.configured", side_effect=lambda p: p == "gemini"):
            def fake(provider, model, instruction, prompt):
                return dict(OPINION), {"input_tokens": 10, "output_tokens": 10}
            result = run_comparison({"quotes": {"GDXD": {"close": 10}}}, fake)
        self.assertEqual(result["providers_succeeded"], 1)
        self.assertEqual(result["provider_results"]["claude"]["status"], "NOT_CONFIGURED")
        self.assertEqual(result["actual_order_count"], 0)


if __name__ == "__main__":
    unittest.main()
