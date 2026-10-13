from copy import deepcopy
import hashlib
import json
from pathlib import Path

from fixfirst import diagnosis_cases as cases

DATASET = Path(__file__).resolve().parents[1] / "examples/diagnosis-dataset"
PORTABLE_ID = hashlib.sha256(cases.PORTABLE_PYTHON.encode()).hexdigest()[:16]


def saved_case():
    return json.loads((DATASET / "cases.jsonl").read_text(encoding="utf-8").splitlines()[0])["session"]


def test_dataset_rebinds_the_portable_interpreter_without_rewriting_its_input(monkeypatch):
    data = saved_case()
    original = deepcopy(data)
    monkeypatch.setattr(cases, "environment_id", lambda _: "windows-placeholder")
    session = cases.load_session(DATASET, data)
    assert data == original
    assert session.target_python == cases.PORTABLE_PYTHON
    assert session.environment["_environment_id"] == "windows-placeholder"
    assert {r.environment_id for r in session.runs} == {"windows-placeholder"}
    assert {i.environment_id for i in session.issues} == {"windows-placeholder"}


def test_foreign_and_stale_evidence_is_not_rebound(monkeypatch):
    data = saved_case()
    data["environment"]["_environment_id"] = "stale-snapshot"
    data["runs"][0]["environment_id"] = "foreign-run"
    data["issues"][0]["environment_id"] = "foreign-issue"
    monkeypatch.setattr(cases, "environment_id", lambda _: "windows-placeholder")
    session = cases.load_session(DATASET, data)
    assert session.environment["_environment_id"] == "stale-snapshot"
    assert session.runs[0].environment_id == "foreign-run"
    assert session.issues[0].environment_id == "foreign-issue"


def test_real_interpreter_paths_are_not_treated_as_dataset_placeholders(monkeypatch):
    data = saved_case()
    data["target_python"] = "/different/python"
    monkeypatch.setattr(cases, "environment_id", lambda _: "windows-placeholder")
    session = cases.load_session(DATASET, data)
    assert session.environment["_environment_id"] == PORTABLE_ID
    assert {r.environment_id for r in session.runs} == {PORTABLE_ID}


def test_matching_portable_identity_remains_unchanged(monkeypatch):
    data = saved_case()
    monkeypatch.setattr(cases, "environment_id", lambda _: PORTABLE_ID)
    session = cases.load_session(DATASET, data)
    assert session.environment["_environment_id"] == PORTABLE_ID
    assert {r.environment_id for r in session.runs} == {PORTABLE_ID}
