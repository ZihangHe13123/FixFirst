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
    assert all(a == {"project": str(run_.project), "python": str(run_.python)} for a in mcp.seen)


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
    monkeypatch.setattr(agent_pilot.rc, "install_commands",
                        lambda project, python, cache: [[str(python), "-c", DETACH + "raise SystemExit(3)\n"]])
    row = {}
    agent_pilot.run_real(ctx, row, agent_pilot.Settings(max_turns=2), {"id": "local", "ref": "v1", "install": []},
                         source, snapshot, reference, "baseline", 1, script(tmp_path, [call("finish", summary="x")]))
    project = ctx.out / row["run_dir"] / "project"
    with left_behind(project):
        assert (row["end"], row["grading"], row["processes_stopped_at_end"]) == ("setup_failed", "not_graded", 1)
        assert not written_after_the_run(project)


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
