"""Call provenance must distinguish installed APIs from project bindings."""

from pathlib import Path
import hashlib
import sys

import pytest

from fixfirst.classification import load_model, predict_tree
from fixfirst.diagnosis_cases import CHECKS
from fixfirst.evidence import FEATURE_NAMES, V4_FEATURE_NAMES, observations
from fixfirst.service import create_session, scan
from fixfirst.source_context import index_source_context
from fixfirst.workspace import build_view


def recorded_features(root, source):
    (root / "app.py").write_text(source)
    (root / "test_app.py").write_text("from app import convert\ndef test_convert():\n    convert()\n")
    session = create_session(root, sys.executable, goal="pass_tests")
    scan(session, CHECKS)
    _, details = observations(session, session.issues)
    return dict(zip(FEATURE_NAMES, next(iter(details.values()))["features"]))


def test_import_alias_is_resolved_in_the_failing_file(tmp_path):
    (tmp_path / "unrelated.py").write_text("import urllib.parse as codec\n")
    features = recorded_features(tmp_path,
        'import json as codec\ndef convert():\n    return codec.loads(text="{}")\n')
    assert features["call_signature_mismatch"] == 1
    assert features["callee_external"] == 1
    assert features["callee_project"] == 0
    assert features["context_external_api"] == 1


@pytest.mark.parametrize("source", [
    'import json as codec\ndef parse(codec):\n    return codec.loads("{}", extra=1)\n'
    'class Local:\n    def loads(self, value):\n        return value\n'
    'def convert():\n    return parse(Local())\n',
    'from json import loads as decode\ndef local(value):\n    return value\n'
    'decode = local\ndef convert():\n    return decode("{}", extra=1)\n',
])
def test_shadowed_imports_do_not_become_external_call_failures(tmp_path, source):
    features = recorded_features(tmp_path, source)
    assert features["call_signature_mismatch"] == 1
    assert features["callee_external"] == 0
    assert features["context_external_api"] == 0


@pytest.mark.parametrize("parent,expected", [("unittest.TestCase", 1), ("object", 0)])
def test_an_attribute_owner_is_not_automatically_a_purely_local_class(tmp_path, parent, expected):
    if sys.version_info < (3, 12):
        pytest.skip("assertEquals was removed in Python 3.12")
    features = recorded_features(tmp_path,
        f'import unittest\nclass Local({parent}):\n    pass\n'
        'def convert():\n    return Local().assertEquals(1, 1)\n')
    assert features["context_external_api"] == expected


def test_scope_and_relative_module_resolution_without_executing_code(tmp_path):
    package = tmp_path / "src/pkg"
    package.mkdir(parents=True)
    (package / "app.py").write_text(
        "from .helper import parse as decode\n"
        "def convert(value):\n    return decode(value)\n"
        "def uncertain(decode):\n    return decode(1)\n"
        "def decorated(fn):\n    return fn\n"
        "@decorated\ndef opaque(value):\n    return value\n"
        "opaque(1)\n"
    )
    index = index_source_context(tmp_path, ["src/pkg/app.py"], 128000)
    assert index["calls"]["src/pkg/app.py:3"] == ["pkg.helper.parse"]
    assert "src/pkg/app.py:5" not in index["calls"]
    assert "src/pkg/app.py:11" not in index["calls"]


def test_wildcard_imports_and_external_links_leave_provenance_unknown(tmp_path):
    (tmp_path / "app.py").write_text("import json\nfrom uncertain import *\njson.loads('{}')\n")
    outside = tmp_path.parent / (tmp_path.name + "-outside.py")
    outside.write_text("import json\njson.loads('{}')\n")
    (tmp_path / "link.py").symlink_to(outside)
    try:
        assert index_source_context(tmp_path, ["app.py", "link.py"], 128000)["calls"] == {}
    finally:
        outside.unlink()


def test_deep_attribute_chains_leave_the_static_index_usable(tmp_path):
    (tmp_path / "app.py").write_text("import json\njson" + ".value" * 300 + "()\n")
    assert index_source_context(tmp_path, ["app.py"], 128000)["calls"] == {}


def test_previous_candidate_remains_usable_with_new_observations(tmp_path):
    features = recorded_features(tmp_path,
        'def convert():\n    return {"value": 1}["absent"]\n')
    path = Path(__file__).resolve().parents[1] / "experiments/core_diagnosis/model-development-2026-09-30/candidate-tree.json"
    model = load_model(path)
    assert model["schema_version"] == 4
    vector = [features[name] for name in FEATURE_NAMES]
    assert predict_tree(vector, model) == predict_tree(vector[:len(V4_FEATURE_NAMES)], model)


def test_collection_wrappers_do_not_turn_builtin_errors_into_library_exceptions(tmp_path):
    (tmp_path / "test_import.py").write_text("import fixfirst_nonexistent_source_context_package\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, CHECKS)
    _, details = observations(session, session.issues)
    evidence = next(iter(details.values()))
    assert evidence["exception"] == "ModuleNotFoundError"
    assert evidence["exception_module"] not in ("_pytest.nodes", "_pytest.runner")
    assert evidence["features"][FEATURE_NAMES.index("library_exception_type")] == 0


def test_nested_interpreter_keeps_its_environment_identity_when_exported(tmp_path):
    from fixfirst.diagnosis_cases import PORTABLE_PYTHON, portable
    from fixfirst.evidence import current_environment
    from fixfirst.models import Session
    from fixfirst.runner import environment_id

    python = str(tmp_path / ".venv/bin/python")
    session = Session(name="portable", project_root=str(tmp_path), target_python=python,
                      environment={"_environment_id": environment_id(python), "_run_id": "environment-run", "packages": []})
    data, shared = portable(session, tmp_path)
    data["environment"] = {**shared, **{k: v for k, v in data["environment"].items() if k.startswith("_")}}
    restored = Session.model_validate(data)
    assert restored.target_python == PORTABLE_PYTHON
    assert current_environment(restored)["_run_id"] == "environment-run"


@pytest.mark.parametrize("requirement,source,old,new,expected,title", [
    ("PyYAML>=3.11", 'import yaml\ndef convert():\n    return yaml.load("count: 2")\n',
     'yaml.load("count: 2")', 'yaml.safe_load("count: 2")', {"count": 2}, "Choose an explicit safe YAML loader"),
    ("click>=7.0", 'from click.testing import CliRunner as Runner\ndef convert():\n    return Runner(mix_stderr=False).charset\n',
     'Runner(mix_stderr=False)', 'Runner()', "utf-8", "Update CliRunner's stream capture arguments"),
])
def test_documented_call_changes_have_a_working_narrow_repair(
    tmp_path, requirement, source, old, new, expected, title,
):
    if requirement.startswith("PyYAML"):
        pytest.importorskip("yaml")
    (tmp_path / "requirements.txt").write_text(requirement)
    (tmp_path / "app.py").write_text(source)
    test = tmp_path / "test_app.py"
    test.write_text(f"from app import convert\ndef test_convert():\n    assert convert() == {expected!r}\n")
    original = hashlib.sha256(test.read_bytes()).hexdigest()
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, CHECKS)
    issues = [i for i in session.issues if i.tool == "pytest_run" and i.status == "open"]
    assert len(issues) == 1 and issues[0].diagnosis_rule == "H10"
    assert build_view(session)["steps"][0]["title"] == title
    (tmp_path / "app.py").write_text(source.replace(old, new))
    scan(session, CHECKS)
    assert session.goal_status == "achieved"
    assert hashlib.sha256(test.read_bytes()).hexdigest() == original


@pytest.mark.parametrize("source,requirement", [
    ('import json\ndef convert():\n    return json.loads(text="{}")\n', ""),
    ('import numpy as np\ndef convert():\n    return np.array([1], inconsistent=True)\n', "numpy>=1.21"),
    ('import yaml\ndef convert():\n    return yaml.load("count: 2")\n', "PyYAML>=6.0"),
    ('from click.testing import CliRunner\ndef convert():\n    return CliRunner(mix_stderr=False)\n', "click>=8.2"),
])
def test_an_unknown_argument_or_modern_contract_does_not_recommend_downgrading(
    tmp_path, source, requirement,
):
    if "yaml" in source:
        pytest.importorskip("yaml")
    (tmp_path / "requirements.txt").write_text(requirement)
    (tmp_path / "app.py").write_text(source)
    (tmp_path / "test_app.py").write_text("from app import convert\ndef test_convert():\n    convert()\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, CHECKS)
    issues = [i for i in session.issues if i.tool == "pytest_run" and i.status == "open"]
    assert issues and all(i.diagnosis == "code_defect" for i in issues)
    assert not any(a.action_id.startswith("declared-") for a in session.actions)
