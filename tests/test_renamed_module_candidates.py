"""A similar filename must be evidence for the particular failed import."""

import sys

import pytest

from fixfirst.evidence import FEATURE_NAMES, observations, renamed_module_candidates
from fixfirst.models import Session
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


@pytest.fixture(autouse=True)
def isolate_test_processes(monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")


def diagnose(root):
    session = create_session(root, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    return session, issue


def assert_generic_review(session, issue):
    assert issue.diagnosis_rule != "D16"
    assert not any("P13" in action.rule_ids for action in session.actions)
    step = build_view(session)["steps"][0]
    assert step["possible"] or step["suspected"]
    assert step["command"] is None


@pytest.mark.parametrize("name, module", [
    ("test_settings.py", "settings"),
    ("test_configuration.py", "configuration"),
    ("tests_configuration.py", "configuration"),
    ("configuration_test.py", "configuration"),
    ("configuration_tests.py", "configuration"),
])
def test_a_modules_test_file_is_not_a_renamed_module(tmp_path, name, module):
    (tmp_path / name).write_text("VALUE = 23\n")
    (tmp_path / "test_entry.py").write_text(f"import {module}\n")
    session, issue = diagnose(tmp_path)
    assert_generic_review(session, issue)
    # The rule rejects this evidence; the original tree input still contains it.
    assert any(f.predicate == "similar_local" and f.value == name for f in session.facts)
    _, details = observations(session, [issue])
    assert details[issue.issue_id]["features"][FEATURE_NAMES.index("module_similar_local")] == 1


def test_the_importing_file_is_not_its_own_rename(tmp_path):
    (tmp_path / "values.py").write_text("import value\n")
    (tmp_path / "test_entry.py").write_text("import values\n")
    session, issue = diagnose(tmp_path)
    assert_generic_review(session, issue)
    assert any(f.predicate == "similar_local" and f.value == "values.py" for f in session.facts)


def test_a_separate_eligible_candidate_still_gets_the_import_advice(tmp_path):
    (tmp_path / "test_settings.py").write_text("import settings\n")
    (tmp_path / "settingss.py").write_text("VALUE = 23\n")
    session, issue = diagnose(tmp_path)
    assert (issue.diagnosis, issue.diagnosis_rule) == ("local_module", "D16")
    steps = [a for a in session.actions if "P13" in a.rule_ids]
    assert len(steps) == 1
    assert "settingss.py" in steps[0].title
    assert "test_settings.py" not in steps[0].title
    assert "test_settings.py" not in steps[0].explanation


@pytest.mark.parametrize("root, location, candidates, expected", [
    ("/project", "pkg/values.py:1", ["pkg/values.py", "values_extra.py"], ["values_extra.py"]),
    ("/project", "/project/pkg/values.py:1", ["pkg/./values.py", "other/values.py"], ["other/values.py"]),
    (r"C:\Project", r"c:\project\pkg\values.py:1", ["pkg/values.py", "other/values.py"], ["other/values.py"]),
])
def test_importer_identity_uses_the_full_normalized_project_path(root, location, candidates, expected):
    session = Session(name="candidate", project_root=root, target_python="python")
    evidence = {"missing_module": "value", "source_location": location, "raised_in": "project"}
    assert renamed_module_candidates(session, evidence, candidates) == expected


def test_test_affixes_match_the_missing_leaf_exactly():
    session = Session(name="candidate", project_root="/project", target_python="python")
    evidence = {"missing_module": "pkg.settings", "source_location": "entry.py:1", "raised_in": "test"}
    candidates = ["test_settings.py", "settings_tests.py", "test_settings_extra.py", "settingss.py"]
    assert renamed_module_candidates(session, evidence, candidates) == ["test_settings_extra.py", "settingss.py"]


def test_an_outer_project_caller_is_not_the_library_importer():
    session = Session(name="candidate", project_root="/project", target_python="python")
    evidence = {"missing_module": "value", "source_location": "values.py:1", "raised_in": "third_party"}
    assert renamed_module_candidates(session, evidence, ["values.py"]) == ["values.py"]


@pytest.mark.parametrize("name, module", [
    ("test_settings", "settings"),
    ("settings_test", "settings"),
    ("tests_configuration", "configuration"),
    ("configuration_tests", "configuration"),
])
def test_a_test_package_is_not_a_renamed_module(tmp_path, name, module):
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 23\n")
    (tmp_path / "report.py").write_text(f"import {module}\n")
    (tmp_path / "test_entry.py").write_text("import report\n")
    session, issue = diagnose(tmp_path)
    assert_generic_review(session, issue)
    assert any(f.predicate == "similar_local" and f.value == f"{name}/__init__.py" for f in session.facts)
    _, details = observations(session, [issue])
    assert details[issue.issue_id]["features"][FEATURE_NAMES.index("module_similar_local")] == 1


def test_a_genuinely_renamed_package_still_gets_the_import_advice(tmp_path):
    (tmp_path / "helpers").mkdir()
    (tmp_path / "helpers" / "__init__.py").write_text("VALUE = 23\n")
    (tmp_path / "test_entry.py").write_text("from helper import VALUE\n")
    session, issue = diagnose(tmp_path)
    assert (issue.diagnosis, issue.diagnosis_rule) == ("local_module", "D16")
    step = next(a for a in session.actions if "P13" in a.rule_ids)
    assert "helpers/__init__.py" in step.title
