"""Project environment isolation must not erase the probe's test evidence."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from fixfirst.service import create_session, scan


@pytest.fixture(autouse=True)
def isolated_pytest_environment(monkeypatch):
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")


@pytest.mark.parametrize("mutation,results", [
    ("replace_fixture", ["failed"]),
    ("replace_fixture", ["passed"]),
    ("clear_test", ["failed"]),
    ("delete_fixture", ["failed"]),
    ("replace_fixture", ["passed", "failed"]),
    ("plain", ["failed"]),
    ("redirect_fixture", ["failed"]),
], ids=["replaced-failure", "replaced-pass", "cleared-failure", "deleted-failure",
        "replaced-mixed", "unchanged-control", "changed-destination"])
def test_real_check_retains_outcomes_exceptions_and_completion(tmp_path, mutation, results):
    actions = {
        "replace_fixture": "    monkeypatch.setattr(os, 'environ', {'PATH': os.environ.get('PATH', '')})\n",
        "delete_fixture": "    for name in list(os.environ):\n        if name.startswith('FIXFIRST_'):\n            monkeypatch.delenv(name)\n",
        "redirect_fixture": "    monkeypatch.setenv('FIXFIRST_PROBE', str(Path.cwd() / 'redirected.jsonl'))\n",
    }
    if mutation in actions:
        (tmp_path / "conftest.py").write_text(
            "import os\nfrom pathlib import Path\nimport pytest\n\n"
            "@pytest.fixture(autouse=True)\ndef isolated_environment(monkeypatch):\n"
            + actions[mutation], encoding="utf-8")
    tests = "import os\n\n"
    for number, result in enumerate(results):
        tests += f"def test_case_{number}():\n"
        if mutation == "clear_test":
            tests += "    os.environ.clear()\n"
        tests += "    assert " + ("True" if result == "passed" else "False, 'expected project failure'") + "\n\n"
    (tmp_path / "test_environment.py").write_text(tests, encoding="utf-8")
    session = create_session(tmp_path, sys.executable, goal="pass_tests", tests=["test_environment.py"])
    scan(session, ["pytest_run"])
    run = session.runs[-1]
    assert run.status == "completed" and run.exit_code == int("failed" in results)
    assert run.coverage_complete
    assert run.verified_pass is ("failed" not in results)
    assert run.test_summary["passed"] == results.count("passed")
    assert run.test_summary["failed"] == results.count("failed")
    assert run.test_summary["incomplete"] == 0
    calls = [record for record in run.records if record["type"] == "outcome" and record["stage"] == "call"]
    assert [(record["nodeid"], record["outcome"]) for record in calls] == [
        (f"test_environment.py::test_case_{number}", result) for number, result in enumerate(results)]
    exceptions = [record for record in run.records if record["type"] == "exception"]
    assert len(exceptions) == results.count("failed")
    assert all(record["exception_type"] == "AssertionError" and
               "expected project failure" in record["exception_message"] for record in exceptions)
    finishes = [record for record in run.records if record["type"] == "finish"]
    assert len(finishes) == 1 and finishes[0]["collected"] == len(results)
    assert finishes[0]["records_dropped"] is False
    assert not (tmp_path / "redirected.jsonl").exists()


def test_default_scan_sees_failure_and_closes_it_after_the_same_check_passes(tmp_path):
    (tmp_path / "conftest.py").write_text(
        "import os\nimport pytest\n\n@pytest.fixture(autouse=True)\n"
        "def isolated_environment(monkeypatch):\n"
        "    monkeypatch.setattr(os, 'environ', {})\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("READY = False\n", encoding="utf-8")
    (tmp_path / "test_app.py").write_text(
        "from app import READY\n\ndef test_ready():\n    assert READY\n", encoding="utf-8")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session)
    run = next(run for run in reversed(session.runs) if run.tool == "pytest_run")
    assert run.coverage_complete and run.test_summary["failed"] == 1
    issues = [issue for issue in session.issues if "test_app.py::test_ready" in issue.targets]
    assert issues and all(issue.status == "open" for issue in issues)
    (tmp_path / "app.py").write_text("READY = True\n", encoding="utf-8")
    scan(session)
    run = next(run for run in reversed(session.runs) if run.tool == "pytest_run")
    assert run.verified_pass and session.goal_status == "achieved"
    assert all(issue.status == "resolved" for issue in session.issues if issue.issue_id in {i.issue_id for i in issues})


def test_environment_replaced_during_initial_conftest_failure_keeps_exception_evidence(tmp_path):
    (tmp_path / "conftest.py").write_text(
        "import os\nos.environ = {}\nraise RuntimeError('expected conftest failure')\n", encoding="utf-8")
    (tmp_path / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    run = session.runs[-1]
    assert run.exit_code != 0 and not run.verified_pass
    failures = [record for record in run.records if record["type"] == "exception"]
    assert len(failures) == 1
    assert failures[0]["exception_type"] == "RuntimeError"
    assert failures[0]["exception_message"] == "expected conftest failure"
    assert failures[0]["nodeid"] == "<initial-conftest>"


def test_copied_plugin_without_startup_destination_leaves_pytest_outcome_unchanged(tmp_path):
    from fixfirst import probe

    for name in ("probe.py", "_runtime_evidence.py"):
        shutil.copyfile(Path(probe.__file__).with_name(name), tmp_path / ("_probe.py" if name == "probe.py" else name))
    (tmp_path / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if key != "FIXFIRST_PROBE"}
    env["PYTHONPATH"] = str(tmp_path)
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "_probe"],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0 and "1 passed" in done.stdout, done.stderr
    assert not list(tmp_path.glob("*.jsonl"))


def test_copied_probe_preserves_record_limits_and_final_dropped_flag(tmp_path):
    from fixfirst import probe

    path = tmp_path / "events.jsonl"
    env = {**os.environ, "FIXFIRST_PROBE": str(path)}
    code = (
        "import importlib.util,sys\n"
        "spec=importlib.util.spec_from_file_location('copied_probe', sys.argv[1])\n"
        "probe=importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)\n"
        "probe.emit({'type':'oversized','text':'x'*100001})\n"
        "probe.emit({'type':'finish','records_dropped':probe._dropped}, final=True)\n")
    done = subprocess.run([sys.executable, "-c", code, probe.__file__], env=env,
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert [json.loads(line) for line in path.read_text().splitlines()] == [
        {"type": "finish", "records_dropped": True}]
