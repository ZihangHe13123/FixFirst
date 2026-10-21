"""A high-confidence leaf cannot fill explicitly incomplete receiver evidence."""

from copy import deepcopy
import sys

import pytest

from fixfirst.evidence import observations
from fixfirst.mcp_server import render
from fixfirst.reasoning import apply_classifier, infer_and_plan
from fixfirst.removal_ownership import classifier_abstention
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def bounded_case(root, depth, *, parser=False):
    prefix = "from configparser import ConfigParser\nLeaf = ConfigParser\n" if parser else "class Root: pass\nLeaf = Root\n"
    member = "readfp" if parser else "removed"
    (root / "app.py").write_text(prefix + f"while len(Leaf.__mro__) < {depth}:\n"
        "    Leaf = type(f'Level{len(Leaf.__mro__)}', (Leaf,), {})\n"
        "def fail():\n    item = Leaf()\n" + f"    item.{member}()\n")
    (root / "test_app.py").write_text("from app import fail\ndef test_fail():\n    fail()\n")
    session = create_session(root, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    issue = next(i for i in session.issues if i.tool == "pytest_run")
    run = next(r for r in session.runs if r.tool == "pytest_run")
    record = next(r for r in run.records if r.get("type") == "exception")
    return session, issue, run, record


@pytest.mark.parametrize("depth", [65, 70, 130])
def test_bounded_receiver_retains_prediction_without_model_adoption_or_mcp_hint(tmp_path, monkeypatch, depth):
    session, issue, _, record = bounded_case(tmp_path, depth)
    assert record["symbol_observation_status"] == "unsupported_receiver"
    assert record["symbol_observation"] == {}
    monkeypatch.setattr("fixfirst.reasoning.suggest", lambda details, tree: {
        key: ("code_defect", 1.0) for key in details})
    infer_and_plan(session)
    assert (issue.prediction, issue.prediction_confidence) == ("code_defect", 1.0)
    assert "supported bounds" in issue.prediction_note
    assert issue.diagnosis is None
    assert not any(f.subject == issue.issue_id and f.predicate == "model_suggests" for f in session.facts)
    view = build_view(session)
    assert not any(step["possible"] or step["suspected"] for step in view["steps"])
    assert "Defect in project code or tests" not in render(session, view)


@pytest.mark.skipif(sys.version_info < (3, 12), reason="readfp was removed in Python 3.12")
def test_last_supported_mro_keeps_actual_library_rule(tmp_path):
    session, issue, _, record = bounded_case(tmp_path, 64, parser=True)
    assert record["symbol_observation_status"] == "observed_operation"
    assert record["symbol_observation"]["receiver_owners"]
    _, details = observations(session, [issue])
    assert not classifier_abstention(session, issue, details[issue.issue_id])
    assert issue.diagnosis_rule == "D03"


@pytest.fixture
def failure(tmp_path):
    return bounded_case(tmp_path, 65)


@pytest.mark.parametrize("change", [
    "missing_status", "missing_metadata", "unrelated_status", "other_exception", "imported",
    "different_environment", "timeout", "truncated", "success", "missing_exit", "other_run_ref",
    "other_event", "other_stage", "other_node", "other_issue_type",
])
def test_missing_or_unrelated_records_do_not_create_receiver_abstention(failure, monkeypatch, change):
    session, issue, run, record = failure
    _, details = observations(session, [issue])
    evidence = details[issue.issue_id]
    assert classifier_abstention(session, issue, evidence)
    if change == "missing_status":
        record.pop("symbol_observation_status")
    elif change == "missing_metadata":
        record.pop("symbol_observation_status")
        record.pop("symbol_observation")
    elif change == "unrelated_status":
        record["symbol_observation_status"] = "unsupported_call_shape"
    elif change == "other_exception":
        record["exception_type"] = "TypeError"
    elif change == "imported":
        run.source = "imported"
    elif change == "different_environment":
        run.environment_id = "other"
    elif change == "timeout":
        run.status = "timeout"
    elif change == "truncated":
        run.truncated = True
    elif change == "success":
        run.exit_code = 0
    elif change == "missing_exit":
        run.exit_code = None
    elif change == "other_run_ref":
        for event in session.events:
            event.run_id = "other"
    elif change == "other_event":
        issue.event_ids = []
    elif change == "other_stage":
        record["stage"] = "teardown"
    elif change == "other_node":
        record["nodeid"] = "test_app.py::test_unrelated"
    else:
        evidence["exception"] = "TypeError"
    assert not classifier_abstention(session, issue, evidence)
    # Ordinary missing metadata has always been eligible for a learned hint.
    if change in ("missing_status", "missing_metadata", "unrelated_status"):
        monkeypatch.setattr("fixfirst.reasoning.suggest", lambda details, tree: {
            key: ("code_defect", 1.0) for key in details})
        facts = apply_classifier(session, [issue], {issue.issue_id: evidence})
        assert [f.value for f in facts] == ["code_defect"]


def test_grouped_members_do_not_erase_a_limited_member_or_borrow_other_issue(failure):
    session, issue, run, record = failure
    _, details = observations(session, [issue])
    evidence = details[issue.issue_id]
    event = next(e for e in session.events if e.event_id in issue.event_ids)
    index = next(i for i, row in enumerate(run.records) if row is record)
    normal = deepcopy(record)
    normal.pop("symbol_observation_status")
    normal["nodeid"] = "test_app.py::test_other"
    run.records.append(normal)
    normal_event = event.model_copy(deep=True, update={
        "event_id": "normal-member", "location": normal["nodeid"],
        "evidence_refs": [f"{run.run_id}:probe:{len(run.records)-1}"]})
    session.events.append(normal_event)
    issue.event_ids.append(normal_event.event_id)
    assert classifier_abstention(session, issue, evidence)
    # A separately reported failure must not inherit the first one's limit.
    other = issue.model_copy(deep=True, update={"issue_id": "other", "event_ids": [normal_event.event_id]})
    assert not classifier_abstention(session, other, evidence)
    # Selecting the normal member first must not lend its metadata to the limit.
    session.events = [normal_event, *[e for e in session.events if e is not normal_event]]
    assert classifier_abstention(session, issue, evidence)
    assert run.records[index] is record


@pytest.mark.parametrize("size", ["rows", "bytes"])
def test_oversized_retained_ancestry_is_explicitly_incomplete(failure, size):
    session, issue, _, record = failure
    _, details = observations(session, [issue])
    raw = {"source": "failed_instruction_namespace", "kind": "instance", "operation": "LOAD_ATTR",
           "module": "app", "owner": "Leaf", "name": "removed", "file": "/project/app.py", "line": 1,
           "static_namespace_checked": True, "requested_member_present": False, "dynamic": False,
           "unique": False, "candidates": []}
    owner = {"module": "app", "owner": "Leaf", "file": "/project/app.py", "direct": True}
    raw["receiver_owners"] = ([owner] * 129 if size == "rows" else
                              [{**owner, "file": "/" + "a" * 3999}] * 9)
    record["symbol_observation"] = raw
    record["symbol_observation_status"] = "observed_operation"
    assert classifier_abstention(session, issue, details[issue.issue_id])
    raw["receiver_owners"] = [owner]
    assert not classifier_abstention(session, issue, details[issue.issue_id])
    raw["receiver_owners"] = []
    assert not classifier_abstention(session, issue, details[issue.issue_id])
