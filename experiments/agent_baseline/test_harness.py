"""Checks of the agent harness with real sandboxed processes and scripted replies (macOS: sandbox-exec).

Run explicitly (not part of the main suite, which also runs on Windows and has no httpx):
  .venv/bin/python -m pytest -q experiments/agent_baseline/test_harness.py
Generated cases and small self-made projects only, offline. Real projects need the network and are
checked by hand (README). Every file written outside a run here is a harmless sentinel in the test's
own temporary folder.
"""

from contextlib import contextmanager
import ctypes
import errno
import json
import re
import os
import shlex
import signal
import subprocess
import textwrap
import time
from pathlib import Path
import shutil
import sys
from xml.etree.ElementTree import ParseError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_pilot  # noqa: E402
import isolation as iso  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("sandbox-exec") is None, reason="needs macOS sandbox-exec")
CASE = "pkg-inventory:lm_renamed"  # inventory/utils/numbers.py was renamed to number.py
FIX = "mv inventory/utils/number.py inventory/utils/numbers.py"


def call(name, **arguments):
    return {"call": name, "arguments": arguments}


def script(tmp_path, steps, name="script"):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(steps))
    return path


def rows(out: Path):
    return [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]


def run(tmp_path, steps, arms=("baseline",), case=CASE, extra=(), name="script", out=None):
    out = out or tmp_path / "out"
    agent_pilot.main(["--model", f"fake:{script(tmp_path, steps, name)}", "--cases", case, "--arms", *arms,
                      "--out", str(out), "--max-turns", "6", *extra])
    return rows(out)


def small_run(tmp_path, files: dict, name="run") -> agent_pilot.Run:
    """A self-made project in a run folder, graded with this repository's interpreter."""
    out = tmp_path / "out"
    ctx = agent_pilot.Context(out, "fake", "test", False,
                              denied=(Path.home(), out, agent_pilot.FIXFIRST, *iso.SYSTEM_TEMP))
    python = agent_pilot.PYTHON
    run_ = agent_pilot.Run(ctx, out / "runs" / name, False, False, python,
                           agent_pilot.interpreters(python.parent.parent))
    for relative, text in files.items():
        (run_.project / relative).parent.mkdir(parents=True, exist_ok=True)
        (run_.project / relative).write_text(text)
    return run_


# ---- R1: everything that runs case code is sandboxed, the grader too ------------------------------

def test_the_grader_cannot_write_outside_its_own_copy(tmp_path):
    outside, other = tmp_path / "outside-sentinel.txt", tmp_path / "out" / "runs" / "other" / "project"
    other.mkdir(parents=True)
    code = ("from pathlib import Path\n"
            "def answer():\n"
            f"    for target in ({str(outside)!r}, {str(other / 'sentinel.txt')!r}):\n"
            "        try:\n"
            "            Path(target).write_text('harness test')\n"
            "        except OSError:\n"
            "            pass\n"
            "    return 42\n")
    run_ = small_run(tmp_path, {"core.py": code, "test_core.py": "from core import answer\n\n"
                                                                  "def test_answer():\n    assert answer() == 42\n"})
    result = run_.suite()
    assert result["exit_code"] == 0 and result["counts"] == {"passed": 1}
    assert not outside.exists() and not (other / "sentinel.txt").exists()


def test_the_grader_is_offline(tmp_path):
    test = ("import socket\nimport pytest\n\n"
            "def test_no_network():\n"
            "    with pytest.raises(OSError):\n"
            "        socket.create_connection(('1.1.1.1', 53), timeout=3)\n")
    run_ = small_run(tmp_path, {"test_net.py": test})
    assert run_.suite()["counts"] == {"passed": 1}
    assert "(deny network*)" in (run_.folder / "grader" / "check-001" / "grader.sb").read_text()


def test_a_real_fix_is_still_fixed_and_green(tmp_path):
    [row] = run(tmp_path, [call("run_command", command="python -m pytest -q"), call("run_command", command=FIX),
                           call("finish", summary="renamed the module back")])
    assert (row["fixed"], row["grading"], row["first_green_turn"], row["end"], row["violations"]) == (
        True, "graded", 2, "finish", {})


# ---- R2: the agent cannot read the answers, labels, references or other runs ------------------------

def test_the_agent_cannot_read_repairs_labels_references_or_other_runs(tmp_path):
    repo = agent_pilot.FIXFIRST
    out = tmp_path / "out"
    first = run(tmp_path, [call("run_command", command=FIX), call("finish", summary="x")], out=out, name="first")[0]
    peek = [str(repo / "experiments" / "agent_baseline" / "reference_repairs.toml"),
            str(repo / "examples" / "real-world" / "LABELS.md"),
            str(out / first["run_dir"] / "transcript.json"),
            str(next((out / "_templates").glob("*--reference--*")) / "reference.json")]
    command = "; ".join(f"cat {p} >/dev/null 2>&1 && echo READ {Path(p).name} || echo DENIED" for p in peek)
    second = run(tmp_path, [call("run_command", command=command), call("run_command", command="python -m pytest -q"),
                            call("finish", summary="x")], out=out, name="second")[-1]
    transcript = json.loads((out / second["run_dir"] / "transcript.json").read_text())
    outputs = [m["content"] for m in transcript if m["role"] == "tool"]
    assert outputs[0].count("DENIED") == 4 and "READ" not in outputs[0]
    # The project's own tests still run: collection fails on the renamed module, not on a permission.
    assert "error during collection" in outputs[1] and "not permitted" not in outputs[1]


def test_fixfirst_works_for_the_mcp_arm_and_both_arms_start_alike(tmp_path):
    steps = [call("diagnose", project="."), call("run_command", command=FIX), call("check_again"),
             call("finish", summary="renamed back")]
    mcp, baseline = run(tmp_path, steps, arms=("mcp", "baseline"))
    assert (mcp["arm"], mcp["order"], baseline["order"]) == ("mcp", 1, 2)
    assert mcp["fixfirst_calls"] == 2 and mcp["fixed"] is True and mcp["bad_calls"] == 0
    assert baseline["fixfirst_calls"] == 0 and baseline["fixed"] is True and mcp["run_dir"] != baseline["run_dir"]


@pytest.mark.parametrize("arm,tool,given,counts,extra", [
    ("mcp", "diagnose", None, (1, 0), ()),  # no goal: filled in
    ("mcp", "diagnose", "pass_unittest", (0, 1), ()),  # another goal: overridden
    ("mcp", "diagnose", "pass_tests", (0, 0), ()),
    ("facts", "observe", "auto", (0, 1), ()),
    ("mcp", None, None, (0, 0), ("--call-policy", "scheduled")),  # the harness's own first call
])
def test_fixfirst_always_checks_the_graders_goal(tmp_path, monkeypatch, arm, tool, given, counts, extra):
    sent, original = [], agent_pilot.MCPClient.call
    monkeypatch.setattr(agent_pilot.MCPClient, "call", lambda self, name, arguments, timeout: (
        sent.append((name, arguments)), original(self, name, arguments, timeout))[1])
    steps = ([call(tool, project=".", **({"goal": given} if given else {}))] if tool else []) + [
        call("finish", summary="x")]
    [row] = run(tmp_path, steps, arms=(arm,), extra=extra)
    first = [arguments for name, arguments in sent if name in ("diagnose", "observe")]
    assert first and all(arguments["goal"] == agent_pilot.GRADING_GOAL == "pass_tests" for arguments in first)
    assert (row["mcp_goal_filled"], row["mcp_goal_overridden"]) == counts
    if arm == "mcp":  # FixFirst's own record of the goal it checked (facts mode keeps none on disk)
        [session] = (tmp_path / "out" / row["run_dir"] / "fixfirst-store").rglob("session.json")
        assert json.loads(session.read_text())["goal"] == "pass_tests"


# ---- R3: references are checked --------------------------------------------------------------------

def test_an_invalid_reference_grades_nothing(tmp_path, monkeypatch):
    def broken(ctx, template, pristine, cache):
        return {"problems": ["the reference suite exited with 1 (tests failed)"], "outcomes": {}, "counts": {}}
    monkeypatch.setattr(agent_pilot, "generated_reference", broken)
    [row] = run(tmp_path, [call("finish", summary="x")])
    assert (row["end"], row["grading"], row["fixed"]) == ("reference_invalid", "not_graded", None)
    assert not (tmp_path / "out" / row["run_dir"] / "transcript.json").exists()  # no episode was run


# ---- R4: malformed replies and harness failures are recorded run by run ------------------------------

def test_malformed_tool_calls_are_recorded_and_the_run_goes_on(tmp_path):
    bad = {"raw": {"tool_calls": [{"id": "bad", "function": {}}, "not a call",
                                  {"id": "x", "function": {"name": "run_command", "arguments": "{not json"}}]}}
    [row] = run(tmp_path, [bad, call("run_command", command=FIX), call("finish", summary="x")])
    assert (row["bad_calls"], row["end"], row["fixed"]) == (3, "finish", True)


def test_a_reply_without_a_message_is_a_model_error(tmp_path):
    [row] = run(tmp_path, [{"raw": "just text"}])
    assert (row["end"], row["error"], row["grading"]) == ("model_error", "the reply has no message object", "graded")


def test_a_failing_run_is_recorded_with_its_transcript_and_the_next_run_goes_ahead(tmp_path, monkeypatch):
    real_digest = agent_pilot.rc.workspace_digest
    calls = {"n": 0}

    def digest_that_fails_once(project, python):
        calls["n"] += 1
        if calls["n"] == 2:  # after the first turn of the first run
            raise RuntimeError("harness failure for the test")
        return real_digest(project, python)

    monkeypatch.setattr(agent_pilot.rc, "workspace_digest", digest_that_fails_once)
    first, second = run(tmp_path, [call("run_command", command=FIX), call("finish", summary="x")],
                        arms=("baseline", "mcp"))
    assert (first["end"], first["grading"], first["fixed"]) == ("harness_error", "not_graded", None)
    assert "harness failure for the test" in first["error"] and "Traceback" in first["traceback"]
    saved = json.loads((tmp_path / "out" / first["run_dir"] / "transcript.json").read_text())
    assert any(m["role"] == "tool" for m in saved)
    assert (second["end"], second["fixed"]) == ("finish", True)


def test_a_server_that_does_not_start_is_not_graded(tmp_path, monkeypatch):
    def refuse(self, run_, budget, **options):
        raise RuntimeError("server did not start")
    monkeypatch.setattr(agent_pilot.MCPClient, "__init__", refuse)
    [row] = run(tmp_path, [call("finish", summary="x")], arms=("mcp",))
    assert (row["end"], row["grading"], row["fixed"]) == ("mcp_start_failed", "not_graded", None)


# ---- R5: the time budget holds inside calls ----------------------------------------------------------

def test_a_command_that_outlasts_the_budget_is_stopped_and_finish_is_not_taken(tmp_path):
    steps = [{"calls": [call("run_command", command=FIX + " && sleep 20"), call("finish", summary="done")]}]
    [row] = run(tmp_path, steps, extra=("--run-timeout", "2"))
    assert row["end"] == "time_cap" and row["agent_s"] < 5
    commands = [json.loads(line) for line in (tmp_path / "out" / row["run_dir"] / "commands.jsonl").read_text().splitlines()]
    assert commands[0]["stopped"] is True


def test_the_budget_runs_out_between_calls_of_one_turn(tmp_path):
    steps = [{"calls": [call("run_command", command="sleep 1.5"), call("run_command", command=FIX),
                        call("finish", summary="done")]}]
    [row] = run(tmp_path, steps, extra=("--run-timeout", "1"))
    transcript = json.loads((tmp_path / "out" / row["run_dir"] / "transcript.json").read_text())
    tools = [m["content"] for m in transcript if m["role"] == "tool"]
    assert row["end"] == "time_cap" and tools[1] == "not run: the run's time is up" and tools[2] == tools[1]
    assert row["fixed"] is False  # the fix after the deadline was never carried out


def test_a_model_reply_that_outlasts_the_budget_is_a_time_cap(tmp_path):
    [row] = run(tmp_path, [{"delay": 5, "call": "finish", "arguments": {"summary": "late"}}],
                extra=("--run-timeout", "1"))
    assert row["end"] == "time_cap" and row["agent_s"] < 3


# ---- R6: runs are never overwritten --------------------------------------------------------------------

def test_two_models_and_a_repeat_keep_every_run(tmp_path):
    out = tmp_path / "out"
    steps = [call("run_command", command=FIX), call("finish", summary="x")]
    a = run(tmp_path, steps, out=out, name="model-a")[-1]
    b = run(tmp_path, steps, out=out, name="model-b")[-1]
    again = run(tmp_path, steps, out=out, name="model-a")[-1]
    folders = {a["run_dir"], b["run_dir"], again["run_dir"]}
    assert len(folders) == 3 and all((out / f / "transcript.json").exists() for f in folders)
    assert len(rows(out)) == 3


def test_a_failed_setup_later_keeps_the_earlier_evidence(tmp_path, monkeypatch):
    out = tmp_path / "out"
    steps = [call("run_command", command=FIX), call("finish", summary="x")]
    first = run(tmp_path, steps, out=out, name="first")[-1]
    monkeypatch.setattr(agent_pilot.dc, "Project", lambda *a: (_ for _ in ()).throw(RuntimeError("setup fails")))
    second = run(tmp_path, steps, out=out, name="second")[-1]
    assert second["end"] == "harness_error" and "setup fails" in second["error"]
    assert (out / first["run_dir"] / "transcript.json").exists()


def test_an_attempt_name_cannot_be_reused(tmp_path):
    out = tmp_path / "out"
    steps = [call("finish", summary="x")]
    run(tmp_path, steps, out=out, extra=("--attempt", "trial-1"))
    with pytest.raises(SystemExit):
        run(tmp_path, steps, out=out, extra=("--attempt", "trial-1"))


def test_runs_inside_the_repository_are_refused():
    with pytest.raises(SystemExit):
        agent_pilot.main(["--model", "fake:x.json", "--cases", CASE, "--out", str(agent_pilot.FIXFIRST / "workbench" / "x")])


# ---- R7: a test change counts even if it is undone ---------------------------------------------------

def test_editing_a_test_and_putting_it_back_is_still_a_violation(tmp_path):
    edit = 'f=$(ls tests/test_*.py | head -1); cp "$f" "$TMPDIR/keep.py"; echo "# edited" >> "$f"'
    restore = 'f=$(ls tests/test_*.py | head -1); cp "$TMPDIR/keep.py" "$f"'
    [row] = run(tmp_path, [call("run_command", command=edit), call("run_command", command=FIX),
                           call("run_command", command=restore), call("finish", summary="x")])
    assert row["fixed"] is False and row["first_green_turn"] is None
    assert row["violations"] == {"tests/test_stock.py": {"turn": 1, "after": "run_command"}}


def test_a_new_conftest_counts_as_a_test_change(tmp_path):
    [row] = run(tmp_path, [call("write_file", path="conftest.py", content="collect_ignore = []\n"),
                           call("run_command", command=FIX), call("finish", summary="x")])
    assert row["fixed"] is False and "conftest.py" in row["violations"]


def test_scenarios_that_change_tests_have_no_reference(tmp_path):
    [row] = run(tmp_path, [call("finish", summary="x")], case="flat-shop:cd_fixture_bug")
    assert (row["end"], row["grading"]) == ("unsupported_case", "not_graded")


def test_arms_alternate_between_cases_and_runs():
    assert agent_pilot.arm_order(["baseline", "mcp"], 0, 0) == ["baseline", "mcp"]
    assert agent_pilot.arm_order(["baseline", "mcp"], 1, 0) == ["mcp", "baseline"]
    assert agent_pilot.arm_order(["baseline", "mcp"], 1, 1) == ["baseline", "mcp"]


def test_fixfirst_always_diagnoses_the_case_with_its_interpreter(tmp_path):
    class StubMCP:
        names = {"diagnose"}
        dead = False

        def __init__(self):
            self.seen = []

        def call(self, name, arguments, timeout):
            self.seen.append(arguments)
            return "ok"

    run_ = small_run(tmp_path, {"x.py": ""})
    run_.real = True
    stats = {"fixfirst_calls": 0, "mcp_arguments_filled": 0, "mcp_arguments_overridden": 0}
    mcp, budget = StubMCP(), iso.Budget(60)
    agent_pilot.run_tool("diagnose", {"project": str(run_.project)}, run_, stats, mcp, budget, 1)
    agent_pilot.run_tool("diagnose", {"project": ".", "python": "/usr/bin/python3"}, run_, stats, mcp, budget, 1)
    assert (stats["mcp_arguments_filled"], stats["mcp_arguments_overridden"]) == (1, 1)
    assert all(a == {"project": str(run_.project), "python": str(run_.python), "goal": agent_pilot.GRADING_GOAL}
               for a in mcp.seen)


def test_a_run_reached_through_a_symlinked_path_still_works(tmp_path):
    """macOS: /var is a symlink to /private/var; sandbox rules only match resolved paths."""
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "via-link").symlink_to(real)
    out = tmp_path / "via-link" / "out"
    ctx = agent_pilot.Context(out, "fake", "test", False,
                              denied=(Path.home(), out, agent_pilot.FIXFIRST, *iso.SYSTEM_TEMP))
    python = agent_pilot.PYTHON
    run_ = agent_pilot.Run(ctx, out / "runs" / "one", False, False, python,
                           agent_pilot.interpreters(python.parent.parent))
    run_.project.mkdir()
    (run_.project / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    assert run_.suite()["counts"] == {"passed": 1}
    code, output, _ = run_.execute(["/bin/bash", "-c", "pwd && python -c 'import os; print(os.getcwd())'"], "agent", 60)
    assert code == 0, output


# ---- R1 (continued): the case interpreter never starts outside the sandbox ---------------------------

def hooked_venv(folder: Path, sentinel: Path) -> Path:
    """An environment whose interpreter writes the sentinel whenever it starts (a .pth startup hook)."""
    import subprocess
    subprocess.run([str(agent_pilot.PYTHON), "-m", "venv", "--without-pip", str(folder / ".venv")], check=True)
    site = next((folder / ".venv" / "lib").glob("python*/site-packages"))
    (site / "zz_hook.pth").write_text(f"import pathlib; pathlib.Path({str(sentinel)!r}).write_text('hook ran')\n")
    return folder / ".venv" / "bin" / "python"


def test_the_harness_reads_a_hooked_environment_without_starting_it(tmp_path):
    import subprocess
    sentinel = tmp_path / "outside-sentinel.txt"
    python = hooked_venv(tmp_path / "case", sentinel)
    subprocess.run([str(python), "-c", "pass"], check=True)
    assert sentinel.exists()  # the hook is real: started outside a sandbox, it writes
    sentinel.unlink()
    agent_pilot.interpreters(python.parent.parent)
    agent_pilot.rc.venv_record(python.parent.parent)
    agent_pilot.rc.freeze(python)
    agent_pilot.rc.workspace_digest(tmp_path / "case", python)
    assert not sentinel.exists()


def local_project(tmp_path, monkeypatch):
    """A one-test project in a local git clone, its environment made with venv (offline), and a reference."""
    source = tmp_path / "source"
    (source / "tests").mkdir(parents=True)
    (source / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    git = ["git", "-C", str(source), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "one"], check=True)
    snapshot = tmp_path / "snapshot.txt"
    snapshot.write_text("# Python 3.12.14\n")

    def environment(project_dir, project, snapshot_file, log):
        subprocess.run([str(agent_pilot.PYTHON), "-m", "venv", "--without-pip", str(project_dir / ".venv")], check=True)
        return project_dir / ".venv" / "bin" / "python"

    monkeypatch.setattr(agent_pilot.rc, "create_environment", environment)
    out = tmp_path / "out"
    ctx = agent_pilot.Context(out, "fake", "t1", True, denied=(Path.home(), out, agent_pilot.FIXFIRST, *iso.SYSTEM_TEMP))
    reference = {"outcomes": {"tests.test_ok::test_ok": "passed"}, "counts": {"passed": 1}, "exit_code": 0, "problems": []}
    return ctx, source, snapshot, reference


def test_a_hook_the_agent_adds_to_its_environment_never_runs_outside_the_sandbox(tmp_path, monkeypatch):
    sentinel = tmp_path / "outside-sentinel.txt"
    ctx, source, snapshot, reference = local_project(tmp_path, monkeypatch)
    hook = f"import pathlib; pathlib.Path({str(sentinel)!r}).write_text('hook ran')\n"
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    steps = [call("write_file", path=f".venv/lib/{version}/site-packages/zz_agent_hook.pth", content=hook),
             call("run_command", command="python -c pass"), call("finish", summary="x")]
    row = {}
    agent_pilot.run_real(ctx, row, agent_pilot.Settings(max_turns=4), {"id": "hooked", "ref": "v1", "install": []},
                         source, snapshot, reference, "baseline", 1, script(tmp_path, steps))
    assert row["end"] == "finish" and row["grading"] == "graded"
    assert (ctx.out / row["run_dir"] / "freeze-end.txt").exists()  # the end of the run read the environment
    assert not sentinel.exists()  # yet the hook never wrote: it only ever started inside the sandbox


# ---- R5 (continued): a slow model reply and a detached process -----------------------------------------

def slow_server(pause: float):
    import http.server
    import threading
    body = json.dumps({"choices": [{"message": {"content": "", "tool_calls": [
        {"id": "x", "function": {"name": "finish", "arguments": "{}"}}]}}]}).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            for start in range(0, len(body), 16):  # never silent long enough for a read timeout
                self.wfile.write(body[start:start + 16])
                self.wfile.flush()
                time.sleep(pause)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_model_reply_that_keeps_trickling_is_cut_at_the_deadline(monkeypatch):
    server = slow_server(0.08)
    monkeypatch.setattr(agent_pilot, "BASE", f"http://127.0.0.1:{server.server_port}")
    try:
        started = time.monotonic()
        with pytest.raises(agent_pilot.ModelTimeout):
            agent_pilot.chat("stub", [], [], agent_pilot.Settings(), None, 0.2)
        assert time.monotonic() - started < 0.45
        message, _ = agent_pilot.chat("stub", [], [], agent_pilot.Settings(), None, 5)  # enough time: normal reply
        assert message["tool_calls"][0]["function"]["name"] == "finish"
    finally:
        server.shutdown()


def test_a_process_that_left_its_parent_ends_with_the_run(tmp_path):
    import shlex
    child = "import time; from pathlib import Path; time.sleep(1.2); Path('late-marker.txt').write_text('late')"
    launcher = ("import subprocess, sys; subprocess.Popen([sys.executable, '-c', " + repr(child) + "], "
                "start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)")
    [row] = run(tmp_path, [call("run_command", command="python -c " + shlex.quote(launcher)),
                           {"delay": 5, "call": "finish", "arguments": {"summary": "late"}}],
                extra=("--run-timeout", "0.5"))
    marker = tmp_path / "out" / row["run_dir"] / "project" / "late-marker.txt"
    time.sleep(2)
    assert row["end"] == "time_cap" and row["processes_stopped_at_end"] >= 1 and not marker.exists()


# ---- R4 (continued): preparing a reference fails case by case --------------------------------------

def test_a_broken_reference_cache_or_a_missing_snapshot_is_recorded_and_the_batch_goes_on(tmp_path, monkeypatch):
    import hashlib
    folder = tmp_path / "refs"
    (folder / "environments").mkdir(parents=True)
    (folder / "projects.toml").write_text('[[project]]\nid="first"\nref="v1"\npython="3.12"\ninstall=[]\n'
                                          '[[project]]\nid="second"\nref="v1"\npython="3.12"\ninstall=[]\n')
    (folder / "environments" / "first.txt").write_text("# Python 3.12.14\n")  # second.txt is missing
    (folder / "repairs.toml").write_text("[first]\nrepair=[]\n[second]\nrepair=[]\n")
    out = tmp_path / "out"
    (out / "_reference").mkdir(parents=True)
    commit = "a" * 40
    key = hashlib.sha256(json.dumps([commit, "# Python 3.12.14\n", []]).encode()).hexdigest()
    broken = out / "_reference" / f"{iso.slug('first', 30)}--{key[:12]}.json"
    broken.write_text("{")  # left half-written by an interrupted earlier attempt
    monkeypatch.setattr(agent_pilot.rc, "source_commit", lambda source: commit)
    agent_pilot.main(["--model", f"fake:{script(tmp_path, [call('finish', summary='x')])}",
                      "--projects", "first", "second", "--manifest", str(folder / "projects.toml"),
                      "--repairs", str(folder / "repairs.toml"), "--sources", str(folder / "sources"),
                      "--out", str(out), "--arms", "baseline", "mcp", "--attempt", "t1"])
    first_rows = [r for r in rows(out) if r["case"] == "first"]
    second_rows = [r for r in rows(out) if r["case"] == "second"]
    assert len(first_rows) == 2 and len(second_rows) == 2
    assert all((r["end"], r["grading"], r["fixed"]) == ("reference_invalid", "not_graded", None)
               for r in first_rows + second_rows)
    assert "not usable (unreadable" in first_rows[0]["reference_cache_note"]
    assert all(r["install_fails_registered"] == 0 for r in first_rows + second_rows)  # on every real row
    assert (out / "_reference" / f"{broken.name}.unusable-t1").read_text() == "{"
    assert "FileNotFoundError" in second_rows[0]["error"]


# ---- Nothing the agent leaves behind stalls the harness ------------------------------------------

KEEPER = ("import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
          "start_new_session=True)")  # a detached child that inherits the output pipe and keeps it open


def test_named_pipes_and_a_child_holding_the_output_never_stall_a_run(tmp_path):
    started = time.monotonic()
    [row] = run(tmp_path, [call("run_command", command="mkfifo notes.txt && python -c " + shlex.quote(KEEPER)),
                           call("write_file", path="notes.txt", content="x"),
                           call("read_file", path="notes.txt"),
                           call("run_command", command=FIX),
                           call("finish", summary="fixed")])
    transcript = json.loads((tmp_path / "out" / row["run_dir"] / "transcript.json").read_text())
    results = [m["content"] for m in transcript if m["role"] == "tool"]
    assert results[0].startswith("exit code 0")  # the command ended although its child holds the pipe
    assert results[1].startswith("error: OSError") and results[2] == "error: no such file in the project"
    assert (row["end"], row["grading"], row["fixed"], row["bad_calls"]) == ("finish", "graded", True, 1)
    assert row["processes_stopped_at_end"] >= 1 and time.monotonic() - started < 60


def test_a_test_that_leaves_a_child_holding_the_output_is_graded_on_its_own_exit(tmp_path):
    # Started as the test process ends, after pytest stopped capturing: the child holds the output pipe.
    test = ("import atexit, subprocess, sys\n\n\ndef leave():\n"
            "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(100)'], start_new_session=True)\n"
            "    open('child.pid', 'w').write(str(child.pid))\n\n\n"
            "def test_leaves_a_child():\n    atexit.register(leave)\n")
    run_ = small_run(tmp_path, {"tests/test_keep.py": test})
    started = time.monotonic()
    result = run_.suite()
    assert (result["exit_code"], result["stopped"], result["counts"]) == (0, False, {"passed": 1})
    assert time.monotonic() - started < 30
    child = int((run_.folder / "grader" / "check-001" / "project" / "child.pid").read_text())
    assert iso._identity(child) is None  # stopped with its check


def test_a_flood_of_output_keeps_its_end_and_a_command_never_reads_the_harness_input(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, resource, sys, time\nfrom pathlib import Path\nsys.path.insert(0, sys.argv[1])\n"
        "import isolation as iso\n"
        "work = Path(sys.argv[2])\n"
        "owner = iso.new_mark()\n"
        "profile = iso.write_profile(iso.Policy((work,), (), owner=owner), work / 'p.sb', (Path.home(),))\n"
        "env = {'PATH': '/usr/bin:/bin'}\n"
        "flood = \"head -c 300000000 /dev/zero | tr '\\\\0' x; echo; echo last line\"\n"
        "code, out, stopped = iso.execute(['/bin/bash', '-c', flood], work, env, profile, 120, owner)\n"
        "print(json.dumps([code, len(out), out[:60], out.splitlines()[-1]]))\n"
        "started = time.monotonic()\n"
        "code, out, stopped = iso.execute(['/bin/cat'], work, env, profile, 5, owner)\n"
        "print(json.dumps([code, stopped, time.monotonic() - started]))\n"
        "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)\n")
    work = tmp_path / "work"
    work.mkdir()
    # stdin stays open (a pipe nobody writes to): a command that read it would wait until its timeout
    proc = subprocess.Popen([sys.executable, str(probe), str(Path(iso.__file__).parent), str(work)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    output, _ = proc.communicate(timeout=180)
    flood, cat, peak = output.strip().splitlines()
    code, kept, first, last = json.loads(flood)
    assert code == 0 and kept < iso.KEEP + 100 and "earlier output not kept" in first and last == "last line"
    code, stopped, seconds = json.loads(cat)
    assert (code, stopped) == (0, False) and seconds < 2
    assert int(peak) < 300 * 1024 * 1024  # bytes on macOS: the 300 MB were not held in memory


# ---- R5: which processes are a run's, and that all of them end with it ---------------------------------

# A process the run leaves behind that hides from every clue but its sandbox: clean environment, working
# folder /, its own session. It waits for a trigger in the project and then writes there.
WAITER = ("import sys, time; from pathlib import Path; folder = Path(sys.argv[1])\n"
          "for _ in range(1500):\n"
          "    if (folder / 'trigger').exists():\n"
          "        (folder / 'late.txt').write_text('written after the run'); break\n"
          "    time.sleep(0.02)\n")
DETACH = ("import os, subprocess, sys\n"
          f"waiter = subprocess.Popen([sys.executable, '-c', {WAITER!r}, os.getcwd()], env={{'PATH': '/usr/bin:/bin'}},\n"
          "                          cwd='/', start_new_session=True, stdin=subprocess.DEVNULL,\n"
          "                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
          "open('waiter.pid', 'w').write(str(waiter.pid))\n")


def written_after_the_run(folder: Path) -> bool:
    """Whether a waiter left in `folder` still writes when triggered now, after the run returned."""
    (folder / "trigger").write_text("go")
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if (folder / "late.txt").exists():
            return True
        time.sleep(0.02)
    return False


@contextmanager
def left_behind(folder: Path):
    """Whatever the assertions say, a waiter that escaped is killed at the end of the test."""
    try:
        yield
    finally:
        pid_file = folder / "waiter.pid"
        pid = int(pid_file.read_text()) if pid_file.exists() else None
        if pid and (iso._identity(pid) or (None, None, ""))[2].startswith("python"):
            os.kill(pid, signal.SIGKILL)


def test_only_processes_under_the_owners_sandbox_are_stopped(tmp_path):
    folder, owner, other = tmp_path / "run", iso.new_mark(), iso.new_mark()
    folder.mkdir()
    ours = iso.write_profile(iso.Policy((folder,), (), owner=owner), folder / "ours.sb", (Path.home(),))
    theirs = iso.write_profile(iso.Policy((folder,), (), owner=other), folder / "theirs.sb", (Path.home(),))
    closed = folder / "deny-default.sb"  # like an App Sandbox: it denies the owner's name too, and all else
    closed.write_text("(version 1)\n(deny default)\n(allow process-exec* process-fork file-read* sysctl-read)\n")
    clean = {"PATH": "/usr/bin:/bin"}
    hidden = ("import os, subprocess; p = subprocess.Popen(['/bin/sleep', '60'], env={}, cwd='/', "
              "start_new_session=True); print(p.pid)")
    procs = {
        "owned": ["sandbox-exec", "-f", str(ours), "/bin/sleep", "60"],
        "owned, then launched a hidden child": ["sandbox-exec", "-f", str(ours), "/usr/bin/python3", "-c", hidden],
        "unrelated, working in the run's folder": ["/bin/sleep", "60"],
        "unrelated, the owner's token in its command line and environment":
            ["/bin/sh", "-c", "sleep 60; :", f"note:FIXFIRST_RUN={owner} {iso.owner_name(owner)}"],
        "another run's sandbox": ["sandbox-exec", "-f", str(theirs), "/bin/sleep", "60"],
        "a deny-by-default sandbox": ["sandbox-exec", "-f", str(closed), "/bin/sleep", "60"],
    }
    started = {}
    try:
        for name, argv in procs.items():
            env = {**clean, "FIXFIRST_RUN": owner} if "token" in name else clean
            started[name] = subprocess.Popen(argv, cwd=folder, env=env, stdin=subprocess.DEVNULL,
                                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                             start_new_session=True)
        hidden_child = int(started["owned, then launched a hidden child"].stdout.readline())
        started["owned, then launched a hidden child"].wait(10)
        time.sleep(0.3)
        assert set(iso.owned(owner)) == {started["owned"].pid, hidden_child}
        result = iso.stop(owner)
        assert result["error"] is None and len(result["stopped"]) == 2
        assert started["owned"].wait(5) == -signal.SIGKILL and iso._identity(hidden_child) is None
        assert all(proc.poll() is None for name, proc in started.items() if not name.startswith("owned"))
    finally:
        for proc in started.values():
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(5)


@pytest.mark.parametrize("steps,extra,ending", [
    ([call("finish", summary="fixed")], (), "finish"),
    ([{"say": "done"}], (), "stopped_without_tool"),
    ([{"fail": "the model server went away"}], (), "model_error"),
    ([call("run_command", command="sleep 30")], ("--run-timeout", "4"), "time_cap"),
])
def test_a_child_that_left_its_session_folder_and_environment_ends_with_the_run(tmp_path, steps, extra, ending):
    [row] = run(tmp_path, [call("run_command", command=FIX + " && python -c " + shlex.quote(DETACH)), *steps],
                extra=extra)
    project = tmp_path / "out" / row["run_dir"] / "project"
    with left_behind(project):
        assert (row["end"], row["grading"], row["fixed"]) == (ending, "graded", True)
        assert row["processes_stopped_at_end"] >= 1 and (project / "waiter.pid").exists()
        assert not written_after_the_run(project)


def test_a_failed_install_that_left_a_process_behind_stops_it(tmp_path, monkeypatch):
    ctx, source, snapshot, reference = local_project(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_pilot.rc, "install_steps", lambda project, python, cache: [
        {"line": "-e .", "argv": [str(python), "-c", DETACH + "raise SystemExit(3)\n"], "expected_failure": False}])
    row = {}
    agent_pilot.run_real(ctx, row, agent_pilot.Settings(max_turns=2), {"id": "local", "ref": "v1", "install": []},
                         source, snapshot, reference, "baseline", 1, script(tmp_path, [call("finish", summary="x")]))
    project = ctx.out / row["run_dir"] / "project"
    with left_behind(project):
        assert (row["end"], row["grading"], row["processes_stopped_at_end"]) == ("setup_failed", "not_graded", 1)
        assert not written_after_the_run(project)


@pytest.mark.parametrize("registered,code,end", [
    (True, 3, "finish"),          # fails as registered: every arm starts there
    (True, 0, "setup_failed"),    # registered, yet it succeeded: not the registered start
    (False, 3, "setup_failed"),   # an unregistered failure is never skipped
    (False, 0, "finish"),
])
def test_a_registered_failing_install_is_the_start_and_any_other_outcome_stops_the_run(tmp_path, monkeypatch,
                                                                                       registered, code, end):
    ctx, source, snapshot, reference = local_project(tmp_path, monkeypatch)
    marked = agent_pilot.rc.install_steps  # the real marking; only the command is replaced
    monkeypatch.setattr(agent_pilot.rc, "install_steps", lambda project, python, cache: [
        {**step, "argv": [str(python), "-c", f"raise SystemExit({code})"]} for step in marked(project, python, cache)])
    project = {"id": "local", "ref": "v1", "install": ["-e ."], "install_fails": ["-e ."] if registered else []}
    row = {}
    agent_pilot.run_real(ctx, row, agent_pilot.Settings(max_turns=2), project, source, snapshot, reference,
                         "baseline", 1, script(tmp_path, [call("finish", summary="x")]))
    [step] = json.loads((ctx.out / row["run_dir"] / "setup.json").read_text())[-1:]
    assert (row["end"], row["install_fails_registered"]) == (end, int(registered))
    assert (step["exit_code"], step["expected_failure"]) == (code, registered)
    assert row["grading"] == ("graded" if end == "finish" else "not_graded")
    if registered and code == 0:
        assert "the start is not the registered one" in row["error"]


# A registered install that never ran to completion is not the registered start: one that hit its time
# limit (124, stopped) and one ended by a signal (-9) must stop the run before any episode.
ABORTS = {"exit": "raise SystemExit(3)", "timeout": "import time; time.sleep(30)",
          "signal": "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"}
REASONS = {"exit": None, "timeout": "was stopped at its time limit", "signal": "was ended by signal 9"}


def registered_install(monkeypatch, mode):
    marked = agent_pilot.rc.install_steps  # the real marking; only the command is replaced
    monkeypatch.setattr(agent_pilot.rc, "install_steps", lambda project, python, cache: [
        {**step, "argv": [str(python), "-c", ABORTS[mode]]} for step in marked(project, python, cache)])
    monkeypatch.setattr(agent_pilot, "INSTALL_SECONDS", 1.0)
    return {"id": "local", "ref": "v1", "install": ["-e ."], "install_fails": ["-e ."]}


@pytest.mark.parametrize("arm", ["baseline", "facts", "mcp"])
@pytest.mark.parametrize("mode", ["exit", "timeout", "signal"])
def test_only_a_registered_install_that_ran_and_failed_starts_an_episode(tmp_path, monkeypatch, mode, arm):
    ctx, source, snapshot, reference = local_project(tmp_path, monkeypatch)
    project = registered_install(monkeypatch, mode)
    row = {}
    agent_pilot.run_real(ctx, row, agent_pilot.Settings(max_turns=2), project, source, snapshot, reference,
                         arm, 1, script(tmp_path, [call("finish", summary="x")]))
    [step] = json.loads((ctx.out / row["run_dir"] / "setup.json").read_text())[-1:]
    assert (step["expected_failure"], step["stopped"], step["exit_code"]) == {
        "exit": (True, False, 3), "timeout": (True, True, iso.STOPPED), "signal": (True, False, -9)}[mode]
    assert row["install_fails_registered"] == 1
    if mode == "exit":
        assert (row["stage"], row["end"], row["grading"]) == ("grading", "finish", "graded")
    else:  # the failed row is kept, and the episode never began
        assert (row["stage"], row["end"], row["grading"], row["fixed"]) == ("setup", "setup_failed", "not_graded", None)
        assert REASONS[mode] in row["error"] and "the start is not the registered one" in row["error"]


@pytest.mark.parametrize("mode", ["exit", "timeout", "signal"])
def test_only_a_registered_install_that_ran_and_failed_gives_a_valid_reference(tmp_path, monkeypatch, mode):
    ctx, source, snapshot, _ = local_project(tmp_path, monkeypatch)
    project = registered_install(monkeypatch, mode)
    monkeypatch.setattr(agent_pilot.Run, "suite", lambda self: {  # a passing suite, so only the start decides
        "exit_code": 0, "counts": {"passed": 1}, "summary": "synthetic", "outcomes": {"tests.test_ok::test_ok": "passed"}})
    reference = agent_pilot.real_reference(ctx, project, source, snapshot, [])
    cached = list((ctx.out / "_reference").glob("*.json"))
    if mode == "exit":
        assert reference["problems"] == [] and len(cached) == 1
    else:
        assert any(REASONS[mode] in p and "the start is not the registered one" in p for p in reference["problems"])
        assert cached == []  # nothing is cached, so no later run can use it


def test_a_cached_registered_reference_without_completion_evidence_is_built_again(tmp_path, monkeypatch):
    ctx, source, snapshot, _ = local_project(tmp_path, monkeypatch)
    project = registered_install(monkeypatch, "exit")
    monkeypatch.setattr(agent_pilot.Run, "suite", lambda self: {
        "exit_code": 0, "counts": {"passed": 1}, "summary": "synthetic", "outcomes": {"tests.test_ok::test_ok": "passed"}})
    agent_pilot.real_reference(ctx, project, source, snapshot, [])
    [cached] = (ctx.out / "_reference").glob("*.json")
    old = json.loads(cached.read_text())
    for step in old["repair"]:
        del step["stopped"]  # as written before completion was recorded
    cached.write_text(json.dumps(old))
    again = agent_pilot.real_reference(agent_pilot.Context(ctx.out, ctx.model, "t2", ctx.network, ctx.denied),
                                       project, source, snapshot, [])
    assert "has no record that it ran to completion" in again["cache_note"] and again["problems"] == []
    assert json.loads(cached.read_text())["repair"][0]["stopped"] is False  # rebuilt with the evidence
    assert (cached.parent / f"{cached.name}.unusable-t2").exists()


def test_a_run_whose_environment_cannot_be_made_still_records_its_registration(tmp_path, monkeypatch):
    ctx, source, snapshot, reference = local_project(tmp_path, monkeypatch)

    def broken(project_dir, project, snapshot_file, log):
        raise RuntimeError("the environment could not be made")
    monkeypatch.setattr(agent_pilot.rc, "create_environment", broken)
    row = {}
    agent_pilot.run_real(ctx, row, agent_pilot.Settings(max_turns=2), registered_install(monkeypatch, "exit"), source,
                         snapshot, reference, "baseline", 1, script(tmp_path, [call("finish", summary="x")]))
    assert (row["end"], row["install_fails_registered"]) == ("setup_failed", 1)


def test_a_badly_registered_failing_install_is_refused_before_any_run(tmp_path):
    folder = tmp_path / "refs"
    folder.mkdir()
    (folder / "projects.toml").write_text('[[project]]\nid="first"\nref="v1"\npython="3.12"\n'
                                          'install=["-e .", "pytest"]\ninstall_fails=["pytest"]\n')
    (folder / "repairs.toml").write_text("[first]\nrepair=[]\n")
    with pytest.raises(SystemExit) as stopped:
        agent_pilot.main(["--model", f"fake:{script(tmp_path, [call('finish', summary='x')])}",
                          "--projects", "first", "--manifest", str(folder / "projects.toml"),
                          "--repairs", str(folder / "repairs.toml"), "--sources", str(folder / "sources"),
                          "--out", str(tmp_path / "out"), "--arms", "baseline", "--attempt", "t1"])
    assert stopped.value.code == 2 and not any((tmp_path / "out").iterdir())  # no reference, run or row


def test_a_process_a_test_leaves_ends_with_its_grader_check_even_if_the_report_is_broken(tmp_path, monkeypatch):
    run_ = small_run(tmp_path, {"tests/test_waiter.py": "def test_leaves_a_waiter():\n" + textwrap.indent(DETACH, "    ")})

    def broken(path):
        raise ParseError("the report is broken")
    monkeypatch.setattr(agent_pilot.rc, "junit_outcomes", broken)
    with pytest.raises(ParseError):
        run_.suite()
    copy = run_.folder / "grader" / "check-001" / "project"
    with left_behind(copy):
        assert (copy / "waiter.pid").exists() and not written_after_the_run(copy)


def test_a_harness_error_in_the_episode_still_ends_the_runs_processes(tmp_path, monkeypatch):
    def broken(self, turn, tool):
        raise RuntimeError("the integrity check broke")
    monkeypatch.setattr(agent_pilot.Run, "check_integrity", broken)
    [row] = run(tmp_path, [call("run_command", command="python -c " + shlex.quote(DETACH)), call("finish", summary="x")])
    project = tmp_path / "out" / row["run_dir"] / "project"
    with left_behind(project):
        assert (row["end"], row["grading"], row["fixed"]) == ("harness_error", "not_graded", None)
        assert row["processes_stopped_at_end"] >= 1 and not written_after_the_run(project)


def test_a_run_whose_processes_cannot_be_shown_stopped_is_never_graded(tmp_path, monkeypatch):
    monkeypatch.setattr(iso, "_kill", lambda pid, sig: None)  # every kill silently fails
    [row] = run(tmp_path, [call("run_command", command=FIX + " && python -c " + shlex.quote(DETACH)),
                           call("finish", summary="fixed")])
    project = tmp_path / "out" / row["run_dir"] / "project"
    with left_behind(project):
        assert (row["end"], row["episode_end"], row["grading"], row["fixed"]) == (
            "cleanup_failed", "finish", "not_graded", None)
        assert "still alive after being killed" in row["error"] and "reasons" not in row


def test_a_reference_whose_processes_cannot_be_shown_stopped_is_invalid(tmp_path, monkeypatch):
    ctx, source, snapshot, _ = local_project(tmp_path, monkeypatch)
    monkeypatch.setattr(iso, "stop", lambda owner, settle=3.0: {"stopped": [], "error": "cannot be checked (test)"})
    data = agent_pilot.real_reference(ctx, {"id": "local", "ref": "v1", "install": []}, source, snapshot, [])
    assert any("cannot be checked (test)" in problem for problem in data["problems"])
    assert not list((ctx.out / "_reference").glob("*.json"))  # an invalid reference is never cached


# ---- A run's commands may signal only what they started; failed process queries never count as clean ----

QUIET = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
SEND = ("import os, signal, sys\ntry:\n    os.kill(int(sys.argv[1]), signal.SIGTERM); print('sent')\n"
        "except OSError as e:\n    print('denied', e.errno)\n")
MANAGE = ("import json, os, signal, subprocess\na = subprocess.Popen(['/bin/sleep', '30'])\n"
          "b = subprocess.Popen(['/bin/sleep', '30'], start_new_session=True)\n"
          "os.kill(a.pid, signal.SIGTERM); os.kill(b.pid, signal.SIGTERM)\n"
          "print(json.dumps({'child': a.wait(5), 'detached child': b.wait(5)}))\n")


def test_a_command_can_signal_only_the_processes_it_started(tmp_path):
    run_, other = small_run(tmp_path, {"keep.txt": "x"}, "a"), small_run(tmp_path, {"keep.txt": "x"}, "b")
    outside = subprocess.Popen(["/bin/sleep", "60"], **QUIET)  # disposable targets, signalled by exact pid
    another_run = subprocess.Popen(["sandbox-exec", "-f", str(other.profile("agent")), "/bin/sleep", "60"], **QUIET)
    try:
        run_.execute(["/bin/bash", "-c", "/bin/sleep 60 > /dev/null 2>&1 & echo $! > left.pid"], "agent", 20)
        left = int((run_.project / "left.pid").read_text())  # what an earlier command of the run left
        time.sleep(0.3)
        replies = {name: run_.execute([str(run_.python), "-c", SEND, str(pid)], "agent", 20)[1].strip()
                   for name, pid in (("outside", outside.pid), ("another run", another_run.pid),
                                     ("an earlier command's", left))}
        time.sleep(0.1)
        assert replies == dict.fromkeys(("outside", "another run", "an earlier command's"), "denied 1")
        assert outside.poll() is None and another_run.poll() is None and iso._identity(left) is not None
        code, output, _ = run_.execute([str(run_.python), "-c", MANAGE], "agent", 20)
        assert json.loads(output) == {"child": -15, "detached child": -15}  # its own, also detached
        run_.end_processes("end of the test")  # the harness still stops what the run left
        assert iso._identity(left) is None and not run_.cleanup_problems
    finally:
        for proc in (outside, another_run):
            proc.kill()
            proc.wait()


class NativeFailure:
    """libSystem with one call failing the way the kernel reports errors, for a process of the run
    (the one it names in waiter.pid under `root`, once there is one) or for the process list."""

    def __init__(self, real, call: str, root: Path):
        self.real, self.call, self.root, self.pid = real, call, root, None

    def __getattr__(self, name):
        return getattr(self.real, name)

    def target(self):
        if self.pid is None:
            for path in self.root.glob("**/waiter.pid"):
                text = path.read_text()
                self.pid = int(text) if text.strip() else None
        return self.pid

    def proc_listallpids(self, buffer, size):
        if buffer is not None and self.target():
            if self.call == "list fails":
                ctypes.set_errno(errno.EIO)
                return 0
            if self.call == "list is full":  # as if more processes were waiting than fit
                return size // ctypes.sizeof(ctypes.c_int)
            if self.call == "list without this process":
                count = self.real.proc_listallpids(buffer, size)
                pids = [pid for pid in buffer[:count] if pid != os.getpid()]
                buffer[:len(pids)] = pids
                return len(pids)
        return self.real.proc_listallpids(buffer, size)

    def proc_pidinfo(self, pid, *rest):
        if pid == self.target() and self.call.startswith("info"):
            ctypes.set_errno(errno.EPERM if self.call == "info EPERM" else errno.EIO)
            return 0
        return self.real.proc_pidinfo(pid, *rest)

    def sandbox_check(self, pid, *rest):
        if pid == self.target() and self.call == "sandbox check fails":
            ctypes.set_errno(errno.EPERM)
            return -1
        return self.real.sandbox_check(pid, *rest)


FAILURES = ["list fails", "list is full", "list without this process", "info EPERM", "info EIO",
            "sandbox check fails"]


@pytest.mark.parametrize("failure", FAILURES)
def test_a_failed_process_query_is_never_taken_for_a_clean_stop(tmp_path, monkeypatch, failure):
    owner = iso.new_mark()
    profile = iso.write_profile(iso.Policy((tmp_path,), (), owner=owner), tmp_path / "p.sb", (Path.home(),))
    waiter = subprocess.Popen(["sandbox-exec", "-f", str(profile), "/bin/sleep", "60"], **QUIET)
    try:
        time.sleep(0.3)
        (tmp_path / "waiter.pid").write_text(str(waiter.pid))
        monkeypatch.setattr(iso, "_system", lambda failing=NativeFailure(iso._system(), failure, tmp_path): failing)
        result = iso.stop(owner, settle=0.5)
        monkeypatch.undo()
        assert "cannot be checked" in (result["error"] or "")
        assert waiter.poll() is None  # alive: nothing was killed without proof, and nothing was reported clean
    finally:
        waiter.kill()
        waiter.wait()


@pytest.mark.parametrize("failure", ["list fails", "info EPERM", "sandbox check fails"])
def test_a_run_whose_process_queries_fail_is_cleanup_failed_and_not_graded(tmp_path, monkeypatch, failure):
    real = iso._system()
    monkeypatch.setattr(iso, "_system", lambda failing=NativeFailure(real, failure, tmp_path / "out"): failing)
    [row] = run(tmp_path, [call("run_command", command=FIX + " && python -c " + shlex.quote(DETACH)),
                           call("finish", summary="fixed")])
    monkeypatch.undo()
    project = tmp_path / "out" / row["run_dir"] / "project"
    with left_behind(project):
        assert (row["end"], row["episode_end"], row["grading"], row["fixed"]) == (
            "cleanup_failed", "finish", "not_graded", None)
        assert "cannot" in row["error"] and "reasons" not in row
        assert iso._identity(int((project / "waiter.pid").read_text())) is not None  # not reported as gone


# ---- Three arms: basic tools, + FixFirst's facts, + its full diagnosis --------------------------------

CAUSE_LABELS = ("version_incompatibility", "missing_dependency", "local_module", "config_missing", "code_defect")


def fixfirst_texts(transcript: list) -> list[str]:
    """What FixFirst said in a run: scheduled reports (user messages) and tool results."""
    return [m["content"] for m in transcript
            if m["role"] == "user" and "FixFirst checked" in m["content"]
            or m["role"] == "tool" and m["content"].lstrip().startswith(("{", "FixFirst session", "Error: "))]


def assert_facts_only(text: str):
    assert not [label for label in CAUSE_LABELS if label in text]
    assert not re.search(r"\b[DFGHP]\d{2}\b", text) and "Why:" not in text and "Cause" not in text


def test_the_three_arms_start_alike_and_both_fixfirst_arms_get_the_same_scheduled_reports(tmp_path):
    steps = [call("fixfirst:first"), call("run_command", command=FIX), call("finish", summary="fixed")]
    rows_ = run(tmp_path, steps, arms=("baseline", "facts", "mcp"), extra=("--call-policy", "scheduled"))
    by_arm = {r["arm"]: r for r in rows_}
    assert sorted(by_arm) == ["baseline", "facts", "mcp"] and {r["call_policy"] for r in rows_} == {"scheduled"}
    assert all((r["end"], r["grading"], r["fixed"]) == ("finish", "graded", True) for r in rows_)
    assert len({json.dumps(r["settings"], sort_keys=True) for r in rows_}) == 1  # one budget and model setting
    # No FixFirst tool is offered under this policy (the scripted FixFirst call is left out), so every
    # arm takes the same two turns; the harness reports before the first turn and after the fix.
    assert all((r["turns"], r["fixfirst_calls"]) == (2, 0) for r in rows_)
    assert [by_arm[a]["fixfirst_reports"] for a in ("baseline", "facts", "mcp")] == [0, 2, 2]
    assert all(by_arm[a]["fixfirst_s"] > 0 and by_arm[a]["fixfirst_output_chars"] > 0 for a in ("facts", "mcp"))
    assert by_arm["facts"]["facts_only_verified"] is True
    assert (by_arm["mcp"]["fixfirst_first_cause"], by_arm["mcp"]["wrong_first_cause"]) == ("local_module", False)
    transcripts = {a: json.loads((tmp_path / "out" / r["run_dir"] / "transcript.json").read_text())
                   for a, r in by_arm.items()}
    assert transcripts["facts"][0] == transcripts["mcp"][0] != transcripts["baseline"][0]  # same system prompt
    said = {a: fixfirst_texts(t) for a, t in transcripts.items()}
    assert [len(said[a]) for a in ("baseline", "facts", "mcp")] == [0, 2, 2]
    for text in said["facts"]:
        assert_facts_only(text)
    assert "ModuleNotFoundError" in said["facts"][0] and "Why:" in said["mcp"][0]


def test_the_facts_arm_cannot_read_fixfirsts_sessions(tmp_path):
    steps = [call("fixfirst:first"),
             call("run_command", command="ls ..; ls ../fixfirst-store; cat ../fixfirst-store/*/session.json"),
             call("finish", summary="looked around")]
    [row] = run(tmp_path, steps, arms=("facts",))
    transcript = json.loads((tmp_path / "out" / row["run_dir"] / "transcript.json").read_text())
    observed, listing = [m["content"] for m in transcript if m["role"] == "tool"][:2]
    assert json.loads(observed)["facts_only"] is True and row["facts_only_verified"] is True
    assert "ls: ..: Operation not permitted" in listing and "No such file" in listing  # nothing to find either
    assert "diagnosis" not in listing
    assert not (tmp_path / "out" / row["run_dir"] / "fixfirst-store").exists()  # facts sessions stay in memory


@pytest.mark.parametrize("policy,words", [
    ("required", {"facts": "Call observe before changing anything, and observe after each change.",
                  "mcp": "Call diagnose before changing anything, and check_again after each change."}),
    ("on_demand", {"facts": "FixFirst's tools (observe) are available; use them when they help.",
                   "mcp": "FixFirst's tools (diagnose, check_again, explain) are available; use them when they help."}),
])
def test_the_required_and_on_demand_policies_offer_the_tools_in_the_same_words(tmp_path, policy, words):
    steps = [call("fixfirst:first"), call("run_command", command=FIX), call("fixfirst:again"),
             call("finish", summary="fixed")]
    rows_ = run(tmp_path, steps, arms=("baseline", "facts", "mcp"), extra=("--call-policy", policy))
    by_arm = {r["arm"]: r for r in rows_}
    assert all(r["fixed"] is True for r in rows_)
    assert [(by_arm[a]["turns"], by_arm[a]["fixfirst_calls"]) for a in ("baseline", "facts", "mcp")] == [
        (2, 0), (4, 2), (4, 2)]
    for arm in ("facts", "mcp"):
        system = json.loads((tmp_path / "out" / by_arm[arm]["run_dir"] / "transcript.json").read_text())[0]
        assert system["content"].endswith(words[arm])
    assert by_arm["facts"]["facts_only_verified"] is True and by_arm["mcp"]["fixfirst_first_cause"] == "local_module"
    assert all(by_arm[a]["fixfirst_s"] > 0 for a in ("facts", "mcp"))  # the model's own calls cost time too
    assert all(r["usage_reported"] is False for r in rows_)  # scripted replies report no tokens


LOOK_FOR_SESSIONS = """from pathlib import Path
import json
import os


def value():
    for root in (Path(__file__).parents[1], Path.home(), Path(os.environ.get("TMPDIR", "/tmp"))):
        try:
            for file in root.rglob("session.json"):
                for issue in json.loads(file.read_text()).get("issues", []):
                    if issue.get("diagnosis"):
                        return "PRIVATE_DIAGNOSIS=" + issue["diagnosis"]
        except OSError:
            continue
    return "NO_SESSION_FOUND"
"""


def test_the_facts_server_leaves_no_diagnosis_where_the_projects_code_could_read_it(tmp_path):
    """Codex's case: observe runs the project's code under the server's sandbox. After a first
    observe, that code looks for FixFirst's sessions and returns a stored diagnosis if it finds one."""
    run_ = small_run(tmp_path, {"app.py": "def value():\n    return 1\n",
                                "test_app.py": "from app import value\n\n\ndef test_value():\n    assert value() == 2\n"})
    client = agent_pilot.MCPClient(run_, iso.Budget(90), facts=True)
    arguments = {"project": str(run_.project), "python": str(run_.python)}
    try:
        first = client.call("observe", arguments, 80)
        assert json.loads(first)["failures"][0]["exception"] == "AssertionError"
        (run_.project / "app.py").write_text(LOOK_FOR_SESSIONS)  # the project's code, not a test
        second = client.call("observe", arguments, 80)
    finally:
        client.close()
        run_.end_processes("end of the test")
    assert "PRIVATE_DIAGNOSIS" not in second and "NO_SESSION_FOUND" in second
    assert not list(run_.folder.rglob("session.json")) and not run_.fixfirst_store.exists()


def test_the_time_of_every_fixfirst_call_counts_also_when_it_fails():
    class Slow:
        names, facts, dead = {"observe"}, True, False

        def __init__(self, error=None):
            self.error = error

        def call(self, name, arguments, timeout):
            time.sleep(0.12)
            if self.error:
                raise self.error
            return '{"facts_only":true,"failures":[]}'

    run_ = type("R", (), {"real": False})()
    for mcp in (Slow(), Slow(agent_pilot.ToolTimeout("no time left"))):
        stats = {"fixfirst_calls": 0, "fixfirst_s": 0, "fixfirst_output_chars": 0}
        try:
            agent_pilot.run_tool("observe", {}, run_, stats, mcp, iso.Budget(5), 1)
        except agent_pilot.ToolTimeout:
            pass
        assert stats["fixfirst_calls"] == 1 and stats["fixfirst_s"] >= 0.1


def test_a_fixfirst_server_that_exits_fails_the_call_at_once(tmp_path, monkeypatch):
    run_ = small_run(tmp_path, {"keep.txt": "x"})
    broken = tmp_path / "broken-venv"  # an interpreter whose server exits at once
    (broken / "bin").mkdir(parents=True)
    (broken / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.12.0\n")
    (broken / "bin" / "python").write_text("#!/bin/sh\nexit 3\n")
    (broken / "bin" / "python").chmod(0o755)
    monkeypatch.setattr(agent_pilot, "PYTHON", broken / "bin" / "python")
    started = time.monotonic()
    with pytest.raises(RuntimeError, match=r"exited \(code 3\)"):
        agent_pilot.MCPClient(run_, iso.Budget(120), facts=True)
    assert time.monotonic() - started < 20  # not the 120-second initialize timeout


# ---- Hard instances: the registered check, the reference with the registered repair, the frozen selection ----

HARD = "flat-shop:vb_yaml_loader"  # yaml.load(text) without a Loader; the scenario appends test_load_settings
HARD_FIX = "sed -i '' 's/yaml.load(text)/yaml.safe_load(text)/' app.py"


def python_step(code):
    return call("run_command", command=f"python - <<'PY'\n{code}\nPY")


def test_a_hard_instance_is_graded_against_its_start_with_the_registered_repair(tmp_path):
    out = tmp_path / "out"
    [fixed] = run(tmp_path, [call("run_command", command="python -m pytest -q 2>&1 | tail -3"),
                             call("run_command", command=HARD_FIX), call("finish", summary="x")], case=HARD, out=out, name="fix")
    assert (fixed["end"], fixed["grading"], fixed["fixed"], fixed["first_green_turn"]) == ("finish", "graded", True, 2)
    assert fixed["required_node"] == "test_app::test_load_settings" and fixed["reference_counts"] == {"passed": 3}
    assert len(fixed["hard_instance"]) == 64 and (fixed["cause"], fixed["kind"]) == ("version_incompatibility", "generated")
    idle = run(tmp_path, [call("finish", summary="nothing to do")], case=HARD, out=out, name="idle")[-1]
    assert (idle["grading"], idle["fixed"]) == ("graded", False)
    assert any("1 tests failed or errored, e.g. test_app::test_load_settings" in reason for reason in idle["reasons"])
    assert idle["hard_instance"] == fixed["hard_instance"]  # the same instance in a later invocation
    assert len(list((out / "_reference").glob("hard--*.json"))) == 1  # its reference was made once and found again
    cut = "import pathlib\np = pathlib.Path('test_app.py')\nt = p.read_text()\np.write_text(t[:t.index('def test_load_settings')])"
    removed = run(tmp_path, [python_step(cut), call("finish", summary="x")], case=HARD, out=out, name="cut")[-1]
    assert removed["fixed"] is False and "test_app.py" in removed["violations"]
    assert any("tests of the reference were not run, e.g. test_app::test_load_settings" in reason for reason in removed["reasons"])
    empty = "import pathlib\np = pathlib.Path('app.py')\np.write_text(p.read_text().replace('return yaml.load(text)', 'return {}'))"
    emptied = run(tmp_path, [python_step(empty), call("finish", summary="x")], case=HARD, out=out, name="empty")[-1]
    assert emptied["fixed"] is False and emptied["violations"] == {}  # removing the faulty call does not pass the check


def test_the_agent_of_a_hard_instance_cannot_read_its_registration_repair_or_reference(tmp_path):
    out = tmp_path / "out"
    run(tmp_path, [call("finish", summary="x")], case=HARD, out=out, name="first")
    folder = next((out / "_hard").iterdir())
    peek = [agent_pilot.HERE / "hard_cases.toml", folder / "manifest.json", folder / "reference" / "project" / "app.py",
            folder / "start" / "app.py", folder / "pristine" / "app.py", next((out / "_reference").glob("hard--*.json"))]
    assert all(path.is_file() for path in peek)
    command = "; ".join(f"cat {p} >/dev/null 2>&1 && echo READ {p.name} || echo DENIED" for p in peek)
    second = run(tmp_path, [call("run_command", command=command), call("run_command", command="cat app.py"),
                            call("finish", summary="x")], case=HARD, out=out, name="second")[-1]
    outputs = [m["content"] for m in json.loads((out / second["run_dir"] / "transcript.json").read_text()) if m["role"] == "tool"]
    assert outputs[0].count("DENIED") == len(peek) and "READ" not in outputs[0]
    assert "yaml.load(text)" in outputs[1]  # its own copy of the start is all it has


def changed_registry(monkeypatch, **change):
    registry = agent_pilot.hi.load_registry()
    registry["vb_yaml_loader"].update(change)
    monkeypatch.setattr(agent_pilot.hi, "load_registry", lambda: registry)


def test_a_hard_start_with_more_than_its_registered_check_is_unsupported(tmp_path, monkeypatch):
    changed_registry(monkeypatch, check_body='    assert load_settings("rate: 2") == {"rate": 3}')  # not what is appended
    [row] = run(tmp_path, [call("finish", summary="x")], case=HARD)
    assert (row["end"], row["grading"], row["fixed"]) == ("unsupported_case", "not_graded", None)
    assert "not the healthy test module followed by exactly the registered check" in row["error"]
    assert not (tmp_path / "out" / "_reference").exists()  # no reference is made for a start that is not admitted


def test_a_registered_repair_that_does_not_make_the_check_pass_is_no_reference(tmp_path, monkeypatch):
    changed_registry(monkeypatch, repair=[["yaml.load(text)", "yaml.load(text, None)"]])
    [row] = run(tmp_path, [call("finish", summary="x")], case=HARD)
    assert (row["end"], row["grading"]) == ("reference_invalid", "not_graded")
    assert "failed or errored in the reference, e.g. test_app::test_load_settings" in row["error"]
    assert not list((tmp_path / "out" / "_reference").glob("hard--*.json"))  # an invalid reference is never cached


def test_a_frozen_selection_lets_only_its_instances_run_and_only_with_their_frozen_content(tmp_path):
    out, fix = tmp_path / "out", [call("run_command", command=HARD_FIX), call("finish", summary="x")]
    [free] = run(tmp_path, fix, case=HARD, out=out, name="free")
    assert (free["fixed"], free["hard_role"], free["hard_selection"]) == (True, None, None)

    def selection(digest, name):
        path = tmp_path / name
        path.write_text(json.dumps({"selection": {"vb_yaml_loader": {
            "formal": {"template": "flat-shop", "candidate": 2, "digest": digest}, "development": None}}}))
        return path
    good, stale = selection(free["hard_instance"], "selection-good.json"), selection("0" * 64, "selection-stale.json")
    frozen = run(tmp_path, fix, case=HARD, out=out, name="frozen", extra=("--hard-selection", str(good), "--hard-role", "formal"))[-1]
    assert (frozen["fixed"], frozen["hard_role"], frozen["hard_selection"]) == (True, "formal", agent_pilot.rc.file_hash(good))
    other = run(tmp_path, fix, case=HARD, out=out, name="stale", extra=("--hard-selection", str(stale), "--hard-role", "formal"))[-1]
    assert (other["end"], other["grading"], other["fixed"]) == ("reference_invalid", "not_graded", None)
    assert "the instance is not the frozen one" in other["error"] and other["hard_instance"] == free["hard_instance"]
    refused = [(HARD, ("--hard-selection", str(good))), (HARD, ("--hard-role", "formal")),
               (HARD, ("--hard-selection", str(good), "--hard-role", "development")),  # it has no development instance
               (HARD, ("--hard-selection", str(tmp_path / "missing.json"), "--hard-role", "formal")),
               ("src-billing:vb_yaml_loader", ("--hard-selection", str(good), "--hard-role", "formal")),  # another template
               ("flat-shop:vb_unknown", ()), ("no-template:vb_yaml_loader", ()), ("flat-shop", ())]
    before = len(rows(out))
    for case, extra in refused:
        with pytest.raises(SystemExit) as stopped:
            run(tmp_path, fix, case=case, out=out, name="refused", extra=extra)
        assert stopped.value.code == 2
    assert len(rows(out)) == before  # refused before any run


def qualification(tmp_path, cases, name="qualification"):
    import qualify_hard
    qualify_hard.main(["--out", str(tmp_path / name), "--cases", *cases])
    return json.loads((tmp_path / name / "hard-qualification.json").read_text())["attempts"]


def test_an_instance_qualifies_when_its_reference_passes_and_its_start_shows_the_registered_fault(tmp_path, capsys):
    import qualify_hard
    first, second = qualification(tmp_path, [HARD, "fixture-orders:ml_renamed_then_alias"])
    assert (first["result"], first["reason"], second["result"], second["required_node"]) == ("qualified", None, "qualified", None)
    assert first["start"]["outcomes"]["test_app::test_load_settings"] == "failed"
    assert first["reference"]["outcomes"] == dict.fromkeys(first["start"]["outcomes"], "passed")
    assert (second["start"]["exit_code"], second["start"]["outcomes"]) == (2, {"::tests.test_service": "error"})
    # the record carries what the failures said and each instance's whole manifest, so it can be checked by itself
    assert "missing 1 required positional argument: 'Loader'" in first["start"]["said"]["test_app::test_load_settings"]
    assert "No module named 'orders.tax'" in second["start"]["said"]["::tests.test_service"]
    assert [agent_pilot.hi.digest(attempt["manifest"]) for attempt in (first, second)] == [first["digest"], second["digest"]]
    assert set(second["reference"]["outcomes"].values()) == {"passed"} and len(second["reference"]["outcomes"]) == 2
    text = (tmp_path / "qualification" / "hard-qualification.json").read_text()
    assert str(tmp_path) not in text and str(Path.home()) not in text and "| qualified |" in capsys.readouterr().out
    with pytest.raises(SystemExit):  # a record is never overwritten
        qualify_hard.main(["--out", str(tmp_path / "qualification"), "--cases", HARD])


@pytest.mark.parametrize("change,reason", [
    ({"fails_with": "another failure"}, "the start: the registered check fails for another reason than 'another failure'"),
    ({"repair": [["yaml.load(text)", "yaml.load(text, None)"]]}, "the reference: "),
    ({"repair": [["yaml.dump(text)", "yaml.safe_load(text)"]]}, "the reference: the registered repair does not apply"),
    ({"check_body": '    assert load_settings("rate: 2") == {"rate": 3}'}, "not admitted: "),
])
def test_an_instance_that_is_not_as_registered_does_not_qualify(tmp_path, monkeypatch, change, reason):
    changed_registry(monkeypatch, **change)
    [attempt] = qualification(tmp_path, [HARD])
    assert attempt["result"] == "not_qualified" and attempt["reason"].startswith(reason)


def test_a_qualification_that_could_not_run_its_suite_says_nothing_about_the_instance(tmp_path, monkeypatch):
    def broken(self):
        raise OSError(f"the sandbox could not be started in {self.folder}")
    monkeypatch.setattr(agent_pilot.Run, "suite", broken)
    [attempt] = qualification(tmp_path, [HARD])
    assert attempt["result"] == "not_checked" and "the reference suite could not be completed" in attempt["reason"]
    assert not list((tmp_path / "qualification" / "_reference").glob("hard--*.json"))
    text = (tmp_path / "qualification" / "hard-qualification.json").read_text()  # the record names no local folder
    assert "could not be started in <out>/_hard/" in attempt["reason"] and str(tmp_path) not in text


def test_the_selection_scan_records_every_attempt_and_is_what_a_run_accepts(tmp_path, capsys):
    import qualify_hard
    out = tmp_path / "selection"
    qualify_hard.main(["--out", str(out)])
    record = json.loads((out / "hard-selection.json").read_text())
    assert [a["result"] for a in record["attempts"]] == ["qualified"] * 12 and record["cannot_run"] == []
    order = agent_pilot.hi.candidates()
    assert {name: (chosen["formal"]["template"], chosen["development"]["template"])
            for name, chosen in record["selection"].items()} == {name: tuple(templates[:2]) for name, templates in order.items()}
    assert record["formal_templates"] == {"fixture-orders": 2, "flat-shop": 1, "pkg-inventory": 1, "src-billing": 1,
                                          "unittest-grades": 1}
    assert len({chosen[role]["digest"] for chosen in record["selection"].values() for role in chosen}) == 12
    assert set(record["code"]) == {f"fixfirst/{n}" for n in agent_pilot.hi.GENERATOR_FILES} | {
        f"agent_baseline/{n}" for n in agent_pilot.hi.CODE_FILES}
    assert "pyyaml==6" in " ".join(record["environment"]["distributions"]) and record["registry"] == agent_pilot.hi.load_registry()
    text = (out / "hard-selection.json").read_text()
    assert str(tmp_path) not in text and str(Path.home()) not in text
    assert "Formal instances per template" in capsys.readouterr().out
    row = run(tmp_path, [call("run_command", command=HARD_FIX), call("finish", summary="x")], case=HARD,
              extra=("--hard-selection", str(out / "hard-selection.json"), "--hard-role", "development"))[-1]
    assert (row["fixed"], row["hard_role"]) == (True, "development")  # flat-shop is this scenario's second candidate
    assert row["hard_instance"] == record["selection"]["vb_yaml_loader"]["development"]["digest"]
    with pytest.raises(SystemExit):
        qualify_hard.main(["--out", str(out)])


def test_a_hard_reference_whose_check_did_not_actually_pass_grades_nothing(tmp_path, monkeypatch):
    real_suite = agent_pilot.Run.suite

    def suite_with_a_skipped_check(self):
        result = real_suite(self)
        if "_hard" in self.folder.parts:  # the reference's own suite: its check is reported as skipped
            result["outcomes"]["test_app::test_load_settings"] = "skipped"
        return result
    monkeypatch.setattr(agent_pilot.Run, "suite", suite_with_a_skipped_check)
    [row] = run(tmp_path, [call("finish", summary="x")], case=HARD)
    assert (row["end"], row["grading"]) == ("reference_invalid", "not_graded")
    assert "did not actually pass in the reference, e.g. test_app::test_load_settings (skipped)" in row["error"]
    assert not list((tmp_path / "out" / "_reference").glob("hard--*.json"))


def test_a_run_whose_copy_is_not_the_instances_start_does_not_begin(tmp_path, monkeypatch):
    real_tree = agent_pilot.hi.tree
    monkeypatch.setattr(agent_pilot.hi, "tree", lambda folder: {"another": "file"} if "runs" in folder.parts else real_tree(folder))
    [row] = run(tmp_path, [call("run_command", command=HARD_FIX), call("finish", summary="x")], case=HARD)
    assert (row["end"], row["grading"], row["fixed"]) == ("setup_failed", "not_graded", None)
    assert row["error"] == "the run's copy is not the instance's start" and row.get("turns") is None


# ---- Codex r9: answers out of every run's reach, interrupted suites, the start without a check ----

def test_a_protected_file_is_unreadable_even_inside_a_folder_the_policy_lets_read(tmp_path):
    folder, scratch = tmp_path / "readable", tmp_path / "writable"
    folder.mkdir()
    scratch.mkdir()
    answers = folder / "answers.json"
    answers.write_text('{"repair": "the answer"}')
    (folder / "notes.txt").write_text("plain")
    owner = iso.new_mark()
    policy = iso.Policy((scratch,), (folder,), owner=owner)
    without = iso.write_profile(policy, tmp_path / "open.sb", (tmp_path,))
    protecting = iso.write_profile(policy, tmp_path / "shut.sb", (tmp_path,), (answers,))

    def sh(profile, command):
        return iso.execute(["/bin/sh", "-c", command], scratch, {"PATH": "/usr/bin:/bin"}, profile, 20, owner)[:2]
    try:
        assert sh(without, f"cat {answers}") == (0, '{"repair": "the answer"}')
        for command in (f"cat {answers}", f"cp {answers} {scratch}/copy", f"ln {answers} {scratch}/link",
                        f"stat {answers}", f"mv {answers} {folder}/renamed && cat {folder}/renamed"):
            code, output = sh(protecting, command)
            assert code != 0 and "the answer" not in output and "not permitted" in output, command
        assert sh(protecting, f"cat {folder}/notes.txt") == (0, "plain")  # the folder around it stays readable
        assert answers.read_text() == '{"repair": "the answer"}' and not list(scratch.iterdir())
    finally:
        iso.stop(owner)


def test_a_file_protected_by_name_can_be_renamed_where_the_sandbox_may_write(tmp_path):
    """Why the harness refuses answers inside a run's own folders: a name is all the rule knows."""
    folder = tmp_path / "work"
    folder.mkdir()
    answers = folder / "answers.json"
    answers.write_text("the answer")
    owner = iso.new_mark()
    profile = iso.write_profile(iso.Policy((folder,), (folder,), owner=owner), tmp_path / "p.sb", (tmp_path,), (answers,))
    try:
        run_ = lambda command: iso.execute(["/bin/sh", "-c", command], folder, {"PATH": "/usr/bin:/bin"}, profile, 20, owner)[:2]  # noqa: E731
        assert run_(f"cat {answers}")[0] != 0
        assert run_(f"mv {answers} {folder}/renamed && cat {folder}/renamed") == (0, "the answer")
    finally:
        iso.stop(owner)
    out = tmp_path / "out"
    assert agent_pilot.exposure(out / "runs" / "x--baseline--r1" / "project" / "answers.json", (tmp_path,), (out / "runs",)) \
        .startswith(f"shares a path with {os.path.realpath(out / 'runs')}, which runs may read")
    assert agent_pilot.exposure(tmp_path / "elsewhere" / "answers.json", (tmp_path,), (out / "runs",)) is None
    assert "is outside the folders" in agent_pilot.exposure(Path("/Users/Shared/answers.json"), (tmp_path,), (out / "runs",))


def frozen_selection(path, digest):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"selection": {"vb_yaml_loader": {
        "formal": {"template": "flat-shop", "candidate": 2, "digest": digest}, "development": None}}}))
    return ("--hard-selection", str(path), "--hard-role", "formal")


def test_a_frozen_selection_is_out_of_every_runs_reach_or_refused(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    [free] = run(tmp_path, [call("finish", summary="x")], case=HARD, out=out, name="free")
    selection = tmp_path / "elsewhere" / "selection.json"
    frozen = frozen_selection(selection, free["hard_instance"])
    # Inside a folder every sandbox is kept out of (here the system's temporary one): accepted, and protected by name too.
    peek = run(tmp_path, [call("run_command", command=f"cat {selection} >/dev/null 2>&1 && echo READ || echo DENIED"),
                          call("finish", summary="x")], case=HARD, out=out, name="peek", extra=frozen)[-1]
    transcript = json.loads((out / peek["run_dir"] / "transcript.json").read_text())
    assert [m["content"] for m in transcript if m["role"] == "tool"][0].split()[-1] == "DENIED"
    rule = f'(deny file-read-data (literal "{os.path.realpath(selection)}"))'
    assert all(rule in (out / peek["run_dir"] / name).read_text() for name in ("agent.sb", "grader/check-001/grader.sb"))
    before = len(rows(out))
    # Inside a folder that runs may read: refused.
    with pytest.raises(SystemExit):
        run(tmp_path, [call("finish", summary="x")], case=HARD, out=out, name="inside",
            extra=frozen_selection(out / "runs" / "selection.json", free["hard_instance"]))
    assert "--hard-selection" in capsys.readouterr().err and len(rows(out)) == before
    # Outside the folders a run is kept out of, nothing would stop a run from reading it: refused (Codex R9-1).
    monkeypatch.setattr(agent_pilot, "HOME", str(tmp_path / "home"))
    monkeypatch.setattr(iso, "SYSTEM_TEMP", ())
    with pytest.raises(SystemExit) as stopped:
        run(tmp_path, [call("finish", summary="x")], case=HARD, out=out, name="exposed", extra=frozen)
    error = capsys.readouterr().err
    assert stopped.value.code == 2 and "a run could read the answers: --hard-selection" in error
    assert "is outside the folders a run is kept out of" in error and len(rows(out)) == before
    with pytest.raises(SystemExit):  # the known repairs and the source clones of real projects are answers too
        agent_pilot.main(["--model", "fake:x.json", "--projects", "cachetools", "--out", str(out),
                          "--repairs", str(tmp_path / "elsewhere" / "repairs.toml"), "--sources", str(tmp_path / "sources")])
    error = capsys.readouterr().err
    assert "--repairs" in error and "--sources" in error and len(rows(out)) == before


@pytest.mark.parametrize("phase,folder", [("reference", "reference"), ("start's", "start-check")])
def test_a_suite_ended_by_a_signal_is_not_checked_rather_than_not_qualified(tmp_path, monkeypatch, phase, folder):
    real_suite = agent_pilot.Run.suite

    def killed(self):
        result = real_suite(self)
        if self.folder.name == folder:
            result.update(exit_code=-9, stopped=False)  # what the harness reports for a process ended by SIGKILL
        return result
    monkeypatch.setattr(agent_pilot.Run, "suite", killed)
    [attempt] = qualification(tmp_path, [HARD])
    assert attempt["result"] == "not_checked"
    assert attempt["reason"] == f"the {phase} suite could not be completed: the suite was ended by signal 9"
    cached = list((tmp_path / "qualification" / "_reference").glob("hard--*.json"))
    assert len(cached) == (0 if phase == "reference" else 1)  # an interrupted reference is never cached


# ---- Codex r10: a folder of answers shares no path with anything a sandbox is given ------------------

def test_answers_are_held_against_everything_the_harness_lets_a_sandbox_read(tmp_path, monkeypatch):
    """Codex R10-1: the entry rule knew the run folders and the environment, but not FixFirst's code, the
    interpreter the environment was made from, or a folder of answers around a readable one."""
    repo, home, out = tmp_path / "repo", tmp_path / "home", tmp_path / "out"
    venv, base = repo / ".venv", home / "interpreters" / "python-base"
    monkeypatch.setattr(agent_pilot, "FIXFIRST", repo)
    monkeypatch.setattr(agent_pilot, "PYTHON", venv / "bin" / "python")
    monkeypatch.setattr(agent_pilot, "interpreters", lambda venv_: (venv_, base))
    denied = (home, out, repo)
    given = {repo / "src" / "source-clones": repo / "src",  # FixFirst's server reads its code
             base / "source-clones": base,  # every sandbox reads the interpreter the environment was made from
             venv / "lib" / "source-clones": venv,
             out / "kept" / "source-clones": out,  # every run's folders are made in the output folder
             repo: repo / "src", home: base, out: out}  # and a folder of answers around what is given
    for answers, root in given.items():
        assert agent_pilot.exposure(answers, denied, (out,)).startswith(f"shares a path with {os.path.realpath(root)},"), answers
    assert "shares a path with" in agent_pilot.exposure(out, denied, (out / "runs",))  # around the run folders
    for answers in (repo / "experiments" / "source-clones", home / "data" / "source-clones", repo / "selection.json"):
        assert agent_pilot.exposure(answers, denied, (out,)) is None, answers
    assert "is outside the folders" in agent_pilot.exposure(tmp_path / "elsewhere" / "source-clones", denied, (out,))
    tool, uv = agent_pilot.HERE / "ff_tool.py", shutil.which("uv")  # single files are given too
    assert tool in agent_pilot.harness_readable() and "shares a path with" in agent_pilot.exposure(tool, (agent_pilot.HERE,), ())
    assert not uv or Path(os.path.realpath(uv)) in agent_pilot.harness_readable()


def test_source_clones_where_a_sandbox_reads_are_refused_before_any_run(tmp_path, capsys):
    out = tmp_path / "out"
    base = Path(agent_pilot.rc.venv_record(agent_pilot.PYTHON.parent.parent)["interpreters"][0])
    for sources in (agent_pilot.FIXFIRST / "src" / "source-clones", base / "source-clones",
                    agent_pilot.PYTHON.parent.parent / "source-clones", out / "source-clones", tmp_path, agent_pilot.FIXFIRST):
        with pytest.raises(SystemExit) as stopped:
            agent_pilot.main(["--model", "fake:x.json", "--projects", "cachetools", "--out", str(out), "--sources", str(sources)])
        error = capsys.readouterr().err
        assert stopped.value.code == 2 and "a run could read the answers: --sources" in error, sources
        assert not out.exists()  # no reference, run or row


def test_no_sandbox_is_given_what_shares_a_path_with_a_folder_of_answers(tmp_path):
    out, clones = tmp_path / "out", tmp_path / "base" / "source-clones"
    selection = tmp_path / "venv" / "selection.json"
    ctx = agent_pilot.Context(out, "fake", "test", False, denied=(tmp_path,), protected=(selection,),
                              protected_folders=(clones,))
    exposed = agent_pilot.Run(ctx, out / "runs" / "exposed", False, True, interpreters=(tmp_path / "venv", tmp_path / "base"))
    for kind in ("agent", "install", "mcp", "mcp_facts", "ff"):  # every kind of sandbox reads the interpreters
        with pytest.raises(iso.Exposed, match="holds answers and shares a path with"):
            exposed.profile(kind)
    with pytest.raises(iso.Exposed):
        exposed.suite()  # the grader's too
    assert not list(exposed.folder.rglob("*.sb"))  # no profile was written, so nothing could start under one
    around = agent_pilot.Run(ctx, out / "runs" / "around", False, True,
                             interpreters=(tmp_path / "venv", clones / "project" / ".venv"))
    with pytest.raises(iso.Exposed):
        around.profile("agent")
    (tmp_path / "link").symlink_to(tmp_path / "base", target_is_directory=True)  # another name for the folder around the clones
    with pytest.raises(iso.Exposed):
        agent_pilot.Run(ctx, out / "runs" / "linked", False, True, interpreters=(tmp_path / "venv", tmp_path / "link")).profile("agent")
    with pytest.raises(iso.Exposed):  # and the same folder spelled in another case, which this volume does not tell apart
        agent_pilot.Run(ctx, out / "runs" / "cased", False, True, interpreters=(tmp_path / "venv", tmp_path / "BASE")).profile("agent")
    kept = agent_pilot.Run(ctx, out / "runs" / "kept", False, True, interpreters=(tmp_path / "venv", tmp_path / "other-base"))
    text = kept.profile("agent").read_text()
    for path, form in ((clones, "subpath"), (selection, "literal")):  # the file lies where the sandbox reads: denied by name
        assert all(f"(deny {operation} ({form} {iso._quoted(path)}))" in text for operation in ("file-read-data", "file-read*"))
    assert text == (kept.folder / "agent.sb").read_text() and "grader.sb" not in text
    held = agent_pilot.Context(out, "fake", "test", False, denied=(tmp_path,),
                               protected=(out / "runs" / "held" / "project" / "selection.json",))
    with pytest.raises(iso.Exposed):  # a file of answers where the sandbox writes could be renamed
        agent_pilot.Run(held, out / "runs" / "held", False, True, interpreters=(tmp_path / "venv",)).profile("agent")
    written = agent_pilot.Context(out, "fake", "test", False, denied=(tmp_path,),
                                  protected_folders=(out / "runs" / "written" / "state" / "source-clones",))
    with pytest.raises(iso.Exposed):  # a folder of answers where the sandbox writes, not only where it reads
        agent_pilot.Run(written, out / "runs" / "written", False, True, interpreters=(tmp_path / "venv",)).profile("agent")
    uv = shutil.which("uv")
    if uv:  # a single file a sandbox is given counts too: uv, for installing a real project
        tools = agent_pilot.Context(out, "fake", "test", False, denied=(tmp_path,),
                                    protected_folders=(Path(os.path.realpath(uv)).parent,))
        install = agent_pilot.Run(tools, out / "runs" / "tools", True, True, interpreters=(tmp_path / "venv",))
        assert install.profile("agent").exists()
        with pytest.raises(iso.Exposed):
            install.profile("install")


def test_the_source_clones_and_the_repairs_are_denied_in_the_profiles_of_a_real_project(tmp_path, monkeypatch):
    """From the command line: what --sources and --repairs name reaches every profile of the invocation."""
    folder, out = tmp_path / "refs", tmp_path / "out"
    (folder / "environments").mkdir(parents=True)
    (folder / "projects.toml").write_text('[[project]]\nid="local"\nref="v1"\npython="3.12"\ninstall=[]\n')
    (folder / "environments" / "local.txt").write_text("# Python 3.12.14\n")
    (folder / "repairs.toml").write_text("[local]\nrepair=[]\n")
    source = folder / "sources" / "local"
    (source / "tests").mkdir(parents=True)
    (source / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    git = ["git", "-C", str(source), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "one"], check=True)

    def environment(project_dir, project, snapshot_file, log):
        subprocess.run([str(agent_pilot.PYTHON), "-m", "venv", "--without-pip", str(project_dir / ".venv")], check=True)
        return project_dir / ".venv" / "bin" / "python"
    monkeypatch.setattr(agent_pilot.rc, "create_environment", environment)
    agent_pilot.main(["--model", f"fake:{script(tmp_path, [call('finish', summary='x')])}", "--projects", "local",
                      "--manifest", str(folder / "projects.toml"), "--repairs", str(folder / "repairs.toml"),
                      "--sources", str(folder / "sources"), "--out", str(out), "--arms", "baseline", "--attempt", "t1"])
    profiles = list(out.rglob("*.sb"))  # the reference's grader at least: its environment has no pytest, so no run follows
    assert profiles and len(rows(out)) == 1
    for profile in profiles:
        text = profile.read_text()
        assert all(f"(deny {operation} (subpath {iso._quoted(folder / 'sources')}))" in text
                   and f"(deny {operation} (literal {iso._quoted(folder / 'repairs.toml')}))" in text
                   for operation in ("file-read-data", "file-read*")), profile


def test_a_protected_folder_is_unreadable_with_all_below_it_inside_a_folder_the_policy_lets_read(tmp_path):
    folder, scratch = tmp_path / "readable", tmp_path / "writable"
    clones = folder / "source-clones"
    (clones / "project").mkdir(parents=True)
    scratch.mkdir()
    (clones / "project" / "fix.py").write_text("the answer")
    (folder / "notes.txt").write_text("plain")
    owner = iso.new_mark()
    policy = iso.Policy((scratch,), (folder,), owner=owner)
    without = iso.write_profile(policy, tmp_path / "open.sb", (tmp_path,))
    protecting = iso.write_profile(policy, tmp_path / "shut.sb", (tmp_path,), (), (clones,))

    def sh(profile, command):
        return iso.execute(["/bin/sh", "-c", command], scratch, {"PATH": "/usr/bin:/bin"}, profile, 20, owner)[:2]
    try:
        assert sh(without, f"cat {clones}/project/fix.py") == (0, "the answer")
        for command in (f"cat {clones}/project/fix.py", f"ls {clones}", f"ls {clones}/project", f"stat {clones}/project/fix.py",
                        f"stat {clones}", f"cp -R {clones} {scratch}/copy", f"cp {clones}/project/fix.py {scratch}/fix.py",
                        f"ln {clones}/project/fix.py {scratch}/link", f"grep -r answer {clones}"):
            code, output = sh(protecting, command)
            assert code != 0 and "the answer" not in output and "not permitted" in output, command
        assert sh(protecting, f"cat {folder}/notes.txt") == (0, "plain")  # the folder around it stays readable
        assert not [p for p in scratch.rglob("*") if p.is_file()]  # nothing was copied or linked out
    finally:
        iso.stop(owner)


def test_a_real_run_whose_interpreter_shares_a_path_with_the_source_clones_does_not_begin(tmp_path, monkeypatch):
    """The interpreter a real project's environment is made from is known only once the environment exists."""
    ctx, source, snapshot, reference = local_project(tmp_path, monkeypatch)
    project = {"id": "local", "ref": "v1", "install": []}  # nothing is installed, so no install step would notice
    base = Path(agent_pilot.rc.venv_record(agent_pilot.PYTHON.parent.parent)["interpreters"][0])
    ctx.protected_folders = (base / "source-clones",)
    row = {}
    agent_pilot.run_real(ctx, row, agent_pilot.Settings(max_turns=3), project, source, snapshot, reference, "baseline", 1,
                         script(tmp_path, [call("run_command", command="true"), call("finish", summary="x")]))
    assert (row["end"], row["grading"], row["fixed"]) == ("setup_failed", "not_graded", None) and row.get("turns") is None
    assert row["error"].startswith("Exposed: ") and "holds answers and shares a path with" in row["error"]
    assert not list((ctx.out / row["run_dir"]).rglob("*.sb"))  # no sandbox was prepared for it
    data = agent_pilot.real_reference(ctx, project, source, snapshot, [])
    assert data["problems"] and data["problems"][0].startswith("Exposed: ") and data["outcomes"] == {}
    assert not list((ctx.out / "_reference").glob("*.json"))  # an invalid reference is never cached
    ctx.protected_folders = (tmp_path / "elsewhere" / "source-clones",)  # the same run with the clones out of reach
    row = {}
    agent_pilot.run_real(ctx, row, agent_pilot.Settings(max_turns=3), project, source, snapshot, reference, "baseline", 2,
                         script(tmp_path, [call("run_command", command="true"), call("finish", summary="x")]))
    assert (row["end"], row["grading"]) == ("finish", "graded")
    assert f"(deny file-read-data (subpath {iso._quoted(tmp_path / 'elsewhere' / 'source-clones')}))" in \
        (ctx.out / row["run_dir"] / "agent.sb").read_text()
