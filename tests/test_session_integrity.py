"""Verification against the baseline tests (integrity.py): a pass is a fact about a run; the original
problem is verified only if the tests and the settings that select or judge them did not change."""

import json
import os
import sys

import pytest

from fixfirst import integrity
from fixfirst.cli import main as cli
from fixfirst.mcp_server import TOOLS, render
from fixfirst.service import create_session, scan
from fixfirst.storage import Store
from fixfirst.web import App
from fixfirst.workspace import build_view


def cart_project(tmp_path, pyproject='[project]\nname = "cart"\nversion = "1.0"\n'):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(pyproject)
    (tmp_path / "cart.py").write_text("def total(a, b):\n    return a - b\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_cart.py").write_text(
        "from cart import total\n\n\ndef test_total():\n    assert total(1, 2) == 3\n")
    return tmp_path


def session_for(project):
    session = create_session(project, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    [issue] = session.issues
    assert issue.status == "open" and session.verification_baseline["files"]
    return session, issue.issue_id


def issue(session, issue_id):
    return next(i for i in session.issues if i.issue_id == issue_id)


def test_changing_the_failing_test_keeps_the_pass_but_does_not_verify_the_problem(tmp_path):
    project = cart_project(tmp_path)
    session, original = session_for(project)
    (project / "tests" / "test_cart.py").write_text(
        "from cart import total\n\n\ndef test_total():\n    assert total(1, 2) == -1\n")
    scan(session, ["pytest_run"])
    run = session.runs[-1]
    assert run.exit_code == 0 and run.verified_pass  # the execution result: the run passed
    assert session.baseline_check["changed"] == ["tests:tests/test_cart.py"]  # the baseline changed
    changed = issue(session, original)  # and the original problem is not verified
    assert (changed.status, changed.verification) == ("awaiting_verification", "not_comparable")
    assert "tests/test_cart.py" in changed.note and session.goal_status != "achieved"
    view = build_view(session)
    assert view["status"]["kind"] == "baseline_changed" and view["baseline"]["changed"] == ["tests/test_cart.py"]
    assert "The last check passed (1 test)" in view["status"]["detail"]
    assert "Only a person can accept" in render(session, view)
    # A person accepts the changed test; the next check verifies against it.
    assert integrity.accept(session) == ["tests:tests/test_cart.py"]
    assert session.history[-1]["kind"] == "baseline_accepted"
    scan(session, ["pytest_run"])
    verified = issue(session, original)
    assert (verified.status, verified.verification) == ("resolved", "comparable")
    assert "accepted as the new baseline" in verified.note and session.goal_status == "achieved"


def test_a_fix_in_the_code_is_verified_and_legitimate_setting_changes_do_not_count(tmp_path):
    project = cart_project(tmp_path)
    session, original = session_for(project)
    (project / "cart.py").write_text("def total(a, b):\n    return a + b\n")
    (project / "pyproject.toml").write_text(  # a new version and pythonpath: not about the tests
        '[project]\nname = "cart"\nversion = "1.1"\n\n[tool.pytest.ini_options]\npythonpath = ["."]\n')
    scan(session, ["pytest_run"])
    assert session.baseline_check["changed"] == []
    assert (issue(session, original).status, issue(session, original).verification) == ("resolved", "comparable")
    assert session.goal_status == "achieved" and build_view(session)["status"]["kind"] == "done"


@pytest.mark.parametrize("change,key", [
    ("addopts", "pytest:pyproject.toml:addopts"),
    ("delete", "tests:tests/test_cart.py"),
    ("conftest", "tests:tests/conftest.py"),
])
def test_deselecting_deleting_or_adding_a_conftest_changes_the_baseline(tmp_path, change, key):
    project = cart_project(tmp_path)
    session, original = session_for(project)
    if change == "addopts":
        (project / "pyproject.toml").write_text(
            '[project]\nname = "cart"\nversion = "1.0"\n\n[tool.pytest.ini_options]\naddopts = "-k not_total"\n')
    elif change == "delete":
        (project / "tests" / "test_cart.py").unlink()
    else:
        (project / "tests" / "conftest.py").write_text("collect_ignore = ['test_cart.py']\n")
    scan(session, ["pytest_run"])
    assert key in session.baseline_check["changed"]
    assert issue(session, original).status != "resolved" and session.goal_status != "achieved"


def test_a_program_goal_has_no_test_baseline_so_editing_the_program_is_the_fix(tmp_path):
    (tmp_path / "main.py").write_text("print(1 / 0)\n")
    session = create_session(tmp_path, sys.executable, goal="run_project",
                             execution={"kind": "script", "entry": "main.py"})
    scan(session, ["python_run"])
    [original] = [i.issue_id for i in session.issues]
    assert session.verification_baseline["files"] == {}
    (tmp_path / "main.py").write_text("print(1 / 1)\n")
    scan(session, ["python_run"])
    assert issue(session, original).status == "resolved" and session.goal_status == "achieved"


def test_unittest_counts_the_files_its_pattern_selects(tmp_path):
    (tmp_path / "work.py").write_text("VALUE = 2\n")
    (tmp_path / "test_work.py").write_text(
        "import unittest\nimport work\nclass TestWork(unittest.TestCase):\n"
        " def test_value(self): self.assertEqual(work.VALUE, 1)\n")
    session = create_session(tmp_path, sys.executable, goal="auto")
    assert session.goal == "pass_unittest"
    scan(session, ["unittest_run"])
    assert list(session.verification_baseline["files"]) == ["tests:test_work.py"]
    (tmp_path / "test_work.py").write_text(
        "import unittest\nimport work\nclass TestWork(unittest.TestCase):\n"
        " def test_value(self): self.assertEqual(work.VALUE, 2)\n")
    scan(session, ["unittest_run"])
    assert session.baseline_check["changed"] == ["tests:test_work.py"] and session.goal_status != "achieved"


def test_the_style_goal_counts_ruffs_settings(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n')
    (tmp_path / "app.py").write_text("import os\n")
    session = create_session(tmp_path, sys.executable, goal="check_style")
    scan(session, ["ruff"])
    assert session.issues and all(i.status == "open" for i in session.issues)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\n\n[tool.ruff.lint]\nignore = ["F401"]\n')
    scan(session, ["ruff"])
    assert session.baseline_check["changed"] == ["ruff:pyproject.toml"]
    assert all(i.status != "resolved" for i in session.issues)
    assert build_view(session)["status"]["headline"] == "The code-check settings changed"


def test_only_a_person_accepts_a_new_baseline(tmp_path, capsys):
    assert not [t for t in TOOLS if "baseline" in t["name"] or "accept" in t["name"]]  # nothing for an agent
    project = cart_project(tmp_path / "project")
    store = Store(tmp_path / "store")
    session, _ = session_for(project)
    (project / "tests" / "test_cart.py").write_text("def test_total():\n    assert True\n")
    scan(session, ["pytest_run"])
    store.save(session)
    app = App(store.root, tmp_path / "workbench")
    page = app.workspace(session.session_id)
    assert "The tests changed" in page and 'id="accept-baseline"' in page and "accept-baseline`" in page
    app.act(session.session_id, "accept-baseline", {})  # what the page's button posts
    accepted = store.load(session.session_id)
    assert accepted.baseline_check["changed"] == [] and accepted.history[-1]["kind"] == "baseline_accepted"
    (project / "tests" / "test_cart.py").write_text("def test_total():\n    assert 1\n")
    assert cli(["--store", str(store.root), "accept-baseline", session.session_id]) == 0  # the command line
    assert "New baseline accepted; changed since the previous one: tests/test_cart.py" in capsys.readouterr().out
    assert json.dumps(store.load(session.session_id).verification_baseline).count("accepted by the user") == 1


def test_a_changed_goal_records_its_own_baseline(tmp_path):
    project = cart_project(tmp_path)
    session, _ = session_for(project)
    session.goal = "check_style"
    integrity.check(session)
    assert session.verification_baseline["reason"] == "goal changed" and session.baseline_check["changed"] == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX")
def test_a_named_pipe_among_the_tests_is_hashed_without_waiting(tmp_path):
    os.mkfifo(tmp_path / "test_pipe.py")
    assert integrity._hash(tmp_path / "test_pipe.py") == "not a regular file"
