"""FixFirst as an MCP server over stdio, for coding agents.

Implements the tools part of the Model Context Protocol without extra dependencies: JSON-RPC
2.0 messages, one per line, on stdin and stdout (initialize, ping, tools/list, tools/call).
The tools use the same service functions, the same plain-language view (workspace.build_view)
and the same session store as the web interface, so `fixfirst serve` shows what an agent did.
FixFirst still never edits code: the agent changes the code, FixFirst diagnoses and confirms
the fix with a real check.
"""

import contextlib
import json
import signal
import sys
from pathlib import Path

from . import __version__
from .processes import ProcessScope
from .reasoning import infer_and_plan
from .service import create_session, scan
from .storage import Store
from .workspace import GOAL_CHOICES, build_view, inspect_folder

# Newest first. A client asking for one of these gets it back; otherwise the newest is offered.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_STEPS = 5

INSTRUCTIONS = (
    "FixFirst explains why a Python project's checks fail and confirms fixes with real checks. "
    "Call diagnose once before changing anything. Fix the first step it lists, then call "
    "check_again: a problem only counts as fixed when check_again reports it fixed. When the "
    "status says the goal is reached, stop. Use explain for the error, rules and sources behind "
    "a step. FixFirst runs the project's checks (tests execute project code) but never edits files."
)

GOALS = [key for key, _, _ in GOAL_CHOICES]
SESSION_ID = {"type": "string", "description": "Session from diagnose. Default: the latest one."}

TOOLS = [
    {
        "name": "diagnose",
        "title": "Diagnose a Python project",
        "description": (
            "Run the project's program or existing tests, plus available environment checks, and explain "
            "each failure: the root cause, where it is and the next steps, most important first. "
            "Call it before changing code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Absolute path of the project folder."},
                "python": {
                    "type": "string",
                    "description": "Interpreter that runs the project. Default: the project's .venv, "
                    "venv or env, otherwise FixFirst's own Python.",
                },
                "goal": {
                    "type": "string",
                    "enum": ["auto", *GOALS],
                    "description": "auto (default): suggest existing tests or a program entry; run_project: "
                    "run a script/module/notebook; pass_tests: pytest; pass_unittest: unittest; "
                    "collect_tests: pytest collection; check_style: Ruff.",
                },
                "execution": {
                    "type": "object",
                    "description": "Program entry or unittest settings. No shell command parsing.",
                    "properties": {
                        "kind": {"type": "string", "enum": ["script", "module", "notebook", "unittest"]},
                        "entry": {"type": "string"},
                        "args": {"type": "array", "items": {"type": "string"}},
                        "stdin": {"type": "string"},
                        "pattern": {"type": "string"},
                    },
                    "required": ["kind", "entry"], "additionalProperties": False,
                },
            },
            "required": ["project"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "check_again",
        "title": "Check again after a change",
        "description": (
            "Re-run the checks of a session after you changed the code. Reports what is now fixed, "
            "what is new and the next step."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": SESSION_ID},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "explain",
        "title": "Explain a step",
        "description": (
            "Show the evidence behind one step of the latest list: the error, the rules that "
            "concluded it, the documentation they rely on and the checks that ran. Runs nothing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": SESSION_ID,
                "step": {"type": "integer", "minimum": 1, "description": "Step number (default 1)."},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
]


class ToolError(Exception):
    """A problem the agent can act on; reported in the tool result, not as a protocol error."""


def _check_arguments(name, arguments):
    schema = next(t["inputSchema"] for t in TOOLS if t["name"] == name)
    if not isinstance(arguments, dict):
        raise ToolError(f"{name} expects an object of arguments")
    unknown = sorted(set(arguments) - set(schema["properties"]))
    missing = [key for key in schema.get("required", []) if not arguments.get(key)]
    if unknown or missing:
        raise ToolError(
            f"Invalid arguments for {name}: "
            + "; ".join(filter(None, [
                f"unknown {', '.join(unknown)}" if unknown else "",
                f"missing {', '.join(missing)}" if missing else "",
            ]))
            + f". Accepted: {', '.join(schema['properties'])}."
        )


class Server:
    def __init__(self, store_root):
        self.store = Store(store_root)
        self.sessions: dict[tuple, str] = {}  # (project, python, goal) -> session id
        self.latest: str | None = None

    # ----- protocol ---------------------------------------------------------------------------

    def handle(self, message) -> dict | None:
        """Answer one JSON-RPC message; notifications get no answer."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
            return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request")
        if "id" not in message:
            return None  # notifications/initialized, notifications/cancelled, ...
        request_id, method, params = message["id"], message["method"], message.get("params") or {}
        if method == "initialize":
            asked = params.get("protocolVersion")
            return _result(request_id, {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "fixfirst", "title": "FixFirst", "version": __version__},
                "instructions": INSTRUCTIONS,
            })
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/list":
            return _result(request_id, {"tools": TOOLS})
        if method == "tools/call":
            name, arguments = params.get("name"), params.get("arguments") or {}
            tool = {"diagnose": self.diagnose, "check_again": self.check_again, "explain": self.explain}.get(name)
            if tool is None:
                return _error(request_id, -32602, f"Unknown tool: {name}")
            try:
                _check_arguments(name, arguments)
                # Anything a check prints must not reach stdout, which carries the protocol.
                with contextlib.redirect_stdout(sys.stderr):
                    text, failed = tool(**arguments), False
            except (ToolError, ValueError, OSError, KeyError) as exc:
                text, failed = str(exc).strip("'\"") or type(exc).__name__, True
            except Exception as exc:  # a bug must not end the agent's session with FixFirst
                text, failed = f"FixFirst failed: {type(exc).__name__}: {exc}", True
            return _result(request_id, {"content": [{"type": "text", "text": text}], "isError": failed})
        return _error(request_id, -32601, f"Method not found: {method}")

    # ----- tools ------------------------------------------------------------------------------

    def diagnose(self, project, python=None, goal="auto", execution=None):
        if goal not in ["auto", *GOALS]:
            raise ToolError(f"Unknown goal {goal!r}; use one of {', '.join(GOALS)}")
        folder = inspect_folder(str(project), python or None)
        if not folder["ok"]:
            raise ToolError(folder.get("error") or "; ".join(folder["warnings"]))
        interpreter = folder["python"]["path"]
        session = create_session(folder["path"], interpreter, goal=goal, execution=execution)
        key = (folder["path"], interpreter, session.goal,
               session.execution.model_dump_json() if session.execution else "")
        notes = [f"Python: {interpreter} ({folder['python']['origin']})", *folder["warnings"]]
        if key in self.sessions:
            # A second diagnose continues the session, so earlier fixes stay verified.
            notes.insert(0, "Continuing the session started earlier; this is the same as check_again.")
            return self.check_again(self.sessions[key], notes)
        with self.store.lock(session.session_id):
            infer_and_plan(session)
            scan(session)
            self.store.save(session)
        self.sessions[key] = self.latest = session.session_id
        return render(session, build_view(session), notes)

    def check_again(self, session_id=None, notes=()):
        session_id = self._session_id(session_id)
        with self.store.lock(session_id):
            session = self.store.load(session_id)
            before = {i.issue_id: i.status for i in session.issues}
            scan(session)
            self.store.save(session)
        self.latest = session_id
        fixed = [i.title for i in session.issues if i.status == "resolved" and before.get(i.issue_id) != "resolved"]
        new = [i.title for i in session.issues if i.issue_id not in before and i.status == "open"]
        changes = []
        if fixed:
            changes.append("Fixed since the last check: " + "; ".join(t[:120] for t in fixed))
        if new:
            changes.append("New since the last check: " + "; ".join(t[:120] for t in new))
        if not fixed and not new:
            changes.append("Nothing changed since the last check.")
        return render(session, build_view(session), [*notes, *changes])

    def explain(self, session_id=None, step=1):
        session_id = self._session_id(session_id)
        session = self.store.load(session_id)
        view = build_view(session)
        lines = [f"FixFirst session {session_id} · status: {view['status']['headline']}"]
        steps = _numbered(view)
        if steps:
            if not 1 <= int(step) <= len(steps):
                raise ToolError(f"There are {len(steps)} steps; choose one from 1 to {len(steps)}")
            chosen = steps[int(step) - 1]
            lines += _step(int(step), chosen, explanation_limit=None)
            lines += [f"   Error: {error}" for error in chosen["errors"][:3]]
            lines += [f"   Rule {rule}" for rule in chosen["rules"]]
            lines += [f"   Source: {s['title']} <{s['url']}>" for s in chosen["sources"] if s.get("url")]
            if chosen["suspected"]:
                lines.append("   No rule matched the evidence: this is the decision tree's best guess "
                             "from similar cases. Check it against the error before acting on it.")
        else:
            lines.append("No step is open for this goal.")
        lines.append("Checks recorded (latest last):")
        for run in session.runs[-6:]:
            summary = run.test_summary or {}
            counts = ", ".join(f"{v} {k}" for k, v in summary.items() if isinstance(v, int) and v)
            lines.append(f"   {run.tool}: {run.status}" + (f" ({counts})" if counts else ""))
        return "\n".join(lines)

    def _session_id(self, session_id):
        session_id = session_id or self.latest
        if not session_id:
            raise ToolError("No session yet: call diagnose with the project folder first.")
        # Check before locking: the lock would create a directory for an unknown id.
        if not (self.store.directory(session_id) / "session.json").is_file():
            raise ToolError(f"Unknown session {session_id}: call diagnose with the project folder first.")
        return session_id


# ----- plain-text view for an agent ------------------------------------------------------------


def _plain(text: str) -> str:
    """The web page asks the user to press a button; an agent calls the tool instead."""
    return text.replace("press Check again", "call check_again").replace("Press Check again", "Call check_again")


def _numbered(view) -> list[dict]:
    """Must-fix steps first, then optional ones; the numbers explain() accepts."""
    return [] if view["status"]["kind"] == "done" else view["steps"] + view["optional"]


def _step(number, step, explanation_limit=600) -> list[str]:
    lines = [f"{number}. {step['title']}" + (" (optional)" if step["optional"] else "")]
    if step["optional"]:
        lines.append("   Optional: this does not change how the code runs; fix it if every test must pass.")
        if step["impact"]:
            lines.append(f"   Impact: {step['impact']}")
    if step["where"]:
        lines.append("   Where: " + ", ".join(step["where"][:4]) + (" ..." if len(step["where"]) > 4 else ""))
    rules = [rule.split(":", 1)[0] for rule in step["rules"]]
    if step["suspected"]:
        lines.append(f"   Possible cause, not confirmed (decision tree): {step['cause']}")
    elif step["cause"]:
        lines.append(f"   Cause: {step['cause']}" + (f" (rule {', '.join(rules)})" if rules else ""))
    if step["possible"]:
        lines.append(f"   Likely cause, not confirmed: {step['possible']}")
    explanation = step["explanation"] or ""
    if explanation_limit and len(explanation) > explanation_limit:
        explanation = explanation[:explanation_limit].rsplit(" ", 1)[0] + " ... (explain shows the rest)"
    if explanation:
        lines.append(f"   Why: {explanation}")
    if step["command"]:
        lines.append(f"   Command: {step['command']}")
    if step["gather"]:
        lines.append("   FixFirst collects this itself: call check_again.")
    if step["search"]:
        lines.append("   The web interface's Find it can search releases for this (needs internet).")
    if step["confirm"]:
        lines.append(f"   Confirm: {step['confirm']}")
    return lines


def render(session, view, notes=()) -> str:
    status = view["status"]
    lines = [
        f"FixFirst session {session.session_id} · project {view['project']} · goal: {view['goal_name']}",
        f"Status: {status['headline']}. {_plain(status['detail'])}",
    ]
    if status["kind"] == "done":
        lines.append("The goal is reached and verified by a real check. Nothing else is needed for it.")
    if status["kind"] in ("baseline_changed", "baseline_unverifiable"):
        lines.append("Only a person can accept changed tests as the new baseline (FixFirst's web page or "
                     "`fixfirst accept-baseline`); restore them, or ask the user.")
    lines += notes
    steps = _numbered(view)
    if steps:
        lines += ["", "Steps, most important first:"]
        for number, step in enumerate(steps[:MAX_STEPS], 1):
            lines += _step(number, step)
        if len(steps) > MAX_STEPS:
            lines.append(f"({len(steps) - MAX_STEPS} more steps; fix these first, then check again.)")
    if view["other"]:
        other = view["other"]
        shown = "; ".join(s["title"] for s in other[:3]) + ("; ..." if len(other) > 3 else "")
        lines += ["", f"Other findings that do not block this goal ({len(other)}): {shown}"]
    if view["pending"]:
        lines.append(f"Waiting to be re-checked ({len(view['pending'])}): an earlier error stopped the check "
                     "before these; they are checked again once the steps above are fixed.")
    if view["fixed"]:
        fixed = "; ".join(item["title"][:100] for item in view["fixed"][:5])
        lines += ["", f"Fixed and verified ({len(view['fixed'])}): {fixed}"]
    return "\n".join(lines)


# ----- stdio loop ------------------------------------------------------------------------------


def _result(request_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve(store_root, stdin=None, stdout=None) -> int:
    """Read JSON-RPC messages from stdin until it closes; answer each on stdout."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    server = Server(Path(store_root))
    scope = ProcessScope()
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"FixFirst MCP server {__version__} ready; sessions in {server.store.root}", file=sys.stderr, flush=True)

    def send(answer):
        stdout.write(json.dumps(answer, ensure_ascii=False).encode("utf-8") + b"\n")
        stdout.flush()

    try:
        with scope.activate():
            for raw in stdin:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    send(_error(None, -32700, "Parse error"))
                    continue
                batch = message if isinstance(message, list) else [message]
                answers = [a for a in (server.handle(m) for m in batch) if a is not None]
                if answers:
                    send(answers if isinstance(message, list) else answers[0])
    finally:
        scope.cancel()  # stop any check that is still running
    return 0
