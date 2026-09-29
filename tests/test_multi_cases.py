import sys

import pytest

from fixfirst import multi_cases as m

CASES = {case[0]: case for case in m.CASES}


def test_every_order_consistent_with_hiding_is_acceptable():
    assert m.acceptable_orders(CASES["M5"]) == [("renamed_helper", "private_moved", "numpy_alias")]
    assert sorted(m.acceptable_orders(CASES["M2"])) == [
        ("private_moved", "env_missing", "total_off_by_one"),
        ("private_moved", "total_off_by_one", "env_missing"),
    ]
    assert len(m.acceptable_orders(CASES["M4"])) == 2
    # The optional lint finding is never part of a required order.
    assert m.acceptable_orders(CASES["M3"]) == [("stdlib_removed",)]


def test_repairing_a_layer_reveals_exactly_the_next_one(tmp_path):
    assert m.validate(CASES["M5"], tmp_path / "m5") == [["renamed_helper"], ["private_moved"], ["numpy_alias"]]
    assert m.validate(CASES["M2"], tmp_path / "m2") == [["private_moved"], ["env_missing", "total_off_by_one"]]


def test_a_wrong_hiding_relation_is_caught(tmp_path):
    # Claiming that the run-time fault is observable from the start contradicts a real run.
    wrong = ("M1", "flat-shop", [("renamed_helper", ()), ("numpy_alias", ())])
    with pytest.raises(ValueError, match="numpy_alias is not observable"):
        m.validate(wrong, tmp_path / "wrong")


def test_the_fault_behind_an_issue_is_the_one_whose_repair_removes_it():
    # Once the variable has a default, the off-by-one total also breaks test_final_grade with
    # "8 != 6", which the fault's observable text ("4 != 3") does not match.
    title = "Assertion failed · tests/test_grades.py::TestStudent::test_final_grade"
    _, issues = m.open_issues(CASES["M4"], ["env_missing"], sys.executable)
    assert title in {issue.title for issue in issues}
    assert m.targeted(CASES["M4"], title, ["env_missing"], sys.executable) == "total_off_by_one"


def test_a_naive_baseline_is_replayed_to_the_goal():
    result = m.replay(CASES["M3"], m.message_order)
    assert result["steps"][0]["fault"] == "stdlib_removed"
    assert (result["first_issue_right"], result["wrong_issue_attempts"], result["reached_goal"]) == (True, 0, True)


def test_picking_an_issue_behind_no_required_fault_repairs_nothing():
    def lint_first(session, issues):
        return next(i for i in issues if "`json` imported but unused" in i.title)

    result = m.replay(CASES["M3"], lint_first, limit=1)
    assert (result["first_issue_right"], result["wrong_issue_attempts"], result["reached_goal"]) == (False, 1, False)
