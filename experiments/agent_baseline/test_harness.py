"""Checks of the agent harness with real sandboxed processes and scripted replies (macOS: sandbox-exec).

Run explicitly (not part of the main suite, which also runs on Windows and has no httpx):
  .venv/bin/python -m pytest -q experiments/agent_baseline/test_harness.py
Generated cases and small self-made projects only, offline. Real projects need the network and are
checked by hand (README). Every file written outside a run here is a harmless sentinel in the test's
own temporary folder.
"""

import json
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
                           (python.parent.parent, agent_pilot.base_prefix(python)))
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
                           (python.parent.parent, agent_pilot.base_prefix(python)))
    run_.project.mkdir()
    (run_.project / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    assert run_.suite()["counts"] == {"passed": 1}
    code, output, _ = run_.execute(["/bin/bash", "-c", "pwd && python -c 'import os; print(os.getcwd())'"], "agent", 60)
    assert code == 0, output
