"""The arm comparison's counting and tests (experiments/agent_baseline/compare_arms.py), on rows
whose answers are known."""

import json
from pathlib import Path
import re
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
    assert re.search(r"\| m \| scheduled \| [0-9a-f]{8} \| facts \| 1 \| 1/1", printed)
    assert "baseline → facts" in printed and "facts → mcp" in printed
    numbers = json.loads((tmp_path / "out.json").read_text())
    assert [s["arm"] for s in numbers["summary"]] == ["baseline", "facts", "mcp"] and len(numbers["paired"]) == 3


def test_runs_under_different_protocols_are_neither_pooled_nor_paired():
    """Codex's case: a 1-second and a 900-second budget, from different harness versions."""
    short = row("baseline", "c", False, settings={"run_timeout": 1}, harness_commit="a")
    long = row("mcp", "c", True, settings={"run_timeout": 900}, harness_commit="b")
    summary = ca.summarise([short, long])
    assert len({s["protocol"] for s in summary}) == 2 and ca.paired([short, long]) == []
    same = row("mcp", "c", True, settings={"run_timeout": 1}, harness_commit="a")
    [pair] = ca.paired([short, same])
    assert pair["pairs"] == 1
    dirty = {**same, "uncommitted_changes": [" M experiments/agent_baseline/agent_pilot.py"]}
    assert ca.paired([short, dirty]) == []  # a harness with uncommitted changes is another version


def test_the_same_run_read_twice_counts_once_and_conflicting_results_are_refused(tmp_path, capsys):
    rows = [row("baseline", "c", False), row("mcp", "c", True)]
    [baseline, mcp] = ca.summarise(rows + rows)
    assert (baseline["runs"], mcp["runs"], mcp["fixed_ci95"]) == (1, 1, list(ca.wilson(1, 1)))
    assert ca.paired(rows + rows)[0]["pairs"] == 1
    with pytest.raises(ValueError, match="two different results for the same run"):
        ca.summarise(rows + [row("mcp", "c", False)])
    results = tmp_path / "results.jsonl"
    results.write_text("\n".join(json.dumps(r) for r in rows + rows) + "\n")
    ca.main([str(results)])
    assert "2 duplicate rows (the same run read twice) were counted once." in capsys.readouterr().out


def test_tokens_a_server_did_not_report_are_missing_not_zero():
    reported = row("baseline", "c1", True, tokens=100, usage_reported=True)
    unreported = row("baseline", "c2", True, usage_reported=False)
    old_style = {k: v for k, v in row("baseline", "c3", True).items() if k not in ("prompt_tokens", "completion_tokens")}
    [summary] = ca.summarise([reported, unreported, old_style])
    assert (summary["mean_tokens"], summary["tokens_missing"]) == (100, 2)
    [pair] = ca.paired([unreported, row("mcp", "c2", True, tokens=50, usage_reported=True)])
    assert (pair["token_pairs"], pair["median_token_difference"]) == (0, None)
