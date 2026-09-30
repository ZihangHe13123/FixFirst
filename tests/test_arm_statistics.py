"""The arm comparison's counting and tests (experiments/agent_baseline/compare_arms.py), on rows
whose answers are known."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "agent_baseline"))

import compare_arms as ca  # noqa: E402


def row(arm, case, fixed, run=1, turn=None, tokens=0, grading="graded", **extra):
    return {"model": "m", "call_policy": "scheduled", "attempt": "a", "arm": arm, "case": case, "run": run,
            "grading": grading, "fixed": fixed if grading == "graded" else None, "first_green_turn": turn,
            "prompt_tokens": tokens, "completion_tokens": 0, **extra}


def test_intervals_and_exact_tests_match_hand_computed_values():
    assert ca.wilson(8, 10) == (0.49, 0.943) and ca.wilson(0, 0) == (None, None)
    assert ca.wilson(10, 10)[1] == 1.0 and ca.wilson(0, 10)[0] == 0.0
    assert ca.binomial_two_sided(0, 5) == pytest.approx(0.0625)  # 2 * (1/32)
    assert ca.mcnemar(5, 0) == pytest.approx(0.0625) and ca.mcnemar(3, 3) == 1.0 and ca.mcnemar(0, 0) == 1.0
    assert ca.sign_test([1, 2, -1, 0]) == 1.0  # two up, one down, one tie left out
    assert ca.sign_test([1, 1, 1, 1, 1, 1]) == pytest.approx(0.03125)
    assert ca.median([3, 1, 2]) == 2 and ca.median([4, 1, 2, 3]) == 2.5 and ca.median([None]) is None


def test_arms_are_summarised_and_runs_that_were_not_graded_never_count_as_failures():
    rows = [row("baseline", "c1", True, turn=4, tokens=100), row("baseline", "c2", False, tokens=300),
            row("baseline", "c3", None, grading="not_graded"),
            row("mcp", "c1", True, turn=2, tokens=200, wrong_first_cause=False, fixfirst_reports=2),
            row("mcp", "c2", True, turn=3, tokens=250, wrong_first_cause=True, fixfirst_reports=2,
                tests_changed=["tests/test_a.py"]),
            row("mcp", "c3", True, turn=5, tokens=150, wrong_first_cause=False, fixfirst_reports=2)]
    baseline, mcp = ca.summarise(rows)
    assert (baseline["arm"], baseline["graded"], baseline["not_graded"], baseline["fixed"]) == ("baseline", 2, 1, 1)
    assert baseline["fixed_rate"] == 0.5 and baseline["median_first_green_turn"] == 4 and baseline["mean_tokens"] == 200
    assert (mcp["fixed"], mcp["median_first_green_turn"], mcp["mean_fixfirst_reports"]) == (3, 3, 2)
    assert (mcp["wrong_first_cause"], mcp["first_cause_known"], mcp["changed_tests"]) == (1, 3, 1)
    [pair] = ca.paired(rows)
    # c3 was not graded in the baseline, so only c1 and c2 are pairs; c2 is fixed only with FixFirst.
    assert (pair["first"], pair["second"], pair["pairs"]) == ("baseline", "mcp", 2)
    assert (pair["fixed_only_first"], pair["fixed_only_second"], pair["mcnemar_p"]) == (0, 1, 1.0)
    assert (pair["green_turn_pairs"], pair["median_green_turn_difference"]) == (1, -2)
    assert pair["median_token_difference"] == 25.0  # the median of +100 (c1) and -50 (c2)


def test_the_command_line_prints_tables_and_writes_the_numbers(tmp_path, capsys):
    results = tmp_path / "results.jsonl"
    results.write_text("\n".join(json.dumps(r) for r in [
        row("baseline", "c1", True, turn=3), row("facts", "c1", True, turn=2), row("mcp", "c1", False),
        row("mcp", "c1", True, attempt="other")]) + "\n")
    ca.main([str(results), "--attempt", "a", "--json", str(tmp_path / "out.json")])
    printed = capsys.readouterr().out
    assert "| m | scheduled | facts | 1 | 1/1" in printed and "baseline → facts" in printed and "facts → mcp" in printed
    numbers = json.loads((tmp_path / "out.json").read_text())
    assert [s["arm"] for s in numbers["summary"]] == ["baseline", "facts", "mcp"] and len(numbers["paired"]) == 3
