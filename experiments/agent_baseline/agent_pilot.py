"""Agent baseline: a model fixes generated FixFirst cases, with and without FixFirst.

Every arm gets the same system prompt and the same basic tools (run_command, read_file,
write_file, finish). Arms:
  baseline  basic tools only
  fixfirst  plus fixfirst_check (ff_tool.py, raw issue list) and a usage note: the 28 Sep pilot
  mcp       plus the tools of `fixfirst mcp`, spoken to over MCP stdio; the server's
            instructions are added to the system prompt, as MCP clients do
Every command, FixFirst check and grading run executes under macOS sandbox-exec: writes only
inside the case, no network.

Configuration (environment variables):
  LLM_BASE_URL            OpenAI-compatible endpoint (default http://127.0.0.1:8123/v1)
  LLM_API_KEY             bearer token for that endpoint (optional)
  FIXFIRST_TARGET_PYTHON  interpreter the cases run with (default: this repo's .venv)

Usage:
  .venv/bin/python experiments/agent_baseline/agent_pilot.py --model M \
      --cases pkg-inventory:lm_renamed flat-shop:lm_src_layout --arms baseline fixfirst
"""

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import httpx

from fixfirst import diagnosis_cases as dc

HERE = Path(__file__).resolve().parent
FIXFIRST = HERE.parents[1]
PYTHON = Path(os.environ.get("FIXFIRST_TARGET_PYTHON", str(FIXFIRST / ".venv" / "bin" / "python")))
BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8123/v1")
_KEY = os.environ.get("LLM_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {_KEY}"} if _KEY else {}
TMP = os.path.realpath(tempfile.gettempdir())
HOME = str(Path.home())
MAX_TURNS = 20
OUTPUT_LIMIT = 6000

SYSTEM = (
    "You are an autonomous coding agent. The Python project in your working directory has "
    "failing tests. Make the full test suite pass by fixing the root cause in the project. "
    "Do not edit, delete or skip tests. The machine is offline, so packages cannot be "
    "installed. Use the tools; do not guess what a command would print. When the full test "
    "suite passes, call finish with one sentence on the cause and the fix."
)

BASIC_TOOLS = [
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a bash command in the project directory (python and pytest are on PATH). Returns the exit code and output.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file in the project. Paths are relative to the project directory.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Replace the whole content of a file in the project (creates it if missing).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Call when the full test suite passes.",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}},
]

# What an MCP client adds to the system prompt from the server's "instructions" field.
FIXFIRST_INSTRUCTIONS = (
    "\n\nThe connected FixFirst server says: call fixfirst_check before changing anything, "
    "and call it again after each change to confirm the fix."
)

FIXFIRST_TOOL = {"type": "function", "function": {
    "name": "fixfirst_check",
    "description": (
        "Run FixFirst, a local troubleshooting tool. It runs the project's checks (environment, "
        "declared dependencies, pytest), diagnoses the root cause of each failure from evidence and "
        "a knowledge base of removed APIs, and ranks the next steps. Call it again after a change "
        "to see which problems are fixed."),
    "parameters": {"type": "object", "properties": {}}}}


def profile(case: Path, extra: list[Path] = ()) -> Path:
    writable = [case, *extra, Path(TMP)]
    rules = " ".join(f'(subpath "{p}")' for p in writable)
    text = (
        "(version 1)\n(allow default)\n(deny network*)\n"
        f'(deny file-read* (subpath "{HOME}/.ssh") (subpath "{HOME}/.omlx") (subpath "{HOME}/.claude") '
        f'(subpath "{HOME}/Library/Keychains"))\n'
        f'(deny file-write*)\n(allow file-write* {rules} (literal "/dev/null") (subpath "/dev/fd"))\n'
    )
    path = case.parent / f"{case.name}.sb"
    path.write_text(text)
    return path


def sandbox_env(case, home=None):
    return {"PATH": f"{PYTHON.parent}:/usr/bin:/bin", "HOME": str(home or case), "LANG": "en_US.UTF-8",
            "TMPDIR": TMP, "VIRTUAL_ENV": str(PYTHON.parent.parent), "PYTHONDONTWRITEBYTECODE": "1"}


class MCPClient:
    """Minimal MCP stdio client: starts `fixfirst mcp` in the sandbox and relays tool calls."""

    def __init__(self, case: Path, sb: Path, state_dir: Path):
        argv = ["sandbox-exec", "-f", str(sb), str(PYTHON), "-m", "fixfirst",
                "--store", str(state_dir / "store"), "mcp"]
        self.log = (state_dir / "mcp-server.log").open("w")
        self.proc = subprocess.Popen(argv, cwd=case, env=sandbox_env(case, state_dir), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1)
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.next_id = 0
        hello = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                            "clientInfo": {"name": "agent_pilot", "version": "1"}})
        self.instructions = hello.get("instructions", "")
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()
        self.tools = self.request("tools/list", {})["tools"]

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(line)

    def request(self, method, params, timeout=900):
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method,
                                          "params": params}) + "\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            answer = json.loads(self.lines.get(timeout=max(1, deadline - time.monotonic())))
            if answer.get("id") == self.next_id:
                if "error" in answer:
                    raise RuntimeError(answer["error"]["message"])
                return answer["result"]

    def openai_tools(self):
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["inputSchema"]}} for t in self.tools]

    def call(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(c.get("text", "") for c in result["content"] if c.get("type") == "text")
        return ("Error: " if result.get("isError") else "") + text

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
        self.log.close()


def sandboxed(case, argv, sb, timeout=180, home=None):
    env = sandbox_env(case, home)
    try:
        proc = subprocess.run(["sandbox-exec", "-f", str(sb), *argv], cwd=case, env=env,
                              capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return 124, f"(timed out after {timeout} s)"


def clip(text):
    return text if len(text) <= OUTPUT_LIMIT else "...(earlier output cut)...\n" + text[-OUTPUT_LIMIT:]


def inside(case: Path, path: str) -> Path | None:
    target = (case / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    return target if target == case or case in target.parents else None


def pytest_counts(output):
    counts = {}
    for number, word in re.findall(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)", output):
        counts[word.rstrip("s") if word.startswith("error") else word] = int(number)
    return counts


def build_case(root: Path, template: str, scenario: str, arm: str):
    t = next(x for x in dc.TEMPLATES if x.name == template)
    s = next(x for x in dc.SCENARIOS if x.scenario_id == scenario)
    pristine = root / "_templates" / template
    if not pristine.exists():
        dc.build_template(pristine, t)
    case = (root / f"{template}--{scenario}--{arm}").resolve()
    if case.exists():
        shutil.rmtree(case)
    shutil.copytree(pristine, case)
    s.apply(dc.Project(case, t, dc.TEMPLATES.index(t)))
    return pristine.resolve(), case, s.label


def test_files(case: Path):
    return {p.relative_to(case): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in case.rglob("test_*.py") if ".pytest_cache" not in p.parts}


def digest(case: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(case.rglob("*")):
        if p.is_file() and not {".pytest_cache", "__pycache__"} & set(p.parts):
            h.update(str(p.relative_to(case)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def is_green(case, generated, before_tests, expected):
    """Grade a copy of the project against the original tests, without touching the case."""
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        copy = Path(tmp) / "c"
        shutil.copytree(case, copy, ignore=shutil.ignore_patterns(".pytest_cache", "__pycache__"))
        for rel in before_tests:
            shutil.copy2(generated / rel, copy / rel)
        code, output = sandboxed(copy, [str(PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                 profile(copy))
        counts = pytest_counts(output)
        return code == 0 and counts.get("passed") == expected and not counts.get("skipped")


def episode(model, arm, case, log, green):
    state_dir = case.parent / f"{case.name}.state"
    state_dir.mkdir(exist_ok=True)
    sb = profile(case, [state_dir])
    mcp = MCPClient(case, sb, state_dir) if arm == "mcp" else None
    try:
        return _episode(model, arm, case, log, green, sb, state_dir, mcp)
    finally:
        if mcp:
            mcp.close()


def _episode(model, arm, case, log, green, sb, state_dir, mcp):
    tools = BASIC_TOOLS + ([FIXFIRST_TOOL] if arm == "fixfirst" else []) + (mcp.openai_tools() if mcp else [])
    system = SYSTEM + (FIXFIRST_INSTRUCTIONS if arm == "fixfirst" else "")
    if mcp and mcp.instructions:
        system += "\n\n" + mcp.instructions  # what an MCP client adds from the server
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"The project is in {case}. Its tests fail. Fix it."}]
    stats = {"turns": 0, "tool_calls": 0, "pytest_runs": 0, "fixfirst_calls": 0, "prompt_tokens": 0,
             "completion_tokens": 0, "model_s": 0.0, "tool_s": 0.0, "end": "turn_cap", "bad_calls": 0,
             "first_green_turn": None}
    last = digest(case)
    for _ in range(MAX_TURNS):
        body = {"model": model, "messages": messages, "tools": tools, "max_tokens": 4096, "temperature": 0.2}
        started = time.monotonic()
        response = httpx.post(f"{BASE}/chat/completions", json=body, headers=HEADERS, timeout=1200)
        stats["model_s"] += time.monotonic() - started
        response.raise_for_status()
        data = response.json()
        stats["turns"] += 1
        usage = data.get("usage") or {}
        stats["prompt_tokens"] += usage.get("prompt_tokens") or 0
        stats["completion_tokens"] += usage.get("completion_tokens") or 0
        message = data["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        assistant = {"role": "assistant", "content": message.get("content") or ""}
        if calls:
            assistant["tool_calls"] = calls
        messages.append(assistant)
        if not calls:
            stats["end"] = "stopped_without_tool"
            break
        finished = False
        for call in calls:
            stats["tool_calls"] += 1
            name = call["function"]["name"]
            started = time.monotonic()
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
                result = run_tool(name, args, case, sb, state_dir, stats, mcp)
            except Exception as exc:
                stats["bad_calls"] += 1
                result = f"error: {exc}"
            stats["tool_s"] += time.monotonic() - started
            messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": result})
            finished = finished or name == "finish"
        current = digest(case)
        if current != last:
            last = current
            if stats["first_green_turn"] is None and green():
                stats["first_green_turn"] = stats["turns"]
        if finished:
            stats["end"] = "finish"
            break
    log.write_text(json.dumps(messages, ensure_ascii=False, indent=1))
    return stats


def run_tool(name, args, case, sb, state_dir, stats, mcp=None):
    if mcp and name in {t["name"] for t in mcp.tools}:
        stats["fixfirst_calls"] += 1
        return clip(mcp.call(name, args))
    if name == "run_command":
        command = args["command"]
        if "pytest" in command:
            stats["pytest_runs"] += 1
        code, output = sandboxed(case, ["/bin/bash", "-c", command], sb)
        return f"exit code {code}\n{clip(output)}"
    if name == "read_file":
        target = inside(case, args["path"])
        if not target or not target.is_file():
            return "error: no such file in the project"
        return clip(target.read_text(encoding="utf-8", errors="replace"))
    if name == "write_file":
        target = inside(case, args["path"])
        if not target:
            return "error: path is outside the project"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args["content"], encoding="utf-8")
        return f"wrote {len(args['content'])} characters to {target.relative_to(case)}"
    if name == "fixfirst_check":
        stats["fixfirst_calls"] += 1
        code, output = sandboxed(case, [str(PYTHON), str(HERE / "ff_tool.py"), str(case),
                                        str(state_dir / "session.json"), str(PYTHON)], sb, timeout=600,
                                 home=state_dir)
        return clip(output) if code == 0 else f"fixfirst failed (exit {code}):\n{clip(output)}"
    if name == "finish":
        return "ok"
    return f"error: unknown tool {name}"


def grade(case, before_tests, generated: Path, expected):
    changed = [str(p) for p, digest_ in test_files(case).items() if before_tests.get(p) != digest_]
    for rel in before_tests:  # judge against the original tests
        shutil.copy2(generated / rel, case / rel)
    sb = profile(case)
    code, output = sandboxed(case, [str(PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider"], sb)
    counts = pytest_counts(output)
    passed = code == 0 and counts.get("passed") == expected and not counts.get("skipped")
    return {"fixed": passed, "tests_changed": changed, "grader_counts": counts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", nargs="+", required=True, help="template:scenario, e.g. flat-shop:lm_src_layout")
    parser.add_argument("--arms", nargs="+", default=["baseline", "mcp"],
                        choices=["baseline", "fixfirst", "mcp"])
    parser.add_argument("--out", default=str(FIXFIRST / "workbench" / "agent_baseline"))
    args = parser.parse_args()
    root = Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for spec in args.cases:
        template, scenario = spec.split(":")
        for arm in args.arms:
            pristine, case, label = build_case(root, template, scenario, arm)
            code, output = sandboxed(pristine, [str(PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                     profile(pristine))
            expected = pytest_counts(output).get("passed")
            generated = root / "_generated" / case.name
            if generated.exists():
                shutil.rmtree(generated)
            shutil.copytree(case, generated)
            before = test_files(case)
            started = time.monotonic()
            log = root / f"{case.name}--{args.model}.json"
            stats = episode(args.model, arm, case, log,
                            lambda: is_green(case, generated, before, expected))
            stats["total_s"] = round(time.monotonic() - started, 1)
            stats.update(grade(case, before, generated, expected))
            row = {"model": args.model, "case": f"{template}:{scenario}", "cause": label, "arm": arm,
                   "expected_tests": expected, **{k: round(v, 1) if isinstance(v, float) else v for k, v in stats.items()}}
            print(json.dumps(row, ensure_ascii=False), flush=True)
            with (root / "results.jsonl").open("a") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
