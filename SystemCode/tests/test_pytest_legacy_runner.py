"""Old test runners receive only options they support, without changing modern checks."""

import os
from pathlib import Path
import sys

import pytest

from fixfirst import runner
from fixfirst.models import Run
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def project(root, python=sys.executable):
    (root / "pytest.ini").write_text("[pytest]\n")
    (root / "value.py").write_text("VALUE = 1\n")
    (root / "tests_value.py").write_text("from value import VALUE\ndef test_value():\n    assert VALUE == 2\n")
    return create_session(root, python, goal="pass_tests", tests=["tests_value.py"])


@pytest.mark.parametrize("version, rootdir", [("3.2.1", False), ("3.4.2", False),
                                            ("3.5.0", True), ("3.10.1", True), ("9.1.1", True)])
def test_rootdir_is_only_sent_to_versions_that_support_it(tmp_path, monkeypatch, version, rootdir):
    session = project(tmp_path)
    session.environment = {"_environment_id": runner.environment_id(sys.executable),
                           "packages": [{"name": "pytest", "version": version}]}
    def execute(argv, cwd, tool, scope, python, *args, **kwargs):
        return Run(tool=tool, argv=argv, scope=scope, cwd=cwd, exit_code=5,
                   environment_id=runner.environment_id(python))
    monkeypatch.setattr(runner, "execute", execute)
    run = runner.collect(session, "pytest_run")
    assert ("--rootdir" in run.argv) is rootdir
    assert run.argv[-2:] == ["--", "tests_value.py"]


def test_unsupported_runner_has_a_specific_first_step(tmp_path):
    session = project(tmp_path)
    session.environment = {"_environment_id": runner.environment_id(sys.executable),
                           "packages": [{"name": "pytest", "version": "3.1.0"}]}
    from fixfirst.service import ingest

    ingest(session, [runner.collect(session, "pytest_run")])
    first = build_view(session)["steps"][0]
    assert first["title"] == "pytest 3.1.0 is too old for this check"
    assert "minimum supported pytest version is 3.2.1" in first["instructions"]
    assert session.goal_status != "achieved"


def test_stale_metadata_does_not_change_the_command(tmp_path):
    session = project(tmp_path)
    session.environment = {"_environment_id": "another-interpreter", "packages": [{"name": "pytest", "version": "3.1.0"}]}
    assert runner.pytest_version(session) is None


def test_real_pytest_32_records_failure_and_repair(tmp_path, monkeypatch):
    python = os.environ.get("FIXFIRST_TEST_PYTEST32_PYTHON")
    if not python or not Path(python).is_file():
        pytest.skip("A Python 3.9 environment with pytest 3.2.1 is optional")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    session = project(tmp_path, python)
    scan(session, ["pytest_run"])
    run = session.runs[-1]
    assert run.exit_code == 1 and "--rootdir" not in run.argv
    assert run.coverage_complete and run.test_summary["failed"] == 1
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    (tmp_path / "value.py").write_text("VALUE = 2\n")
    scan(session, ["pytest_run"])
    assert session.runs[-1].verified_pass
    assert next(i for i in session.issues if i.issue_id == issue.issue_id).status == "resolved"
