"""Mechanism/ownership tests; no actual model service or reference answers are consulted."""

import hashlib
import json
from pathlib import Path
import sys

from packaging.markers import default_environment
import pytest

from fixfirst.models import Run, Session
from fixfirst.reasoning import diagnose
from fixfirst.runner import environment_id
from fixfirst.service import ingest


def setup_case(tmp_path, mechanism="py", *, windows=False, overrides=None):
    root = "C:/case" if windows else str(tmp_path)
    python = root + ("/.venv/Scripts/python.exe" if windows else "/.venv/bin/python")
    lib = root + ("/.venv/Lib/site-packages" if windows else "/.venv/lib/python3.12/site-packages")
    stdlib = "C:/Python312/Lib" if windows else "/python/lib/python3.12"
    env_id = environment_id(python)
    env = {"python_version": "3.12.13", "executable": python, "prefix": root + "/.venv",
           "paths": {"purelib": lib, "platlib": lib, "stdlib": stdlib},
           "packages": [{"name": "pytest", "version": "6.2.5", "requires": ["py>=1.8.2"]},
                        {"name": "py", "version": "1.10.0" if mechanism == "py" else "1.11.0", "requires": []}],
           "import_distributions": {"_pytest": ["pytest"], "pytest": ["pytest"], "py": ["py"]},
           "stdlib_modules": ["ast", "warnings"], "markers": default_environment()}
    env_run = Run(tool="environment", environment_id=env_id, cwd=root, scope="environment", exit_code=0)
    project = {"files": [], "declarations": [], "requires_python": [], "own_names": [],
               "environment_run_id": env_run.run_id, "local_modules": [], "python_files": []}
    project_run = Run(tool="project", environment_id=env_id, cwd=root,
                      scope="declarations:project", exit_code=0)
    if mechanism == "py":
        text = (f'Traceback (most recent call last):\n  File "{lib}/py/_vendored_packages/apipkg/__init__.py", '
                'line 150, in __makeattr\n    raise AttributeError(name)\nAttributeError: __spec__\n')
    else:
        text = (f'ImportError while loading conftest "{root}/conftest.py".\n'
                'Traceback (most recent call last):\n'
                f'  File "{lib}/_pytest/assertion/rewrite.py", line 958, in visit_Name\n    value = ast.Str()\n'
                f'  File "{stdlib}/ast.py", line 584, in _new\n    warnings._deprecated()\n'
                f'  File "{stdlib}/warnings.py", line 532, in _deprecated\n    warn(msg)\n'
                'DeprecationWarning: ast.Str is deprecated and will be removed in Python 3.14; use ast.Constant instead\n')
    run = Run(tool="pytest_run", environment_id=env_id, cwd=root, scope="tests:project",
              argv=[python, "-m", "pytest", "-q"], exit_code=1 if mechanism == "py" else 4, stderr=text)
    if overrides:
        overrides(env, project, run)
    env_run.stdout, project_run.stdout = json.dumps(env), json.dumps(project)
    session = Session(project_root=root, target_python=python, name="test", goal="pass_tests",
                      environment={**env, "_run_id": env_run.run_id, "_environment_id": env_id})
    ingest(session, [env_run, run, project_run])
    return session, run


@pytest.mark.parametrize("mechanism,rule,target", [("py", "D49", "py==1.11.0"), ("ast", "D50", "pytest==7.3.2")])
@pytest.mark.parametrize("windows", [False, True])
def test_named_rule_and_candidate_require_the_actual_tool_operation(tmp_path, mechanism, rule, target, windows):
    session, _ = setup_case(tmp_path, mechanism, windows=windows)
    issues = [i for i in session.issues if i.tool == "pytest_run"]
    assert len(issues) == 1 and issues[0].diagnosis_rule == rule
    actions = [a for a in session.actions if "P85" in a.rule_ids]
    assert len(actions) == 1
    assert any(target in arg for arg in actions[0].command)
    assert "Python 3.12.13" in actions[0].title
    assert "second route" in actions[0].explanation
    assert "source" not in session.environment["packages"][0]
    assert diagnose(session, knowledge=False)[issues[0].issue_id]["rule_id"] not in {"D49", "D50"}


@pytest.mark.parametrize("field,value", [
    ("py", "1.11.0"), ("py", "1.9.0"), ("py", "1.11.0rc1"), ("py", "1.10.0+patched"),
    ("py", "1.10.0.post1"), ("python", "3.11.9"), ("python", "3.13.0"), ("python", "3.12.0rc1"),
])
def test_affected_intervals_are_bounded_and_unrecognised_versions_do_not_prove_failure(tmp_path, field, value):
    def change(env, project, run):
        if field == "python":
            env["python_version"] = value
        else:
            env["packages"][1]["version"] = value
    session, _ = setup_case(tmp_path, overrides=change)
    assert all(i.diagnosis_rule != "D49" for i in session.issues)


@pytest.mark.parametrize("change", ["project", "foreign_env", "ambiguous", "local", "imported", "truncated", "success", "stale", "hidden"])
def test_spoofed_or_incomplete_ownership_never_becomes_a_tool_diagnosis(tmp_path, change):
    def mutate(env, project, run):
        if change == "project":
            run.stderr = run.stderr.replace(env["paths"]["purelib"] + "/_pytest/assertion/rewrite.py", str(tmp_path / "mod.py"))
        elif change == "foreign_env":
            run.stderr = run.stderr.replace(env["paths"]["purelib"], "/another/lib/python3.12/site-packages")
        elif change == "ambiguous":
            env["import_distributions"]["_pytest"].append("fake-pytest")
        elif change == "local":
            project["local_modules"] = [{"name": "_pytest", "path": "_pytest.py"}]
        elif change == "imported":
            run.source = "imported"
        elif change == "truncated":
            run.truncated = True
        elif change == "success":
            run.exit_code = 0
        elif change == "stale":
            run.environment_id = "other-env"
        elif change == "hidden":
            lines = run.stderr.splitlines()
            run.stderr = "\n".join(line for line in lines if "rewrite.py" not in line)
    session, _ = setup_case(tmp_path, "ast", overrides=mutate)
    assert all(i.diagnosis_rule not in {"D49", "D50"} for i in session.issues)


def test_old_tool_stack_does_not_override_project_shadowing(tmp_path):
    def change(env, project, run):
        env["import_distributions"]["pluggy"] = ["pluggy"]
        env["packages"].append({"name": "pluggy", "version": "1.0.0", "requires": []})
        project["local_modules"] = [{"name": "pluggy", "path": "pluggy.py"}]
        run.stderr = (f'Traceback (most recent call last):\n  File "{env["paths"]["purelib"]}/_pytest/config/__init__.py", '
                      "line 44, in <module>\n    from pluggy import HookimplMarker\n"
                      "ImportError: cannot import name 'HookimplMarker' from 'pluggy'\n")
    session, _ = setup_case(tmp_path, overrides=change)
    assert [i.diagnosis for i in session.issues if i.tool == "pytest_run"] == ["local_module"]
    assert not any("P85" in a.rule_ids for a in session.actions)


def test_constraint_conflict_names_the_py_pin_and_never_installs_pytest_7(tmp_path):
    def change(env, project, run):
        project["declarations"] = [
            {"name": "pytest", "requirement": "pytest>=6,<7", "source": "requirements.txt:1", "group": "required", "status": "satisfied", "installed": "6.2.5"},
            {"name": "py", "requirement": "py==1.10.0", "source": "requirements.txt:2", "group": "required", "status": "satisfied", "installed": "1.10.0"},
        ]
    session, _ = setup_case(tmp_path, overrides=change)
    action = next(a for a in session.actions if "P85" in a.rule_ids)
    assert not action.command
    assert "requirements.txt:2" in action.explanation and "py==1.11.0" in action.explanation
    assert "py==1.10.0" in action.explanation
    assert not any(any("pytest==7" in arg for arg in a.command) for a in session.actions)


def test_warning_source_is_only_named_when_recorded_and_never_claimed_effective(tmp_path):
    plain, _ = setup_case(tmp_path, "ast")
    action = next(a for a in plain.actions if "P85" in a.rule_ids)
    assert "Recorded project" not in action.explanation
    assert "their source is not inferred" in action.explanation
    def change(env, project, run):
        project["pytest_warning_filters"] = [{"source": "pytest.ini [pytest]", "filters": ["error"]}]
    configured, _ = setup_case(tmp_path, "ast", overrides=change)
    action = next(a for a in configured.actions if "P85" in a.rule_ids)
    assert "pytest.ini [pytest]: error" in action.explanation
    assert "Do not delete" in action.explanation


def test_new_startup_probe_retains_project_warning_without_reclassifying_it(tmp_path):
    from fixfirst.service import create_session, scan
    (tmp_path / "pytest.ini").write_text("[pytest]\nfilterwarnings=error\n")
    (tmp_path / "conftest.py").write_text("import warnings\nwarnings.warn('project-owned warning', DeprecationWarning)\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["environment", "pytest_run", "project"])
    run = next(r for r in session.runs if r.tool == "pytest_run")
    assert run.exit_code != 0
    failures = [r for r in run.records if r.get("type") == "exception"]
    assert any(r.get("exception_type") == "DeprecationWarning" and r["source_file"].endswith("conftest.py") for r in failures)
    assert all(i.diagnosis_rule not in {"D49", "D50"} for i in session.issues)


def test_frozen_default_model_is_not_changed():
    path = Path(__file__).resolve().parents[1] / "src/fixfirst/knowledge/diagnosis_tree.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3"


def test_startup_observation_cannot_replace_an_exception_whose_stringifier_raises(monkeypatch):
    from fixfirst import probe
    class BrokenString(Exception):
        def __str__(self):
            raise KeyboardInterrupt("stringification")
    try:
        raise BrokenString()
    except BrokenString:
        original = sys.exc_info()
    class Outcome:
        excinfo = original
    wrapper = probe.pytest_load_initial_conftests()
    next(wrapper)
    with pytest.raises(StopIteration):
        wrapper.send(Outcome())
    assert Outcome.excinfo is original
