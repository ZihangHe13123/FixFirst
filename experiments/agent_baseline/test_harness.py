"""Checks of the agent harness with real sandboxed processes and scripted replies (macOS: sandbox-exec).

Run explicitly (not part of the main suite, which also runs on Windows and has no httpx):
  .venv/bin/python -m pytest -q experiments/agent_baseline/test_harness.py
Generated cases and small self-made projects only, offline. Real projects need the network and are
checked by hand (README). Every file written outside a run here is a harmless sentinel in the test's
own temporary folder.
"""

import json
import shlex
import subprocess
import time
from pathlib import Path
import shutil
import sys

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
    def refuse(self, run_, budget):
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


def test_a_hook_the_agent_adds_to_its_environment_never_runs_outside_the_sandbox(tmp_path, monkeypatch):
    import subprocess
    sentinel = tmp_path / "outside-sentinel.txt"
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
    hook = f"import pathlib; pathlib.Path({str(sentinel)!r}).write_text('hook ran')\n"
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    steps = [call("write_file", path=f".venv/lib/{version}/site-packages/zz_agent_hook.pth", content=hook),
             call("run_command", command="python -c pass"), call("finish", summary="x")]
    out = tmp_path / "out"
    ctx = agent_pilot.Context(out, "fake", "t1", True, denied=(Path.home(), out, agent_pilot.FIXFIRST, *iso.SYSTEM_TEMP))
    row = {}
    reference = {"outcomes": {"tests.test_ok::test_ok": "passed"}, "counts": {"passed": 1}, "exit_code": 0, "problems": []}
    agent_pilot.run_real(ctx, row, agent_pilot.Settings(max_turns=4), {"id": "hooked", "ref": "v1", "install": []},
                         source, snapshot, reference, "baseline", 1, script(tmp_path, steps))
    assert row["end"] == "finish" and row["grading"] == "graded"
    assert (out / row["run_dir"] / "freeze-end.txt").exists()  # the end of the run read the environment
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
    test = ("import atexit, subprocess, sys\n\n\ndef test_leaves_a_child():\n"
            "    atexit.register(subprocess.Popen, [sys.executable, '-c', 'import time; time.sleep(100)'],\n"
            "                    start_new_session=True)\n")
    run_ = small_run(tmp_path, {"tests/test_keep.py": test})
    started = time.monotonic()
    result = run_.suite()
    assert (result["exit_code"], result["stopped"], result["counts"]) == (0, False, {"passed": 1})
    assert time.monotonic() - started < 30
    assert not iso.marked_processes("no-such-mark", run_.folder / "grader")  # the child was stopped


def test_a_flood_of_output_keeps_its_end_and_a_command_never_reads_the_harness_input(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, resource, sys, time\nfrom pathlib import Path\nsys.path.insert(0, sys.argv[1])\n"
        "import isolation as iso\n"
        "work = Path(sys.argv[2])\n"
        "profile = iso.write_profile(iso.Policy((work,), ()), work / 'p.sb', (Path.home(),))\n"
        "env = {'PATH': '/usr/bin:/bin'}\n"
        "flood = \"head -c 300000000 /dev/zero | tr '\\\\0' x; echo; echo last line\"\n"
        "code, out, stopped = iso.execute(['/bin/bash', '-c', flood], work, env, profile, 120)\n"
        "print(json.dumps([code, len(out), out[:60], out.splitlines()[-1]]))\n"
        "started = time.monotonic()\n"
        "code, out, stopped = iso.execute(['/bin/cat'], work, env, profile, 5)\n"
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
