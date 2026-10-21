"""Historical names apply only to the observed interface and release."""

import sys
from pathlib import Path

import pytest

from fixfirst.classification import load_model, predict_tree
from fixfirst.diagnosis_cases import CHECKS
from fixfirst.evidence import FEATURE_NAMES, V5_FEATURE_NAMES, observations
from fixfirst.interface_history import matching_history
from fixfirst.service import create_session, scan


def inspect_failure(root, source):
    (root / "app.py").write_text(source)
    (root / "test_app.py").write_text("from app import convert\ndef test_convert():\n    convert()\n")
    s = create_session(root, sys.executable, goal="pass_tests")
    scan(s, CHECKS)
    _, details = observations(s, s.issues)
    d = next(v for v in details.values() if "features" in v)
    return s, dict(zip(FEATURE_NAMES, d["features"]))


@pytest.mark.parametrize("source,expected", [
    ("from sklearn.preprocessing import OneHotEncoder as Encoder\n"
     "def convert():\n    return Encoder(sparse=False)\n", 1),
    ("from sklearn.metrics import mean_squared_error as error\n"
     "def convert():\n    return error([1], [2], squared=False)\n", 1),
    ("import numpy\ndef convert():\n    return numpy.array([1], squared=False)\n", 0),
    ("from sklearn.preprocessing import StandardScaler\n"
     "def convert():\n    return StandardScaler(squared=False)\n", 0),
    ("def mean_squared_error(first, second):\n    return 1\n"
     "def convert():\n    return mean_squared_error([1], [2], squared=False)\n", 0),
])
def test_removed_keyword_requires_the_actual_callable(tmp_path, source, expected):
    pytest.importorskip("sklearn")
    s, f = inspect_failure(tmp_path, source)
    assert f["interface_history_match"] == expected
    rules = {i.diagnosis_rule for i in s.issues if i.tool == "pytest_run"}
    assert ("D04" in rules) == bool(expected)
    if not expected:
        assert all(i.diagnosis != "version_incompatibility" for i in s.issues if i.tool == "pytest_run")


@pytest.mark.parametrize("version,module,local,expected", [
    ("3.12.0", "imp", False, True),
    ("3.11.9", "imp", False, False),
    ("", "imp", False, False),
    ("3.12.0", "imp", True, False),
    ("3.12.0", "uninstalled_vendor", False, False),
])
def test_historical_module_requires_version_and_nonlocal_identity(version, module, local, expected):
    evidence = {"missing_module": module}
    project = {"local_modules": [{"name": module}] if local else []}
    assert bool(matching_history(evidence, project, {"python_version": version})) == expected


@pytest.mark.parametrize("member,expected", [("total", 1), ("unrelated", 0)])
def test_near_attribute_must_belong_to_the_named_class(tmp_path, member, expected):
    _, f = inspect_failure(tmp_path,
        "import unittest\n"
        "class Other:\n    def total(self):\n        return 1\n"
        f"class Calculator(unittest.TestCase):\n    def {member}(self):\n        return 1\n"
        "def convert():\n    return Calculator().totl()\n")
    assert f["context_local_symbol"] == expected
    assert f["interface_history_match"] == 0


def test_previous_61_feature_candidate_keeps_its_prefix(tmp_path):
    _, f = inspect_failure(tmp_path, "def convert():\n    return {}['absent']\n")
    path = Path(__file__).resolve().parents[1] / (
        "experiments/core_diagnosis/observation-development-2026-09-30/results/paired61-tree.json")
    model = load_model(path)
    assert model["schema_version"] == 5
    vector = [f[name] for name in FEATURE_NAMES]
    assert predict_tree(vector, model) == predict_tree(vector[:len(V5_FEATURE_NAMES)], model)


def test_knowledge_disabled_diagnosis_cannot_read_interface_history_features(tmp_path):
    pytest.importorskip("sklearn")
    from fixfirst.reasoning import diagnose

    s, f = inspect_failure(tmp_path, "from sklearn.preprocessing import OneHotEncoder\n"
                           "def convert():\n    return OneHotEncoder(sparse=False)\n")
    assert f["interface_history_match"] == 1
    plain = next(d["evidence"]["features"] for d in diagnose(s, knowledge=False).values()
                 if "features" in d["evidence"])
    assert plain[FEATURE_NAMES.index("interface_history_match")] == 0
    assert plain[FEATURE_NAMES.index("external_call_without_history")] == plain[FEATURE_NAMES.index("callee_external")]
