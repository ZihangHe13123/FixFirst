"""Smoke test: does each model return a well-formed tool call through the endpoint?

Usage: .venv/bin/python experiments/agent_baseline/toolcall_smoke.py MODEL[:think|:nothink] ...
Uses LLM_BASE_URL and LLM_API_KEY like agent_pilot.py.
"""

import json
import os
import sys
import time

import httpx

BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8123/v1")
_KEY = os.environ.get("LLM_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {_KEY}"} if _KEY else {}

TOOLS = [{
    "type": "function",
    "function": {
        "name": "run_command",
        "description": "Run a shell command in the project directory and return its output.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The command to run."}},
            "required": ["command"],
        },
    },
}]

MESSAGES = [
    {"role": "system", "content": "You are a coding agent working in a Python project. "
     "Use the tools to gather information; do not guess command output."},
    {"role": "user", "content": "The tests in this project fail. Start by running the test suite with pytest."},
]


def trial(model, thinking=None):
    body = {"model": model, "messages": MESSAGES, "tools": TOOLS, "max_tokens": 4096, "temperature": 0.2}
    if thinking is not None:
        body["chat_template_kwargs"] = {"enable_thinking": thinking}
    started = time.monotonic()
    r = httpx.post(f"{BASE}/chat/completions", json=body, headers=HEADERS, timeout=900)
    seconds = time.monotonic() - started
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    parsed = []
    for c in calls:
        try:
            parsed.append((c["function"]["name"], json.loads(c["function"]["arguments"])))
        except Exception as exc:  # malformed arguments
            parsed.append((c["function"].get("name"), f"BAD JSON: {exc}"))
    usage = data.get("usage", {})
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    return {
        "model": model, "thinking": thinking, "seconds": round(seconds, 1),
        "finish": data["choices"][0].get("finish_reason"),
        "tool_calls": parsed, "text": (msg.get("content") or "")[:160],
        "reasoning_chars": len(reasoning),
        "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
    }


if __name__ == "__main__":
    for spec in sys.argv[1:]:
        model, _, mode = spec.partition(":")
        thinking = {"think": True, "nothink": False}.get(mode)
        # The first call includes model loading; the second measures steady speed.
        for label in ("cold", "warm"):
            try:
                result = trial(model, thinking)
            except Exception as exc:
                result = {"model": model, "thinking": thinking, "error": repr(exc)[:300]}
            result["run"] = label
            print(json.dumps(result, ensure_ascii=False), flush=True)
