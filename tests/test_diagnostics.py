import hashlib
import json
import sys

import pytest

from fixfirst.grouping import group_events, normalize
from fixfirst.historical_cases import verify_assets
from fixfirst.models import Event, Run
from fixfirst.project import read_project
from fixfirst.service import create_session, scan
from fixfirst.classification import classify
from fixfirst.reasoning import infer_and_plan
from pathlib import Path


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


def test_model_disagreement_does_not_drive_wrong_import_action(tmp_path):
    (tmp_path / "test_app.py").write_text(
        "class InvalidVersion(Exception): pass\ndef test_app():\n    raise InvalidVersion('bad version')\n"
    )
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    model = Path(__file__).parents[1] / "examples/execution-evaluation/decision_tree.json"
    classify(session.issues, str(model))
    infer_and_plan(session)
    issue = session.issues[0]
    assert issue.prediction == "import_failure" and issue.category == "test_runtime_error"
    assert "模型候选与规则证据不同" in issue.prediction_note
    assert any(a.action_id == "review-test_runtime_error" for a in session.actions)
    assert not any(a.action_id == "review-import" for a in session.actions)
