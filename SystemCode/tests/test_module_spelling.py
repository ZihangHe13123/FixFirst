"""Spelling hints require a failed load from the actual module namespace."""

import math
import sys

from fixfirst._runtime_evidence import exception_metadata, one_edit
from fixfirst.evidence import issue_evidence
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def test_actual_module_attribute_records_a_unique_public_spelling():
    try:
        math.sqtr(4)
    except AttributeError as error:
        evidence = exception_metadata(error, error.__traceback__)["module_attribute"]
    assert evidence["module"] == "math" and evidence["name"] == "sqtr"
    assert evidence["suggestions"] == ["sqrt"] and evidence["unique"]


def test_fabricated_exception_text_does_not_supply_a_module_receiver():
    try:
        raise AttributeError("module 'math' has no attribute 'sqtr'")
    except AttributeError as error:
        assert exception_metadata(error, error.__traceback__)["module_attribute"] == {}


def test_edit_distance_is_bounded_and_does_not_accept_identical_names():
    assert one_edit("arrange", "arange") and one_edit("sqtr", "sqrt")
    assert not one_edit("float", "float64") and not one_edit("get", "get")
    assert not one_edit("msort", "sort") and not one_edit("mat", "ma")
    assert not one_edit("values", "valued")


def test_numpy_typo_is_not_sent_to_a_release_search(tmp_path):
    (tmp_path / "app.py").write_text("import numpy as np\ndef values():\n    return np.arrange(3).tolist()\n")
    (tmp_path / "test_app.py").write_text("from app import values\ndef test_values():\n    assert values() == [0, 1, 2]\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    issue = next(i for i in session.issues if i.tool == "pytest_run")
    detail = issue_evidence(session, issue)
    assert detail["module_attribute"]["suggestions"] == ["arange"]
    first = build_view(session)["steps"][0]
    assert "numpy.arange" in first["title"] and "app.py:3" in first["title"]
    assert not any(a.check == "version_search" for a in session.actions)
    (tmp_path / "app.py").write_text("import numpy as np\ndef values():\n    return np.arange(3).tolist()\n")
    scan(session, ["pytest_run"])
    assert session.goal_status == "achieved"
