import json
from pathlib import Path
import sys

from fixfirst.knowledge_graph import build_graph, trace_graph
from fixfirst.project import assess_project, read_project
from fixfirst.reasoning import infer_and_plan
from fixfirst.report import render
from fixfirst.service import create_session, scan


def test_declarations_use_target_markers_and_keep_optional_separate(tmp_path):
    (tmp_path / "pyproject.toml").write_text("""[project]
requires-python = ">=3.13"
dependencies = ["not_installed_pkg>=2", "example>=2", "windows-only; sys_platform == 'win32'"]
[project.optional-dependencies]
gpu = ["cuda-missing"]
""")
    (tmp_path / "requirements.txt").write_text("-r nested.txt\n-c constraints.txt\n")
    (tmp_path / "nested.txt").write_text("-r requirements.txt\nexample>=2\n")
    (tmp_path / "constraints.txt").write_text("constraint-only<5\n")
    session = create_session(tmp_path, sys.executable)
    scan(session, ["project"])
    payload = json.loads(session.runs[-1].stdout)
    # Target environment markers, not the host packaging library's defaults.
    env = dict(session.environment)
    env["python_version"] = "3.12.1"
    env["markers"] = {**env["markers"], "sys_platform": "linux"}
    env["packages"] = [{"name": "Example", "version": "1.0"}]
    payload = assess_project(read_project(tmp_path), env)
    rows = {r["name"]: r for r in payload["declarations"]}
    assert rows["not-installed-pkg"]["status"] == "missing"
    assert rows["example"]["status"] == "version_mismatch"
    assert rows["windows-only"]["status"] == "inactive_marker"
    assert rows["cuda-missing"]["status"] == "optional"
    assert rows["constraint-only"]["status"] == "constraint_only"
    assert payload["requires_python"][0]["status"] == "python_mismatch"
    assert len(payload["files"]) == 4
    assert not payload["notes"]


def test_incomplete_marker_snapshot_never_uses_host(tmp_path):
    (tmp_path / "requirements.txt").write_text('missing-package; sys_platform == "darwin"\n')
    payload = assess_project(read_project(tmp_path), {"packages": []})
    assert payload["declarations"][0]["status"] == "unknown"


def test_project_boundaries_include_cycles_invalid_toml_and_constraint_context(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "-c same.txt\n-r same.txt\n-r ../outside.txt\n-r loop.txt\n"
        "-e git+https://example.test/repo\n"
    )
    (tmp_path / "same.txt").write_text("must-exist>=1\n")
    (tmp_path / "loop.txt").write_text("-r requirements.txt\n")
    (tmp_path / "pyproject.toml").write_text("[invalid")
    result = read_project(tmp_path)
    assert {r["constraint"] for r in result["declarations"]} == {True, False}
    assert len(result["files"]) == 4
    assert len(result["notes"]) == 3
    assert all(Path(r["path"]).name != "outside.txt" for r in result["files"])


def test_pip_pass_can_miss_project_dependency_and_advice_has_provenance(tmp_path):
    (tmp_path / "requirements.txt").write_text("fixfirst-never-installed-demo>=2\n")
    session = create_session(tmp_path, sys.executable)
    scan(session, ["pip_check", "project"])
    assert session.runs[0].verified_pass
    issue = next(i for i in session.issues if i.tool == "project")
    assert "requirements.txt:1" in issue.title
    action = next(a for a in session.actions if a.action_id == "review-" + issue.issue_id)
    assert "fixfirst-never-installed-demo" in action.explanation
    graph = build_graph(session)
    paths = trace_graph(graph, action.action_id)["paths"]
    assert any(path[-1]["target"] == session.runs[-1].run_id for path in paths)
    # Removing a dependency changes scope; it does not prove the old requirement was met.
    (tmp_path / "requirements.txt").write_text("pytest>=8\n")
    scan(session, ["project"])
    assert next(i for i in session.issues if i.issue_id == issue.issue_id).status != "resolved"
    render(session, tmp_path / "store", tmp_path / "report.html", public=True)
    text = (tmp_path / "report.html").read_text()
    assert "Project dependency declarations" in text and "Satisfied" in text
    assert str(tmp_path) not in text


def test_declared_missing_import_is_diagnosed_and_stale_snapshot_is_not_used(tmp_path):
    (tmp_path / "requirements.txt").write_text("missing_demo>=2\n")
    (tmp_path / "test_app.py").write_text("import missing_demo\n")
    session = create_session(tmp_path, sys.executable)
    scan(session, ["pytest", "project"])
    issue = next(i for i in session.issues if i.tool == "pytest")
    assert (issue.diagnosis, issue.diagnosis_rule) == ("missing_dependency", "D20")
    action = next(a for a in session.actions if a.action_id == "install-missing_demo")
    assert "requirements.txt:1" in action.explanation
    assert any(f.predicate == "declared_in" for f in session.facts)
    scan(session, ["environment"])
    infer_and_plan(session)
    assert not any(f.predicate == "declared_in" for f in session.facts)
    assert any(a.action_id == "inspect-project" for a in session.actions)


def test_multiple_distributions_and_direct_reference_are_not_verified(tmp_path):
    (tmp_path / "requirements.txt").write_text("example>=1\nremote @ https://example.test/a.whl\n")
    data = assess_project(
        read_project(tmp_path),
        {"packages": [{"name": "example", "version": "1"}, {"name": "example", "version": "2"}]},
    )
    assert [r["status"] for r in data["declarations"]] == ["ambiguous_install", "direct_reference"]


def test_setup_py_and_flit_declarations_are_read_without_running_them(tmp_path):
    from fixfirst.project import read_project

    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n"
        "import os\n"
        "REQUIRES = ['six>=1.6', 'lxml']\n"
        "EXTRAS = {'tests': ['pytest'], ':python_version<\"3\"': ['futures']}\n"
        "setup(name='demo', install_requires=REQUIRES, extras_require=EXTRAS,\n"
        "      tests_require=['pytest-cov'], package_data=os.listdir('.'))\n"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[tool.flit.metadata]\nmodule = "demo"\nrequires = ["click >= 7.1.1, <7.2.0"]\n'
        '[tool.flit.metadata.requires-extra]\ntest = ["shellingham >=1.3.0"]\n'
    )
    rows = {(r["name"], r["source"], r["group"]) for r in read_project(tmp_path)["declarations"]}
    assert rows == {
        ("six", "setup.py install_requires", "required"),
        ("lxml", "setup.py install_requires", "required"),
        ("pytest", "setup.py extras_require[tests]", "tests"),
        ("pytest-cov", "setup.py tests_require", "tests_require"),
        ("click", "pyproject.toml [tool.flit.metadata.requires]", "required"),
        ("shellingham", "pyproject.toml [tool.flit.metadata.requires-extra.test]", "test"),
    }


def test_lock_files_record_the_versions_a_project_was_tested_with(tmp_path):
    from fixfirst.project import tested_versions

    (tmp_path / "Pipfile.lock").write_text(
        '{"default": {"SQLAlchemy": {"version": "==1.2.6"}}, "develop": {"pytest": {"version": "==3.5.0"}}}'
    )
    (tmp_path / "poetry.lock").write_text('[[package]]\nname = "Tablib"\nversion = "0.12.1"\n')
    assert tested_versions(tmp_path) == [
        {"name": "sqlalchemy", "version": "1.2.6", "source": "Pipfile.lock"},
        {"name": "pytest", "version": "3.5.0", "source": "Pipfile.lock"},
        {"name": "tablib", "version": "0.12.1", "source": "poetry.lock"},
    ]
