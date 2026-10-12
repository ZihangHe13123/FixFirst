import json
import sys

from fixfirst import probe
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def test_passing_records_cannot_crowd_out_failure_evidence(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    priority = tmp_path / "events.jsonl.important"
    monkeypatch.setattr(probe, "_probe_path", str(path))
    monkeypatch.setattr(probe, "_important_path", str(priority))
    monkeypatch.setattr(probe, "_dropped", False)
    for index in range(8000):
        probe.emit({"type": "outcome", "stage": "call", "nodeid": f"test_long.py::test_values[{index}]", "outcome": "passed"})
    failure = {"type": "failure", "stage": "call", "nodeid": "test_long.py::test_last", "message": "ValueError: retained"}
    exception = {"type": "exception", "stage": "call", "nodeid": failure["nodeid"], "exception_type": "ValueError"}
    probe.emit(failure)
    probe.emit(exception)
    probe.emit({"type": "finish", "records_dropped": probe._dropped}, final=True)
    assert [json.loads(line) for line in priority.read_text().splitlines()] == [failure, exception]
    assert json.loads(path.read_text().splitlines()[-1])["records_dropped"] is True
    assert path.stat().st_size < 801000


def test_priority_budget_is_bounded_and_cannot_claim_complete_records(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    priority = tmp_path / "events.jsonl.important"
    monkeypatch.setattr(probe, "_probe_path", str(path))
    monkeypatch.setattr(probe, "_important_path", str(priority))
    monkeypatch.setattr(probe, "_dropped", False)
    monkeypatch.setattr(probe, "IMPORTANT_BYTES", 100)
    path.write_text(" " * 800000)
    probe.emit({"type": "failure", "message": "x" * 1000})
    assert probe._dropped is True and not priority.exists()


def test_real_large_suite_keeps_a_late_failure_and_reports_incompleteness(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    (tmp_path / "test_many.py").write_text(
        "import pytest\n@pytest.mark.parametrize('value', range(2600))\n"
        "def test_bulk(value):\n    assert value >= 0\n"
        "def test_last():\n    raise ValueError('TAIL_FAILURE_WAS_RECORDED')\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    run = session.runs[-1]
    assert run.exit_code == 1 and not run.coverage_complete
    assert run.test_summary["failed"] == 1
    assert any(r.get("type") == "failure" and "TAIL_FAILURE_WAS_RECORDED" in r.get("message", "") for r in run.records)
    assert any(r.get("type") == "exception" and r.get("exception_type") == "ValueError" for r in run.records)
    steps = build_view(session)["steps"]
    first = steps[0]
    assert first["title"] == "Test records are incomplete; select a smaller test range"
    assert "--tests" in first["instructions"]
    assert first["cause"] is None and first["possible"] is None
    assert first["rules"] == [] and not first["confirmed_code_defect"]
    assert any(step["id"] != first["id"] and step["issue_ids"] for step in steps)
    assert all("Test records are incomplete" in issue.note for issue in session.issues if issue.status == "open")
    assert session.goal_status != "achieved"
