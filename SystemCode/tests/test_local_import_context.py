"""A layout candidate cannot borrow another failure's runtime evidence."""

import sys

import pytest

from fixfirst.evidence import current_environment, project_index
from fixfirst.local_import_context import for_issue
from fixfirst.service import create_session, scan


@pytest.fixture
def import_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    (tmp_path / "source").mkdir()
    (tmp_path / "source/local_ledger.py").write_text("VALUE=23\n")
    (tmp_path / "test_ledger.py").write_text("import local_ledger\ndef test_value(): pass\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    assert issue.diagnosis_rule == "D13-C"
    return session, issue, tmp_path


def context(session, issue):
    run, project = project_index(session)
    return for_issue(session, issue, run, project, current_environment(session))


def test_old_import_probe_cannot_authorize_a_new_direct_raise(import_failure):
    session, issue, root = import_failure
    old_event = next(e for e in session.events if e.event_id in issue.event_ids)
    old_refs = list(old_event.evidence_refs)
    (root / "test_ledger.py").write_text('raise ModuleNotFoundError("No module named \'local_ledger\'")\n')
    scan(session, ["project", "pytest_run"])
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    assert context(session, issue) is None
    for event in session.events:
        if event.event_id in issue.event_ids:
            event.evidence_refs = old_refs[:]
    assert context(session, issue) is None


@pytest.mark.parametrize("change", ["tool", "probe_index", "nodeid", "stage", "record_type", "no_refs", "failure_cwd"])
def test_current_probe_identity_must_match_the_event(import_failure, change):
    session, issue, _ = import_failure
    assert context(session, issue) is not None
    event = next(e for e in session.events if e.event_id in issue.event_ids)
    run = next(r for r in session.runs if r.run_id == event.run_id)
    if change == "tool":
        event.tool = "unittest_run"
    elif change == "probe_index":
        event.evidence_refs = [f"{run.run_id}:probe:{len(run.records)+10}"]
    elif change == "no_refs":
        event.evidence_refs = []
    elif change == "failure_cwd":
        run.cwd = session.project_root + "-another-project"
    else:
        index = int(event.evidence_refs[0].rsplit(":", 1)[1])
        run.records[index][{"nodeid": "nodeid", "stage": "stage", "record_type": "type"}[change]] = {
            "nodeid": "another_test.py", "stage": "teardown", "record_type": "finish"}[change]
    assert context(session, issue) is None


def test_another_node_in_same_run_cannot_donate_an_import_statement(import_failure):
    session, _, root = import_failure
    (root / "test_other.py").write_text('raise ModuleNotFoundError("No module named \'local_ledger\'")\n')
    scan(session, ["project", "pytest_run"])
    latest = next(r for r in reversed(session.runs) if r.tool == "pytest_run")
    events = [e for e in session.events if e.run_id == latest.run_id]
    good = next(e for e in events if e.location == "test_ledger.py")
    bad = next(e for e in events if e.location == "test_other.py")
    issue = next(i for i in session.issues if bad.event_id in i.event_ids)
    isolated = issue.model_copy(update={"event_ids": [bad.event_id]})
    assert context(session, isolated) is None
    bad.evidence_refs = list(good.evidence_refs)
    assert context(session, isolated) is None
