"""Repair planning regressions from the public development field trial."""

import sys

from fixfirst import cli
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def test_unobserved_old_failure_does_not_generate_current_version_advice(tmp_path, capsys):
    application = tmp_path / "app.py"
    application.write_text("import numpy as np\ndef convert():\n    return np.float(1)\n")
    (tmp_path / "test_app.py").write_text("from app import convert\ndef test_value():\n    assert convert() == 1\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    old = next(i for i in session.issues if i.tool == "pytest_run")
    assert old.diagnosis_rule == "D02"
    assert any("numpy.float" in a.title for a in session.actions)
    # A new collection failure prevents observing the old call failure. It is
    # neither verified fixed nor evidence for giving its old remedy again.
    application.write_text("import fixfirst_new_missing_dependency\n")
    scan(session, ["environment", "project", "pytest_run"])
    old = next(i for i in session.issues if i.issue_id == old.issue_id)
    assert old.status == "not_observed"
    assert not any(old.issue_id in a.issue_ids and a.kind != "rerun" for a in session.actions)
    expected = build_view(session)["steps"][:5]
    cli.show(session)
    output = capsys.readouterr().out.split("Next steps", 1)[1]
    assert "Replace numpy.float" not in output
    positions = [output.index(step["title"]) for step in expected]
    assert positions == sorted(positions)
