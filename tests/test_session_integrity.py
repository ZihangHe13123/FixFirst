"""Verification against the baseline tests (integrity.py): a pass is a fact about a run; the original
problem is verified only if the tests and the settings that select or judge them are known to be
unchanged."""

import json
import os
import sys

import pytest

from fixfirst import integrity
from fixfirst.cli import main as cli
from fixfirst.mcp_server import TOOLS, render
from fixfirst.models import Run
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


def session_for(project, goal="pass_tests", check="pytest_run"):
    session = create_session(project, sys.executable, goal=goal)
    scan(session, [check])
    return session, [i.issue_id for i in session.issues if i.status == "open"]


def issue(session, issue_id):
    return next(i for i in session.issues if i.issue_id == issue_id)


def outcome(session, issue_id):
    found = issue(session, issue_id)
    return found.status, found.verification


def test_changing_the_failing_test_keeps_the_pass_but_does_not_verify_the_problem(tmp_path):
    project = cart_project(tmp_path)
    session, [original] = session_for(project)
    assert {"tests/test_cart.py", "cart.py"} <= set(session.verification_baseline["scopes"]["pytest"]["files"])
    (project / "tests" / "test_cart.py").write_text(
        "from cart import total\n\n\ndef test_total():\n    assert total(1, 2) == -1\n")
    scan(session, ["pytest_run"])
    run = session.runs[-1]
    assert run.exit_code == 0 and run.verified_pass  # the execution result: the run passed
    check = session.baseline_check  # the baseline changed
    assert (check["state"], check["changed"], check["unverifiable"]) == ("changed", ["tests:tests/test_cart.py"], [])
    assert outcome(session, original) == ("awaiting_verification", "not_comparable")  # not verified
    assert "tests/test_cart.py" in issue(session, original).note and session.goal_status != "achieved"
    view = build_view(session)
    assert view["status"]["kind"] == "baseline_changed" and view["baseline"]["changed"] == ["tests/test_cart.py"]
    assert "The last check passed (1 test)" in view["status"]["detail"]
    assert "Only a person can accept" in render(session, view)
    # A person accepts the changed test; the next check verifies against it.
    assert integrity.accept(session) == {"changed": ["tests:tests/test_cart.py"], "unverifiable": []}
    assert session.history[-1]["kind"] == "baseline_accepted"
    scan(session, ["pytest_run"])
    assert outcome(session, original) == ("resolved", "comparable")
    assert "accepted as the new baseline" in issue(session, original).note and session.goal_status == "achieved"


def test_a_fix_in_the_code_is_verified_and_legitimate_setting_changes_do_not_count(tmp_path):
    project = cart_project(tmp_path)
    session, [original] = session_for(project)
    (project / "cart.py").write_text("def total(a, b):\n    return a + b\n")
    (project / "helper.py").write_text("VALUE = 1\n")  # a new source file is not a test
    (project / "pyproject.toml").write_text(  # a new version and pythonpath: not about the tests
        '[project]\nname = "cart"\nversion = "1.1"\n\n[tool.pytest.ini_options]\npythonpath = ["."]\n')
    scan(session, ["pytest_run"])
    assert session.baseline_check["state"] == "unchanged"
    assert outcome(session, original) == ("resolved", "comparable")
    assert session.goal_status == "achieved" and build_view(session)["status"]["kind"] == "done"


@pytest.mark.parametrize("change,key", [
    ("addopts", "pytest:pyproject.toml:addopts"),
    ("delete", "tests:tests/test_cart.py"),
    ("conftest", "tests:tests/conftest.py"),
])
def test_deselecting_deleting_or_adding_a_conftest_changes_the_baseline(tmp_path, change, key):
    project = cart_project(tmp_path)
    session, [original] = session_for(project)
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


def test_the_projects_own_test_file_patterns_count(tmp_path):
    """Codex's first case: pytest.ini selects spec_*.py, which the default names would miss."""
    (tmp_path / "pytest.ini").write_text("[pytest]\npython_files = spec_*.py\n")
    (tmp_path / "spec_app.py").write_text("def test_value():\n    assert 1 == 2\n")
    session, [original] = session_for(tmp_path)
    (tmp_path / "spec_app.py").write_text("def test_value():\n    assert 1 == 1\n")
    scan(session, ["pytest_run"])
    assert session.runs[-1].exit_code == 0 and session.baseline_check["changed"] == ["tests:spec_app.py"]
    assert outcome(session, original) == ("awaiting_verification", "not_comparable")
    assert session.goal_status != "achieved"


def test_a_file_a_run_collected_tests_from_counts_whatever_its_name(tmp_path):
    """No pattern names checks.py (a conftest hook collects it; FixFirst clears addopts), but pytest
    collected tests from it."""
    (tmp_path / "conftest.py").write_text(
        "import pytest\n\n\ndef pytest_collect_file(parent, file_path):\n"
        "    if file_path.name == 'checks.py':\n        return pytest.Module.from_parent(parent, path=file_path)\n")
    (tmp_path / "checks.py").write_text("def test_value():\n    assert 1 == 2\n")
    session, [original] = session_for(tmp_path)
    (tmp_path / "checks.py").write_text("def test_value():\n    assert 1 == 1\n")
    scan(session, ["pytest_run"])
    assert session.runs[-1].exit_code == 0 and session.baseline_check["changed"] == ["tests:checks.py"]
    assert outcome(session, original) == ("awaiting_verification", "not_comparable")


def test_the_baseline_is_taken_before_the_first_run_so_a_test_that_rewrites_itself_is_seen(tmp_path):
    """Codex's second case: the first run changes its own test, then fails; the next run passes."""
    (tmp_path / "test_app.py").write_text(
        "from pathlib import Path\n\n\ndef test_value():\n"
        "    Path(__file__).write_text('def test_value():\\n    assert 1 == 1\\n')\n    assert 1 == 2\n")
    session, [original] = session_for(tmp_path)
    assert session.baseline_check["changed"] == ["tests:test_app.py"]  # seen after the first run already
    scan(session, ["pytest_run"])
    assert session.runs[-1].exit_code == 0
    assert outcome(session, original) == ("awaiting_verification", "not_comparable")
    assert session.goal_status != "achieved"


def test_changing_the_goal_and_back_keeps_the_original_baseline(tmp_path):
    """Codex's third case: pass_tests -> collect_tests -> pass_tests must not bless a changed test."""
    (tmp_path / "test_app.py").write_text("def test_value():\n    assert 1 == 2\n")
    session, [original] = session_for(tmp_path)
    (tmp_path / "test_app.py").write_text("def test_value():\n    assert 1 == 1\n")
    session.goal = "collect_tests"
    scan(session, ["pytest"])
    session.goal = "pass_tests"
    scan(session, ["pytest_run"])
    assert list(session.verification_baseline["scopes"]) == ["pytest"]  # one baseline for both goals
    assert session.baseline_check["changed"] == ["tests:test_app.py"]
    assert outcome(session, original) == ("awaiting_verification", "not_comparable")
    session.goal = "check_style"
    scan(session, ["ruff"])  # another scope gets its own baseline; the pytest one stays as it was
    assert set(session.verification_baseline["scopes"]) == {"pytest", "ruff"}
    assert session.verification_baseline["scopes"]["pytest"]["reason"] == "first check"


def test_limits_and_oversized_files_make_the_state_unverifiable_never_unchanged(tmp_path, monkeypatch):
    """Codex's fourth case: a truncated snapshot must not vouch for the tests."""
    (tmp_path / "0.txt").write_text("listed first")
    (tmp_path / "test_value.py").write_text("def test_value():\n    assert 1 == 2\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    monkeypatch.setattr(integrity, "MAX_ENTRIES", 1)
    check = integrity.check(session)
    assert check["state"] == "unverifiable" and "files and folders" in check["unverifiable"][0]
    monkeypatch.setattr(integrity, "MAX_ENTRIES", 200_000)
    monkeypatch.setattr(integrity, "MAX_FILES", 0)
    assert integrity.check(session)["state"] == "unverifiable"
    monkeypatch.setattr(integrity, "MAX_FILES", 20_000)
    monkeypatch.setattr(integrity, "MAX_BYTES", 10)
    check = integrity.check(session)
    assert check["state"] == "unverifiable" and "test_value.py is larger than 10 bytes" in check["unverifiable"]


@pytest.mark.skipif(not hasattr(os, "mkfifo") or os.geteuid() == 0, reason="POSIX, as a normal user")
def test_an_unreadable_file_a_named_pipe_or_an_untracked_test_is_unverifiable(tmp_path):
    (tmp_path / "test_value.py").write_text("def test_value():\n    assert 1 == 2\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    assert integrity.check(session)["state"] == "unchanged"
    (tmp_path / "test_value.py").chmod(0)
    try:
        check = integrity.check(session)
        assert check["state"] == "unverifiable" and "test_value.py cannot be read" in check["unverifiable"][0]
    finally:
        (tmp_path / "test_value.py").chmod(0o644)
    os.mkfifo(tmp_path / "test_pipe.py")
    check = integrity.check(session)
    assert check["state"] == "unverifiable" and "test_pipe.py is not a regular file" in check["unverifiable"]
    (tmp_path / "test_pipe.py").unlink()
    session.runs.append(Run(tool="pytest_run", records=[{"type": "outcome", "nodeid": "docs/guide.txt::guide"}]))
    check = integrity.check(session)
    assert check["unverifiable"] == ["docs/guide.txt was collected as a test, but its content is not recorded"]


def test_an_environment_inside_the_project_is_not_read_whatever_its_name(tmp_path):
    (tmp_path / "test_value.py").write_text("def test_value():\n    assert True\n")
    library = tmp_path / "my env" / "lib" / "python3.12" / "site-packages" / "lib"
    library.mkdir(parents=True)
    (tmp_path / "my env" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (library / "test_inside.py").write_text("def test_x():\n    pass\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    integrity.check(session)
    assert list(session.verification_baseline["scopes"]["pytest"]["files"]) == ["test_value.py"]


def test_a_program_goal_has_no_test_baseline_so_editing_the_program_is_the_fix(tmp_path):
    (tmp_path / "main.py").write_text("print(1 / 0)\n")
    session = create_session(tmp_path, sys.executable, goal="run_project",
                             execution={"kind": "script", "entry": "main.py"})
    scan(session, ["python_run"])
    [original] = [i.issue_id for i in session.issues]
    assert session.baseline_check["state"] == "not_applicable" and not session.verification_baseline
    (tmp_path / "main.py").write_text("print(1 / 1)\n")
    scan(session, ["python_run"])
    assert issue(session, original).status == "resolved" and session.goal_status == "achieved"
    with pytest.raises(ValueError, match="no test baseline"):
        integrity.accept(session)


def test_unittest_counts_the_files_its_pattern_selects(tmp_path):
    (tmp_path / "work.py").write_text("VALUE = 2\n")
    (tmp_path / "test_work.py").write_text(
        "import unittest\nimport work\nclass TestWork(unittest.TestCase):\n"
        " def test_value(self): self.assertEqual(work.VALUE, 1)\n")
    session = create_session(tmp_path, sys.executable, goal="auto")
    assert session.goal == "pass_unittest"
    scan(session, ["unittest_run"])
    [original] = [i.issue_id for i in session.issues if i.status == "open"]
    (tmp_path / "test_work.py").write_text(
        "import unittest\nimport work\nclass TestWork(unittest.TestCase):\n"
        " def test_value(self): self.assertEqual(work.VALUE, 2)\n")
    scan(session, ["unittest_run"])
    assert session.baseline_check["changed"] == ["tests:test_work.py"] and session.goal_status != "achieved"
    assert outcome(session, original) == ("awaiting_verification", "not_comparable")


def test_the_style_goal_counts_ruffs_settings(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n')
    (tmp_path / "app.py").write_text("import os\n")
    session, _ = session_for(tmp_path, goal="check_style", check="ruff")
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
    assert accepted.baseline_check["state"] == "unchanged" and accepted.history[-1]["kind"] == "baseline_accepted"
    (project / "tests" / "test_cart.py").write_text("def test_total():\n    assert 1\n")
    assert cli(["--store", str(store.root), "accept-baseline", session.session_id]) == 0  # the command line
    assert "New baseline accepted; changed since the previous one: tests/test_cart.py" in capsys.readouterr().out
    assert json.dumps(store.load(session.session_id).verification_baseline).count("accepted by the user") == 1
