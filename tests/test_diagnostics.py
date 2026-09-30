import hashlib
import json
import sys

import pytest

from fixfirst.grouping import group_events, normalize
from fixfirst.historical_cases import verify_assets
from fixfirst.models import Event, Run
from fixfirst.project import read_project
from fixfirst.service import create_session, scan
from fixfirst.evidence import FEATURE_NAMES
from fixfirst.reasoning import infer_and_plan


@pytest.mark.parametrize(
    "body,kind,code",
    [
        (
            "class InvalidVersion(Exception): pass\ndef test_app():\n    raise InvalidVersion('bad 3.11.1+')\n",
            "test_runtime_error",
            "InvalidVersion",
        ),
        (
            """def test_app():
    assert False, "ModuleNotFoundError: No module named 'requests'"
""",
            "test_assertion",
            "AssertionError",
        ),
        (
            """def test_app():
    try:
        import not_installed_inner
    except ImportError as cause:
        raise ValueError("request rejected") from cause
""",
            "test_runtime_error",
            "ValueError",
        ),
    ],
)
def test_actual_exception_type_overrides_traceback_words(tmp_path, body, kind, code):
    (tmp_path / "test_app.py").write_text(body)
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    assert len(session.events) == 1
    event = session.events[0]
    assert (event.kind, event.code) == (kind, code)
    assert event.component == ""
    assert event.source_file.endswith("test_app.py") and event.source_line > 0
    assert event.message.startswith(code + ":")
    assert len(event.message) < 250
    first_id = session.issues[0].issue_id
    scan(session, ["pytest_run"])
    assert len(session.issues) == 1 and session.issues[0].issue_id == first_id


def test_redaction_keeps_structured_exception_and_completion(tmp_path):
    secret = "secret-value-for-test"
    (tmp_path / "test_app.py").write_text(
        f"def test_app():\n    raise ValueError('token={secret}')\n"
    )
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    assert session.runs[0].coverage_complete
    assert session.events[0].code == "ValueError"
    assert secret not in session.model_dump_json()
    assert "[credential]" in session.events[0].message


@pytest.mark.parametrize("method", ["exact", "tfidf"])
def test_volatile_object_address_merges_but_different_numeric_values_stay_separate(method):
    run = Run(tool="pytest_run")
    events = [
        Event(
            run_id=run.run_id,
            tool="pytest_run",
            stage="call",
            kind="test_runtime_error",
            location="test_app.py::test_app",
            message=f"ValueError: invalid <Widget object at {address}>",
        )
        for address in ("0x123ABC", "0x789DEF")
    ]
    assert len(group_events(events, run, method=method)) == 1
    assert normalize("expected 0x100 actual 0x200") != normalize("expected 0x100 actual 0x300")


def test_structural_boundaries_preserve_version_path_and_module():
    run = Run(tool="pytest")
    base = dict(run_id=run.run_id, tool="pytest", stage="collect", kind="import_failure")
    events = [
        Event(**base, component="api.v1", message="No module api.v1"),
        Event(**base, component="api.v2", message="No module api.v2"),
        Event(**base, component="same", message="same requires version 2.1"),
        Event(**base, component="same", message="same requires version 2.2"),
        Event(**base, location="test_a.py", message="Cannot import name value"),
        Event(**base, location="test_b.py", message="Cannot import name value"),
    ]
    assert len(group_events(events, run, method="tfidf")) == len(events)


def test_invalid_dependency_array_does_not_create_character_packages(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies="requests"\n')
    data = read_project(tmp_path)
    assert not data["declarations"] and data["notes"]


def test_historical_assets_reject_tampered_files(tmp_path):
    wheel = tmp_path / "example.whl"
    wheel.write_bytes(b"original")
    (tmp_path / "LICENSE").write_text("test license")
    manifest = {
        "assets": [
            {
                "package": "demo",
                "version": "1",
                "filename": wheel.name,
                "bytes": 8,
                "sha256": hashlib.sha256(b"original").hexdigest(),
                "licenses": ["LICENSE"],
            }
        ]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert verify_assets(tmp_path)[("demo", "1")] == wheel
    wheel.write_bytes(b"modified")
    with pytest.raises(ValueError, match="SHA256"):
        verify_assets(tmp_path)


def single_leaf_model(tmp_path, label):
    path = tmp_path / "model.json"
    model = {
        "schema_version": 6,
        "task": "root_cause",
        "feature_names": FEATURE_NAMES,
        "classes": [label],
        "nodes": [{"left": -1, "right": -1, "feature": -2, "threshold": -2.0, "values": [1.0]}],
    }
    path.write_text(json.dumps(model))
    return str(path)


def test_classifier_suggestion_never_overrides_rule_diagnosis(tmp_path):
    (tmp_path / "test_app.py").write_text("def test_app():\n    assert 1 == 2\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    session.model_path = single_leaf_model(tmp_path, "missing_dependency")
    infer_and_plan(session)
    issue = session.issues[0]
    assert issue.prediction == "missing_dependency"
    assert (issue.diagnosis, issue.diagnosis_source, issue.diagnosis_rule) == (
        "code_defect",
        "rule",
        "D40",
    )
    assert "rule D40" in issue.prediction_note
    assert session.actions[0].action_id == "review-test_assertion"
    assert not any(a.cause == "missing_dependency" for a in session.actions)


def test_classifier_suggestion_fills_gap_as_lower_ranked_hypothesis(tmp_path):
    (tmp_path / "test_app.py").write_text(
        "class InvalidVersion(Exception): pass\ndef test_app():\n    raise InvalidVersion('bad version')\n"
    )
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    session.model_path = single_leaf_model(tmp_path, "version_incompatibility")
    infer_and_plan(session)
    issue = session.issues[0]
    assert (issue.diagnosis, issue.diagnosis_source) == ("version_incompatibility", "model")
    actions = {a.action_id: a for a in session.actions}
    consider = actions["consider-version_incompatibility"]
    assert consider.evidence_rank == 0
    assert all(f.status == "hypothesis" for f in session.facts if f.fact_id in consider.reason_refs)
    assert actions["review-test_runtime_error"].priority < consider.priority
    session.use_classifier = False
    infer_and_plan(session)
    assert session.issues[0].diagnosis is None


def test_a_check_that_could_not_run_gets_no_root_cause(tmp_path):
    (tmp_path / "test_app.py").write_text("def test_app():\n    assert True\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    session.target_python = str(tmp_path / "missing-python")
    scan(session, ["pytest_run"])
    issue = session.issues[0]
    assert issue.kind == "tool_failure"
    assert issue.diagnosis is None and issue.prediction is None
    assert not any(a.action_id.startswith("consider-") for a in session.actions)
