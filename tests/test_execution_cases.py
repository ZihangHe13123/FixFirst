"""The execution-suite generator on its own fixtures: real pytest runs of the owned shopping-cart project."""

import json

from fixfirst import execution_cases


def test_the_suite_completes_when_a_repair_restores_conftest(tmp_path, monkeypatch):
    """Two fault variants are repaired in conftest.py, which FixFirst counts as changed tests.

    The generator used to stop there: it required the goal to be reached right after the repair,
    while the product leaves the issue awaiting verification until the tests are accepted. A
    variant repaired in the source alone must still need no acceptance.
    """
    monkeypatch.setattr(execution_cases, "VARIANTS", ("setup", "teardown", "assertion"))
    manifest = json.loads(execution_cases.build_dataset(tmp_path / "data", projects=1).read_text(encoding="utf-8"))
    assert [case["variant"] for case in manifest["cases"]] == ["setup", "teardown", "assertion"]
    assert all(case["baseline_pass"] and case["restored_pass"] for case in manifest["cases"])
    for case in manifest["cases"]:
        restored = json.loads((tmp_path / "data" / case["path"] / "restored.json").read_text(encoding="utf-8"))
        accepted = [entry for entry in restored["history"] if entry.get("kind") == "baseline_accepted"]
        assert restored["goal_status"] == "achieved"
        assert [issue["status"] for issue in restored["issues"]] == ["resolved"]
        assert restored["baseline_check"]["state"] == "unchanged"
        if case["variant"] == "assertion":
            assert not accepted
        else:
            assert len(accepted) == 1 and accepted[0]["changed"] == ["tests:conftest.py"]
