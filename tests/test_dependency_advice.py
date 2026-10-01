"""Repair planning regressions from the public development field trial."""

import json
import sys

from packaging.markers import default_environment
from packaging.specifiers import SpecifierSet
import pytest

from fixfirst import cli
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def test_unobserved_old_failure_does_not_generate_current_version_advice(tmp_path, capsys):
    application = tmp_path / "app.py"
    application.write_text("import numpy as np\ndef convert():\n    return np.float(1)\n")
    (tmp_path / "test_app.py").write_text("from app import convert\ndef test_value():\n    assert convert() == 1\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    old = next(i for i in session.issues if i.tool == "pytest_run")
    assert old.diagnosis_rule == "D02"
    assert any("numpy.float" in a.title for a in session.actions)
    # A new collection failure prevents observing the old call failure. It is
    # neither verified fixed nor evidence for giving its old remedy again.
    application.write_text("import fixfirst_new_missing_dependency\n")
    scan(session, ["environment", "project", "pytest_run"])
    old = next(i for i in session.issues if i.issue_id == old.issue_id)
    assert old.status == "not_observed"
    assert not any(old.issue_id in a.issue_ids and a.kind != "rerun" for a in session.actions)
    expected = build_view(session)["steps"][:5]
    cli.show(session)
    output = capsys.readouterr().out.split("Next steps", 1)[1]
    assert "Replace numpy.float" not in output
    positions = [output.index(step["title"]) for step in expected]
    assert positions == sorted(positions)


def recorded_session(root, requirements, packages, failure, imports=None):
    from fixfirst.models import Run
    from fixfirst.project import assess_project, read_project
    from fixfirst.runner import environment_id
    from fixfirst.service import ingest

    (root / "requirements.txt").write_text(requirements)
    session = create_session(root, sys.executable, goal="pass_tests")
    identity = environment_id(session.target_python)
    environment = {"python_version": "3.12.13", "packages": packages,
                   "markers": {**default_environment(), "python_version": "3.12", "python_full_version": "3.12.13"},
                   "import_distributions": imports or {}, "stdlib_modules": []}
    env_run = Run(tool="environment", exit_code=0, environment_id=identity, stdout=json.dumps(environment))
    session.environment = {**environment, "_run_id": env_run.run_id, "_environment_id": identity}
    project = assess_project(read_project(root), environment)
    project["environment_run_id"] = env_run.run_id
    ingest(session, [env_run, Run(tool="project", exit_code=0, environment_id=identity,
                                 scope="declarations:project", stdout=json.dumps(project)),
                     Run(tool="pytest_run", exit_code=2, environment_id=identity, scope="tests:project", stderr=failure)])
    return session


def test_installed_lower_bound_precedes_an_older_search_for_missing_attribute(tmp_path):
    session = recorded_session(tmp_path, "Flask-SQLAlchemy==3.1.1\n",
        [{"name": "SQLAlchemy", "version": "1.4.54", "requires": []},
         {"name": "Flask-SQLAlchemy", "version": "3.1.1", "requires": ["sqlalchemy>=2.0.16"]}],
        "AttributeError: module 'sqlalchemy.orm' has no attribute 'DeclarativeBase'",
        {"sqlalchemy": ["SQLAlchemy"]})
    issue = next(i for i in session.issues if i.tool == "pytest_run")
    assert issue.diagnosis_rule == "D06"
    step = build_view(session)["steps"][0]
    action = next(a for a in session.actions if a.action_id == step["id"])
    assert action.command[-1].startswith("sqlalchemy")
    spec = SpecifierSet(action.command[-1].removeprefix("sqlalchemy"))
    assert "2.0.16" in spec and "1.4.54" not in spec and "3.0" not in spec
    assert "no longer provides" not in step["explanation"]
    assert not any(a.check == "version_search" for a in session.actions)


def test_fixed_project_pin_blocks_all_older_searches_for_the_same_distribution(tmp_path):
    session = recorded_session(tmp_path, "Django==1.10.5\n",
        [{"name": "Django", "version": "1.10.5", "requires": []},
         {"name": "djangorestframework", "version": "3.4.4", "requires": ["Django>=1.8"]}],
        "ImportError: cannot import name 'quote' from 'django.utils.six.moves.urllib.parse'", {"django": ["Django"]})
    assert not any(a.check == "version_search" for a in session.actions)
    step = build_view(session)["steps"][0]
    assert "requirements.txt:1" in step["explanation"] and "Django==1.10.5" in step["explanation"]
    assert "Python" in step["title"] and not step["command"]


def test_missing_required_dependencies_form_one_constrained_request(tmp_path):
    session = recorded_session(tmp_path, "rich>=13\nclick<9\nattrs\n", [],
                               "ModuleNotFoundError: No module named 'rich'")
    first = build_view(session)["steps"][0]
    action = next(a for a in session.actions if a.action_id == first["id"])
    assert set(action.command[5:]) == {"rich>=13", "click<9", "attrs"}
    assert "3 missing" in action.title


def test_failed_build_is_tied_to_the_pin_and_becomes_history_after_it_changes(tmp_path):
    from fixfirst.models import Run
    from fixfirst.project import assess_project, read_project
    from fixfirst.runner import environment_id
    from fixfirst.service import ingest

    session = recorded_session(tmp_path, "pandas==1.1.0\nrich\n", [],
                               "ModuleNotFoundError: No module named 'pandas'")
    install = Run(tool="pip_install", source="imported", environment_id="unknown", exit_code=1,
                  stdout="Collecting pandas==1.1.0 (from -r requirements.txt (line 1))\n"
                         "ERROR: Failed to build 'pandas' when installing build dependencies for pandas\n")
    ingest(session, [install])
    step = build_view(session)["steps"][0]
    assert step["id"] == "review-install-pandas" and not step["command"]
    assert "pandas==1.1.0" in step["explanation"] and "requirements.txt:1" in step["explanation"]
    assert "imported" in step["explanation"]
    assert not any("pandas==1.1.0" in a.command for a in session.actions)
    (tmp_path / "requirements.txt").write_text("pandas\nrich\n")
    payload = assess_project(read_project(tmp_path), session.environment)
    payload["environment_run_id"] = session.environment["_run_id"]
    ingest(session, [Run(tool="project", environment_id=environment_id(session.target_python), exit_code=0,
                         scope="declarations:project", stdout=json.dumps(payload))])
    assert not any(a.action_id == "review-install-pandas" for a in session.actions)
    first = build_view(session)["steps"][0]
    assert first["command"] and "pandas" in first["command"] and "rich" in first["command"]


@pytest.mark.parametrize("specifier,empty", [
    ("==1.1.9,>1.1.9", True), (">=2.0.16,<1", True), (">=2.0.16,<3", False),
    ("==1.2.*,>=1.3", True), ("~=1.2.3,>=1.3", True), (">=1,<=1", False),
])
def test_requirement_intersections_do_not_silently_drop_a_pin(specifier, empty):
    from fixfirst.dependency_context import contradicts

    assert contradicts(specifier) is empty


def test_requirement_markers_are_target_scoped_and_extras_stay_optional():
    from fixfirst.dependency_context import context, requirements_for

    package = {"name": "consumer", "version": "1", "requires": [
        "example>=2; sys_platform == 'win32'", "example<2; sys_platform == 'linux'",
        "example==0; extra == 'legacy'",
    ]}
    env = {"packages": [package], "markers": {**default_environment(), "sys_platform": "win32"}}
    win = context(env, {})
    assert [r["specifier"] for r in requirements_for(win, "example")] == [">=2"]
    missing = context({**env, "markers": {}}, {})
    assert not requirements_for(missing, "example") and missing["notes"]
    changed = context({**env, "packages": [{**package, "requires": ["example>=3"]}]}, {})
    assert win["fingerprint"] != changed["fingerprint"]


def test_conda_declarations_keep_installer_semantics(tmp_path):
    from fixfirst.project import read_project

    (tmp_path / "environment.yml").write_text(
        "name: demo\ndependencies:\n  - python=3.12\n  - numpy\n  - imageio>=2\n"
        "  - pytorch\n  - private-channel::custom=1.0=build\n  - pip:\n    - rich>=13\n")
    project = read_project(tmp_path)
    assert {r["requirement"] for r in project["declarations"]} == {"numpy", "imageio>=2", "rich>=13"}
    assert project["requires_python"][0]["specifier"] == "==3.12.*"
    assert len(project["conda_declarations"]) == 2
    assert any("no PyPI name is assumed" in note for note in project["notes"])


def test_explicit_extras_propagate_but_unrequested_extras_do_not():
    from fixfirst.dependency_context import context, requirements_for

    env = {"markers": default_environment(), "packages": [
        {"name": "consumer", "version": "1", "requires": ["adapter[fast]; extra == 'web'"]},
        {"name": "adapter", "version": "1", "requires": ["example>=2; extra == 'fast'", "example<2; extra == 'old'"]},
    ]}
    project = {"declarations": [{"requirement": "consumer[web]", "source": "requirements.txt:1", "group": "required"}]}
    enabled = context(env, project)
    assert [r["specifier"] for r in requirements_for(enabled, "example")] == [">=2"]
    assert not requirements_for(context(env, {}), "example")


def test_batch_keeps_both_explicit_extras_for_the_same_package(tmp_path):
    session = recorded_session(tmp_path, "demo[a]\ndemo[b]\nrich\n", [],
                               "ModuleNotFoundError: No module named 'rich'")
    action = next(a for a in session.actions if a.action_id == build_view(session)["steps"][0]["id"])
    assert set(action.command[5:]) == {"demo[a,b]", "rich"}


def test_yaml_aliases_cannot_expand_the_total_dependency_budget():
    from fixfirst.conda_declarations import read

    parsed = read("dependencies:\n  - pip: &packages [rich, click, attrs]\n"
                  "  - pip: *packages\n  - pip: *packages\n", "environment.yml", limit=5)
    assert len(parsed["pip"]) <= 5
    assert any("limit" in note for note in parsed["notes"])


def test_release_candidates_respect_reverse_constraints_before_any_trial():
    from fixfirst.versions import search
    from test_versions import FakeSandbox, MAC, pypi

    box = FakeSandbox(last="1.5.12")
    result = search("python", "3.12.13", MAC, "django", "1.10.5", "django.utils.six.moves",
                    fetch=lambda url: pypi("1.5.12", "1.8.19", "1.9.13"), sandbox=box, specifier=">=1.8")
    assert "1.5.12" not in box.tried
    assert result["provides"] is None
    exact = search("python", "3.12.13", MAC, "django", "1.10.5", "django.utils.six.moves",
                   fetch=lambda url: pypi("1.5.12", "1.8.19"), sandbox=box, specifier="==1.10.5")
    assert exact["status"] == "constraints_exclude_candidates" and not exact["checked"]
