import os
from pathlib import Path

import pytest

from fixfirst.legacy_pytest import normalize_records
from fixfirst.models import Run
from fixfirst.service import create_session, scan
from fixfirst.test_results import summarize_tests
from fixfirst.test_selection import canonical_nodeid, normalize_tests, selection_observed


@pytest.mark.parametrize("raw, expected", [
    ("tests/test_value.py::TestValue::()::test_value", "tests/test_value.py::TestValue::test_value"),
    ("tests/test_value.py::TestValue::()", "tests/test_value.py::TestValue"),
    ("tests/test_value.py::TestValue::()::test_value[a::()::b]", "tests/test_value.py::TestValue::test_value[a::()::b]"),
    ("tests/test_value.py::test_value[Class::()::case]", "tests/test_value.py::test_value[Class::()::case]"),
    ("tests/test_value.py::TestValue::test_value", "tests/test_value.py::TestValue::test_value"),
])
def test_only_the_instance_segment_is_normalized(raw, expected):
    assert canonical_nodeid(raw) == expected


def test_different_classes_functions_and_parameters_remain_different():
    nodes = ["test_x.py::Alpha::()::test_x[a]", "test_x.py::Alpha::()::test_x[b]",
             "test_x.py::Beta::()::test_x[a]", "test_x.py::Alpha::()::test_y[a]"]
    assert len({canonical_nodeid(node) for node in nodes}) == 4
    assert not selection_observed([nodes[0]], [nodes[1]])


def test_saved_nodes_use_the_canonical_form_and_reject_duplicates(tmp_path):
    (tmp_path / "test_x.py").write_text("class TestX:\n    def test_x(self):\n        pass\n")
    assert normalize_tests(tmp_path, ["test_x.py::TestX::()::test_x"]) == ["test_x.py::TestX::test_x"]
    with pytest.raises(ValueError, match="distinct"):
        normalize_tests(tmp_path, ["test_x.py::TestX::()::test_x", "test_x.py::TestX::test_x"])


def test_normalization_collisions_cannot_earn_coverage():
    nodes = ["test_x.py::TestX::()::test_x", "test_x.py::TestX::test_x"]
    run = Run(tool="pytest_run", tool_version="3.10.1", exit_code=0)
    run.records = [{"type": "outcome", "nodeid": node, "stage": stage, "outcome": "passed"}
                   for node in nodes for stage in ("setup", "call", "teardown")]
    run.records += [{"type": "finish", "nodes": nodes, "collected": 2, "collect_only": False,
                     "records_dropped": False, "exit_code": 0}]
    normalize_records(run)
    summarize_tests(run)
    assert not run.coverage_complete and not run.verified_pass


def test_new_pytest_and_imported_records_keep_the_original_address():
    for run in (Run(tool="pytest_run", tool_version="9.1.1"),
                Run(tool="pytest_run", tool_version="3.10.1", source="imported")):
        run.records = [{"type": "outcome", "nodeid": "test_x.py::TestX::()::test_x"}]
        normalize_records(run)
        assert run.records[0]["nodeid"] == "test_x.py::TestX::()::test_x"


def test_real_pytest_3_class_failure_and_pass_have_the_same_saved_scope(tmp_path, monkeypatch):
    python = os.environ.get("FIXFIRST_TEST_PYTEST310_PYTHON")
    if not python or not Path(python).is_file():
        pytest.skip("A Python 3.9 environment with pytest 3.10.1 is optional")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "value.py").write_text("VALUE = 1\n")
    (tmp_path / "test_x.py").write_text("from value import VALUE\nclass TestX:\n    def test_x(self):\n        assert VALUE == 2\n")
    session = create_session(tmp_path, python, goal="pass_tests", tests=["test_x.py::TestX::test_x"])
    scan(session, ["pytest_run"])
    assert session.runs[-1].coverage_complete and session.runs[-1].test_summary["failed"] == 1
    assert any(r.get("original_nodeid") == "test_x.py::TestX::()::test_x" for r in session.runs[-1].records)
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    (tmp_path / "value.py").write_text("VALUE = 2\n")
    scan(session, ["pytest_run"])
    assert session.runs[-1].passed_nodes == ["test_x.py::TestX::test_x"]
    assert next(i for i in session.issues if i.issue_id == issue.issue_id).status == "resolved"
