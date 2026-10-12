import shutil
import subprocess
import sys

import pytest

from fixfirst.cli import main
from fixfirst.mcp_server import FACTS_TOOLS, Server, TOOLS
from fixfirst.models import check_scope
from fixfirst.service import create_session, scan
from fixfirst.storage import Store
from fixfirst.test_selection import configure_tests, normalize_tests
from fixfirst.web import App
from fixfirst.workspace import build_view


def project(root):
    root.mkdir(exist_ok=True)
    (root / "ledger.py").write_text("def value():\n    return 0\n")
    (root / "tests_ledger.py").write_text(
        "import pytest\nfrom ledger import value\n\n"
        "@pytest.mark.parametrize('expected', [1, 2])\n"
        "def test_value(expected):\n    assert value() == expected\n")
    return root


def fix(root):
    (root / "ledger.py").write_text("def value():\n    return 1\n")


def test_unseen_file_avoids_unrelated_collection_failure_and_is_saved(tmp_path):
    root = project(tmp_path / "project")
    (root / "test_unrelated.py").write_text("import no_such_auxiliary_module\n")
    session = create_session(root, sys.executable, goal="pass_tests", tests=["tests_ledger.py"])
    scan(session, ["pytest_run"])
    run = session.runs[-1]
    assert run.test_summary == {"passed": 0, "failed": 2, "skipped": 0, "xfail_or_xpass": 0,
                                "selected": 2, "incomplete": 0}
    assert run.requested_tests == ["tests_ledger.py"] and not run.targets
    assert run.argv[-2:] == ["--", "tests_ledger.py"]
    assert session.goal_status == "blocked"
    store = Store(tmp_path / "store")
    store.save(session)
    restored = store.load(session.session_id)
    assert restored.test_targets == ["tests_ledger.py"]
    scan(restored, ["pytest_run"])
    assert restored.runs[-1].argv[-2:] == ["--", "tests_ledger.py"]


@pytest.mark.parametrize("target,count", [("tests_ledger.py::test_value[1]", 1),
                                           ("tests_ledger.py::test_value", 2)])
def test_unseen_node_and_parameterised_node_are_observed(tmp_path, target, count):
    root = project(tmp_path)
    session = create_session(root, sys.executable, goal="auto", tests=[target])
    assert session.goal == "pass_tests"
    scan(session, ["pytest_run"])
    assert session.runs[-1].test_summary["failed"] == count
    if count == 1:
        before = session.issues[0].issue_id
        fix(root)
        scan(session, ["pytest_run"])
        assert next(i for i in session.issues if i.issue_id == before).status == "resolved"
        assert session.goal_status == "achieved"
        view = build_view(session)
        assert view["status"]["headline"] == "The selected tests pass"
        assert "only the saved test selection" in view["status"]["detail"]


def test_changed_selection_cannot_close_same_node_in_original_scope(tmp_path):
    root = project(tmp_path)
    session = create_session(root, sys.executable, goal="pass_tests", tests=["tests_ledger.py"])
    scan(session, ["pytest_run"])
    before = {i.issue_id for i in session.issues}
    scope = check_scope(session, "pytest_run")
    configure_tests(session, ["tests_ledger.py::test_value[1]"])
    assert session.goal_status == "unknown" and check_scope(session, "pytest_run") != scope
    fix(root)
    scan(session, ["pytest_run"])
    assert session.goal_status == "achieved"
    assert all(i.status != "resolved" for i in session.issues if i.issue_id in before)
    configure_tests(session, ["tests_ledger.py"])
    scan(session, ["pytest_run"])
    assert session.goal_status == "blocked"  # expected=2 is still failing
    assert session.runs[-1].test_summary["failed"] == 1


def test_identical_failure_in_two_saved_scopes_keeps_both_issues(tmp_path):
    root = project(tmp_path)
    session = create_session(root, sys.executable, goal="pass_tests", tests=["tests_ledger.py"])
    scan(session, ["pytest_run"])
    ids = {i.issue_id for i in session.issues}
    configure_tests(session, ["tests_ledger.py::test_value[1]"])
    scan(session, ["pytest_run"])
    assert any(i.issue_id not in ids and i.status == "open" for i in session.issues)
    assert any(i.issue_id in ids and i.status != "resolved" for i in session.issues)


def test_partial_action_still_needs_full_saved_selection_for_goal(tmp_path):
    root = project(tmp_path)
    session = create_session(root, sys.executable, goal="pass_tests", tests=["tests_ledger.py"])
    scan(session, ["pytest_run"])
    fix(root)
    scan(session, ["pytest_run"], targets=["tests_ledger.py::test_value[1]"])
    assert session.runs[-1].scope.endswith(":partial")
    assert session.goal_status != "achieved"


@pytest.mark.parametrize("change", ["deleted", "skipped", "timeout"])
def test_missing_skipped_or_incomplete_selected_test_never_verifies(tmp_path, change):
    root = project(tmp_path)
    session = create_session(root, sys.executable, goal="pass_tests", tests=["tests_ledger.py::test_value[1]"])
    scan(session, ["pytest_run"])
    before = session.issues[0].issue_id
    if change == "deleted":
        (root / "tests_ledger.py").unlink()
    elif change == "skipped":
        source = (root / "tests_ledger.py").read_text()
        (root / "tests_ledger.py").write_text(source.replace("def test_value", "@pytest.mark.skip\ndef test_value"))
    else:
        (root / "ledger.py").write_text("import time\ntime.sleep(10)\ndef value():\n    return 1\n")
    scan(session, ["pytest_run"], timeout=1 if change == "timeout" else 30)
    assert next(i for i in session.issues if i.issue_id == before).status != "resolved"
    assert session.goal_status != "achieved"


def test_selection_validation_is_before_execution(tmp_path):
    root = project(tmp_path / "project")
    outside = tmp_path / "outside.py"
    outside.write_text("raise RuntimeError('must not run')\n")
    link = root / "linked.py"
    link.symlink_to(outside)
    for tests in (["--help"], ["../outside.py"], [str(outside)], ["linked.py"], ["."],
                  ["tests_ledger.py::"], ["tests_ledger.py\n"], ["missing.py"],
                  ["tests_ledger.py", "./tests_ledger.py"], "tests_ledger.py", [1]):
        with pytest.raises(ValueError):
            create_session(root, sys.executable, goal="pass_tests", tests=tests)
    assert normalize_tests(root, [str(root / "tests_ledger.py")]) == ["tests_ledger.py"]


def test_cli_initial_selection_nodes_and_default_rescan(tmp_path, capsys):
    root = project(tmp_path / "project")
    store = tmp_path / "store"
    args = ["--store", str(store)]
    assert main([*args, "init", str(root), "--python", sys.executable,
                 "--goal", "pass_tests", "--tests", "tests_ledger.py::test_value[1]"]) == 0
    output = capsys.readouterr().out
    session_id = output.splitlines()[0]
    assert main([*args, "scan", session_id, "--checks", "pytest_run"]) == 0
    assert main([*args, "scan", session_id, "--checks", "pytest_run", "--nodes", "tests_ledger.py"]) == 0
    session = Store(store).load(session_id)
    assert session.test_targets == ["tests_ledger.py"]
    assert main([*args, "configure", session_id, "--tests"]) == 0
    assert not Store(store).load(session_id).test_targets


def test_mcp_selection_reuses_scope_and_keeps_facts_contract(tmp_path):
    root = project(tmp_path / "project")
    server = Server(tmp_path / "store")
    server.diagnose(str(root), python=sys.executable, goal="pass_tests", tests=["tests_ledger.py::test_value[1]"])
    session_id = server.latest
    server.check_again()
    session = server.store.load(session_id)
    assert session.test_targets == ["tests_ledger.py::test_value[1]"]
    assert [r.requested_tests for r in session.runs if r.tool == "pytest_run"] == [session.test_targets] * 2
    server.diagnose(str(root), python=sys.executable, goal="pass_tests", tests=["tests_ledger.py"])
    assert server.latest != session_id
    assert "tests" in TOOLS[0]["inputSchema"]["properties"]
    assert "tests" not in FACTS_TOOLS[0]["inputSchema"]["properties"]


def test_web_selection_uses_same_configuration(tmp_path):
    root = project(tmp_path / "project")
    app = App(tmp_path / "store", tmp_path / "workbench")
    session = app.create({"project": str(root), "python": sys.executable, "goal": "pass_tests",
                          "tests": ["tests_ledger.py::test_value[1]"]})
    app.act(session.session_id, "scan", {})
    run = next(r for r in reversed(app.store.load(session.session_id).runs) if r.tool == "pytest_run")
    assert run.test_summary["selected"] == run.test_summary["failed"] == 1
    assert app.store.load(session.session_id).test_targets == ["tests_ledger.py::test_value[1]"]
    page = app.workspace(session.session_id)
    assert "settings-test-paths" in page and "tests_ledger.py::test_value[1]" in page
    app.act(session.session_id, "configure", {"goal": "pass_tests", "tests": []})
    assert app.store.load(session.session_id).test_targets == []


def test_empty_default_discovery_is_separate_and_quotes_without_execution(tmp_path):
    (tmp_path / "main.py").write_text("print('ok')\n")
    (tmp_path / "Makefile").write_text("test:\n\tpython -m unittest discover; touch SHOULD_NOT_EXIST\n")
    (tmp_path / "tox.ini").write_text("[testenv]\ncommands = nosetests tests_ledger.py\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session)
    view = build_view(session)
    first = view["steps"][0]
    assert first["title"] == "Default pytest did not find any tests"
    assert "--tests" in first["instructions"] and "nosetests tests_ledger.py" in first["instructions"]
    assert "Makefile:2" in first["instructions"]
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()
    assert all(next(i for i in session.issues if i.issue_id == key).tool == "pytest_run"
               for key in first["issue_ids"])


def test_command_quotes_cover_configs_and_ignore_nonregular_or_oversized_sources(tmp_path):
    from fixfirst.project_test_commands import declared_commands

    (tmp_path / "setup.cfg").write_text("[aliases]\ntest = nosetests tests_ledger.py\n")
    (tmp_path / "pyproject.toml").write_text('[tool.hatch.envs.default.scripts]\ntest = "python -m unittest discover"\n')
    (tmp_path / "tox.ini").write_text("#" * 65_000 + "\n[testenv]\ncommands = SHOULD_NOT_APPEAR\n")
    (tmp_path / "Makefile").mkdir()
    quoted = declared_commands(tmp_path)
    assert any(source.startswith("setup.cfg") and command == "nosetests tests_ledger.py" for source, command in quoted)
    assert any(source.startswith("pyproject.toml") and command == "python -m unittest discover" for source, command in quoted)
    assert all(source.startswith(("setup.cfg", "pyproject.toml")) for source, _ in quoted)


@pytest.fixture(scope="module")
def pytest_without_optional_tools(tmp_path_factory):
    uv = shutil.which("uv")
    if not uv:
        pytest.skip("uv is needed to construct a pytest-only target environment")
    path = tmp_path_factory.mktemp("pytest-only") / "env"
    subprocess.run([uv, "venv", str(path), "--python", sys.executable], check=True, capture_output=True)
    python = path / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run([uv, "pip", "install", "--python", str(python), "pytest==8.3.5"],
                   check=True, capture_output=True)
    return str(python)


def test_missing_pip_and_ruff_are_optional_but_ruff_goal_is_required(tmp_path, pytest_without_optional_tools):
    root = project(tmp_path)
    session = create_session(root, pytest_without_optional_tools, goal="pass_tests", tests=["tests_ledger.py"])
    scan(session)
    assert not any(r.tool in ("pip_check", "ruff") for r in session.runs)
    assert session.runs[-1].test_summary["failed"] == 2
    style = create_session(root, pytest_without_optional_tools, goal="check_style")
    scan(style)
    assert any(i.tool == "ruff" and i.status == "open" for i in style.issues)


def test_old_missing_optional_tool_issues_stop_blocking_after_default_rescan(tmp_path, pytest_without_optional_tools):
    (tmp_path / "main.py").write_text("print('ok')\n")
    session = create_session(tmp_path, pytest_without_optional_tools, goal="pass_tests")
    scan(session, ["pip_check", "ruff"])
    assert {i.tool for i in session.issues} == {"pip_check", "ruff"}
    scan(session)
    view = build_view(session)
    assert view["steps"][0]["title"] == "Default pytest did not find any tests"
    tools = {i.issue_id: i.tool for i in session.issues}
    assert all(tools[key] == "pytest_run" for step in view["steps"] for key in step["issue_ids"])
