"""Agent baseline (task B7): a model fixes failing projects, with and without FixFirst.

Cases:
  generated  --cases template:scenario: projects built by diagnosis_cases.py. They run with this
             repository's .venv, offline, as in the 28 Sep pilot.
  real       --projects ID ...: projects from a manifest (default examples/real-world/projects.toml).
             Every run exports the project from a fixed commit of its source clone (--sources) and
             rebuilds its own .venv from the recorded snapshot (real_cases.py). The grader's reference
             outcome comes from applying the known repair in --repairs to a separate copy.
Arms (same system prompt, basic tools, model settings, budget, network condition and grader):
  baseline   run_command, read_file, write_file, finish
  mcp        plus the tools of `fixfirst mcp`, spoken to over MCP stdio; the server's instructions
             are added to the system prompt, as MCP clients do. Its diagnosis always targets the
             case's project and interpreter, whatever the model passes.
  fixfirst   the 28 Sep pilot's raw tool (ff_tool.py), generated cases only, kept to repeat the pilot
Isolation: every command, FixFirst check and grading run of a real case uses the case's own
interpreter in an environment without inherited Python, pytest or application variables. Commands
run under macOS sandbox-exec: writes only inside the project, the run's state folder and the temp
folder. --network on (the B7 condition) allows the network so packages can be installed; reading
under the home folder is then limited to the run, this repository and the interpreters.
Recorded per run (results.jsonl and the run folder): source commit, pip freeze at start and end,
every command with exit code and duration, settings and seed, time and tokens, how the run ended
(finish, turn or time cap, a model error, setup failure) and the grader's verdict with reasons.
Arms alternate per case and run. --model fake:SCRIPT.json replays scripted tool calls instead of
asking a model, to check the harness.

Configuration (environment variables):
  LLM_BASE_URL            OpenAI-compatible endpoint (default http://127.0.0.1:8123/v1)
  LLM_API_KEY             bearer token for that endpoint (optional)
  FIXFIRST_TARGET_PYTHON  interpreter the generated cases run with (default: this repo's .venv)

Usage:
  .venv/bin/python experiments/agent_baseline/agent_pilot.py --model M \
      --cases pkg-inventory:lm_renamed flat-shop:lm_src_layout --arms baseline mcp
  .venv/bin/python experiments/agent_baseline/agent_pilot.py --model M --projects cachetools \
      --sources ../test-projects/generalisation --network on --max-turns 12 --run-timeout 900
"""

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

from fixfirst import diagnosis_cases as dc

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import real_cases as rc  # noqa: E402

FIXFIRST = HERE.parents[1]
PYTHON = Path(os.environ.get("FIXFIRST_TARGET_PYTHON", str(FIXFIRST / ".venv" / "bin" / "python")))
BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8123/v1")
_KEY = os.environ.get("LLM_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {_KEY}"} if _KEY else {}
TMP = os.path.realpath(tempfile.gettempdir())
HOME = str(Path.home())
OUTPUT_LIMIT = 6000
SENSITIVE = (".ssh", ".omlx", ".claude", "Library/Keychains")
INSTALL = re.compile(r"\b(pip|uv)\b.*\b(install|uninstall)\b")


def system_prompt(network: bool) -> str:
    packages = ("You may install, upgrade or remove packages with `python -m pip`; the machine is online."
                if network else "The machine is offline, so packages cannot be installed.")
    return (
        "You are an autonomous coding agent. The Python project in your working directory has "
        "failing tests. Make the full test suite pass by fixing the root cause in the project. "
        f"Do not edit, delete or skip tests. {packages} Use the tools; do not guess what a command "
        "would print. When the full test suite passes, call finish with one sentence on the cause and the fix."
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


@dataclass
class Settings:
    max_turns: int = 20
    run_timeout: int = 1800
    temperature: float = 0.2
    max_tokens: int = 4096
    seed: int = 20261001


@dataclass
class Workspace:
    """Where one run happens and with what: the same interpreter for every command, FixFirst's
    diagnosis target and the grader."""
    case: Path
    python: Path
    state: Path
    sb: Path
    network: bool = False
    home: Path | None = None  # HOME for commands; None keeps the pilot's (the case folder)
    real: bool = False
    commands: list = field(default_factory=list)


def profile(case: Path, extra: list[Path] = (), network: bool = False, readable: list[Path] | None = None) -> Path:
    writable = [case, *extra, Path(TMP)]
    rules = " ".join(f'(subpath "{p}")' for p in writable)
    text = "(version 1)\n(allow default)\n"
    if not network:
        text += "(deny network*)\n"
    if readable is not None:  # with the network on, nothing else under the home folder can be read
        text += f'(deny file-read-data (subpath "{HOME}"))\n'
        text += "(allow file-read-data " + " ".join(f'(subpath "{p}")' for p in readable) + ")\n"
    text += "(deny file-read* " + " ".join(f'(subpath "{HOME}/{p}")' for p in SENSITIVE) + ")\n"
    text += f'(deny file-write*)\n(allow file-write* {rules} (literal "/dev/null") (subpath "/dev/fd"))\n'
    path = case.parent / f"{case.name}.sb"
    path.write_text(text)
    return path


def sandbox_env(case, home=None, python=None):
    python = python or PYTHON
    return {"PATH": f"{python.parent}:/usr/bin:/bin", "HOME": str(home or case), "LANG": "en_US.UTF-8",
            "TMPDIR": TMP, "VIRTUAL_ENV": str(python.parent.parent), "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}


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


def sandboxed(case, argv, sb, timeout=180, home=None, python=None):
    env = sandbox_env(case, home, python)
    try:
        proc = subprocess.run(["sandbox-exec", "-f", str(sb), *argv], cwd=case, env=env,
                              capture_output=True, text=True, errors="replace", timeout=timeout)
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


# ---- Models ------------------------------------------------------------------------------------

class ModelError(Exception):
    """The model endpoint did not answer with a message."""


class FakeModel:
    """Scripted replies, to check the harness without a model. The script is a JSON list; each step
    is {"call": name, "arguments": {...}}, {"calls": [...]} for several, {"say": text} for an answer
    without a tool call, or {"fail": text} for a failed request."""

    def __init__(self, path: Path):
        self.steps = json.loads(Path(path).read_text(encoding="utf-8"))
        self.index = 0

    def reply(self):
        if self.index >= len(self.steps):
            return {"content": "(script finished)"}, {}
        step = self.steps[self.index]
        self.index += 1
        if "fail" in step:
            raise ModelError(step["fail"])
        if "say" in step:
            return {"content": step["say"]}, {}
        calls = step.get("calls") or [step]
        return {"content": "", "tool_calls": [
            {"id": f"call-{self.index}-{n}", "type": "function",
             "function": {"name": c["call"], "arguments": json.dumps(c.get("arguments", {}))}}
            for n, c in enumerate(calls)]}, {}


def chat(model, messages, tools, settings: Settings, fake: FakeModel | None):
    if fake:
        return fake.reply()
    body = {"model": model, "messages": messages, "tools": tools, "max_tokens": settings.max_tokens,
            "temperature": settings.temperature, "seed": settings.seed}
    response = httpx.post(f"{BASE}/chat/completions", json=body, headers=HEADERS, timeout=1200)
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict) \
            or not isinstance(choices[0].get("message"), dict):
        raise ModelError("the response has no message")
    return choices[0]["message"], data.get("usage") or {}


# ---- Generated cases (the 28 Sep pilot) ------------------------------------------------------------

def build_case(root: Path, template: str, scenario: str, arm: str, suffix: str = ""):
    t = next(x for x in dc.TEMPLATES if x.name == template)
    s = next(x for x in dc.SCENARIOS if x.scenario_id == scenario)
    pristine = root / "_templates" / template
    if not pristine.exists():
        dc.build_template(pristine, t)
    case = (root / f"{template}--{scenario}--{arm}{suffix}").resolve()
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
    """Would the project pass now, with its tests untouched? Graded on a copy."""
    if any(before_tests.get(p) != d for p, d in test_files(case).items()) or set(test_files(case)) != set(before_tests):
        return False
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        copy = Path(tmp) / "c"
        shutil.copytree(case, copy, ignore=shutil.ignore_patterns(".pytest_cache", "__pycache__"))
        code, output = sandboxed(copy, [str(PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                 profile(copy))
        counts = pytest_counts(output)
        return code == 0 and counts.get("passed") == expected and not counts.get("skipped")


def grade(case, before_tests, generated: Path, expected):
    """Fixed only when the tests were left alone and the original tests pass. Passing once the
    original tests are put back is recorded separately and never counts as untouched tests."""
    after = test_files(case)
    changed = sorted(str(p) for p in set(before_tests) | set(after) if before_tests.get(p) != after.get(p))
    for rel in before_tests:  # judge against the original tests
        shutil.copy2(generated / rel, case / rel)
    sb = profile(case)
    code, output = sandboxed(case, [str(PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider"], sb)
    counts = pytest_counts(output)
    passes = code == 0 and counts.get("passed") == expected and not counts.get("skipped")
    reasons = ([f"tests changed: {', '.join(changed)}"] if changed else []) + \
        ([] if passes else [f"the original tests do not pass ({counts})"])
    return {"fixed": passes and not changed, "passes_with_original_tests": passes, "tests_changed": changed,
            "grader_counts": counts, "reasons": reasons}


# ---- The episode --------------------------------------------------------------------------------

def episode(model, arm, ws: Workspace, log: Path, green, settings: Settings, fake=None, state_digest=None):
    mcp = MCPClient(ws.case, ws.sb, ws.state) if arm == "mcp" else None
    try:
        return _episode(model, arm, ws, log, green, settings, fake, mcp, state_digest or (lambda: digest(ws.case)))
    finally:
        if mcp:
            mcp.close()


def _episode(model, arm, ws: Workspace, log, green, settings, fake, mcp, state_digest):
    tools = BASIC_TOOLS + ([FIXFIRST_TOOL] if arm == "fixfirst" else []) + (mcp.openai_tools() if mcp else [])
    system = system_prompt(ws.network) + (FIXFIRST_INSTRUCTIONS if arm == "fixfirst" else "")
    if mcp and mcp.instructions:
        system += "\n\n" + mcp.instructions  # what an MCP client adds from the server
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"The project is in {ws.case}. Its tests fail. Fix it."}]
    stats = {"turns": 0, "tool_calls": 0, "pytest_runs": 0, "fixfirst_calls": 0, "prompt_tokens": 0,
             "completion_tokens": 0, "model_s": 0.0, "tool_s": 0.0, "end": "turn_cap", "bad_calls": 0,
             "first_green_turn": None, "error": None, "mcp_arguments_filled": 0, "mcp_arguments_overridden": 0}
    deadline = time.monotonic() + settings.run_timeout
    last = state_digest()
    for _ in range(settings.max_turns):
        if time.monotonic() > deadline:
            stats["end"] = "time_cap"
            break
        started = time.monotonic()
        try:
            message, usage = chat(model, messages, tools, settings, fake)
        except (httpx.HTTPError, ValueError, ModelError) as error:
            stats["model_s"] += time.monotonic() - started
            stats["end"], stats["error"] = "model_error", f"{type(error).__name__}: {error}"[:500]
            break
        stats["model_s"] += time.monotonic() - started
        stats["turns"] += 1
        stats["prompt_tokens"] += usage.get("prompt_tokens") or 0
        stats["completion_tokens"] += usage.get("completion_tokens") or 0
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
                result = run_tool(name, args, ws, stats, mcp)
            except Exception as exc:
                stats["bad_calls"] += 1
                result = f"error: {exc}"
            stats["tool_s"] += time.monotonic() - started
            messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": result})
            finished = finished or name == "finish"
        current = state_digest()
        if current != last:
            last = current
            if stats["first_green_turn"] is None and green():
                stats["first_green_turn"] = stats["turns"]
        if finished:
            stats["end"] = "finish"
            break
    log.write_text(json.dumps(messages, ensure_ascii=False, indent=1))
    return stats


def run_tool(name, args, ws: Workspace, stats, mcp=None):
    if mcp and name in {t["name"] for t in mcp.tools}:
        stats["fixfirst_calls"] += 1
        if name == "diagnose" and ws.real:
            # The case's project and interpreter, whatever the model passed: a missing value is
            # filled in, a different one is overridden.
            forced = {"project": str(ws.case), "python": str(ws.python)}
            for key, value in forced.items():
                given = args.get(key)
                if not given:
                    stats["mcp_arguments_filled"] += 1
                elif os.path.abspath(ws.case / str(given)) != value:
                    stats["mcp_arguments_overridden"] += 1
            args = {**args, **forced}
        return clip(mcp.call(name, args))
    if name == "run_command":
        command = args["command"]
        if "pytest" in command:
            stats["pytest_runs"] += 1
        started = time.monotonic()
        code, output = sandboxed(ws.case, ["/bin/bash", "-c", command], ws.sb, timeout=600 if ws.network else 180,
                                 home=ws.home, python=ws.python)
        ws.commands.append({"turn": stats["turns"], "command": command, "exit_code": code,
                            "seconds": round(time.monotonic() - started, 1), "install": bool(INSTALL.search(command))})
        return f"exit code {code}\n{clip(output)}"
    if name == "read_file":
        target = inside(ws.case, args["path"])
        if not target or not target.is_file():
            return "error: no such file in the project"
        return clip(target.read_text(encoding="utf-8", errors="replace"))
    if name == "write_file":
        target = inside(ws.case, args["path"])
        if not target:
            return "error: path is outside the project"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args["content"], encoding="utf-8")
        return f"wrote {len(args['content'])} characters to {target.relative_to(ws.case)}"
    if name == "fixfirst_check":
        stats["fixfirst_calls"] += 1
        code, output = sandboxed(ws.case, [str(PYTHON), str(HERE / "ff_tool.py"), str(ws.case),
                                           str(ws.state / "session.json"), str(PYTHON)], ws.sb, timeout=600,
                                 home=ws.state)
        return clip(output) if code == 0 else f"fixfirst failed (exit {code}):\n{clip(output)}"
    if name == "finish":
        return "ok"
    return f"error: unknown tool {name}"


# ---- Real projects ------------------------------------------------------------------------------

def redact(text: str) -> str:
    for path, name in ((FIXFIRST.as_uri(), "file://<repo>"), (str(FIXFIRST), "<repo>"), (TMP, "<tmp>"),
                       (Path(HOME).as_uri(), "file://<home>"), (HOME, "<home>")):
        text = text.replace(path, name)
    return text


def base_prefix(python: Path) -> Path:
    return Path(subprocess.run([str(python), "-c", "import sys; print(sys.base_prefix)"],
                               capture_output=True, text=True).stdout.strip())


def load_repairs(path: Path) -> dict:
    return rc.tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def reference_outcome(root: Path, project: dict, source: Path, commit: str, snapshot: Path, repair: list[str]) -> dict:
    """The test outcome after the known repair, on a separate copy; cached per commit, snapshot and repair."""
    key = hashlib.sha256(json.dumps([commit, snapshot.read_text(encoding="utf-8"), repair]).encode()).hexdigest()
    cached = root / "_reference" / f"{project['id']}.json"
    if cached.exists():
        data = json.loads(cached.read_text(encoding="utf-8"))
        if data.get("key") == key:
            return data
    folder = root / "_reference" / project["id"]
    if folder.exists():
        shutil.rmtree(folder)
    project_dir, state = folder / "project", folder / "state"
    state.mkdir(parents=True)
    rc.export_source(source, commit, project_dir)
    python = rc.build_environment(project_dir, project, snapshot, [])
    steps = []
    for command in repair:
        result = rc.run(["/bin/bash", "-c", command], cwd=project_dir, env=rc.clean_env(python, state))
        steps.append({"command": command, "exit_code": result.returncode})
    suite = rc.run_suite(project_dir, python, state)
    data = {"key": key, "commit": commit, "repair": steps, "exit_code": suite["exit_code"], "counts": suite["counts"],
            "summary": suite["summary"], "outcomes": suite["outcomes"]}
    cached.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return data


def file_hashes(project_dir: Path) -> dict:
    return {p.relative_to(project_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in rc._walk(project_dir)}


def run_real(args, settings, project, source, snapshot, reference, arm, run_index, fake_path):
    root = Path(args.out).resolve()
    run_dir = root / f"{project['id']}--{arm}--r{run_index}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    project_dir, state = run_dir / "project", run_dir / "state"
    state.mkdir(parents=True)
    commit = rc.source_commit(source)
    row = {"model": args.model, "case": project["id"], "kind": "real", "arm": arm, "commit": commit,
           "network": args.network, "settings": vars(settings)}
    setup_log = []
    try:
        rc.export_source(source, commit, project_dir)
        python = rc.build_environment(project_dir, project, snapshot, setup_log)
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        (run_dir / "setup.json").write_text(json.dumps(setup_log, indent=1), encoding="utf-8")
        row.update(end="setup_failed", error=str(error)[:500], fixed=False)
        return row
    (run_dir / "setup.json").write_text(json.dumps(setup_log, indent=1), encoding="utf-8")
    start = rc.freeze(python)
    (run_dir / "freeze-start.txt").write_text("\n".join(start) + "\n", encoding="utf-8")
    before, files_before = rc.integrity(project_dir), file_hashes(project_dir)
    network = args.network == "on"
    readable = [run_dir, FIXFIRST, base_prefix(PYTHON), base_prefix(python)] if network else None
    ws = Workspace(project_dir, python, state, profile(project_dir, [state], network, readable), network,
                   home=state, real=True)
    row.update(python=subprocess.run([str(python), "-c", "import sys; print(sys.version.split()[0])"],
                                     capture_output=True, text=True).stdout.strip(),
               snapshot_mismatch=rc.snapshot_mismatch(snapshot, start),
               start_digest=rc.workspace_digest(project_dir, python)[:16])

    def green():
        if rc.changed(before, rc.integrity(project_dir)):
            return False
        return rc.judge(rc.run_suite(project_dir, python, state), reference, [])["fixed"]

    started = time.monotonic()
    fake = FakeModel(fake_path) if fake_path else None
    stats = episode(args.model, arm, ws, run_dir / "transcript.json", green, settings, fake,
                    lambda: rc.workspace_digest(project_dir, python))
    stats["total_s"] = round(time.monotonic() - started, 1)
    end = rc.freeze(python)
    (run_dir / "freeze-end.txt").write_text("\n".join(end) + "\n", encoding="utf-8")
    with (run_dir / "commands.jsonl").open("w", encoding="utf-8") as stream:
        for command in ws.commands:
            stream.write(json.dumps(command, ensure_ascii=False) + "\n")
    tests_changed = rc.changed(before, rc.integrity(project_dir))
    verdict = rc.judge(rc.run_suite(project_dir, python, state), reference, tests_changed)
    files_after = file_hashes(project_dir)
    row.update({k: round(v, 1) if isinstance(v, float) else v for k, v in stats.items()})
    row.update(fixed=verdict["fixed"], reasons=verdict["reasons"], grader_counts=verdict["counts"],
               reference_counts=verdict["reference_counts"], tests_changed=tests_changed,
               files_changed=rc.changed(files_before, files_after), packages=rc.freeze_difference(start, end),
               commands=len(ws.commands), install_commands=sum(c["install"] for c in ws.commands))
    return row


def run_generated(args, settings, spec, arm, run_index, fake_path):
    root = Path(args.out).resolve()
    template, scenario = spec.split(":")
    suffix = f"--r{run_index}" if args.runs > 1 else ""
    pristine, case, label = build_case(root, template, scenario, arm, suffix)
    code, output = sandboxed(pristine, [str(PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                             profile(pristine))
    expected = pytest_counts(output).get("passed")
    generated = root / "_generated" / case.name
    if generated.exists():
        shutil.rmtree(generated)
    shutil.copytree(case, generated)
    before = test_files(case)
    state = case.parent / f"{case.name}.state"
    state.mkdir(exist_ok=True)
    ws = Workspace(case, PYTHON, state, profile(case, [state]))
    started = time.monotonic()
    fake = FakeModel(fake_path) if fake_path else None
    stats = episode(args.model, arm, ws, root / f"{case.name}--{Path(args.model).name}.json",
                    lambda: is_green(case, generated, before, expected), settings, fake)
    stats["total_s"] = round(time.monotonic() - started, 1)
    stats.update(grade(case, before, generated, expected))
    return {"model": args.model, "case": spec, "kind": "generated", "cause": label, "arm": arm,
            "expected_tests": expected, "network": "off",
            **{k: round(v, 1) if isinstance(v, float) else v for k, v in stats.items()}}


def arm_order(arms: list[str], case_index: int, run_index: int) -> list[str]:
    """Alternate which arm goes first, per case and run."""
    return list(arms) if (case_index + run_index) % 2 == 0 else list(reversed(arms))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="model name, or fake:SCRIPT.json")
    parser.add_argument("--cases", nargs="*", default=[], help="generated: template:scenario")
    parser.add_argument("--projects", nargs="*", default=[], help="real projects from the manifest")
    parser.add_argument("--manifest", default=str(FIXFIRST / "examples" / "real-world" / "projects.toml"))
    parser.add_argument("--sources", default=str(FIXFIRST / "workbench" / "agent_baseline" / "_sources"),
                        help="folder with a git clone of each project at its release")
    parser.add_argument("--repairs", default=str(HERE / "reference_repairs.toml"),
                        help="known repairs, used only to compute the grader's reference outcome")
    parser.add_argument("--arms", nargs="+", default=["baseline", "mcp"], choices=["baseline", "fixfirst", "mcp"])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--network", choices=["off", "on"], default="off")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--run-timeout", type=int, default=1800, help="seconds per run")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--out", default=str(FIXFIRST / "workbench" / "agent_baseline"))
    args = parser.parse_args(argv)
    if not args.cases and not args.projects:
        parser.error("give --cases or --projects")
    if args.projects and "fixfirst" in args.arms:
        parser.error("the fixfirst arm is only for the generated cases of the 28 Sep pilot")
    settings = Settings(args.max_turns, args.run_timeout, args.temperature, args.max_tokens, args.seed)
    fake_path = Path(args.model.split(":", 1)[1]) if args.model.startswith("fake:") else None
    root = Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest).resolve()
    manifest = rc.load_manifest(manifest_path) if args.projects else {}
    repairs = load_repairs(Path(args.repairs))
    harness = subprocess.run(["git", "rev-parse", "HEAD"], cwd=FIXFIRST, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "experiments/agent_baseline"], cwd=FIXFIRST,
                           capture_output=True, text=True).stdout.split("\n")
    work = [("generated", spec) for spec in args.cases] + [("real", pid) for pid in args.projects]
    for case_index, (kind, name) in enumerate(work):
        if kind == "real":
            project = manifest[name]
            source = Path(args.sources).resolve() / name
            snapshot = manifest_path.parent / "environments" / f"{name}.txt"
            if name not in repairs:
                raise SystemExit(f"{name}: no known repair in {args.repairs}; the grader needs a reference")
            reference = reference_outcome(root, project, source, rc.source_commit(source), snapshot,
                                          repairs[name]["repair"])
        for run_index in range(1, args.runs + 1):
            for order, arm in enumerate(arm_order(args.arms, case_index, run_index - 1), start=1):
                if kind == "real":
                    row = run_real(args, settings, project, source, snapshot, reference, arm, run_index, fake_path)
                else:
                    row = run_generated(args, settings, name, arm, run_index, fake_path)
                row.update(run=run_index, order=order, seed=args.seed, harness_commit=harness,
                           uncommitted_changes=[line for line in dirty if line.strip()])
                text = redact(json.dumps(row, ensure_ascii=False))
                print(text, flush=True)
                with (root / "results.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(text + "\n")


if __name__ == "__main__":
    main()
