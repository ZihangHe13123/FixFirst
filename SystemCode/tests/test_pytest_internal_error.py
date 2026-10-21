import sys

from fixfirst.models import Run
from fixfirst.runner import environment_id
from fixfirst.service import create_session, ingest, scan
from fixfirst.workspace import build_view


def test_real_internal_error_is_the_first_step_and_never_a_confirmed_fix(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    (tmp_path / "helpers.py").write_text("VALUE = 1\n")
    (tmp_path / "test_app.py").write_text("def test_app():\n    assert True\n")
    (tmp_path / "conftest.py").write_text(
        "def pytest_collection(session):\n    raise ModuleNotFoundError(\"No module named 'helper'\")\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    assert session.runs[-1].exit_code == 3
    first = build_view(session)["steps"][0]
    assert first["title"] == "pytest stopped with an internal error"
    assert "not confirmed" in first["instructions"] and "--tests" in first["instructions"]
    assert first["cause"] is None and first["command"] is None
    assert all(i.diagnosis_source != "rule" for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    assert not session.runs[-1].verified_pass and session.goal_status != "achieved"


def test_collection_failure_is_not_an_internal_error(tmp_path):
    (tmp_path / "test_app.py").write_text("import yaml_missing_name\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    assert session.runs[-1].exit_code == 2
    assert build_view(session)["steps"][0]["title"] != "pytest stopped with an internal error"


def test_imported_exit_three_is_not_treated_as_an_executed_internal_error(tmp_path):
    (tmp_path / "test_app.py").write_text("def test_app():\n    pass\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    run = Run(tool="pytest_run", source="imported", exit_code=3, stderr="INTERNALERROR> RuntimeError: broken",
              environment_id=environment_id(sys.executable))
    ingest(session, [run])
    assert all(step["title"] != "pytest stopped with an internal error" for step in build_view(session)["steps"])
