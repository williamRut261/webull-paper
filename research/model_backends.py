"""Strict provider adapters for AI research: no brokerage access or execution."""
import json
import os
import re
from urllib.request import Request, urlopen

PROVIDERS = {
    "gemini": {"env": "GEMINI_API_KEY", "model": "gemini-3.5-flash-lite",
               "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"},
    "openai": {"env": "OPENAI_API_KEY", "model": "gpt-5-mini",
               "url": "https://api.openai.com/v1/chat/completions"},
    "grok": {"env": "XAI_API_KEY", "model": "grok-4.7",
             "url": "https://api.x.ai/v1/chat/completions"},
    "claude": {"env": "ANTHROPIC_API_KEY", "model": "claude-haiku-4-5",
               "url": "https://api.anthropic.com/v1/messages"},
}
MODEL_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,80}\Z")


def model_for(provider, env=None):
    if provider not in PROVIDERS:
        raise ValueError("Unsupported provider")
    env = os.environ if env is None else env
    model = env.get("AI_DESK_" + provider.upper() + "_MODEL") or PROVIDERS[provider]["model"]
    if not MODEL_PATTERN.fullmatch(model):
        raise ValueError("Invalid model identifier")
    return model


def configured(provider, env=None):
    if provider not in PROVIDERS:
        raise ValueError("Unsupported provider")
    env = os.environ if env is None else env
    return bool(env.get(PROVIDERS[provider]["env"], "").strip())


def parse_opinion(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > 12000:
        raise ValueError("Missing or oversized model response")
    cleaned = text.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        first, sep, rest = cleaned.partition("\n")
        if not sep or first not in (fence, fence + "json", fence + "JSON") or not rest.rstrip().endswith(fence):
            raise ValueError("Invalid JSON fence")
        cleaned = rest.rstrip()[:-3].strip()
    answer = json.loads(cleaned)
    if not isinstance(answer, dict):
        raise ValueError("Opinion must be JSON object")
    if not {"symbol", "action", "confidence", "rationale", "evidence", "risks"} <= set(answer):
        raise ValueError("Missing opinion fields")
    if not isinstance(answer["rationale"], str) or len(answer["rationale"]) > 1600:
        raise ValueError("Invalid rationale")
    for field in ("evidence", "risks"):
        entries = answer[field]
        if not isinstance(entries, list) or len(entries) > 8 or any(
                not isinstance(x, str) or len(x) > 650 for x in entries):
            raise ValueError("Invalid evidence/risks")
    return answer


def request_opinion(provider, model, instruction, prompt, *, opener=urlopen, env=None):
    """One bounded request; returns opinion and normalized usage.

    Fixed HTTPS endpoints prevent user-specified key exfiltration. Never log
    headers, raw exception text, or model responses on failure.
    """
    if provider not in PROVIDERS or not MODEL_PATTERN.fullmatch(model):
        raise ValueError("Invalid provider or model")
    env = os.environ if env is None else env
    key = env.get(PROVIDERS[provider]["env"], "").strip()
    if not key:
        raise ValueError("Missing provider API key")
    if not isinstance(prompt, str) or len(prompt) > 75000:
        raise ValueError("Research prompt too large")
    headers = {"Content-Type": "application/json"}
    if provider == "claude":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        body = {"model": model, "max_tokens": 900, "system": instruction,
                "messages": [{"role": "user", "content": prompt}]}
    else:
        headers["Authorization"] = "Bearer " + key
        body = {"model": model,
                "messages": [{"role": "system", "content": instruction},
                             {"role": "user", "content": prompt}]}
        body["max_completion_tokens" if provider == "openai" else "max_tokens"] = 900
    req = Request(PROVIDERS[provider]["url"], data=json.dumps(body).encode("utf-8"),
                  headers=headers, method="POST")
    with opener(req, timeout=45) as response:
        raw = response.read(24001)
    if len(raw) > 24000:
        raise ValueError("Oversized model response")
    reply = json.loads(raw)
    if provider == "claude":
        text = "".join(b.get("text", "") for b in reply.get("content", [])
                       if b.get("type") == "text")
        usage = reply.get("usage", {})
        counts = (usage.get("input_tokens"), usage.get("output_tokens"))
    else:
        text = reply["choices"][0]["message"].get("content")
        usage = reply.get("usage", {})
        counts = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
    return parse_opinion(text), {
        "input_tokens": counts[0] if type(counts[0]) is int and 0 <= counts[0] < 100000000 else None,
        "output_tokens": counts[1] if type(counts[1]) is int and 0 <= counts[1] < 100000000 else None,
    }
