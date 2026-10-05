"""Agent baseline (task B7): a model fixes failing projects, with and without FixFirst.

Cases:
  generated  --cases template:scenario: projects built by diagnosis_cases.py, run offline with this
             repository's .venv as in the 28 Sep pilot. Their reference is the healthy template;
             scenarios that change test files or pytest settings have none and are refused.
  hard       the same option with a scenario of hard_cases.py. Its start may add exactly the check
             registered in hard_cases.toml; its reference is the start with the registered repair (see
             hard_instances.py). With --hard-selection only the instances frozen for --hard-role run,
             and only while their content is the frozen one.
Answers (--repairs, --sources, --hard-selection) must lie where no run's sandbox reads: inside the home
folder, the repository or a system temporary folder, and sharing no path with what a sandbox is given
(the output folder, FixFirst's code and environment, the interpreters, the tools); otherwise nothing is
run. The repairs and the selection are also denied by name in every sandbox, the source clones with
everything below them.
  real       --projects ID ...: projects from a manifest (default examples/real-world/projects.toml).
             Every run exports the project from a fixed commit of its source clone (--sources) and
             rebuilds its own .venv from the recorded snapshot; the reference comes from applying the
             known repair in --repairs to a separate copy, and must itself pass cleanly.
Arms (same system prompt, basic tools, model settings, budget, network condition and grader):
  baseline   run_command, read_file, write_file, finish
  mcp        plus the tools of `fixfirst mcp` over MCP stdio, its instructions added to the system
             prompt as MCP clients do; its diagnosis always targets the case's project and interpreter
  fixfirst   the 28 Sep pilot's raw tool (ff_tool.py), generated cases only
Isolation (isolation.py): everything that runs a case's code (the agent's commands, FixFirst's server
and its checks, installing the project, the grader, the reference) runs under macOS sandbox-exec. It
writes only to the run's own folders (or the grader's copy), reads under the home folder, the output
folder, the repository and the system temporary folders only the run's folders and the interpreters
(FixFirst's server also its code), and has the network only for the agent and installs when
--network on. The grader is always offline. Commands, pytest, FixFirst's diagnosis target and the
grader use the case's interpreter with nothing inherited from the harness's environment.
Time: --run-timeout is the agent's budget; model requests, every tool call and every process get only
what is left, and processes are killed as a whole tree at the deadline. The harness's own checks do
not count against it. Nothing the model asks for after the deadline is carried out.
Integrity: after every tool call the harness compares test files, conftest.py and test-selecting pytest
settings with the start; a change is recorded with its turn and stays recorded even if undone later.
It sees the state between tool calls, not every write inside one command.
Records (never overwritten): each run has its own folder, runs/<case>--<arm>--r<n>--<model>--<attempt>,
with the transcript and commands written as they happen, pip freeze at start and end, the setup log
and the row. results.jsonl gets one row per run, also when setup, the model, the harness or the grader
fails; `end`, `error` and `grading` say what happened. Arms alternate per case and run.
--model fake:SCRIPT.json replays scripted replies instead of asking a model, to check the harness.

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
import traceback
from pathlib import Path
from xml.etree.ElementTree import ParseError

import httpx

from fixfirst import diagnosis_cases as dc
from fixfirst.facts import TOP_LEVEL_KEYS as FACTS_KEYS
from fixfirst.storage import Store

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hard_instances as hi  # noqa: E402
import isolation as iso  # noqa: E402
import real_cases as rc  # noqa: E402
import pytest_policy as pp  # noqa: E402

FIXFIRST = HERE.parents[1]
PYTHON = Path(os.environ.get("FIXFIRST_TARGET_PYTHON", str(FIXFIRST / ".venv" / "bin" / "python")))
BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8123/v1")
_KEY = os.environ.get("LLM_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {_KEY}"} if _KEY else {}
TMP = os.path.realpath(tempfile.gettempdir())
INSTALL_SECONDS = 900  # each install or repair step of a real case
GRADING_GOAL = "pass_tests"  # FixFirst checks what the grader checks: the full test suite, with pytest
HOME = str(Path.home())
OUTPUT_LIMIT = 6000
COMMAND_CAP = {True: 600, False: 180}  # seconds per command, with and without the network
INSTALL = re.compile(r"\b(pip|uv)\b.*\b(install|uninstall)\b")
PYTEST_FILES = ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg", "conftest.py")


def system_prompt(network: bool, grading_policy=pp.LEGACY) -> str:
    packages = ("You may install, upgrade or remove packages with `python -m pip`; the machine is online."
                if network else "The machine is offline, so packages cannot be installed.")
    return (
        "You are an autonomous coding agent. The Python project in your working directory has "
        "failing tests. Make the full test suite pass by fixing the root cause in the project. "
        f"Do not edit, delete or skip tests. {packages} Use the tools; do not guess what a command "
        "would print. When the full test suite passes, call finish with one sentence on the cause and the fix."
    ) + (pp.PROMPT if grading_policy == pp.H5 else "")


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

# Arms with FixFirst over MCP: the tool called first, and the one called after a change.
FIXFIRST_ARMS = {"facts": ("observe", "observe"), "mcp": ("diagnose", "check_again")}
# How the FixFirst arms call it. server: the tools and the server's own instructions, as an MCP
# client would add them (B7's protocol). scheduled: the harness calls FixFirst before the first
# turn and after every turn that changed the project, the same way in both FixFirst arms, and the
# model gets the report (not the tools). required: the tools, and the same instruction to call them
# in both arms. on_demand: the tools, and only that they are available.
CALL_POLICIES = ("server", "scheduled", "required", "on_demand")

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
    run_timeout: float = 1800
    temperature: float = 0.2
    max_tokens: int = 4096
    seed: int = 20261001
    call_policy: str = "server"


class ModelError(Exception):
    """The model endpoint did not answer with a usable message."""


class ModelTimeout(ModelError):
    """The model did not answer before the run's time was up."""


class ToolTimeout(Exception):
    """A tool call reached the run's deadline and was stopped."""


class SetupError(Exception):
    """The case could not be prepared; nothing was run or graded."""


def interpreters(venv: Path) -> tuple:
    """The folders an environment's interpreter reads, from its pyvenv.cfg (the interpreter is not run)."""
    return (venv, *map(Path, rc.venv_record(venv)["interpreters"]))


def fixfirst_readable() -> tuple:
    """What FixFirst's own server needs to read: its code and its environment, not the rest of the repository."""
    return (FIXFIRST / "src", *interpreters(PYTHON.parent.parent))


def harness_readable() -> tuple:
    """What a policy may let a sandbox read besides a run's own folders, known before any case is prepared:
    FixFirst's code, its environment and that environment's interpreter (the generated cases run in it
    too), the 28 Sep tool, and uv for installing a real project. A real project's own environment lies in
    its run folder; the interpreter it was made from is known only once it exists, and Context.check holds
    the run's sandbox against the answers then."""
    uv = shutil.which("uv")
    return (*fixfirst_readable(), HERE / "ff_tool.py", *((Path(os.path.realpath(uv)),) if uv else ()))


@dataclass
class Context:
    """One invocation: where runs go, which attempt this is, what is denied to every run."""
    out: Path
    model: str  # the model's identity in folder names (a scripted fake is named by its file)
    attempt: str
    network: bool
    denied: tuple = ()
    protected: tuple = ()  # files with answers (known repairs, a frozen selection): unreadable in every sandbox
    protected_folders: tuple = ()  # folders with answers (the source clones): the same, with all below them
    grading_policy: str = pp.LEGACY

    def __post_init__(self):
        if self.grading_policy not in pp.POLICIES:
            raise ValueError(f"unknown grading policy {self.grading_policy!r}")

    def check(self, policy: iso.Policy):
        """Hold what a sandbox would be given against the answers: nothing that shares a path with a folder
        of answers, and no place to write that holds a file of answers (such a file is denied by name
        only, which a rename there would undo)."""
        given = (*policy.readable, *policy.readable_files, *policy.writable)
        clashes = [(answers, root) for answers in self.protected_folders for root in given if iso.overlap(answers, root)]
        clashes += [(answers, root) for answers in self.protected for root in policy.writable if iso.overlap(answers, root)]
        if clashes:
            answers, root = clashes[0]
            raise iso.Exposed(f"{answers} holds answers and shares a path with {root}, which a sandbox would be given")

    def write_profile(self, policy: iso.Policy, path: Path) -> Path:
        """Every sandbox profile of this invocation is written here, after check()."""
        self.check(policy)
        return iso.write_profile(policy, path, self.denied, self.protected, self.protected_folders)


@dataclass
class Run:
    """One run's folders, interpreter and bookkeeping."""
    ctx: Context
    folder: Path
    network: bool
    real: bool
    python: Path = PYTHON
    interpreters: tuple = ()
    baseline: dict = field(default_factory=dict)
    violations: dict = field(default_factory=dict)  # changed test file or setting -> where it was first seen
    commands: int = 0
    installs: int = 0
    checks: int = 0
    mark: str = field(default_factory=iso.new_mark)  # owner token in every sandbox profile of the run
    stopped: list = field(default_factory=list)  # names of the run's processes stopped when it ended
    cleanup_problems: list = field(default_factory=list)  # processes that could not be shown stopped

    def __post_init__(self):
        for sub in ("state", "tmp"):
            (self.folder / sub).mkdir(parents=True, exist_ok=True)

    project = property(lambda self: self.folder / "project")
    state = property(lambda self: self.folder / "state")
    tmp = property(lambda self: self.folder / "tmp")
    transcript = property(lambda self: self.folder / "transcript.json")
    # FixFirst's sessions (its diagnoses too) stay out of the agent's reach: only its server writes here.
    fixfirst_store = property(lambda self: self.folder / "fixfirst-store")
    commands_log = property(lambda self: self.folder / "commands.jsonl")

    def policy(self, kind: str) -> iso.Policy:
        agent = iso.Policy((self.project, self.state, self.tmp), tuple(self.interpreters), self.network,
                           owner=self.mark)
        if kind == "agent":
            return agent
        if kind == "install":  # installing the project itself: its build requirements come from PyPI
            uv = shutil.which("uv")
            return iso.Policy(agent.writable, agent.readable, True, (Path(os.path.realpath(uv)),) if uv else (),
                              owner=self.mark)
        if kind in ("mcp", "mcp_facts"):  # the facts server keeps no store, so it gets none
            store = (self.fixfirst_store,) if kind == "mcp" else ()
            return iso.Policy((*agent.writable, *store), (*agent.readable, *fixfirst_readable()),
                              agent.network, owner=self.mark)
        if kind == "ff":
            return agent.extended(readable=fixfirst_readable(), readable_files=(HERE / "ff_tool.py",))
        raise ValueError(kind)

    def profile(self, kind: str) -> Path:
        path = self.folder / f"{kind}.sb"
        if not path.exists():
            self.ctx.write_profile(self.policy(kind), path)
        return path

    def env(self, python: Path | None = None) -> dict:
        return rc.clean_env(python or self.python, self.state, self.tmp)

    def execute(self, argv, kind: str, timeout: float, env: dict | None = None):
        return iso.execute(argv, self.project, env or self.env(), self.profile(kind), timeout, self.mark)

    def end_processes(self, when: str):
        """Stop every process of the run (all run under its profiles) and show that none is left; if
        that cannot be shown, the problem is kept and the run is not graded."""
        result = iso.stop(self.mark)
        self.stopped += result["stopped"]
        if result["error"]:
            self.cleanup_problems.append(f"{when}: {result['error']}")

    def suite(self) -> dict:
        """The full suite on a fresh copy, offline, writing only into its own grader folder."""
        self.checks += 1
        grader = self.folder / "grader" / f"check-{self.checks:03d}"
        grader.mkdir(parents=True)
        owner = iso.new_mark()  # the check's own: its processes are not the run's
        profile = self.ctx.write_profile(iso.Policy((grader,), (self.project, *self.interpreters), False, owner=owner),
                                         grader / "grader.sb")

        def execute(argv, cwd, env, timeout):
            try:
                return iso.execute(argv, cwd, env, profile, timeout, owner)
            finally:
                stopped = iso.stop(owner)  # nothing a test started outlives its check or touches its report
                if stopped["error"]:
                    self.cleanup_problems.append(f"grader check {self.checks}: {stopped['error']}")
                    raise iso.CleanupError(f"the grader check's processes could not be stopped: {stopped['error']}")

        suite = rc.run_suite(self.project, self.python, grader, execute, grading_policy=self.ctx.grading_policy)
        if self.ctx.grading_policy == pp.H5:
            rc.write_json(grader / "suite.json", suite)
        return suite

    def set_baseline(self, source=None):
        source = source or self.project
        self.baseline = pp.snapshot(source) if self.ctx.grading_policy == pp.H5 else rc.integrity(source)
        if self.ctx.grading_policy == pp.H5:
            rc.write_json(self.folder / "h5-baseline.json", self.baseline)

    def reference_fields(self, suite):
        if self.ctx.grading_policy != pp.H5:
            return {}
        return {**{k: suite[k] for k in ("grading_policy", "grading_policy_sha256", "h5_observation", "h5_state",
                                       "h5_process_stopped", "h5_junit_error")},
                "h5_baseline": self.baseline, "h5_violations": self.violations}

    def check_integrity(self, turn, tool: str):
        if self.ctx.grading_policy == pp.H5:
            for key, detail in pp.violations(self.baseline, pp.snapshot(self.project)).items():
                self.violations.setdefault(key, {**detail, "turn": turn, "after": tool})
            return
        for key in rc.changed(self.baseline, rc.integrity(self.project)):
            self.violations.setdefault(key, {"turn": turn, "after": tool})

    def log_command(self, entry: dict):
        with self.commands_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


class MCPClient:
    """Minimal MCP stdio client: starts `fixfirst mcp` in the sandbox and relays tool calls."""

    def __init__(self, run: Run, budget: iso.Budget, facts: bool = False):
        if not facts:  # the facts server keeps its sessions in memory and writes no store
            run.fixfirst_store.mkdir(exist_ok=True)
        argv = ["sandbox-exec", "-f", str(run.profile("mcp_facts" if facts else "mcp")), str(PYTHON), "-m", "fixfirst",
                "--store", str(run.fixfirst_store), "mcp", *(["--facts"] if facts else [])]
        self.owner, self.facts = run.mark, facts
        self.log = (run.folder / "mcp-server.log").open("w")
        self.dead = False
        self.proc = subprocess.Popen(argv, cwd=run.project, env=rc.clean_env(PYTHON, run.state, run.tmp),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True,
                                     bufsize=1, start_new_session=True)
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.next_id = 0
        hello = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                            "clientInfo": {"name": "agent_pilot", "version": "1"}},
                             min(120, budget.remaining()))
        self.instructions = hello.get("instructions", "")
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()
        self.tools = self.request("tools/list", {}, min(120, budget.remaining()))["tools"]
        self.names = {t["name"] for t in self.tools}

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)  # the server exited: a waiting request fails now, not at its timeout

    def request(self, method, params, timeout):
        if self.dead:
            raise RuntimeError("FixFirst's server was stopped")
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method,
                                          "params": params}) + "\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            try:
                if left <= 0:
                    raise queue.Empty
                line = self.lines.get(timeout=left)
                if line is None:
                    self.dead = True
                    raise RuntimeError(f"FixFirst's server exited (code {self.proc.wait(5)}) before it answered "
                                       f"{method}; see mcp-server.log")
                answer = json.loads(line)
            except queue.Empty:
                self.stop()
                raise ToolTimeout(f"FixFirst's server did not answer {method} in time") from None
            if answer.get("id") == self.next_id:
                if "error" in answer:
                    raise RuntimeError(answer["error"]["message"])
                return answer["result"]

    def openai_tools(self):
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["inputSchema"]}} for t in self.tools]

    def call(self, name, arguments, timeout):
        result = self.request("tools/call", {"name": name, "arguments": arguments}, timeout)
        text = "\n".join(c.get("text", "") for c in result["content"] if c.get("type") == "text")
        return ("Error: " if result.get("isError") else "") + text

    def stop(self):
        """Kill the server and every check it started (they run in their own sessions)."""
        self.dead = True
        iso.kill_tree(self.proc, self.owner)

    def close(self):
        if not self.dead:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                self.stop()
        self.log.close()


def clip(text):
    return text if len(text) <= OUTPUT_LIMIT else "...(earlier output cut)...\n" + text[-OUTPUT_LIMIT:]


def inside(case: Path, path: str) -> Path | None:
    root = case.resolve()
    target = (root / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    return target if target == root or root in target.parents else None


# ---- Models ------------------------------------------------------------------------------------

class FakeModel:
    """Scripted replies, to check the harness without a model. The script is a JSON list; each step
    is {"call": name, "arguments": {...}}, {"calls": [...]} for several, {"say": text} for an answer
    without a tool call, {"fail": text} for a failed request or {"raw": message} for a message sent as
    it is (to test malformed replies). "delay": seconds makes the reply take that long. The call names
    "fixfirst:first" and "fixfirst:again" stand for the arm's FixFirst tools (with the harness's
    default arguments when the step gives none); in an arm that offers none, such calls are left out
    (and a step with nothing left is skipped)."""

    def __init__(self, path: Path, aliases: dict | None = None):
        self.steps = json.loads(Path(path).read_text(encoding="utf-8"))
        self.index = 0
        self.aliases = aliases or {}

    def reply(self, timeout: float):
        if self.index >= len(self.steps):
            return {"content": "(script finished)"}, {}
        step = self.steps[self.index]
        self.index += 1
        delay = float(step.get("delay", 0))
        if delay > timeout:
            time.sleep(max(0.0, timeout))
            raise ModelTimeout("the scripted reply took longer than the time left")
        time.sleep(delay)
        if "fail" in step:
            raise ModelError(step["fail"])
        if "raw" in step:
            return step["raw"], step.get("usage", {})
        if "say" in step:
            return {"content": step["say"]}, {}
        calls = []
        for c in step.get("calls") or [step]:
            if str(c.get("call", "")).startswith("fixfirst:"):
                if c["call"] not in self.aliases:
                    continue
                name, defaults = self.aliases[c["call"]]
                c = {**c, "call": name, "arguments": c.get("arguments") or defaults}
            calls.append(c)
        if not calls:
            return self.reply(timeout)
        return {"content": "", "tool_calls": [
            {"id": f"call-{self.index}-{n}", "type": "function",
             "function": {"name": c["call"], "arguments": json.dumps(c.get("arguments", {}))}}
            for n, c in enumerate(calls)]}, {}


def chat(model, messages, tools, settings: Settings, fake: FakeModel | None, timeout: float):
    if fake:
        return fake.reply(timeout)
    body = {"model": model, "messages": messages, "tools": tools, "max_tokens": settings.max_tokens,
            "temperature": settings.temperature, "seed": settings.seed}
    data = post_before(f"{BASE}/chat/completions", body, timeout)
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ModelError("the response has no choices")
    return choices[0].get("message"), data.get("usage")


def post_before(url: str, body: dict, timeout: float) -> dict:
    """POST and read the JSON reply, all within `timeout` seconds. httpx's timeouts limit each wait,
    not the whole request (a server that keeps sending slowly would never trip them), so the request
    runs in a thread and its connection is closed at the deadline."""
    if timeout <= 0:
        raise ModelTimeout("no time left for the request")
    client = httpx.Client(timeout=timeout)
    result, done = {}, threading.Event()

    def request():
        try:
            response = client.post(url, json=body, headers=HEADERS)
            response.raise_for_status()
            result["data"] = response.json()
        except Exception as error:  # handed to the caller below
            result["error"] = error
        finally:
            done.set()

    threading.Thread(target=request, daemon=True).start()
    finished = done.wait(timeout)
    client.close()  # at the deadline this aborts the request in the thread
    if not finished:
        raise ModelTimeout(f"no complete reply within {timeout:.2f} s")
    error = result.get("error")
    if isinstance(error, httpx.TimeoutException):
        raise ModelTimeout(str(error) or "timed out") from error
    if error:
        raise error
    return result["data"]


def parse_call(call) -> tuple[str | None, dict | None, str | None]:
    """(name, arguments, problem) of one tool call; a problem means the call is not carried out."""
    if not isinstance(call, dict):
        return None, None, "the tool call is not an object"
    function = call.get("function")
    if not isinstance(function, dict) or not isinstance(function.get("name"), str) or not function["name"]:
        return None, None, "the tool call has no function name"
    raw = function.get("arguments") or "{}"
    try:
        arguments = raw if isinstance(raw, dict) else json.loads(raw)
    except (TypeError, ValueError):
        return function["name"], None, "the arguments are not JSON"
    if not isinstance(arguments, dict):
        return function["name"], None, "the arguments are not a JSON object"
    return function["name"], arguments, None


def count(value) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


# ---- The episode --------------------------------------------------------------------------------

def episode(model, arm, run: Run, settings: Settings, fake, green, state_digest) -> dict:
    stats = {"turns": 0, "tool_calls": 0, "pytest_runs": 0, "fixfirst_calls": 0, "prompt_tokens": 0,
             "completion_tokens": 0, "model_s": 0.0, "tool_s": 0.0, "end": "turn_cap", "bad_calls": 0,
             "first_green_turn": None, "first_green_s": None, "error": None, "mcp_arguments_filled": 0,
             "mcp_arguments_overridden": 0, "mcp_goal_filled": 0, "mcp_goal_overridden": 0, "fixfirst_reports": 0, "fixfirst_s": 0.0, "fixfirst_output_chars": 0,
             "usage_reported": False}
    budget = iso.Budget(settings.run_timeout)
    tools = BASIC_TOOLS + ([FIXFIRST_TOOL] if arm == "fixfirst" else [])
    system = system_prompt(run.network, run.ctx.grading_policy) + (FIXFIRST_INSTRUCTIONS if arm == "fixfirst" else "")
    messages = []
    mcp = None
    first_tool, again_tool = FIXFIRST_ARMS.get(arm, (None, None))
    scheduled = bool(first_tool) and settings.call_policy == "scheduled"

    def save():
        run.transcript.write_text(json.dumps(messages, ensure_ascii=False, indent=1), encoding="utf-8")

    try:
        if first_tool:
            try:
                mcp = MCPClient(run, budget, facts=arm == "facts")
            except (OSError, RuntimeError, ValueError, KeyError, ToolTimeout) as error:
                stats.update(end="mcp_start_failed", error=f"{type(error).__name__}: {error}"[:500])
                return stats
            if not scheduled:
                tools = tools + mcp.openai_tools()
            system += policy_text(settings.call_policy, mcp, first_tool, again_tool)
        messages += [{"role": "system", "content": system},
                     {"role": "user", "content": f"The project is in {run.project}. Its tests fail. Fix it."}]
        if scheduled:
            try:
                report = fixfirst_report(first_tool, run, mcp, budget, stats)
            except ToolTimeout as error:
                stats.update(end="time_cap", error=f"ToolTimeout: {error}"[:500])
                return stats
            except (OSError, RuntimeError) as error:
                stats.update(end="mcp_start_failed", error=f"{type(error).__name__}: {error}"[:500])
                return stats
            messages[-1]["content"] += "\n\nFixFirst checked the project before your first step:\n" + report
        with budget.pause():
            last = state_digest()
        for turn in range(1, settings.max_turns + 1):
            if budget.remaining() <= 0:
                stats["end"] = "time_cap"
                break
            started = time.monotonic()
            try:
                message, usage = chat(model, messages, tools, settings, fake, budget.remaining())
            except ModelTimeout as error:
                stats["end"] = "time_cap" if budget.remaining() <= 0 else "model_error"
                stats["error"] = f"{type(error).__name__}: {error}"[:500]
                break
            except (httpx.HTTPError, ValueError, ModelError) as error:
                stats["end"], stats["error"] = "model_error", f"{type(error).__name__}: {error}"[:500]
                break
            finally:
                stats["model_s"] += time.monotonic() - started
            if not isinstance(message, dict):
                stats["end"], stats["error"] = "model_error", "the reply has no message object"
                break
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list):
                stats["end"], stats["error"] = "model_error", "tool_calls is not a list"
                break
            usage = usage if isinstance(usage, dict) else {}
            # Tokens the server did not report are unknown, not zero.
            stats["usage_reported"] |= any(key in usage for key in ("prompt_tokens", "completion_tokens"))
            stats["turns"] = turn
            stats["prompt_tokens"] += count(usage.get("prompt_tokens"))
            stats["completion_tokens"] += count(usage.get("completion_tokens"))
            content = message.get("content")
            assistant = {"role": "assistant", "content": content if isinstance(content, str) else ""}
            if calls:
                assistant["tool_calls"] = calls
            messages.append(assistant)
            if not calls:
                stats["end"] = "stopped_without_tool"
                break
            finished = timed_out = False
            for index, call in enumerate(calls):
                call_id = call.get("id") if isinstance(call, dict) and isinstance(call.get("id"), str) else f"call-{turn}-{index}"
                if timed_out or budget.remaining() <= 0:
                    timed_out = True
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": "not run: the run's time is up"})
                    continue
                stats["tool_calls"] += 1
                name, arguments, problem = parse_call(call)
                started = time.monotonic()
                if problem:
                    stats["bad_calls"] += 1
                    result = f"error: {problem}"
                else:
                    try:
                        result = run_tool(name, arguments, run, stats, mcp, budget, turn)
                    except ToolTimeout as error:
                        timed_out, result = True, f"stopped: the run's time is up ({error})"
                    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as error:
                        stats["bad_calls"] += 1
                        result = f"error: {type(error).__name__}: {error}"
                stats["tool_s"] += time.monotonic() - started
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                if not problem and name not in ("read_file", "finish"):
                    with budget.pause():
                        run.check_integrity(turn, name)
                if name == "finish" and not problem and not timed_out and budget.remaining() > 0:
                    finished = True
            save()
            if timed_out or budget.remaining() <= 0:
                stats["end"] = "time_cap"
                break
            newly_green = False
            with budget.pause():
                current = state_digest()
                changed = current != last
                if changed:
                    last = current
                    newly_green = stats["first_green_turn"] is None and green()
            if newly_green:
                stats["first_green_turn"], stats["first_green_s"] = turn, round(budget.used(), 2)
            if finished:
                stats["end"] = "finish"
                break
            if scheduled and changed:
                try:
                    report = fixfirst_report(again_tool, run, mcp, budget, stats)
                except ToolTimeout:
                    stats["end"] = "time_cap"
                    break
                except (OSError, RuntimeError) as error:  # the report says so; the run goes on
                    report = f"FixFirst could not check the project: {type(error).__name__}: {error}"
                messages.append({"role": "user", "content": "FixFirst checked the project again after your "
                                                            "changes:\n" + report})
    finally:
        save()
        if mcp:
            mcp.close()
        stats["agent_s"] = round(budget.used(), 2)
        stats["harness_s"] = round(budget.paused, 2)
        stats["fixfirst_s"] = round(stats["fixfirst_s"], 2)
        # Every process of the run ends with the episode, before anything is read or graded.
        run.end_processes("end of the episode")
        stats["processes_stopped_at_end"] = len(run.stopped)
    return stats


def policy_text(policy: str, mcp, first_tool: str, again_tool: str) -> str:
    """What the system prompt says about FixFirst: the same wording in both FixFirst arms, except
    under the server policy, where each arm gets its server's own instructions."""
    if policy == "server":
        return "\n\n" + mcp.instructions if mcp.instructions else ""  # what an MCP client adds from the server
    if policy == "scheduled":
        return ("\n\nFixFirst checks the project for you: its report comes with the task and again after "
                "each turn that changed the project.")
    if policy == "required":
        return f"\n\nCall {first_tool} before changing anything, and {again_tool} after each change."
    return f"\n\nFixFirst's tools ({', '.join(t['name'] for t in mcp.tools)}) are available; use them when they help."


def fixfirst_report(tool: str, run: Run, mcp, budget: iso.Budget, stats) -> str:
    """A FixFirst call the harness makes itself (scheduled policy): the same arguments in both arms,
    and its time counts against the agent's budget like a tool call's."""
    arguments = ({} if tool == "check_again"
                 else {"project": str(run.project), "python": str(run.python), "goal": GRADING_GOAL})
    started = time.monotonic()
    try:
        text = mcp.call(tool, arguments, budget.remaining())
    finally:
        stats["fixfirst_s"] += time.monotonic() - started
    stats["fixfirst_reports"] += 1
    note_fixfirst_output(text, run, mcp, stats)
    stats["fixfirst_output_chars"] += len(clip(text))
    return clip(text)


def note_fixfirst_output(text: str, run: Run, mcp, stats):
    """For the comparison: in the facts arm, whether every report held only facts' fields; in the
    full arm, the cause of the first step FixFirst listed (read from its own session store)."""
    if getattr(mcp, "facts", False):
        try:
            ok = set(json.loads(text)) <= set(FACTS_KEYS)
        except (ValueError, TypeError):
            ok = text.startswith("Error: ")  # a tool error, not a report
        stats["facts_only_verified"] = stats.get("facts_only_verified", True) and ok
    elif stats.get("fixfirst_first_cause") is None and not text.startswith("Error: "):
        found = re.match(r"FixFirst session (session-[0-9a-f]+)", text)
        if found:
            session = Store(run.fixfirst_store).load(found[1])
            stats["fixfirst_first_cause"] = next((a.cause for a in session.actions if a.cause), "none")


def run_tool(name, args, run: Run, stats, mcp, budget: iso.Budget, turn):
    if mcp and name in mcp.names:
        if mcp.dead:
            return "error: FixFirst's server was stopped"
        stats["fixfirst_calls"] += 1
        if name in ("diagnose", "observe"):
            # FixFirst checks the grader's goal, whatever goal the model asked for: otherwise its own
            # guess (say, unittest for a pytest project) can call a fixed project still failing.
            given = args.get("goal")
            if given != GRADING_GOAL:
                counter = "mcp_goal_overridden" if given else "mcp_goal_filled"
                stats[counter] = stats.get(counter, 0) + 1
            args = {**args, "goal": GRADING_GOAL}
        if name in ("diagnose", "observe") and run.real:
            # The case's project and interpreter, whatever the model passed: a missing value is
            # filled in, a different one is overridden.
            forced = {"project": str(run.project), "python": str(run.python)}
            for key, value in forced.items():
                given = args.get(key)
                if not given:
                    stats["mcp_arguments_filled"] += 1
                elif os.path.abspath(run.project / str(given)) != value:
                    stats["mcp_arguments_overridden"] += 1
            args = {**args, **forced}
        started = time.monotonic()
        try:
            text = mcp.call(name, args, budget.remaining())
        finally:  # FixFirst's cost, also when the call fails or runs out of time
            stats["fixfirst_s"] = stats.get("fixfirst_s", 0) + time.monotonic() - started
        note_fixfirst_output(text, run, mcp, stats)
        stats["fixfirst_output_chars"] = stats.get("fixfirst_output_chars", 0) + len(clip(text))
        return clip(text)
    if name == "run_command":
        command = args["command"]
        if not isinstance(command, str):
            raise TypeError("command must be a string")
        if "pytest" in command:
            stats["pytest_runs"] += 1
        started = time.monotonic()
        code, output, stopped = run.execute(["/bin/bash", "-c", command], "agent",
                                            min(COMMAND_CAP[run.network], budget.remaining()))
        run.commands += 1
        install = bool(INSTALL.search(command))
        run.installs += install
        run.log_command({"turn": turn, "command": command, "exit_code": code, "stopped": stopped,
                         "seconds": round(time.monotonic() - started, 2), "install": install})
        if stopped and budget.remaining() <= 0:
            raise ToolTimeout("the command was stopped at the deadline")
        return f"exit code {code}\n{clip(output)}"
    # The file tools run in the harness, so they never wait on a named pipe and never read without limit.
    if name == "read_file":
        target = inside(run.project, str(args["path"]))
        if not target or not target.is_file():
            return "error: no such file in the project"
        data = rc.read_regular(target)
        if data is None:
            return "error: not a regular file of at most 16 MB"
        return clip(data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n"))
    if name == "write_file":
        target = inside(run.project, str(args["path"]))
        if not target:
            return "error: path is outside the project"
        target.parent.mkdir(parents=True, exist_ok=True)
        rc.write_regular(target, str(args["content"]))
        return f"wrote {len(str(args['content']))} characters to {target.relative_to(run.project.resolve())}"
    if name == "fixfirst_check":
        stats["fixfirst_calls"] += 1
        started = time.monotonic()
        try:
            code, output, stopped = run.execute([str(PYTHON), str(HERE / "ff_tool.py"), str(run.project),
                                                 str(run.state / "session.json"), str(PYTHON)], "ff",
                                                min(600, budget.remaining()), env=run.env(PYTHON))
        finally:
            stats["fixfirst_s"] = stats.get("fixfirst_s", 0) + time.monotonic() - started
        if stopped and budget.remaining() <= 0:
            raise ToolTimeout("FixFirst's check was stopped at the deadline")
        return clip(output) if code == 0 else f"fixfirst failed (exit {code}):\n{clip(output)}"
    if name == "finish":
        return "ok"
    stats["bad_calls"] += 1
    return f"error: unknown tool {name}"


# ---- References --------------------------------------------------------------------------------

def generated_reference(ctx: Context, template: str, pristine: Path, cache: dict) -> dict:
    """The healthy template's own outcome, run like a grader run."""
    cache_key = template if ctx.grading_policy == pp.LEGACY else (template, pp.H5, pp.identity())
    if cache_key in cache:
        return cache[cache_key]
    folder = ctx.out / "_templates" / f"{template}--reference--{ctx.attempt}"
    run = Run(ctx, folder, False, False, PYTHON, interpreters(PYTHON.parent.parent))
    shutil.copytree(pristine, run.project)
    if ctx.grading_policy == pp.H5:
        run.set_baseline()
    suite = run.suite()
    if ctx.grading_policy == pp.H5:
        run.check_integrity("reference", "full suite")
    data = {"template": template, "exit_code": suite["exit_code"], "counts": suite["counts"],
            "summary": suite["summary"], "outcomes": suite["outcomes"], **run.reference_fields(suite)}
    data["problems"] = rc.validate_reference(data)
    (folder / "reference.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    cache[cache_key] = data
    return data


def hard_instance(ctx: Context, t, scenario_id: str, cache: dict, frozen: dict | None) -> dict:
    """A hard instance, made once per invocation: the healthy template, the start and the reference each
    in a folder of its own, the manifest whose digest identifies it, and the reference outcome, cached
    under that digest. `end` says why it cannot be run: unsupported_case when the start is not admitted,
    reference_invalid when the reference cannot grade or the instance is not the frozen one."""
    spec = f"{t.name}:{scenario_id}"
    cache_key = ("hard", spec) if ctx.grading_policy == pp.LEGACY else ("hard", spec, pp.H5, pp.identity())
    if cache_key in cache:
        return cache[cache_key]
    entry = hi.load_registry()[scenario_id]
    folder = ctx.out / "_hard" / f"{iso.slug(spec, 40)}--{ctx.attempt}"
    built = hi.build(folder, t, hi.scenario(scenario_id))
    data = cache[cache_key] = {"start": built["start"], "required": hi.required_node(t, entry), "digest": None,
                                    "manifest": None, "reference": None, "problems": [], "end": None}
    problems = hi.admit(built["pristine"], built["start"], t, entry)
    if problems:
        data.update(problems=problems, end="unsupported_case")
        return data
    run = Run(ctx, folder / "reference", False, False, PYTHON, interpreters(PYTHON.parent.parent))
    problems = hi.make_reference(run.project, built["pristine"], built["start"], t, entry)
    if problems:
        data.update(problems=problems, end="reference_invalid")
        return data
    if ctx.grading_policy == pp.H5:
        run.set_baseline(built["start"])
    manifest = hi.manifest(t, scenario_id, entry, built["start"], run.project, hi.environment(PYTHON), hi.code_identity(),
                           grading_policy=ctx.grading_policy)
    digest = hi.digest(manifest)
    rc.write_json(folder / "manifest.json", {"digest": digest, **manifest})
    data.update(digest=digest, manifest=manifest)
    if frozen is not None and frozen.get(spec) != digest:
        data.update(end="reference_invalid", problems=[
            f"the instance is not the frozen one: its digest is {digest[:16]}, the selection has {str(frozen.get(spec))[:16]}"])
        return data
    (ctx.out / "_reference").mkdir(parents=True, exist_ok=True)
    cached = ctx.out / "_reference" / f"hard--{iso.slug(spec, 40)}--{digest[:12]}.json"
    reference, note = rc.read_reference_cache(cached, digest, ctx.attempt, ctx.grading_policy)
    if reference and hi.reference_problems(reference, t, entry):  # passes as a reference, not as a hard instance's
        aside = cached.with_name(f"{cached.name}.unusable-{ctx.attempt}")
        cached.rename(aside)
        reference, note = None, f"the cached reference was not usable for a hard instance; kept as {aside.name} and built again"
    if reference is None:
        reference = {"key": digest, "commit": "", "repair": [], "cache_note": note}
        try:
            suite = run.suite()
            if ctx.grading_policy == pp.H5:
                run.check_integrity("reference", "full suite")
            reference.update(exit_code=suite["exit_code"], stopped=suite["stopped"], counts=suite["counts"],
                             summary=suite["summary"], outcomes=suite["outcomes"], **run.reference_fields(suite))
        except (RuntimeError, OSError, subprocess.SubprocessError, ParseError) as error:
            reference.update(exit_code=None, stopped=None, counts={}, outcomes={}, summary="",
                             setup_error=f"{type(error).__name__}: {error}"[:500])
        finally:
            run.end_processes("after the reference")
        # Not the instance's doing: the suite could not be run, was interrupted, or left processes behind.
        reference["not_completed"] = (reference.get("setup_error") or "; ".join(run.cleanup_problems)
                                      or hi.not_completed(reference["exit_code"], reference["stopped"]))
        reference["problems"] = (([reference["setup_error"]] if reference.get("setup_error") else [])
                                 + run.cleanup_problems + hi.reference_problems(reference, t, entry))
        rc.write_json(folder / "reference.json", reference)
        if not reference["problems"]:
            rc.write_json(cached, reference)
    data.update(reference=reference, problems=reference["problems"],
                end="reference_invalid" if reference["problems"] else None)
    return data


def real_reference(ctx: Context, project: dict, source: Path, snapshot: Path, repair: list[str]) -> dict:
    """The outcome after the known repair, on a separate copy, checked before it grades anything.
    Only valid references are cached (written atomically); an unusable cache is set aside and the
    reference built again. Every attempt keeps its own folder. Errors are left to the caller, which
    records them for every planned run of the case."""
    commit = rc.source_commit(source)
    if not commit:
        raise RuntimeError(f"no git clone of {project['id']} in {source}")
    parts = [commit, snapshot.read_text(encoding="utf-8"), repair]
    if project.get("install_fails"):  # a registered failing install is part of the start
        parts.append(project["install_fails"])
    if ctx.grading_policy == pp.H5:
        parts.append({"grading_policy": pp.H5, "grading_policy_sha256": pp.identity()})
    key = hashlib.sha256(json.dumps(parts).encode()).hexdigest()
    name = f"{iso.slug(project['id'], 30)}--{key[:12]}"
    (ctx.out / "_reference").mkdir(parents=True, exist_ok=True)
    cached = ctx.out / "_reference" / f"{name}.json"
    data, note = rc.read_reference_cache(cached, key, ctx.attempt, ctx.grading_policy)
    if data:
        return data
    folder = ctx.out / "_reference" / f"{name}--{ctx.attempt}"
    run = Run(ctx, folder, True, True)
    data = {"key": key, "commit": commit, "repair": [], "problems": [], "cache_note": note}
    try:
        rc.export_source(source, commit, run.project)
        run.python = rc.create_environment(run.project, project, snapshot, [])
        run.interpreters = interpreters(run.project / ".venv")
        env = {**run.env(), "SETUPTOOLS_SCM_PRETEND_VERSION": project["ref"].lstrip("v")}
        for step in rc.install_steps(project, run.python, run.tmp / "uv-cache"):
            code, output, stopped = run.execute(step["argv"], "install", INSTALL_SECONDS, env=env)
            data["repair"].append({"command": "install the project: " + " ".join(step["argv"][-2:]), "exit_code": code,
                                   "stopped": stopped, "expected_failure": step["expected_failure"],
                                   "output": output[-1000:]})
        if ctx.grading_policy == pp.H5:
            run.set_baseline()
        for command in repair:
            code, output, stopped = run.execute(["/bin/bash", "-c", command], "install", INSTALL_SECONDS)
            data["repair"].append({"command": command, "exit_code": code, "stopped": stopped, "output": output[-1000:]})
            if ctx.grading_policy == pp.H5:
                run.check_integrity("reference", command)
        suite = run.suite()
        if ctx.grading_policy == pp.H5:
            run.check_integrity("reference", "full suite")
        data.update(exit_code=suite["exit_code"], counts=suite["counts"], summary=suite["summary"],
                    outcomes=suite["outcomes"], **run.reference_fields(suite))
    except (RuntimeError, OSError, subprocess.SubprocessError, ParseError) as error:
        data.update(exit_code=None, counts={}, outcomes={}, summary="",
                    setup_error=f"{type(error).__name__}: {error}"[:500])
    finally:
        run.end_processes("after the reference")
    data["processes_stopped"] = run.stopped
    data["problems"] = (([data["setup_error"]] if data.get("setup_error") else []) + run.cleanup_problems
                        + rc.validate_reference(data))
    rc.write_json(folder / "reference.json", data)
    if not data["problems"]:
        rc.write_json(cached, data)
    return data


# ---- Runs ---------------------------------------------------------------------------------------

def grade(run: Run, reference: dict, row: dict):
    row["stage"] = "grading"
    try:
        run.check_integrity("end", "final state")
        if run.ctx.grading_policy == pp.H5:
            row.update(violations=run.violations,
                       violation_categories=sorted({v["category"] for v in run.violations.values()}))
        if run.ctx.grading_policy == pp.H5 and run.baseline != reference.get("h5_baseline"):
            raise ValueError("H5 run's starting protection snapshot differs from the reference's start")
        verdict = rc.judge(run.suite(), reference, sorted(run.violations))
    except (OSError, ParseError, KeyError, ValueError) as error:
        # A confirmed policy breach is already a failed attempt. A broken report caused by
        # that attempt must not remove it from the success-rate denominator.
        if (run.ctx.grading_policy == pp.H5 and run.violations
                and run.baseline == reference.get("h5_baseline") and not rc.validate_reference(reference)):
            row.update(grading="graded", fixed=False, reasons=["H5 protection violated during the run"],
                       tests_changed=sorted(run.violations), grader_counts={}, reference_counts=reference["counts"],
                       grading_observation_error=f"{type(error).__name__}: {error}"[:500])
            return
        row.update(grading="grading_error", fixed=None, grading_error=f"{type(error).__name__}: {error}"[:500])
        return
    row.update(grading="graded", fixed=verdict["fixed"], reasons=verdict["reasons"],
               grader_counts=verdict["counts"], reference_counts=verdict["reference_counts"],
               tests_changed=verdict["tests_changed"], violations=run.violations)
    if run.ctx.grading_policy == pp.H5:
        row["violation_categories"] = sorted({v["category"] for v in run.violations.values()})
        row["h5_grader_report"] = f"grader/check-{run.checks:03d}/suite.json"


def close_run(run: Run, row: dict):
    """The last step of every run, however it ended (finished, capped, setup, model, grader or harness
    error): stop its processes and show that none is left. A run for which that cannot be shown is
    `cleanup_failed`: its episode's end is kept, and it is never graded."""
    run.end_processes("end of the run")
    row["processes_stopped_at_end"] = len(run.stopped)
    if run.stopped:
        row["processes_stopped"] = run.stopped[:20]
    if run.cleanup_problems:
        row.update(end="cleanup_failed", episode_end=row.get("end"), grading="not_graded", fixed=None,
                   error="; ".join(run.cleanup_problems)[:500])
        for key in ("reasons", "grader_counts", "tests_changed"):
            row.pop(key, None)


def file_hashes(project_dir: Path) -> dict:
    return {p.relative_to(project_dir).as_posix(): rc.file_hash(p) for p in rc._walk(project_dir)}


def play(model, arm, run: Run, settings, fake_path, reference, row, state_digest):
    """The episode, then the grade; a run whose episode never started is not graded."""
    first_tool, again_tool = FIXFIRST_ARMS.get(arm, (None, None))
    aliases = {}
    if first_tool and settings.call_policy != "scheduled":  # the model is offered FixFirst's tools
        start = {"project": str(run.project)}
        aliases = {"fixfirst:first": (first_tool, start),
                   "fixfirst:again": (again_tool, {} if again_tool == "check_again" else start)}
    fake = FakeModel(fake_path, aliases) if fake_path else None
    files_before = file_hashes(run.project)

    def green():
        if run.violations:
            return False
        if run.ctx.grading_policy == pp.H5 and run.baseline != reference.get("h5_baseline"):
            return False
        try:
            return rc.judge(run.suite(), reference, [])["fixed"]
        except (OSError, ParseError, KeyError, ValueError):
            return False

    row["stage"] = "episode"
    started = time.monotonic()
    stats = episode(model, arm, run, settings, fake, green, state_digest)
    stats["total_s"] = round(time.monotonic() - started, 1)
    if stats.get("fixfirst_first_cause") and row.get("cause"):  # generated cases know their cause
        stats["wrong_first_cause"] = stats["fixfirst_first_cause"] != row["cause"]
    row.update({k: round(v, 2) if isinstance(v, float) else v for k, v in stats.items()})
    if run.cleanup_problems:
        row.update(grading="not_graded", fixed=None)  # close_run records why; nothing is graded
    elif stats["end"] == "mcp_start_failed":
        row.update(grading="not_graded", fixed=None)
    else:
        grade(run, reference, row)
    row.update(files_changed=rc.changed(files_before, file_hashes(run.project)), commands=run.commands,
               install_commands=run.installs, grader_checks=run.checks)


def run_real(ctx: Context, row: dict, settings, project, source, snapshot, reference, arm, run_index, fake_path):
    run = Run(ctx, iso.run_folder(ctx.out, project["id"], arm, run_index, ctx.model, ctx.attempt), ctx.network, True)
    row.update(run_dir=run.folder.relative_to(ctx.out).as_posix(), stage="setup",
               install_fails_registered=rc.install_fails_registered(project))
    try:
        prepare_and_play_real(ctx, run, row, settings, project, source, snapshot, reference, arm, fake_path)
    finally:
        close_run(run, row)


def prepare_and_play_real(ctx: Context, run: Run, row: dict, settings, project, source, snapshot, reference, arm,
                          fake_path):
    commit = rc.source_commit(source)
    row["commit"] = commit
    setup_log = []
    try:
        rc.export_source(source, commit, run.project)
        run.python = rc.create_environment(run.project, project, snapshot, setup_log)
        record = rc.venv_record(run.project / ".venv")  # read before any project code can change it
        run.interpreters = interpreters(run.project / ".venv")
        ctx.check(run.policy("agent"))  # known only now; a project that installs nothing writes no profile in setup
        row["python"] = record["version"]
        env = {**run.env(), "SETUPTOOLS_SCM_PRETEND_VERSION": project["ref"].lstrip("v")}
        for step in rc.install_steps(project, run.python, run.tmp / "uv-cache"):
            code, output, stopped = run.execute(step["argv"], "install", INSTALL_SECONDS, env=env)
            setup_log.append({"step": "install the project (sandboxed): " + " ".join(step["argv"][-2:]), "exit_code": code,
                              "stopped": stopped, "expected_failure": step["expected_failure"], "output": output[-2000:]})
            if step["expected_failure"]:
                # Every arm starts where the registered case starts: after this step ran and failed.
                problem = rc.registered_failure_problem(code, stopped)
                if problem:
                    raise SetupError(f"the registered failing install step {step['line']!r} {problem}: "
                                     "the start is not the registered one")
            elif code:
                raise SetupError(f"installing the project failed ({code})")
    except (RuntimeError, OSError, subprocess.SubprocessError, SetupError) as error:
        row.update(end="setup_failed", error=f"{type(error).__name__}: {error}"[:500], grading="not_graded", fixed=None)
        return
    finally:
        (run.folder / "setup.json").write_text(json.dumps(setup_log, indent=1), encoding="utf-8")
    start = rc.freeze(run.python)
    (run.folder / "freeze-start.txt").write_text("\n".join(start) + "\n", encoding="utf-8")
    run.set_baseline()
    row.update(snapshot_mismatch=rc.snapshot_mismatch(snapshot, start),
               start_digest=rc.workspace_digest(run.project, run.python)[:16])
    try:
        play(ctx.model, arm, run, settings, fake_path, reference, row,
             lambda: rc.workspace_digest(run.project, run.python))
    finally:
        end = rc.freeze(run.python)
        (run.folder / "freeze-end.txt").write_text("\n".join(end) + "\n", encoding="utf-8")
        row["packages"] = rc.freeze_difference(start, end)


def run_generated(ctx: Context, row: dict, settings, spec, arm, run_index, fake_path, references, frozen=None):
    template, scenario = spec.split(":")
    t = next(x for x in dc.TEMPLATES if x.name == template)
    if is_hard(spec):
        return run_hard(ctx, row, settings, spec, t, scenario, arm, run_index, fake_path, references, frozen)
    s = next(x for x in dc.SCENARIOS if x.scenario_id == scenario)
    pristine = ctx.out / "_templates" / template
    if not pristine.exists():
        dc.build_template(pristine, t)
    reference = generated_reference(ctx, template, pristine, references)
    run = Run(ctx, iso.run_folder(ctx.out, spec, arm, run_index, ctx.model, ctx.attempt), False, False,
              PYTHON, interpreters(PYTHON.parent.parent))
    row.update(run_dir=run.folder.relative_to(ctx.out).as_posix(), stage="setup", cause=s.label)
    try:
        prepare_and_play_generated(ctx, run, row, settings, t, s, pristine, reference, arm, fake_path)
    finally:
        close_run(run, row)


def is_hard(spec: str) -> bool:
    return spec.split(":")[-1] in hi.hard_scenarios()


def run_hard(ctx: Context, row: dict, settings, spec, t, scenario, arm, run_index, fake_path, cache, frozen):
    """A run of a hard instance: every arm, model and repeat starts from a copy of the same start, checked
    file by file against the instance's manifest; the start's tests and settings are the baseline."""
    run = Run(ctx, iso.run_folder(ctx.out, spec, arm, run_index, ctx.model, ctx.attempt), False, False,
              PYTHON, interpreters(PYTHON.parent.parent))
    row.update(run_dir=run.folder.relative_to(ctx.out).as_posix(), stage="setup", cause=hi.scenario(scenario).label)
    try:
        instance = hard_instance(ctx, t, scenario, cache, frozen)
        row.update(hard_instance=instance["digest"], required_node=instance["required"])
        if instance["end"]:
            row.update(end=instance["end"], error="; ".join(instance["problems"])[:500], grading="not_graded", fixed=None)
            return
        shutil.copytree(instance["start"], run.project)
        if hi.tree(run.project) != instance["manifest"]["start"]:
            row.update(end="setup_failed", error="the run's copy is not the instance's start", grading="not_graded",
                       fixed=None)
            return
        run.set_baseline()
        play(ctx.model, arm, run, settings, fake_path, instance["reference"], row,
             lambda: rc.workspace_digest(run.project, None))
    finally:
        close_run(run, row)


def prepare_and_play_generated(ctx: Context, run: Run, row: dict, settings, t, s, pristine, reference, arm,
                               fake_path):
    if reference["problems"]:
        row.update(end="reference_invalid", error="; ".join(reference["problems"]), grading="not_graded", fixed=None)
        return
    shutil.copytree(pristine, run.project)
    s.apply(dc.Project(run.project, t, dc.TEMPLATES.index(t)))
    if (pp.snapshot(run.project) != pp.snapshot(pristine) if ctx.grading_policy == pp.H5 else
            rc.integrity(run.project) != rc.integrity(pristine)):
        row.update(end="unsupported_case", grading="not_graded", fixed=None,
                   error="the scenario changes test files or pytest settings, so the healthy template is no reference")
        return
    run.set_baseline()
    play(ctx.model, arm, run, settings, fake_path, reference, row, lambda: rc.workspace_digest(run.project, None))


def arm_order(arms: list[str], case_index: int, run_index: int) -> list[str]:
    """Rotate which arm goes first, per case and run (with two arms: alternate)."""
    shift = (case_index + run_index) % len(arms)
    return list(arms[shift:]) + list(arms[:shift])


def check_output_folder(out: Path, grading_policy=pp.LEGACY) -> str | None:
    """Runs must not sit below a folder with pytest settings: pytest would read them."""
    out = out.resolve()
    if out == FIXFIRST or FIXFIRST in out.parents:
        return f"{out} is inside the FixFirst repository; choose a folder outside it (default: {FIXFIRST.parent / 'agent-runs'})"
    for folder in ((out, *out.parents) if grading_policy == pp.H5 else out.parents):
        names = (*pp.CONFIG_FILES, "conftest.py") if grading_policy == pp.H5 else PYTEST_FILES
        found = [name for name in names if os.path.lexists(folder / name)]
        if found:
            return f"{folder} has {', '.join(found)}; pytest in the runs would read it"
    return None


def exposure(path: Path, denied: tuple, readable: tuple) -> str | None:
    """Why a run's sandbox could read `path`, a file or folder that holds answers; None when it cannot.
    A sandbox reads everything except the denied folders, and inside those what it is given. So answers
    must lie inside a denied folder and share no path with anything a sandbox may be given: the folders
    in `readable` (where runs get folders of their own: the output folder) and what the harness lets its
    sandboxes read wherever they run (harness_readable). Sharing goes both ways: answers inside such a
    folder, and a folder of answers around one."""
    real = Path(os.path.realpath(path))
    if not any(real == root or root in real.parents for root in (Path(os.path.realpath(r)) for r in denied)):
        return ("is outside the folders a run is kept out of (the home folder, the output folder, the repository, "
                "the system temporary folders)")
    for root in (*readable, *harness_readable()):
        if iso.overlap(real, root):
            return (f"shares a path with {os.path.realpath(root)}, which runs may read (the output folder, FixFirst's "
                    "code and environment, the interpreters, the tools)")
    return None


def redact(text: str, out: Path) -> str:
    pairs = ((out.as_uri(), "file://<out>"), (str(out), "<out>"), (FIXFIRST.as_uri(), "file://<repo>"),
             (str(FIXFIRST), "<repo>"), (TMP, "<tmp>"), ("/private/tmp", "<tmp>"),
             (Path(HOME).as_uri(), "file://<home>"), (HOME, "<home>"))
    for path, name in pairs:
        text = text.replace(path, name)
    return text


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="model name, or fake:SCRIPT.json")
    parser.add_argument("--cases", nargs="*", default=[], help="generated: template:scenario")
    parser.add_argument("--projects", nargs="*", default=[], help="real projects from the manifest")
    parser.add_argument("--manifest", default=str(FIXFIRST / "examples" / "real-world" / "projects.toml"))
    parser.add_argument("--sources", default=str(FIXFIRST.parent / "agent-runs" / "_sources"),
                        help="folder with a git clone of each project at its release")
    parser.add_argument("--repairs", default=str(HERE / "reference_repairs.toml"),
                        help="known repairs, used only to compute the grader's reference outcome")
    parser.add_argument("--arms", nargs="+", default=["baseline", "mcp"], choices=["baseline", "fixfirst", "facts", "mcp"],
                        help="facts: FixFirst's observations only; mcp: its full diagnosis (both over MCP)")
    parser.add_argument("--call-policy", choices=CALL_POLICIES, default="server",
                        help="how the facts and mcp arms call FixFirst (see CALL_POLICIES)")
    parser.add_argument("--grading-policy", choices=pp.POLICIES, default=pp.LEGACY,
                        help="legacy: original grading; h5-v1: allow only persistent import/settings options")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--network", choices=["off", "on"], default="off")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--run-timeout", type=float, default=1800, help="the agent's seconds per run")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--attempt", help="a name for this invocation (default: time and a random suffix)")
    parser.add_argument("--out", default=str(FIXFIRST.parent / "agent-runs"))
    parser.add_argument("--hard-selection", help="the frozen selection of hard instances (qualify_hard.py); "
                                                 "hard cases then run only as selected and only with the frozen content")
    parser.add_argument("--hard-role", choices=hi.ROLES, help="which instances of the selection: formal or development")
    args = parser.parse_args(argv)
    if not args.cases and not args.projects:
        parser.error("give --cases or --projects")
    known = {t.name for t in dc.TEMPLATES}, {s.scenario_id for s in dc.SCENARIOS} | set(hi.hard_scenarios())
    unknown = [spec for spec in args.cases if spec.count(":") != 1 or spec.split(":")[0] not in known[0]
               or spec.split(":")[1] not in known[1]]
    if unknown:
        parser.error(f"not a template:scenario of the generated cases: {', '.join(unknown)}")
    if bool(args.hard_selection) != bool(args.hard_role):
        parser.error("--hard-selection and --hard-role go together")
    frozen, selection_digest = None, None
    if args.hard_selection:
        try:
            hi.load_registry()
            frozen = hi.selected(json.loads(Path(args.hard_selection).read_text(encoding="utf-8")), args.hard_role)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            parser.error(f"--hard-selection cannot be read: {type(error).__name__}: {error}")
        selection_digest = rc.file_hash(Path(args.hard_selection))
        outside = [spec for spec in args.cases if is_hard(spec) and spec not in frozen]
        if outside:
            parser.error(f"not the selection's {args.hard_role} instances: {', '.join(outside)}")
    if args.projects and "fixfirst" in args.arms:
        parser.error("the fixfirst arm is only for the generated cases of the 28 Sep pilot")
    if args.attempt and not re.fullmatch(r"[A-Za-z0-9._-]+", args.attempt):
        parser.error("--attempt may use letters, digits, dot, dash and underscore")
    out = Path(args.out).resolve()
    problem = check_output_folder(out, args.grading_policy)
    if problem:
        parser.error(problem)
    # What holds answers (a frozen selection carries the registered repairs; the known repairs; the source
    # clones with their later history) must be out of every run's reach, wherever the user keeps it.
    denied = (Path(HOME), out, FIXFIRST, *iso.SYSTEM_TEMP)
    answers = {"--hard-selection": args.hard_selection, "--repairs": args.repairs if args.projects else None,
               "--sources": args.sources if args.projects else None}
    try:  # every run's folders are made inside the output folder, so none of it may hold answers
        exposed = [f"{option} {args_path} {reason}" for option, args_path in answers.items() if args_path
                   for reason in [exposure(Path(args_path), denied, (out,))] if reason]
    except (OSError, KeyError) as error:
        parser.error(f"what the harness's sandboxes read cannot be established: {type(error).__name__}: {error}")
    if exposed:
        parser.error("a run could read the answers: " + "; ".join(exposed))
    protected = tuple(Path(os.path.realpath(answers[option])) for option in ("--hard-selection", "--repairs")
                      if answers[option])
    protected_folders = (Path(os.path.realpath(answers["--sources"])),) if answers["--sources"] else ()
    attempt = args.attempt or iso.new_attempt()
    if (out / "runs").exists() and any((out / "runs").glob(f"*--{attempt}")):
        parser.error(f"attempt {attempt} already has runs in {out}; runs are never overwritten")
    out.mkdir(parents=True, exist_ok=True)
    fake_path = Path(args.model.split(":", 1)[1]).resolve() if args.model.startswith("fake:") else None
    identity = f"fake-{fake_path.stem}-{iso.slug(str(fake_path))[-8:]}" if fake_path else args.model
    ctx = Context(out, identity, attempt, args.network == "on", denied=denied, protected=protected,
                  protected_folders=protected_folders, grading_policy=args.grading_policy)
    settings = Settings(args.max_turns, args.run_timeout, args.temperature, args.max_tokens, args.seed,
                        args.call_policy)
    manifest_path = Path(args.manifest).resolve()
    manifest = rc.load_manifest(manifest_path) if args.projects else {}
    repairs = rc.tomllib.loads(Path(args.repairs).read_text(encoding="utf-8")) if args.projects else {}
    harness = subprocess.run(["git", "rev-parse", "HEAD"], cwd=FIXFIRST, capture_output=True, text=True).stdout.strip()
    dirty = [line for line in subprocess.run(["git", "status", "--porcelain", "--", "src", "experiments/agent_baseline"],
                                             cwd=FIXFIRST, capture_output=True, text=True).stdout.splitlines() if line.strip()]
    unknown = [p for p in args.projects if p not in manifest]
    no_repair = [p for p in args.projects if p in manifest and p not in repairs]
    if unknown or no_repair:
        parser.error("; ".join([f"not in the manifest: {', '.join(unknown)}"] * bool(unknown)
                               + [f"no known repair in {args.repairs} (the grader needs a reference): "
                                  f"{', '.join(no_repair)}"] * bool(no_repair)))
    registration = {p: rc.install_fails_problems(manifest[p]) for p in args.projects}
    if any(registration.values()):
        parser.error("; ".join(f"{p}: {'; '.join(v)}" for p, v in registration.items() if v))
    references = {}
    work = [("generated", spec) for spec in args.cases] + [("real", pid) for pid in args.projects]
    for case_index, (kind, name) in enumerate(work):
        reference = None
        if kind == "real":
            project = manifest[name]
            source = Path(args.sources).resolve() / name
            snapshot = manifest_path.parent / "environments" / f"{name}.txt"
            try:
                reference = real_reference(ctx, project, source, snapshot, repairs[name]["repair"])
            except Exception as error:  # the per-case boundary: every planned run gets a row below
                reference = {"problems": [f"preparing the reference failed: {type(error).__name__}: {error}"[:500]],
                             "traceback": traceback.format_exc()[-3000:]}
        for run_index in range(1, args.runs + 1):
            for order, arm in enumerate(arm_order(args.arms, case_index, run_index - 1), start=1):
                row = {"model": args.model, "model_slug": iso.slug(identity), "attempt": attempt, "case": name,
                       "kind": kind, "arm": arm, "call_policy": args.call_policy, "run": run_index, "order": order,
                       "seed": args.seed,
                       "network": "on" if (ctx.network and kind == "real") else "off", "settings": vars(settings),
                       "harness_commit": harness, "uncommitted_changes": dirty, "end": None, "error": None,
                       "grading": None, "fixed": None}
                if args.grading_policy == pp.H5:
                    row.update(grading_policy=pp.H5, grading_policy_sha256=pp.identity())
                if kind == "real":  # every real row, also when its reference or setup failed
                    row["install_fails_registered"] = rc.install_fails_registered(project)
                elif is_hard(name):  # every row of a hard instance says under which selection it ran, if any
                    row.update(hard_role=args.hard_role, hard_selection=selection_digest)
                try:
                    if kind == "real" and reference["problems"]:
                        row.update(end="reference_invalid", error="; ".join(reference["problems"])[:500],
                                   grading="not_graded", reference_traceback=reference.get("traceback"),
                                   reference_cache_note=reference.get("cache_note"))
                    elif kind == "real":
                        run_real(ctx, row, settings, project, source, snapshot, reference, arm, run_index, fake_path)
                    else:
                        run_generated(ctx, row, settings, name, arm, run_index, fake_path, references, frozen)
                except Exception as error:  # the per-run boundary: record it and go on to the next run
                    row.update(end=row.get("end") or "harness_error", grading="not_graded", fixed=None,
                               error=f"{type(error).__name__}: {error}"[:500],
                               traceback=traceback.format_exc()[-3000:])
                finally:
                    text = redact(json.dumps(row, ensure_ascii=False, default=str), out)
                    print(text, flush=True)
                    with (out / "results.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(text + "\n")
                    if row.get("run_dir"):
                        (out / row["run_dir"] / "row.json").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
