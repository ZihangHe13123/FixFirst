"""Real executions in a target environment that has neither pytest nor FixFirst."""

import json
import os
import subprocess
import sys
import venv

import pytest

from fixfirst.execution import discover
from fixfirst.models import Execution
from fixfirst.mcp_server import Server
from fixfirst.processes import ProcessScope
from fixfirst.report import public_data
from fixfirst.runner import venv_python
from fixfirst.service import create_session, import_log, scan
from fixfirst.storage import Store
from fixfirst.web import App
from fixfirst.workspace import build_view, inspect_folder


@pytest.fixture(scope="module")
def bare_python(tmp_path_factory):
    root = tmp_path_factory.mktemp("python-without-tests")
    venv.EnvBuilder(with_pip=False).create(root)
    python = str(venv_python(root))
    result = subprocess.run(
        [python, "-c", "import importlib.util as u; assert u.find_spec('pytest') is None; "
         "assert u.find_spec('fixfirst') is None"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return python


def script_session(root, python, source, **execution):
    (root / "main.py").write_text(source, encoding="utf-8")
    return create_session(root, python, goal="run_project",
                          execution={"kind": "script", "entry": "main.py", **execution})


def test_program_diagnose_save_fix_without_pytest(tmp_path, bare_python):
    session = script_session(tmp_path, bare_python, "from collections import Mapping\n")
    scan(session)
    assert session.goal_status == "blocked"
    issue = next(i for i in session.issues if i.tool == "python_run")
    assert issue.diagnosis == "version_incompatibility" and issue.diagnosis_source == "rule"
    assert issue.prediction is None
    steps = build_view(session)["steps"]
    assert steps and "main.py:1" in steps[0]["where"]
    assert "collections.Mapping" in steps[0]["title"]
    assert "same program" in steps[0]["confirm"]
    assert {r.tool for r in session.runs} == {"environment", "project", "python_run"}
    store = Store(tmp_path / ".fixfirst")
    store.save(session)
    session = store.load(session.session_id)
    (tmp_path / "main.py").write_text("from collections.abc import Mapping\nprint('ready')\n")
    scan(session)
    assert session.goal_status == "achieved"
    assert next(i for i in session.issues if i.issue_id == issue.issue_id).status == "resolved"
    assert build_view(session)["status"]["headline"] == "Program completed successfully"


@pytest.mark.parametrize("source,diagnosis,location,advice", [
    ("print(unknown_value)\n", "code_defect", "main.py:1", "reported source"),
    ("if True print('x')\n", "code_defect", "main.py:1", "reported source"),
    ("open('input.csv')\n", None, "main.py:1", "input file"),
    ("import requests\n", "missing_dependency", "main.py:1", "requests"),
    ("open('settings.json')\n", "config_missing", "main.py:1", "settings.json"),
])
def test_native_errors_get_location_and_remedy(tmp_path, bare_python, source, diagnosis, location, advice):
    session = script_session(tmp_path, bare_python, source)
    scan(session)
    issue = next(i for i in session.issues if i.tool == "python_run")
    if diagnosis:
        assert issue.diagnosis == diagnosis
    steps = build_view(session)["steps"]
    assert any(location in step["where"] for step in steps)
    assert any(advice in (step["title"] + step["explanation"]) for step in steps)


def test_module_arguments_stdin_and_unicode_working_directory(tmp_path, bare_python):
    root = tmp_path / "课程 作业"
    root.mkdir()
    (root / "homework").mkdir()
    (root / "homework/__main__.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "assert sys.argv[1] == 'a b; $(not_a_command)'\n"
        "assert input() == '你好'\nassert Path('data.txt').read_text() == 'data'\nprint('done')\n",
        encoding="utf-8")
    (root / "data.txt").write_text("data")
    session = create_session(root, bare_python, goal="run_project", execution={
        "kind": "module", "entry": "homework", "args": ["a b; $(not_a_command)"], "stdin": "你好\n"})
    scan(session)
    assert session.goal_status == "achieved"
    assert "done" in next(r for r in session.runs if r.tool == "python_run").stdout
    assert public_data(session)["execution"]["stdin"] == "[input omitted]"


@pytest.mark.parametrize("change", ["entry", "args", "stdin"])
def test_changed_run_scope_does_not_resolve_original_error(tmp_path, bare_python, change):
    session = script_session(tmp_path, bare_python, "raise ValueError('bad input')\n")
    scan(session)
    original = session.issues[0].issue_id
    (tmp_path / "main.py").write_text("print('ok')\n")
    config = session.execution.model_dump()
    if change == "entry":
        (tmp_path / "other.py").write_text("print('ok')\n")
        config["entry"] = "other.py"
    elif change == "args":
        config["args"] = ["new"]
    else:
        config["stdin"] = "new\n"
    session.execution = Execution.model_validate(config)
    scan(session)
    assert session.goal_status == "achieved"
    assert next(i for i in session.issues if i.issue_id == original).status != "resolved"
    session.execution = Execution(kind="script", entry="main.py")
    scan(session)
    assert next(i for i in session.issues if i.issue_id == original).status == "resolved"


def test_identical_error_in_two_configurations_keeps_both_records(tmp_path, bare_python):
    session = script_session(tmp_path, bare_python, "raise ValueError('same')\n")
    scan(session, ["python_run"])
    first = session.issues[0].issue_id
    session.execution.args = ["new"]
    scan(session, ["python_run"])
    assert len(session.issues) == 2
    assert len({i.scope for i in session.issues}) == 2
    (tmp_path / "main.py").write_text("print('ok')\n")
    scan(session, ["python_run"])
    assert next(i for i in session.issues if i.issue_id == first).status != "resolved"
    assert sum(i.status == "resolved" for i in session.issues) == 1


@pytest.mark.parametrize("mode", ["deleted", "timeout", "output_limit", "cancelled"])
def test_incomplete_execution_never_confirms_a_fix(tmp_path, bare_python, mode):
    session = script_session(tmp_path, bare_python, "raise ValueError('broken')\n")
    scan(session, ["python_run"])
    original = session.issues[0].issue_id
    if mode == "deleted":
        (tmp_path / "main.py").unlink()
    elif mode == "timeout":
        (tmp_path / "main.py").write_text("import time\ntime.sleep(10)\n")
    elif mode == "output_limit":
        (tmp_path / "main.py").write_text("print('x' * 2000000)\n")
    else:
        (tmp_path / "main.py").write_text("print('ok')\n")
    if mode == "cancelled":
        scope = ProcessScope()
        scope.cancel()
        with scope.activate():
            scan(session, ["python_run"], timeout=1)
    else:
        scan(session, ["python_run"], timeout=0.3 if mode == "timeout" else 5)
    assert session.goal_status != "achieved"
    assert next(i for i in session.issues if i.issue_id == original).status != "resolved"
    assert session.runs[-1].status == ("launch_failed" if mode == "deleted" else mode)


def test_unittest_without_pytest_and_removed_test_not_verified(tmp_path, bare_python):
    file = tmp_path / "test_homework.py"
    file.write_text("import unittest\nclass TestWork(unittest.TestCase):\n"
                    " def test_value(self): self.assertEqual(1, 2)\n")
    session = create_session(tmp_path, bare_python, goal="auto")
    assert session.goal == "pass_unittest"
    scan(session)
    original = session.issues[0].issue_id
    file.write_text("import unittest\nclass TestWork(unittest.TestCase):\n"
                    " def test_another(self): self.assertEqual(1, 1)\n")
    scan(session)
    assert session.goal_status == "unknown"
    assert next(i for i in session.issues if i.issue_id == original).status != "resolved"
    file.write_text("import unittest\nclass TestWork(unittest.TestCase):\n"
                    " def test_value(self): self.assertEqual(1, 1)\n")
    scan(session)
    assert session.goal_status == "achieved"
    assert next(i for i in session.issues if i.issue_id == original).status == "resolved"


@pytest.mark.parametrize("source", [
    "",
    "import unittest\nclass TestWork(unittest.TestCase):\n"
    " @unittest.skip('later')\n def test_value(self): pass\n",
    "import unittest\nclass TestWork(unittest.TestCase):\n"
    " def test_value(self):\n  with self.subTest(x=1): self.assertEqual(1, 2)\n",
    "import unittest\nclass TestWork(unittest.TestCase):\n"
    " def test_value(self):\n  with self.subTest(x=1): self.skipTest('later')\n",
])
def test_zero_skipped_or_failing_subtests_are_not_success(tmp_path, bare_python, source):
    (tmp_path / "test_app.py").write_text(source)
    session = create_session(tmp_path, bare_python, goal="pass_unittest")
    scan(session)
    assert session.goal_status != "achieved"
    assert not next(r for r in session.runs if r.tool == "unittest_run").verified_pass


def test_discovery_is_static_and_does_not_require_test_tools(tmp_path, bare_python):
    (tmp_path / "main.py").write_text("from pathlib import Path\nPath('EXECUTED').touch()\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_empty.py").write_text("# placeholder\n")
    info = inspect_folder(str(tmp_path), bare_python)
    assert info["discovery"]["suggested_goal"] == "run_project"
    assert not any("pytest is not installed" in w for w in info["warnings"])
    assert not (tmp_path / "EXECUTED").exists()
    (tmp_path / "tests/test_value.py").write_text("def test_value(): assert False\n")
    assert discover(tmp_path)["suggested_goal"] == "pass_tests"
    assert not (tmp_path / "EXECUTED").exists()


def test_discovery_respects_custom_pytest_names_and_unittest_conventions(tmp_path):
    file = tmp_path / "testwork.py"
    file.write_text("import unittest\nclass Work(unittest.TestCase):\n def test_x(self): pass\n")
    assert discover(tmp_path)["suggested_goal"] == "pass_unittest"
    file.unlink()
    (tmp_path / "pytest.ini").write_text("[pytest]\npython_files = check_*.py\npython_functions = check_*\n")
    (tmp_path / "check_homework.py").write_text("def check_value(): assert True\n")
    assert discover(tmp_path)["suggested_goal"] == "pass_tests"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX named pipes")
def test_discovery_does_not_block_on_special_files(tmp_path):
    os.mkfifo(tmp_path / "main.py")
    os.mkfifo(tmp_path / "pyproject.toml")
    (tmp_path / "run.py").write_text("print('ok')\n")
    result = subprocess.run([sys.executable, "-c",
                             "import json,sys; from pathlib import Path; "
                             "from fixfirst.execution import discover; "
                             "print(json.dumps(discover(Path(sys.argv[1]))))", str(tmp_path)],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["default_entry"] == {"kind": "script", "entry": "run.py"}


def test_missing_standard_input_has_actionable_advice(tmp_path, bare_python):
    session = script_session(tmp_path, bare_python, "print(input())\n")
    scan(session)
    assert any(a.action_id == "provide-program-input" for a in session.actions)
    assert any("--stdin-file" in step["explanation"] for step in build_view(session)["steps"])


def test_switching_python_cannot_resolve_previous_environment(tmp_path, bare_python):
    session = script_session(tmp_path, bare_python, "raise ValueError('bad')\n")
    scan(session, ["python_run"])
    original = session.issues[0].issue_id
    session.target_python = sys.executable
    (tmp_path / "main.py").write_text("print('ok')\n")
    scan(session, ["python_run"])
    assert session.goal_status == "achieved"
    assert next(i for i in session.issues if i.issue_id == original).status != "resolved"


def test_ambiguous_entry_requires_selection_and_outside_entry_rejected(tmp_path, bare_python):
    (tmp_path / "first.ipynb").write_text("{}")
    (tmp_path / "second.ipynb").write_text("{}")
    with pytest.raises(ValueError, match="Choose"):
        create_session(tmp_path, bare_python, goal="auto")
    with pytest.raises(ValueError, match="inside"):
        create_session(tmp_path, bare_python, goal="run_project",
                       execution={"kind": "script", "entry": "../main.py"})
    with pytest.raises(ValueError, match="module name"):
        create_session(tmp_path, bare_python, goal="run_project",
                       execution={"kind": "module", "entry": "foo; rm"})


def test_web_and_mcp_auto_detect_plain_program(tmp_path, bare_python):
    (tmp_path / "main.py").write_text("print(undefined)\n")
    app = App(tmp_path / ".web-store", tmp_path / ".workbench")
    created = app.start({"project": str(tmp_path), "python": bare_python})
    session = app.store.load(created["session_id"])
    assert session.goal == "run_project" and session.goal_status == "blocked"
    assert "main.py:1" in app.workspace(session.session_id)
    assert 'id="python"' in app.index() and 'id="other-python" hidden' not in app.index()
    (tmp_path / "main.py").write_text("print('ok')\n")
    app.act(session.session_id, "scan", {})
    assert "Program completed successfully" in app.workspace(session.session_id)
    server = Server(tmp_path / ".mcp-store")
    text = server.diagnose(str(tmp_path), python=bare_python)
    assert "Program completed successfully" in text
    assert server.store.load(server.latest).goal == "run_project"
    app.act(session.session_id, "configure", {"goal": "run_project", "execution":
            {"kind": "script", "entry": "main.py", "args": ["different"]}})
    assert app.store.load(session.session_id).goal_status == "unknown"


def test_cli_runs_program_and_imported_output_does_not_prove_fix(tmp_path, bare_python):
    (tmp_path / "main.py").write_text("print('ok')\n")
    command = [sys.executable, "-m", "fixfirst", "--store", str(tmp_path / ".cli")]
    created = subprocess.run([*command, "init", str(tmp_path), "--python", bare_python,
                              "--script", "main.py", "--arg=a b"],
                             capture_output=True, text=True, timeout=30)
    assert created.returncode == 0, created.stderr + created.stdout
    sid = created.stdout.splitlines()[0]
    done = subprocess.run([*command, "scan", sid], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr + done.stdout
    session = Store(tmp_path / ".cli").load(sid)
    assert session.goal_status == "achieved" and session.execution.args == ["a b"]
    session = script_session(tmp_path, bare_python, "raise ValueError('bad')\n")
    scan(session, ["python_run"])
    original = session.issues[0].issue_id
    log = tmp_path / "run.log"
    log.write_text("ok\n")
    import_log(session, log, "python_run", 0)
    assert session.goal_status != "achieved"
    assert next(i for i in session.issues if i.issue_id == original).status != "resolved"
    log.write_text('Traceback (most recent call last):\n  File "' + str(tmp_path / "main.py")
                   + '", line 1, in <module>\n    print(missing)\nNameError: name missing is not defined\n')
    import_log(session, log, "python_run", 1)
    assert any(i.diagnosis == "code_defect" and i.environment_id == "unknown" for i in session.issues)


def test_notebook_real_kernel_failure_fix_and_original_preserved(tmp_path):
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    file = tmp_path / "作业.ipynb"
    notebook = nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_code_cell("number = 4"),
        nbformat.v4.new_code_cell("print(number / 0)", metadata={"tags": ["raises-exception"]}),
    ])
    notebook.metadata["kernelspec"] = {"name": "old-unavailable-kernel", "display_name": "Old", "language": "python"}
    nbformat.write(notebook, file)
    before = file.read_bytes()
    session = create_session(tmp_path, sys.executable, goal="auto")
    scan(session, ["environment", "project", "python_run"], timeout=40)
    assert file.read_bytes() == before
    assert session.goal_status == "blocked"
    issue = next(i for i in session.issues if i.tool == "python_run")
    assert issue.diagnosis == "code_defect"
    assert any("cell 2" in where for step in build_view(session)["steps"] for where in step["where"])
    notebook.cells[1].source = "print(number / 2)"
    nbformat.write(notebook, file)
    before = file.read_bytes()
    scan(session, ["python_run"], timeout=40)
    assert session.goal_status == "achieved", session.runs[-1].stderr
    assert file.read_bytes() == before
    assert next(i for i in session.issues if i.issue_id == issue.issue_id).status == "resolved"


def test_notebook_missing_kernel_is_actionable(tmp_path, bare_python):
    pytest.importorskip("nbclient")
    (tmp_path / "work.ipynb").write_text(json.dumps(
        {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}))
    session = create_session(tmp_path, bare_python, goal="auto")
    scan(session, ["python_run"], timeout=20)
    assert session.goal_status != "achieved"
    assert "ipykernel" in session.issues[0].title
    action = next(a for a in session.actions if a.action_id == "install-notebook-kernel")
    assert action.command == [bare_python, "-m", "pip", "install", "ipykernel"]


def test_notebook_driver_install_command_targets_host_python(tmp_path, bare_python, monkeypatch):
    (tmp_path / "work.ipynb").write_text("{}")
    project_python = sys.executable
    monkeypatch.setattr("fixfirst.execution.sys.executable", bare_python)
    session = create_session(tmp_path, project_python, goal="auto")
    scan(session, ["python_run"], timeout=20)
    assert session.goal_status != "achieved"
    action = next(a for a in session.actions if a.action_id == "install-notebook-driver")
    assert action.command[0] == bare_python and action.command[0] != project_python


def test_notebook_output_limit_during_unfinished_cell(tmp_path):
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    file = tmp_path / "large.ipynb"
    nbformat.write(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(
        "import time\nprint('x' * 2000000, flush=True)\ntime.sleep(30)")]), file)
    session = create_session(tmp_path, sys.executable, goal="auto")
    scan(session, ["python_run"], timeout=20)
    assert session.runs[-1].status == "output_limit"
    assert session.goal_status != "achieved"
