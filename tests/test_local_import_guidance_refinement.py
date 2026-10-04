"""Local-import steps preserve execution scope and require recorded build evidence."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from fixfirst.local_import_advice import recorded_editable_project, refine
from fixfirst.models import Action, Execution, Issue, Run, Session
from fixfirst.runner import environment_id
from fixfirst.service import create_session, scan


BUILD = ('[build-system]\nrequires = ["setuptools>=68"]\nbuild-backend = "setuptools.build_meta"\n'
         '[project]\nname = "ff-local-guidance-fixture"\nversion = "0.0.1"\n'
         '[tool.setuptools.packages.find]\nwhere = ["src"]\n')


def session_with_snapshot(root, goal="pass_tests", *, metadata=True):
    env_id = environment_id(sys.executable)
    session = Session(name="guidance", project_root=str(root), target_python=sys.executable,
                      goal=goal, execution=Execution(kind="script", entry="main.py") if goal == "run_project" else None)
    environment = Run(tool="environment", cwd=str(root), environment_id=env_id,
                      exit_code=0, verified_pass=True)
    session.environment = {"_environment_id": env_id, "_run_id": environment.run_id}
    project = Run(tool="project", cwd=str(root), environment_id=env_id, exit_code=0,
                  stdout=json.dumps({"environment_run_id": environment.run_id,
                                     "local_modules": [{"name": "local_ledger", "path": "src/local_ledger"}],
                                     "editable_project": {"schema_version": 1, "supported": metadata,
                                                          "sources": ["pyproject.toml"] if metadata else [],
                                                          "backend": "setuptools.build_meta"}}))
    session.runs = [environment, project]
    issue = Issue(issue_id="i", fingerprint="i", tool="pytest_run", stage="collect",
                  kind="missing_module", component="local_ledger", title="missing local_ledger",
                  event_ids=[], evidence_refs=[], member_keys=[], scope="project", environment_id=env_id)
    action = Action(action_id="fix-path-local_ledger", kind="manual_fix", title="Make it importable",
                    explanation="old", verification="old", issue_ids=["i"], rule_ids=["P12"])
    return session, action, {"i": issue}


@pytest.mark.parametrize("filename,content,accepted", [
    ("pyproject.toml", BUILD, True),
    ("pyproject.toml", '[tool.pytest.ini_options]\ntestpaths=["tests"]\n', False),
    ("pyproject.toml", '[project]\nname="demo"\nversion="1"\n', False),
    ("pyproject.toml", BUILD.replace('requires = ["setuptools>=68"]', 'requires = []'), False),
    ("pyproject.toml", BUILD.replace('requires = ["setuptools>=68"]', 'requires = ["wheel"]'), False),
    ("pyproject.toml", BUILD.replace('"setuptools.build_meta"', '"arbitrary.backend"'), False),
    ("pyproject.toml", BUILD + '[build-system.broken]\nvalue=true\n', True),
    ("pyproject.toml", 'not toml', False),
    ("setup.cfg", '[metadata]\nname=demo\nversion=1\n', False),
    ("setup.py", 'from setuptools import setup\nsetup(name="demo", version="1")\n', True),
    ("setup.py", 'import setuptools\nsetuptools.setup(name="demo", version="1")\n', True),
    ("setup.py", 'from setuptools import setup\nsetup(name=discover_name(), version="1")\n', False),
    ("setup.py", 'def setup(**kwargs): pass\nsetup(name="demo", version="1")\n', False),
    ("setup.py", 'from setuptools import setup\nsetup=lambda **kw: None\nsetup(name="demo",version="1")\n', False),
])
def test_only_static_build_entrypoints_enable_optional_install(tmp_path, filename, content, accepted):
    (tmp_path / filename).write_text(content)
    assert recorded_editable_project(tmp_path)["supported"] is accepted


def test_setup_cfg_needs_a_build_entrypoint_and_is_never_executed(tmp_path):
    (tmp_path / "setup.cfg").write_text('[metadata]\nname=demo\nversion=1\n')
    assert not recorded_editable_project(tmp_path)["supported"]
    (tmp_path / "setup.py").write_text('from setuptools import setup\nsetup()\n')
    assert recorded_editable_project(tmp_path)["sources"] == ["setup.py", "setup.cfg"]
    (tmp_path / "setup.py").write_text('raise RuntimeError("never run me")\n')
    assert not recorded_editable_project(tmp_path)["supported"]


@pytest.mark.parametrize("unsafe", ["symlink", "directory", "oversized"])
def test_unsafe_build_files_do_not_authorize_install(tmp_path, unsafe):
    root = tmp_path / "project"
    root.mkdir()
    target = root / "pyproject.toml"
    if unsafe == "symlink":
        outside = tmp_path / "outside.toml"
        outside.write_text(BUILD)
        target.symlink_to(outside)
    elif unsafe == "directory":
        target.mkdir()
    else:
        target.write_text(BUILD + "\n#" + "x" * 128000)
    assert not recorded_editable_project(root)["supported"]


@pytest.mark.parametrize("change", ["imported", "timeout", "truncated", "wrong_cwd", "stale_environment",
                                   "later_imported", "environment_imported", "environment_failed", "later_environment"])
def test_install_route_needs_current_completed_executed_snapshot(tmp_path, change):
    session, action, issues = session_with_snapshot(tmp_path)
    project = session.runs[-1]
    if change == "imported":
        project.source = "imported"
    elif change == "timeout":
        project.status = "timeout"
    elif change == "truncated":
        project.truncated = True
    elif change == "wrong_cwd":
        project.cwd = str(tmp_path / "other")
    elif change == "stale_environment":
        session.environment["_run_id"] = "later-environment"
    elif change == "later_imported":
        session.runs.append(project.model_copy(update={"source": "imported", "run_id": "imported-project"}))
    elif change == "environment_imported":
        session.runs[0].source = "imported"
    elif change == "later_environment":
        session.runs.append(session.runs[0].model_copy(update={"run_id": "later-environment", "exit_code": 1}))
    else:
        session.runs[0].exit_code = 1
    refine(session, [action], issues)
    assert "pip install" not in action.explanation
    assert not action.command


@pytest.mark.parametrize("metadata", [
    {"schema_version": True, "supported": True, "sources": ["pyproject.toml"], "backend": "setuptools.build_meta"},
    {"schema_version": 1, "supported": True, "sources": ["setup.cfg"], "backend": "setuptools"},
    {"schema_version": 1, "supported": True, "sources": "pyproject.toml", "backend": "setuptools.build_meta"},
    {"schema_version": 1, "supported": True, "sources": ["../pyproject.toml"], "backend": "setuptools.build_meta"},
])
def test_incomplete_or_invalid_build_record_does_not_authorize_install(tmp_path, metadata):
    session, action, issues = session_with_snapshot(tmp_path)
    data = json.loads(session.runs[-1].stdout)
    data["editable_project"] = metadata
    session.runs[-1].stdout = json.dumps(data)
    refine(session, [action], issues)
    assert "pip install" not in action.explanation


def test_live_metadata_does_not_change_recorded_install_route(tmp_path):
    session, action, issues = session_with_snapshot(tmp_path, metadata=False)
    (tmp_path / "pyproject.toml").write_text(BUILD)
    refine(session, [action], issues)
    assert "pip install" not in action.explanation
    session.runs[-1].stdout = session.runs[-1].stdout.replace('"supported": false', '"supported": true').replace(
        '"sources": []', '"sources": ["pyproject.toml"]')
    (tmp_path / "pyproject.toml").unlink()
    refine(session, [action], issues)
    assert "-m pip install -e ." in action.explanation


@pytest.mark.parametrize("goal,wording", [("pass_tests", "original test command"),
                                        ("collect_tests", "original test-collection command"),
                                        ("pass_unittest", "original unittest command"),
                                        ("run_project", "original program command"),
                                        ("check_style", "original style-check command")])
def test_all_goals_preserve_original_execution_contract(tmp_path, goal, wording):
    session, action, issues = session_with_snapshot(tmp_path / "project with spaces", goal, metadata=False)
    refine(session, [action], issues)
    assert wording in action.explanation and wording in action.verification
    assert str(tmp_path / "project with spaces" / "src") in action.explanation
    assert "quote the entire path/value" in action.explanation
    assert "Preserve any existing PYTHONPATH entries" in action.explanation
    assert "same Python interpreter" in action.explanation
    assert "arguments and input" in action.verification
    assert ("package.module" in action.explanation) is (goal == "run_project")
    assert "pip install" not in action.explanation and not action.command


def test_notebook_guidance_retains_its_own_execution_scope(tmp_path):
    session, action, issues = session_with_snapshot(tmp_path, "run_project", metadata=False)
    session.execution = Execution(kind="notebook", entry="analysis.ipynb")
    refine(session, [action], issues)
    assert "original notebook execution" in action.verification
    assert "package.module" not in action.explanation


def make_project(root, *, metadata=False):
    (root / "src" / "local_ledger").mkdir(parents=True)
    (root / "src" / "local_ledger" / "__init__.py").write_text("VALUE = 23\n")
    if metadata:
        (root / "pyproject.toml").write_text(BUILD)
    (root / "main.py").write_text(
        "from local_ledger import VALUE\nimport sys\nprint(VALUE, *sys.argv[1:])\n")


def test_program_goal_guidance_repairs_without_packaging_metadata(tmp_path, monkeypatch):
    root = tmp_path / "project with spaces"
    make_project(root)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    session = create_session(root, sys.executable, goal="run_project",
                             execution=Execution(kind="script", entry="main.py", args=["same argument"]))
    session.use_classifier = False
    scan(session, ["environment", "project", "python_run"])
    action = next(a for a in session.actions if "P12" in a.rule_ids)
    assert "pip install" not in action.explanation
    assert "original program command" in action.verification and "quote the entire" in action.explanation
    command = [sys.executable, "main.py", "same argument"]
    outcome = subprocess.run(command, cwd=root, env={**os.environ, "PYTHONPATH": str(root / "src")},
                             capture_output=True, text=True, timeout=30)
    assert outcome.returncode == 0 and outcome.stdout.strip() == "23 same argument"


def test_unittest_goal_uses_the_same_path_repair(tmp_path, monkeypatch):
    root = tmp_path / "unittest project"
    make_project(root)
    (root / "test_ledger.py").write_text(
        "from local_ledger import VALUE\nimport unittest\n"
        "class TestLedger(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(VALUE,23)\n")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    session = create_session(root, sys.executable, goal="pass_unittest",
                             execution=Execution(kind="unittest", entry="."))
    session.use_classifier = False
    scan(session, ["environment", "project", "unittest_run"])
    action = next(a for a in session.actions if "P12" in a.rule_ids)
    assert "original unittest command" in action.verification
    assert "pip install" not in action.explanation
    outcome = subprocess.run([sys.executable, "-m", "unittest", "discover"], cwd=root,
                             env={**os.environ, "PYTHONPATH": str(root / "src")},
                             capture_output=True, text=True, timeout=30)
    assert outcome.returncode == 0 and "OK" in outcome.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell execution; Windows wording is checked separately")
def test_quoted_shell_assignment_preserves_the_existing_import_path(tmp_path, monkeypatch):
    root = tmp_path / "project with spaces"
    make_project(root)
    support = tmp_path / "support with spaces"
    support.mkdir()
    (support / "existing_support.py").write_text("OFFSET = 1\n")
    (root / "main.py").write_text("from local_ledger import VALUE\nfrom existing_support import OFFSET\nprint(VALUE+OFFSET)\n")
    monkeypatch.setenv("PYTHONPATH", str(support))
    session, action, issues = session_with_snapshot(root, "run_project", metadata=False)
    refine(session, [action], issues)
    assert "quote the entire path/value" in action.explanation
    command = 'PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" ' + shlex.quote(sys.executable) + ' main.py'
    outcome = subprocess.run(["/bin/sh", "-c", command], cwd=root, capture_output=True, text=True, timeout=30)
    assert outcome.returncode == 0 and outcome.stdout.strip() == "24"


def test_packaged_metadata_consumer_needs_the_optional_editable_route(tmp_path, monkeypatch):
    pytest.importorskip("setuptools")
    import pip
    import setuptools

    root = tmp_path / "metadata project with spaces"
    make_project(root, metadata=True)
    (root / "main.py").write_text(
        'from local_ledger import VALUE\nfrom importlib.metadata import version\n'
        'print(VALUE, version("ff-local-guidance-fixture"))\n')
    venv = tmp_path / "isolated environment"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=30)
    interpreter = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # Borrow only the local build tools; the installed fixture goes into the
    # disposable interpreter. No downloads or changes to the test environment.
    support = {str(Path(pip.__file__).parent.parent), str(Path(setuptools.__file__).parent.parent)}
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(sorted(support)))
    session = create_session(root, str(interpreter), goal="run_project",
                             execution=Execution(kind="script", entry="main.py"))
    session.use_classifier = False
    scan(session, ["environment", "project", "python_run"])
    action = next(a for a in session.actions if "P12" in a.rule_ids)
    assert "PYTHONPATH alone is insufficient" in action.explanation and "-m pip install -e ." in action.explanation
    assert not action.command
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(root / "src"), *sorted(support)]))
    command = [str(interpreter), "main.py"]
    before = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
    assert before.returncode != 0 and "PackageNotFoundError" in before.stderr
    installed = subprocess.run([str(interpreter), "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", "."],
                               cwd=root, capture_output=True, text=True, timeout=60)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    after = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
    assert after.returncode == 0 and after.stdout.strip() == "23 0.0.1"
