"""Configuration recipes preserve scope and require the current execution snapshot."""

import json
import shlex
import subprocess
import sys

import pytest

from fixfirst.models import Action, Event, Issue, Run, Session
from fixfirst.persistent_configuration import (
    django_plugin_candidate,
    django_recipe,
    import_recipe,
    selection,
    snippet,
)
from fixfirst.runner import environment_id
from fixfirst.service import create_session, scan


def case(root):
    env_id = environment_id(sys.executable)
    s = Session(
        name="configuration",
        project_root=str(root),
        target_python=sys.executable,
        goal="pass_tests",
    )
    env = Run(
        tool="environment", cwd=str(root), environment_id=env_id, exit_code=0, verified_pass=True
    )
    project = Run(tool="project", cwd=str(root), environment_id=env_id, exit_code=0)
    record = {
        "schema_version": 1,
        "complete": True,
        "safe_file": True,
        "rootdir": str(root),
        "pytest_version": "9.1.1",
        "syntax": "ini",
        "section": "pytest",
        "values": {"pythonpath": ["existing root"], "DJANGO_SETTINGS_MODULE": ""},
        "django_plugin_file": "",
        "django_option_registered": False,
        "plugin_autoload_disabled": False,
        "settings_cli": "",
        "settings_environment": "",
    }
    run = Run(
        tool="pytest_run",
        cwd=str(root),
        environment_id=env_id,
        exit_code=2,
        scope="tests:project",
        pytest_options={
            "config_complete": True,
            "config_file": str(root / "pytest.ini"),
            "config_addopts": "-q",
            "environment_addopts": "",
            "persistent_config": record,
        },
    )
    event = Event(
        run_id=run.run_id,
        tool="pytest_run",
        stage="collect",
        kind="missing_module",
        message="missing ledger",
    )
    issue = Issue(
        issue_id="i",
        fingerprint="i",
        tool="pytest_run",
        stage="collect",
        kind="missing_module",
        title="missing",
        component="ledger",
        event_ids=[event.event_id],
        evidence_refs=[],
        member_keys=[],
        scope=run.scope,
        environment_id=env_id,
    )
    s.runs, s.events, s.issues = [env, project, run], [event], [issue]
    environment = {
        "_run_id": env.run_id,
        "packages": [{"name": "pytest", "version": "9.1.1"}],
        "python_version": "3.12.13",
        "paths": {"purelib": str(root / "site")},
    }
    action = Action(
        action_id="path",
        kind="manual_fix",
        title="path",
        explanation="path",
        verification="rerun",
        issue_ids=["i"],
    )
    return s, action, environment, run


def test_selected_file_wins_and_old_paths_with_spaces_are_preserved(tmp_path):
    s, action, environment, run = case(tmp_path)
    selected, error = selection(s, action, environment)
    assert error is None and selected["file"] == "pytest.ini"
    text = import_recipe(selected, "src")
    assert '"existing root"' in text and '"src"' in text
    assert "Update pytest.ini [pytest]" in text and "keep every other option" in text
    # Existing configuration is not read again during planning.
    (tmp_path / "pytest.ini").write_text("bad live content")
    assert selection(s, action, environment)[0] == selected


@pytest.mark.parametrize(
    "bad",
    [
        "imported",
        "truncated",
        "later_run",
        "later_environment",
        "later_project",
        "wrong_scope",
        "wrong_environment",
        "missing_event",
        "wrong_pytest",
        "legacy",
        "unsafe",
        "outside",
        "unknown_syntax",
        "newer_pytest",
        "unknown_options",
        "override_options",
        "bad_paths",
        "bool_schema",
    ],
)
def test_incomplete_stale_foreign_or_ambiguous_context_cannot_authorize_a_recipe(tmp_path, bad):
    s, action, environment, run = case(tmp_path)
    record = run.pytest_options["persistent_config"]
    if bad == "imported":
        run.source = "imported"
    elif bad == "truncated":
        run.truncated = True
    elif bad == "later_run":
        s.runs.append(run.model_copy(update={"run_id": "later"}))
    elif bad == "later_environment":
        s.runs.append(s.runs.pop(0))
    elif bad == "later_project":
        s.runs.append(s.runs.pop(1))
    elif bad == "wrong_scope":
        s.issues[0].scope = "tests:selected"
    elif bad == "wrong_environment":
        run.environment_id = "other"
    elif bad == "missing_event":
        s.issues[0].event_ids.append("missing")
    elif bad == "wrong_pytest":
        environment["packages"][0]["version"] = "8.3.5"
    elif bad == "legacy":
        del run.pytest_options["persistent_config"]
    elif bad == "unsafe":
        record["safe_file"] = False
    elif bad == "outside":
        run.pytest_options["config_file"] = str(tmp_path.parent / "pytest.ini")
    elif bad == "unknown_syntax":
        record["section"] = "other"
    elif bad == "newer_pytest":
        record["pytest_version"] = "10.0"
    elif bad == "unknown_options":
        run.pytest_options["config_complete"] = False
    elif bad == "override_options":
        run.pytest_options["environment_addopts"] = "-c other.ini"
    elif bad == "bad_paths":
        record["values"]["pythonpath"] = [True]
    elif bad == "bool_schema":
        record["schema_version"] = True
    selected, error = selection(s, action, environment)
    assert selected is None and error


def test_no_configuration_can_create_ini_only_at_the_same_project_root(tmp_path):
    s, action, environment, run = case(tmp_path)
    run.pytest_options["config_file"] = ""
    selected, _ = selection(s, action, environment)
    assert selected["new_file"] and snippet(selected, "pythonpath", ["src"]).startswith(
        "Create pytest.ini"
    )
    run.pytest_options["persistent_config"]["rootdir"] = str(tmp_path.parent)
    assert selection(s, action, environment)[0] is None


@pytest.mark.parametrize("root", ["/outside", "../src", "C:/outside", "src\\other", "src\nother"])
def test_import_roots_cannot_escape_or_inject_configuration(tmp_path, root):
    s, action, environment, _ = case(tmp_path)
    selected, _ = selection(s, action, environment)
    assert import_recipe(selected, root) is None


@pytest.mark.parametrize(
    "python,django,candidate",
    [
        ("3.12.13", "4.2.8", "4.11.1"),
        ("3.12.13", "5.2.1", "4.11.1"),
        ("3.13.9", "5.1.3", "4.11.1"),
        ("3.14.0", "5.2.8", "4.14.0"),
        ("3.14.0", "6.0.1", "4.14.0"),
        ("3.12.13", "4.2.7", None),
        ("3.13.9", "5.1.2", None),
        ("3.14.0", "5.2.7", None),
        ("3.13.9", "4.2.26", None),
        ("3.12.13", "3.2.25", None),
        ("3.15.0", "6.0.1", None),
        ("3.14.0rc1", "6.0.1", None),
    ],
)
def test_plugin_candidate_respects_the_interpreter_and_django_boundaries(python, django, candidate):
    environment = {
        "python_version": python,
        "packages": [{"name": "Django", "version": django}, {"name": "pytest", "version": "9.1.1"}],
    }
    result = django_plugin_candidate(environment)
    assert result == (
        [f"pytest-django=={candidate}", f"Django=={django}", "pytest==9.1.1"] if candidate else None
    )


@pytest.mark.parametrize(
    "bad", ["autoload", "cli", "environment", "config_value", "installed_not_loaded"]
)
def test_disabled_or_overridden_django_configuration_never_produces_an_install_command(
    tmp_path, bad
):
    s, action, environment, run = case(tmp_path)
    environment["packages"].append({"name": "Django", "version": "5.2.1"})
    selected, _ = selection(s, action, environment)
    if bad == "autoload":
        selected["plugin_autoload_disabled"] = True
    elif bad == "cli":
        selected["settings_cli"] = "different.settings"
    elif bad == "environment":
        selected["settings_environment"] = "different.settings"
    elif bad == "config_value":
        selected["values"]["DJANGO_SETTINGS_MODULE"] = "different.settings"
    elif bad == "installed_not_loaded":
        environment["packages"].append({"name": "pytest-django", "version": "4.11.1"})
    text, command, error = django_recipe(selected, "suite.config", environment, str(tmp_path))
    assert text is None and command == [] and error


@pytest.mark.parametrize(
    "filename,section,toml",
    [
        ("pytest.ini", "pytest", False),
        ("setup.cfg", "tool:pytest", False),
        ("pyproject.toml", "tool.pytest.ini_options", True),
        ("pytest.toml", "pytest", True),
    ],
)
@pytest.mark.parametrize("goal", ["pass_tests", "collect_tests"])
def test_real_local_import_recipe_survives_a_new_process_without_pythonpath(
    tmp_path, monkeypatch, filename, section, toml, goal
):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    (tmp_path / "src" / "ledger").mkdir(parents=True)
    (tmp_path / "src" / "ledger" / "__init__.py").write_text("VALUE=17\n")
    test = "from ledger import VALUE\ndef test_value():\n    assert VALUE == 17\n"
    (tmp_path / "test_value.py").write_text(test)
    (tmp_path / filename).write_text(f"[{section}]\n")
    session = create_session(tmp_path, sys.executable, goal=goal)
    session.use_classifier = False
    scan(session)
    action = next(a for a in session.actions if "P12" in a.rule_ids)
    assert f"Update {filename} [{section}]" in action.explanation
    assert "including paths outside this project" in action.explanation
    (tmp_path / filename).write_text(
        f"[{section}]\npythonpath = " + ('["src"]\n' if toml else '"src"\n')
    )
    # The fresh subprocess follows the recorded suggestion, with no export.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "test_value.py").read_text() == test


@pytest.mark.parametrize("entry", ["cli", "mcp"])
@pytest.mark.parametrize("has_config", [True, False])
def test_default_user_entries_and_their_rechecks_offer_the_saved_import_path(
    tmp_path, monkeypatch, entry, has_config
):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    project = tmp_path / "project"
    (project / "src" / "ledger").mkdir(parents=True)
    (project / "src" / "ledger" / "__init__.py").write_text("VALUE=17\n")
    (project / "test_value.py").write_text(
        "from ledger import VALUE\ndef test_value():\n    assert VALUE == 17\n"
    )
    if has_config:
        (project / "pytest.ini").write_text("[pytest]\naddopts = -ra -q\n")
    store = tmp_path / "store"
    monkeypatch.setenv("FIXFIRST_STORE", str(store))
    prefix = [sys.executable, "-m", "fixfirst"]
    if entry == "cli":
        created = subprocess.run(
            [*prefix, "init", str(project), "--python", sys.executable, "--goal", "pass_tests"],
            capture_output=True, text=True, timeout=60, check=True,
        )
        session_id = created.stdout.splitlines()[0]
        first = subprocess.run(
            [*prefix, "scan", session_id], capture_output=True, text=True, timeout=60, check=True
        )
        command = next(line.removeprefix("Check again: ") for line in first.stdout.splitlines()
                       if line.startswith("Check again: "))
        # Execute exactly the printed arguments, through this installed interpreter.
        second = subprocess.run(
            [sys.executable, "-m", *shlex.split(command)],
            capture_output=True, text=True, timeout=60, check=True,
        )
        texts = [first.stdout, second.stdout]
    else:
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "diagnose", "arguments": {
                 "project": str(project), "python": sys.executable, "goal": "pass_tests"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "check_again", "arguments": {}}},
        ]
        result = subprocess.run(
            [*prefix, "mcp"], input="".join(json.dumps(r) + "\n" for r in requests),
            capture_output=True, text=True, timeout=120, check=True,
        )
        answers = [json.loads(line) for line in result.stdout.splitlines()]
        tools = [a["result"] for a in answers if a.get("id") in {2, 3}]
        assert len(tools) == 2 and all(t["isError"] is False for t in tools)
        texts = [t["content"][0]["text"] for t in tools]
    assert all("Save the import path in pytest.ini" in text for text in texts), texts
    assert (project / "pytest.ini").exists() is has_config  # Advice did not write the file.


def test_test_only_rescan_uses_the_edited_declaration_instead_of_the_previous_one(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    (tmp_path / "src" / "ledger").mkdir(parents=True)
    (tmp_path / "src" / "ledger" / "__init__.py").write_text("VALUE=17\n")
    (tmp_path / "test_value.py").write_text(
        "from ledger import VALUE\ndef test_value():\n    assert VALUE == 17\n"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pytest-django>=4.5\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    session.use_classifier = False
    scan(session)
    old_project = next(r for r in reversed(session.runs) if r.tool == "project")
    requirements.write_text("pytest-django<4\n")
    scan(session, ["pytest_run"])
    recorded = next(r for r in reversed(session.runs) if r.tool == "project")
    rows = json.loads(recorded.stdout)["declarations"]
    assert recorded.run_id != old_project.run_id
    assert [r["requirement"] for r in rows if r["name"] == "pytest-django"] == ["pytest-django<4"]
    assert requirements.read_text() == "pytest-django<4\n"
    assert any("P12" in a.rule_ids and a.title.startswith("Save ") for a in session.actions)
