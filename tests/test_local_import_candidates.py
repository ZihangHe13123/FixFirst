"""Nested import guidance must not manufacture top-level ownership."""

import json
import os
import subprocess
import sys

import pytest

from fixfirst import local_imports
from fixfirst.evidence import project_index
from fixfirst.project import index_sources
from fixfirst.service import create_session, scan


ENV = {"import_distributions": {}, "packages": [], "stdlib_modules": ["sys", "json"]}


def write(root, path, text="VALUE = 23\n"):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


def index(root):
    return local_imports.index_local_candidates(root, index_sources(root)[0])


def matches(root, name, **project):
    return local_imports.candidate_matches(name, {"local_module_candidates": index(root), **project}, ENV)


@pytest.mark.parametrize("layout", ["lib", "backend/src", "source", "python", "packages/demo/src", "tests"])
def test_six_layouts_record_full_path_and_import_root(tmp_path, layout):
    write(tmp_path, f"{layout}/local_ledger/__init__.py")
    row, = matches(tmp_path, "local_ledger")
    assert row == {"name": "local_ledger", "path": f"{layout}/local_ledger", "import_root": layout,
                   "source": "conventional-layout"}


def test_test_helpers_file_and_full_dotted_names(tmp_path):
    write(tmp_path, "tests/helpers.py")
    write(tmp_path, "source/local_ledger/__init__.py")
    write(tmp_path, "source/local_ledger/sub/__init__.py")
    write(tmp_path, "source/local_ledger/sub/tools.py")
    assert matches(tmp_path, "helpers")[0]["import_root"] == "tests"
    assert matches(tmp_path, "local_ledger.sub.tools")[0]["path"] == "source/local_ledger/sub/tools.py"
    assert matches(tmp_path, "tools") == []
    assert matches(tmp_path, "local_ledger.tools") == []
    assert matches(tmp_path, "local_ledger.sub.missing") == []


@pytest.mark.parametrize("path", ["local_package/source/helpers.py", "source/local_package/src/helpers.py"])
def test_package_ancestor_is_not_cut_into_a_new_top_level(tmp_path, path):
    write(tmp_path, path)
    prefix = path.split("/", 1)[0]
    write(tmp_path, f"{prefix}/__init__.py")
    assert matches(tmp_path, "helpers") == []


def test_multiple_roots_or_module_package_collision_are_ambiguous(tmp_path):
    write(tmp_path, "source/local_ledger.py")
    write(tmp_path, "lib/local_ledger.py")
    assert matches(tmp_path, "local_ledger") == []
    (tmp_path / "lib/local_ledger.py").unlink()
    write(tmp_path, "source/local_ledger/__init__.py")
    assert matches(tmp_path, "local_ledger") == []


def test_helpers_inside_test_package_are_separately_tagged(tmp_path):
    write(tmp_path, "tests/__init__.py", "")
    write(tmp_path, "tests/helpers.py")
    row, = matches(tmp_path, "helpers")
    assert row["source"] == "test-helper-layout"
    assert row["import_root"] == "tests"


def test_nested_src_cannot_cut_an_outer_namespace_package(tmp_path):
    write(tmp_path, "source/local_ledger/src/helpers.py")
    assert matches(tmp_path, "helpers") == []
    assert matches(tmp_path, "local_ledger.src.helpers")[0]["import_root"] == "source"


@pytest.mark.parametrize("path", ["docs/src/helpers.py", "examples/src/helpers.py", "fixtures/src/helpers.py",
                                 "source/fixtures/helpers.py", "vendor/src/helpers.py", "third_party/src/helpers.py",
                                 ".hidden/src/helpers.py", ".venv/lib/helpers.py", "venv/src/helpers.py",
                                 "random/helpers.py"])
def test_incidental_and_excluded_files_do_not_authorize_path_guidance(tmp_path, path):
    write(tmp_path, path)
    assert matches(tmp_path, "helpers") == []


@pytest.mark.parametrize("metadata,text", [
    ("pyproject.toml", '[tool.setuptools.package-dir]\n"" = "modules"\n'),
    ("pyproject.toml", '[tool.setuptools.packages.find]\nwhere = ["modules"]\n'),
    ("pyproject.toml", '[tool.poetry]\npackages = [{include = "local_ledger", from = "modules"}]\n'),
    ("setup.cfg", '[options]\npackage_dir =\n    = modules\n'),
    ("setup.cfg", '[options.packages.find]\nwhere = modules\n'),
    ("setup.py", 'from setuptools import setup\nsetup(package_dir={"": "modules"})\n'),
    ("setup.py", 'import setuptools as s\ns.setup(packages=s.find_packages(where="modules"))\n'),
])
def test_literal_packaging_roots_are_read_without_execution(tmp_path, metadata, text):
    write(tmp_path, "modules/local_ledger/__init__.py", "raise AssertionError('never import')\n")
    write(tmp_path, metadata, text)
    row, = matches(tmp_path, "local_ledger")
    assert row["import_root"] == "modules"
    assert row["source"] == "packaging:" + metadata


def test_explicit_packaging_can_identify_an_otherwise_incidental_root(tmp_path):
    write(tmp_path, "examples/helpers.py")
    assert matches(tmp_path, "helpers") == []
    write(tmp_path, "pyproject.toml", '[tool.setuptools.package-dir]\n"" = "examples"\n')
    assert matches(tmp_path, "helpers")[0]["import_root"] == "examples"


@pytest.mark.parametrize("value", ["../external", "/external", "vendor/src", ".hidden", "bad\\path"])
def test_packaging_roots_cannot_escape_or_enable_excluded_paths(tmp_path, value):
    write(tmp_path, "pyproject.toml", '[tool.setuptools.package-dir]\n"" = ' + json.dumps(value) + '\n')
    assert index(tmp_path) == []


def test_symlink_files_and_directories_do_not_supply_candidates(tmp_path):
    external = tmp_path / "external"
    project = tmp_path / "project"
    write(external, "helpers.py")
    project.mkdir()
    (project / "source").symlink_to(external, target_is_directory=True)
    assert index(project) == []


    (project / "source").unlink()
    (project / "source").mkdir()
    (project / "source/helpers.py").symlink_to(external / "helpers.py")
    assert index(project) == []
    (project / "pyproject.toml").symlink_to(write(external, "pyproject.toml", '[tool.setuptools.package-dir]\n""="source"\n'))
    assert index(project) == []


def test_named_virtual_environment_is_not_a_project_container(tmp_path):
    write(tmp_path, "custom_environment/pyvenv.cfg", "home = /usr/bin\n")
    write(tmp_path, "custom_environment/src/helpers.py")
    assert matches(tmp_path, "helpers") == []


def test_source_and_root_bounds_fail_closed(tmp_path, monkeypatch):
    write(tmp_path, "source/helpers.py")
    files, _ = index_sources(tmp_path)
    monkeypatch.setattr(local_imports, "MAX_SOURCE_FILES", len(files))
    assert local_imports.index_local_candidates(tmp_path, files) == []
    monkeypatch.setattr(local_imports, "MAX_SOURCE_FILES", 2000)
    monkeypatch.setattr(local_imports, "MAX_ROOTS", 0)
    assert local_imports.index_local_candidates(tmp_path, files) == []
    monkeypatch.setattr(local_imports, "MAX_ROOTS", 64)
    monkeypatch.setattr(local_imports, "MAX_CANDIDATES", 0)
    assert local_imports.index_local_candidates(tmp_path, files) == []


def test_external_provider_and_incomplete_environment_prevent_a_local_claim(tmp_path):
    write(tmp_path, "tests/requests.py")
    write(tmp_path, "tests/yaml.py")
    write(tmp_path, "tests/json.py")
    project = {"local_module_candidates": index(tmp_path)}
    assert local_imports.candidate_matches("requests", project, {}) == []
    assert local_imports.candidate_matches("requests", project, {**ENV, "packages": [{"name": "", "version": ""}]}) == []
    assert local_imports.candidate_matches("json", project, ENV) == []
    installed = {**ENV, "import_distributions": {"requests": ["requests"]}}
    assert local_imports.candidate_matches("requests", project, installed) == []
    assert matches(tmp_path, "requests", declarations=[{"name": "requests"}]) == []
    assert matches(tmp_path, "yaml", declarations=[{"name": "PyYAML"}]) == []


def test_project_own_distribution_can_supply_a_candidate(tmp_path):
    write(tmp_path, "source/local_ledger/__init__.py")
    project = {"local_module_candidates": index(tmp_path), "own_names": ["local-ledger"],
               "declarations": [{"name": "local-ledger"}]}
    environment = {**ENV, "import_distributions": {"local_ledger": ["local-ledger"]}}
    assert len(local_imports.candidate_matches("local_ledger", project, environment)) == 1


def test_snapshot_keeps_candidates_separate_from_shadowing_index(tmp_path):
    write(tmp_path, "source/requests.py")
    session = create_session(tmp_path, sys.executable)
    scan(session, ["environment", "project"])
    _, project = project_index(session)
    assert any(row["name"] == "requests" for row in project["local_module_candidates"])
    assert not any(row["name"] == "requests" for row in project["local_modules"])
    assert project["editable_project"]["supported"] is False


@pytest.mark.parametrize("layout,module", [("lib", "local_ledger"), ("backend/src", "local_ledger"),
                                          ("source", "local_ledger"), ("python", "local_ledger"),
                                          ("packages/demo/src", "local_ledger"), ("tests", "helpers")])
def test_real_missing_import_uses_unique_root_and_repairs_same_command(tmp_path, monkeypatch, layout, module):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    root = tmp_path / "project with spaces"
    write(root, f"{layout}/{module}.py")
    write(root, "test_ledger.py", f"from {module} import VALUE\ndef test_value():\n    assert VALUE == 23\n")
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_ledger.py"]
    before = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
    assert before.returncode == 2 and f"No module named '{module}'" in before.stdout
    session = create_session(root, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    assert (issue.diagnosis, issue.diagnosis_rule) == ("local_module", "D13-C")
    action = next(a for a in session.actions if "P12" in a.rule_ids)
    assert layout in action.explanation and "PYTHONPATH" in action.explanation
    assert not action.command
    # This is the only changed input: same interpreter, target and test options.
    after = subprocess.run(command, cwd=root, env={**os.environ, "PYTHONPATH": str(root / layout)},
                           capture_output=True, text=True, timeout=30)
    assert after.returncode == 0 and "1 passed" in after.stdout


@pytest.mark.parametrize("control", ["ambiguous", "declared", "direct_raise", "wrong_dotted", "stdlib"])
def test_real_negative_control_never_gets_new_path_rule(tmp_path, monkeypatch, control):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    write(tmp_path, "source/local_ledger.py")
    statement = "import local_ledger"
    if control == "ambiguous":
        write(tmp_path, "lib/local_ledger.py")
    elif control == "declared":
        write(tmp_path, "requirements.txt", "local-ledger>=1\n")
    elif control == "direct_raise":
        statement = 'raise ModuleNotFoundError("No module named \'local_ledger\'")'
    elif control == "wrong_dotted":
        statement = "import unrelated_package.local_ledger"
    elif control == "stdlib":
        write(tmp_path, "source/sys/nonexistent.py")
        statement = "import sys.nonexistent"
    write(tmp_path, "test_ledger.py", statement + "\ndef test_value():\n    assert True\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    assert any(i.tool == "pytest_run" and i.status == "open" for i in session.issues)
    assert not any(i.diagnosis_rule == "D13-C" for i in session.issues)


@pytest.mark.parametrize("location", ["tests/test_ledger.py", "test_ledger.py"])
def test_packaged_test_helper_is_only_offered_to_tests_in_that_directory(tmp_path, monkeypatch, location):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    write(tmp_path, "tests/__init__.py", "")
    write(tmp_path, "tests/helpers.py")
    write(tmp_path, location, "from helpers import VALUE\ndef test_value():\n    assert VALUE == 23\n")
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", location]
    before = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert before.returncode == 2 and "No module named 'helpers'" in before.stdout
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    if location.startswith("tests/"):
        assert any(i.diagnosis_rule == "D13-C" for i in session.issues)
        action = next(a for a in session.actions if "P12" in a.rule_ids)
        assert "tests" in action.explanation
        after = subprocess.run(command, cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(tmp_path / "tests")},
                               capture_output=True, text=True, timeout=30)
        assert after.returncode == 0 and "1 passed" in after.stdout
    else:
        assert not any(i.diagnosis_rule == "D13-C" for i in session.issues)
