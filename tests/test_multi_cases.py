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
