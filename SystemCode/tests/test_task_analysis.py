"""The preregistered task-level analysis (experiments/agent_baseline/task_analysis.py), on rows whose
answers are known."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "agent_baseline"))

import task_analysis as ta  # noqa: E402


def row(arm, case, fixed, run=1, attempt="a", grading="graded", kind="real", **extra):
    """One run's row; it records its source identity (a real task's source commit, a generated case's
    harness commit) unless told otherwise."""
    return {"model": "m", "call_policy": "server", "attempt": attempt, "arm": arm, "case": case, "run": run,
            "kind": kind, "grading": grading, "fixed": fixed if grading == "graded" else None,
            **({"commit": "c" * 40} if kind == "real" else {"harness_commit": "h" * 40}), **extra}


def task(arm, case, fixed_runs, runs=3, **extra):
    """`runs` graded runs of one task in one arm, the first `fixed_runs` of them fixed."""
    return [row(arm, case, n <= fixed_runs, run=n, **extra) for n in range(1, runs + 1)]


def test_the_main_comparison_is_the_mean_of_task_differences_with_a_sign_test():
    rows = (task("baseline", "a", 0) + task("mcp", "a", 2) + task("baseline", "b", 1) + task("mcp", "b", 1)
            + task("baseline", "c", 3) + task("mcp", "c", 3) + task("baseline", "d", 2) + task("mcp", "d", 0))
    [group] = ta.analyse(rows, resamples=2000)["groups"]
    [main] = group["comparisons"]
    assert (main["first"], main["second"], main["tasks"]) == ("baseline", "mcp", 4)
    assert group["tasks"]["a"] == {"baseline": [0, 3], "mcp": [2, 3]}
    assert main["per_task"] == {"a": 0.667, "b": 0.0, "c": 0.0, "d": -0.667}
    assert main["mean_difference"] == 0.0 and main["sign"] == {"positive": 1, "negative": 1, "ties": 2, "p": 1.0}
    assert main["ci95"] == [-0.866, 0.866]  # mean 0, sd 0.544, t(3) 3.182, 4 tasks
    assert main["bootstrap_ci95"][0] < 0 < main["bootstrap_ci95"][1]


def test_a_consistent_gain_gives_an_interval_above_zero():
    rows = []
    for case, (before, after) in {"a": (0, 1), "b": (1, 2), "c": (0, 2), "d": (2, 3), "e": (1, 2)}.items():
        rows += task("baseline", case, before) + task("mcp", case, after)
    [main] = ta.analyse(rows, resamples=2000)["groups"][0]["comparisons"]
    assert main["mean_difference"] == 0.4 and main["ci95"] == [0.215, 0.585]  # sd 0.149, t(4) 2.776
    assert main["bootstrap_ci95"][0] >= 0.333
    assert main["sign"] == {"positive": 5, "negative": 0, "ties": 0, "p": 0.0625}  # 5 tasks cannot reach p < 0.05


def test_the_interval_is_reproducible_and_exact_when_tasks_agree():
    values = [0.1, -0.2, 0.4, 0.0, 0.3]
    assert ta.bootstrap_interval(values, 1000, "s") == ta.bootstrap_interval(values, 1000, "s")
    low, high = ta.bootstrap_interval(values, 1000, "s")
    assert min(values) <= low <= sum(values) / len(values) <= high <= max(values)
    assert ta.bootstrap_interval([0.25] * 6, 1000, "s") == ta.t_interval([0.25] * 6) == [0.25, 0.25]
    assert ta.bootstrap_interval([0.25], 1000, "s") == ta.t_interval([0.25]) == [None, None]
    assert (ta.t975(3), ta.t975(30), round(ta.t975(40), 3), round(ta.t975(1000), 2)) == (3.182, 2.042, 2.021, 1.96)


def test_an_episode_the_model_ended_counts_as_not_fixed():
    rows = [row("baseline", "a", False, run=1, end="turn_cap"), row("baseline", "a", True, run=2, end="finish"),
            row("mcp", "a", False, run=1, end="model_error"), row("mcp", "a", False, run=2, end="time_cap")]
    [group] = ta.analyse(rows, resamples=100)["groups"]
    assert group["tasks"]["a"] == {"baseline": [1, 2], "mcp": [0, 2]}


def at(minute):
    """An automatic attempt id, which carries when the attempt started."""
    return f"20261001T10{minute:02d}00Z-abc123"


def attempt_rows(attempts, case="a"):
    return [row("baseline", case, value if grading == "graded" else None, attempt=at(i), grading=grading,
                **({} if grading == "graded" else {"end": value})) for i, (grading, value) in enumerate(attempts)]


@pytest.mark.parametrize("attempts,used,reason", [
    ([("not_graded", "setup_failed"), ("graded", True)], True, None),  # one retry after an allowed failure
    ([("not_graded", "mcp_start_failed"), ("not_graded", "setup_failed")], False, None),  # retried, never graded
    ([("graded", True), ("not_graded", "setup_failed")], False, "attempted again after a graded result"),
    ([("not_graded", "setup_failed")] * 3, False, "3 attempts; one retry is allowed"),
    ([("not_graded", "setup_failed")] * 2 + [("graded", True)], False, "3 attempts; one retry is allowed"),
    ([("not_graded", "reference_invalid"), ("graded", True)], False, "does not let be retried"),
    ([("not_graded", "grading_error"), ("graded", True)], False, "does not let be retried"),
])
def test_a_run_is_retried_once_at_most_in_order_and_only_after_an_allowed_failure(attempts, used, reason):
    result = ta.analyse(attempt_rows(attempts), resamples=100)
    happened = ["graded" if grading == "graded" else value for grading, value in attempts]
    assert bool(result["groups"][0]["tasks"]) == used
    if reason:
        [deviation] = result["deviations"]
        assert reason in deviation["reason"] and deviation["attempts"] == happened and not result["retried"]
    elif used:
        assert [r["attempts"] for r in result["retried"]] == [happened] and not result["deviations"]
    else:
        assert [r["ends"] for r in result["never_graded"]] == [happened] and result["never_graded"][0]["retried"]
    assert result["groups"][0]["ledger"]["baseline"]["rows_read"] == len(attempts)


def test_attempts_in_an_order_that_cannot_be_established_are_a_deviation():
    unordered = [row("baseline", "a", None, attempt="first", grading="not_graded", end="setup_failed"),
                 row("baseline", "a", True, attempt="second")]
    [deviation] = ta.analyse(unordered, resamples=100)["deviations"]
    assert "cannot be established" in deviation["reason"]
    stamped = [{**unordered[0], "started_utc": "2026-10-01T10:00:00Z"},
               {**unordered[1], "started_utc": "2026-10-01T11:00:00Z"}]
    result = ta.analyse(stamped, resamples=100)
    assert [r["attempts"] for r in result["retried"]] == [["setup_failed", "graded"]] and not result["deviations"]


def test_a_real_task_from_two_source_versions_or_none_is_left_out_and_listed():
    mixed = [row(arm, "a", run == 2, run=run, commit=commit) for arm in ("baseline", "mcp")
             for run, commit in ((1, "a" * 40), (2, "b" * 40))]
    same = task("baseline", "b", 1) + task("mcp", "b", 2)
    result = ta.analyse(mixed + same, resamples=100)
    [group] = result["groups"]
    assert sorted(group["tasks"]) == ["b"] and group["comparisons"][0]["tasks"] == 1
    [deviation] = result["deviations"]
    assert "2 source commits" in deviation["reason"] and deviation["runs_left_out"] == 4
    assert group["ledger"]["baseline"]["runs_left_out"] == 2
    unrecorded = [{k: v for k, v in r.items() if k != "commit"} for r in task("baseline", "c", 1) + task("mcp", "c", 2)]
    [deviation] = ta.analyse(unrecorded, resamples=100)["deviations"]
    assert "no source commit" in deviation["reason"]
    generated = task("baseline", "s", 1, kind="generated") + task("mcp", "s", 2, kind="generated")
    assert ta.analyse(generated, resamples=100)["deviations"] == []  # bound by the harness commit instead


def test_a_task_without_a_graded_run_in_an_arm_is_left_out_of_that_comparison_only():
    rows = (task("baseline", "a", 1) + task("facts", "a", 2) + task("mcp", "a", 3)
            + task("baseline", "b", 0) + task("facts", "b", 1)
            + [row("mcp", "b", None, grading="not_graded", end="setup_failed")])
    [group] = ta.analyse(rows, resamples=100)["groups"]
    by_pair = {(c["first"], c["second"]): c for c in group["comparisons"]}
    assert list(by_pair) == [("baseline", "mcp"), ("facts", "mcp"), ("baseline", "facts")]
    assert (by_pair["baseline", "mcp"]["tasks"], by_pair["baseline", "mcp"]["left_out"]) == (1, ["b"])
    assert by_pair["facts", "mcp"]["left_out"] == ["b"]
    assert (by_pair["baseline", "facts"]["tasks"], by_pair["baseline", "facts"]["left_out"]) == (2, [])


def test_protocols_and_kinds_of_case_are_never_pooled():
    rows = (task("baseline", "a", 1) + task("mcp", "a", 2)
            + task("baseline", "a", 1, attempt="b", harness_commit="other") + task("mcp", "a", 3, attempt="b",
                                                                                 harness_commit="other")
            + task("baseline", "s1", 0, kind="generated") + task("mcp", "s1", 3, kind="generated"))
    groups = ta.analyse(rows, resamples=100)["groups"]
    assert sorted(g["kind"] for g in groups) == ["generated", "real", "real"]
    assert len({g["protocol"] for g in groups if g["kind"] == "real"}) == 2
    assert all(g["comparisons"][0]["tasks"] == 1 for g in groups)


@pytest.mark.parametrize("change", [{"kind": "generated"}, {"harness_commit": "another-protocol"}])
def test_the_same_run_number_in_another_kind_or_protocol_is_another_run_not_a_conflict(change):
    """Codex's probe: one rule of identity for deduplication, pooling and pairing."""
    groups = ta.analyse([row("baseline", "a", True), row("baseline", "a", False, **change)], resamples=100)["groups"]
    assert len(groups) == 2
    real, generated = row("baseline", "a", False), row("mcp", "a", True, kind="generated")
    assert not any(pair["pairs"] for pair in ta.ca.paired([real, generated]))  # the auxiliary comparison too


def test_agreement_among_tasks_is_flagged_degenerate_with_no_interval():
    rows = []
    for case in "abcdef":
        rows += task("baseline", case, 0) + task("mcp", case, 1)
    result = ta.analyse(rows, resamples=200)
    main = result["groups"][0]["comparisons"][0]
    assert (main["mean_difference"], main["degenerate"], main["ci95"], main["bootstrap_ci95"]) == (
        0.333, True, [None, None], [None, None])
    assert "degenerate" in ta.markdown(result)


def test_a_comparison_whose_arm_was_run_but_never_graded_is_shown_with_no_tasks():
    rows = task("baseline", "a", 1) + [row("mcp", "a", None, grading="not_graded", end="setup_failed")]
    result = ta.analyse(rows, resamples=100)
    [group] = result["groups"]
    assert group["comparisons"] == [{"first": "baseline", "second": "mcp", "tasks": 0, "no_graded_runs_in": ["mcp"]}]
    assert group["ledger"] == {
        "baseline": {"rows_read": 3, "rows_kept": 3, "runs_used": 3, "runs_never_graded": 0, "runs_retried_once": 0,
                     "runs_left_out": 0},
        "mcp": {"rows_read": 1, "rows_kept": 1, "runs_used": 0, "runs_never_graded": 1, "runs_retried_once": 0,
                "runs_left_out": 0}}
    assert "no graded runs in: mcp" in ta.markdown(result)


@pytest.mark.parametrize("resamples", [0, -1, True, 2.5])
def test_a_bad_resample_count_is_refused(resamples, tmp_path):
    with pytest.raises(ValueError, match="resamples"):
        ta.analyse(task("baseline", "a", 1) + task("mcp", "a", 2), resamples=resamples)
    results = tmp_path / "results.jsonl"
    results.write_text("".join(json.dumps(r) + "\n" for r in task("baseline", "a", 1)))
    if isinstance(resamples, int) and not isinstance(resamples, bool):
        with pytest.raises(SystemExit) as stopped:
            ta.main([str(results), "--resamples", str(resamples)])
        assert stopped.value.code == 2


@pytest.mark.parametrize("change", [{"tasks": 1}, {"runs_per_arm": 0}, {"replicates": 0}, {"correlation": 1.5},
                                    {"effects": (2.0,)}, {"baseline": "normal:0:1"}, {"effect_model": "other"}])
def test_bad_simulation_settings_are_refused(change):
    with pytest.raises(ValueError):
        ta.simulate(**{"tasks": 4, "runs_per_arm": 2, "replicates": 2, "resamples": 10, "effects": (0.0,), **change})


def test_fault_type_strata_come_from_the_labels():
    rows = (task("baseline", "a", 0) + task("mcp", "a", 3) + task("baseline", "b", 1) + task("mcp", "b", 1)
            + task("baseline", "c", 2) + task("mcp", "c", 1))
    labels = {"a": "dependency_environment", "b": "code", "real:b": "other", "generated:c": "ignored here"}
    [group] = ta.analyse(rows, labels=labels, resamples=100)["groups"]
    strata = group["comparisons"][0]["by_label"]
    assert sorted(strata) == ["dependency_environment", "other", "unlabelled"]  # "kind:case" comes first
    assert (strata["dependency_environment"]["tasks"], strata["dependency_environment"]["mean_difference"]) == (1, 1.0)
    assert strata["unlabelled"]["per_task"] == {"c": -0.333}


def test_the_command_line_writes_the_numbers_and_refuses_two_results_for_one_run(tmp_path, capsys):
    results = tmp_path / "results.jsonl"
    results.write_text("".join(json.dumps(r) + "\n" for r in task("baseline", "a", 1) + task("mcp", "a", 2)))
    ta.main([str(results), "--json", str(tmp_path / "out.json"), "--resamples", "200"])
    assert "mcp − baseline" in capsys.readouterr().out
    assert json.loads((tmp_path / "out.json").read_text())["groups"][0]["comparisons"][0]["tasks"] == 1
    clash = tmp_path / "clash.jsonl"
    clash.write_text(json.dumps(row("baseline", "a", True)) + "\n" + json.dumps(row("baseline", "a", False)) + "\n")
    with pytest.raises(SystemExit) as stopped:
        ta.main([str(clash)])
    assert stopped.value.code == 2
    written = json.loads((tmp_path / "out.json").read_text())["provenance"]
    assert written["inputs"] == [{"name": "results.jsonl", "sha256": ta.file_sha256(results), "rows": 6}]
    assert set(written["code"]) == {"task_analysis.py", "compare_arms.py", "commit", "commit_status"}


def test_the_simulation_is_reproducible_and_finds_a_large_effect_more_often_than_none():
    small = dict(tasks=8, runs_per_arm=3, replicates=60, effects=(0.0, 0.5), resamples=200, seed=7)
    first = ta.simulate(**small)
    assert first == ta.simulate(**small)
    none, large = first
    assert none["true_mean_difference"] == 0.0
    for key in ("t_interval_excludes_zero", "bootstrap_excludes_zero", "sign_test_p_below_0_05"):
        assert large[key] > none[key]


def test_the_simulation_assumptions_are_options_with_known_answers():
    import random
    rng = random.Random(1)
    assert ta.treated(0.9, 0.3, "shift", rng) == 1.0 and ta.treated(0.4, 0.5, "share", rng) == 0.7
    assert {ta.treated(0.5, 0.2, "half", rng) for _ in range(50)} == {0.5, 0.9}
    assert len(set(ta.outcomes(rng, 0.5, 5, correlation=1.0))) == 1  # all runs repeat one draw
    assert 0 <= ta.baseline_sampler("beta:0.5:0.5")(rng) <= 1
    with pytest.raises(ValueError):
        ta.baseline_sampler("normal:0:1")
    share = dict(tasks=6, runs_per_arm=3, replicates=20, resamples=100, seed=3)
    [half_failures] = ta.simulate(effects=(0.5,), baseline="uniform:0:1", effect_model="share", **share)
    assert abs(half_failures["true_mean_difference"] - 0.25) <= 0.005  # 0.5 x E[1 - p]
    [halved] = ta.simulate(effects=(0.1,), effect_model="half", correlation=0.7, **share)
    assert abs(halved["true_mean_difference"] - 0.097) <= 0.005  # half of the +0.2 shift's 0.194


def timed(arm, case, run, turn, seconds):
    """A graded run fixed at `turn` after `seconds`, or not fixed when turn is None (budget 20 turns, 900 s)."""
    return row(arm, case, turn is not None, run=run, first_green_turn=turn, first_green_s=seconds,
               turns=20, agent_s=1000.0, settings={"max_turns": 20, "run_timeout": 900})


def test_turns_and_time_to_the_first_fix_are_compared_task_by_task():
    rows = [timed("baseline", "a", 1, 4, 10), timed("baseline", "a", 2, 6, 40),  # mean 5 turns, 20 s geometric
            timed("mcp", "a", 1, 3, 4), timed("mcp", "a", 2, 3, 25),  # 3 turns, 10 s geometric (14.5 s arithmetic)
            timed("baseline", "b", 1, 2, 8), timed("mcp", "b", 1, 3, 16),
            timed("baseline", "c", 1, 5, 30), timed("mcp", "c", 1, None, None),  # mcp never fixed c
            {**timed("baseline", "d", 1, 2, 5), "first_green_turn": None}, timed("mcp", "d", 1, 2, 5)]  # no turn
    result = ta.analyse(rows, resamples=100)
    s = result["groups"][0]["comparisons"][0]["speed"]
    turns, time = s["turns_to_first_fix"], s["time_to_first_fix"]
    assert (s["tasks_in_group"], s["tasks_graded_in_both"]) == (4, 4)
    assert (turns["tasks"], turns["mean_difference"], turns["per_task"], turns["left_out"]) == (
        2, -0.5, {"a": -2.0, "b": 1.0}, ["c", "d"])
    assert turns["ci95"] == [-19.559, 18.559]  # sd 2.121, t(1) 12.706, 2 tasks
    assert (time["ratio"], time["per_task"], time["sign"], time["runs"], time["runs_usable"]) == (  # d keeps its time
        1.0, {"a": 0.5, "b": 2.0, "d": 1.0}, {"positive": 1, "negative": 1, "ties": 1, "p": 1.0},
        {"baseline": 4, "mcp": 4}, {"baseline": 5, "mcp": 4})  # c's baseline time is usable, not contributing
    penalized_turns, penalized_time = s["turns_with_failure_penalty"], s["time_with_failure_penalty"]
    assert (penalized_turns["tasks"], penalized_turns["mean_difference"], penalized_turns["per_task"]["c"],
            penalized_turns["left_out"]) == (3, 5.0, 16.0, ["d"])  # c counts as 21 turns for mcp
    assert (penalized_time["per_task"]["c"], penalized_time["ratio"]) == (30.0, 2.34)  # (0.5 x 2 x 30 x 1) ** (1/4)
    [missing_turn, missing_penalty] = result["speed_values_missing"]
    assert (missing_turn["case"], missing_turn["measure"], missing_penalty["measure"]) == (
        "d", "turns", "turns_penalized")
    text = ta.markdown(result)
    assert "Budget-penalized" in text and "never replaces the fix rate" in text and "first_green_s" in text


@pytest.mark.parametrize("change,measure,reason", [
    ({"first_green_s": float("nan")}, "seconds", "not a finite time above 0"),
    ({"first_green_s": 0}, "seconds", "not a finite time above 0"),
    ({"first_green_s": -3.0}, "seconds", "not a finite time above 0"),
    ({"first_green_s": 80.0, "agent_s": 50.0}, "seconds", "after the episode's end"),
    ({"first_green_turn": 0}, "turns", "not a whole number of at least 1"),
    ({"first_green_turn": 2.5}, "turns", "not a whole number"),
    ({"first_green_turn": 9, "turns": 5}, "turns", "after the episode's last turn"),
])
def test_a_speed_value_that_fails_a_check_is_missing_for_that_measure_only(change, measure, reason):
    rows = [timed("baseline", "a", 1, 3, 30), {**timed("mcp", "a", 1, 2, 10), **change}]
    result = ta.analyse(rows, resamples=100)
    [missing] = [m for m in result["speed_values_missing"] if m["measure"] == measure]
    assert reason in missing["reason"] and missing["arm"] == "mcp"
    s = result["groups"][0]["comparisons"][0]["speed"]
    affected, other = (("time_to_first_fix", "turns_to_first_fix") if measure == "seconds"
                       else ("turns_to_first_fix", "time_to_first_fix"))
    assert s[affected]["tasks"] == 0 and s[other]["tasks"] == 1  # nothing clipped, the other measure kept


def test_the_budget_penalized_score_does_not_always_favour_the_arm_that_fixes_more():
    rows = ([timed("baseline", "a", n, 1, 1.0) for n in (1, 2, 3)]
            + [timed("baseline", "a", n, None, None) for n in (4, 5)]
            + [timed("mcp", "a", n, 1, 100.0) for n in (1, 2, 3)])
    s = ta.analyse(rows, resamples=100)["groups"][0]["comparisons"][0]["speed"]
    assert s["time_with_failure_penalty"]["ratio"] == 6.581  # 100 / 900 ** (2/5) = 6.5812: mcp fixed all, yet scores worse


def test_a_degenerate_replicate_neither_detects_nor_covers_in_the_simulation():
    [none] = ta.simulate(tasks=3, runs_per_arm=1, replicates=5, effects=(0.0,), baseline="uniform:0:0",
                         resamples=20, seed=1)
    assert (none["no_interval"], none["t_interval_excludes_zero"], none["t_interval_covers_truth"]) == (1.0, 0.0, 0.0)


# ---- Codex's review of 7914699 (r4) and of the simulation evidence (r5) ----------------------------------

def test_a_source_change_across_a_retry_leaves_the_task_out():
    rows = [row("baseline", "a", None, attempt=at(0), grading="not_graded", end="setup_failed", commit="a" * 40),
            row("baseline", "a", True, attempt=at(1), commit="b" * 40), row("mcp", "a", True, commit="b" * 40)]
    result = ta.analyse(rows, resamples=100)
    [deviation] = result["deviations"]
    assert "2 source commits" in deviation["reason"] and result["groups"][0]["tasks"] == {}
    unrecorded = [{**rows[0], "commit": None}, *rows[1:]]  # failed before it read its source: confirms nothing
    assert ta.analyse(unrecorded, resamples=100)["deviations"] == []


@pytest.mark.parametrize("kind,change", [("real", {"commit": ""}), ("real", {"commit": "  "}), ("real", {"commit": None}),
                                         ("generated", {"harness_commit": None}), ("generated", {"harness_commit": ""})])
def test_a_run_without_a_source_identity_is_left_out(kind, change):
    # a generated case's harness commit is also part of its protocol, so both arms change together
    rows = [row("baseline", "a", True, kind=kind, **change),
            row("mcp", "a", True, kind=kind, **(change if kind == "generated" else {}))]
    result = ta.analyse(rows, resamples=100)
    assert "recorded no" in result["deviations"][0]["reason"] and result["groups"][0]["tasks"] == {}


def test_a_retry_that_was_still_not_graded_counts_as_retried_in_the_ledger():
    rows = [row("baseline", "a", None, attempt=at(0), grading="not_graded", end="setup_failed"),
            row("baseline", "a", None, attempt=at(1), grading="not_graded", end="harness_error"), row("mcp", "a", True)]
    ledger = ta.analyse(rows, resamples=100)["groups"][0]["ledger"]["baseline"]
    assert (ledger["runs_never_graded"], ledger["runs_retried_once"], ledger["rows_read"]) == (1, 1, 2)


def test_a_bare_label_shared_by_two_kinds_is_listed_and_not_applied():
    rows = [row(arm, "a", True, kind=kind) for kind in ("real", "generated") for arm in ("baseline", "mcp")]
    result = ta.analyse(rows, labels={"a": "code"}, resamples=100)
    assert "several kinds" in result["label_problems"][0]
    assert all(set(g["comparisons"][0]["by_label"]) == {"unlabelled"} for g in result["groups"])
    qualified = ta.analyse(rows, labels={"real:a": "code", "generated:a": "environment"}, resamples=100)
    assert {next(iter(g["comparisons"][0]["by_label"])) for g in qualified["groups"]} == {"code", "environment"}


def test_a_bare_label_is_judged_by_the_case_name_even_when_it_has_a_colon():
    """Codex R6-2: generated cases are named template:scenario, so a colon does not make a key qualified."""
    name = "pkg-inventory:lm_renamed"
    rows = [row(arm, name, True, kind=kind) for kind in ("real", "generated") for arm in ("baseline", "mcp")]
    result = ta.analyse(rows, labels={name: "code"}, resamples=100)
    assert name in result["label_problems"][0] and "several kinds" in result["label_problems"][0]
    assert all(set(g["comparisons"][0]["by_label"]) == {"unlabelled"} for g in result["groups"])
    qualified = ta.analyse(rows, labels={f"real:{name}": "code", f"generated:{name}": "environment"}, resamples=100)
    assert qualified["label_problems"] == []
    assert {next(iter(g["comparisons"][0]["by_label"])) for g in qualified["groups"]} == {"code", "environment"}
    alone = [row(arm, name, True, kind="generated") for arm in ("baseline", "mcp")]  # one kind only: bare is fine
    result = ta.analyse(alone, labels={name: "code"}, resamples=100)
    assert result["label_problems"] == [] and set(result["groups"][0]["comparisons"][0]["by_label"]) == {"code"}


def test_differences_equal_up_to_rounding_are_degenerate():
    rows = []
    for i in range(6):  # 0/3 -> 1/3, 1/3 -> 2/3, 2/3 -> 3/3: every task gains exactly 1/3
        rows += task("baseline", str(i), i % 3) + task("mcp", str(i), i % 3 + 1)
    main = ta.analyse(rows, resamples=100)["groups"][0]["comparisons"][0]
    assert len(set(main["per_task"].values())) == 1 and main["degenerate"] and main["ci95"] == [None, None]
    rows = []
    for i, seconds in enumerate([1.0, 10.0, 100.0]):  # mcp takes twice as long everywhere
        rows += [timed("baseline", str(i), 1, 2, seconds), timed("mcp", str(i), 1, 2, seconds * 2)]
    time = ta.analyse(rows, resamples=100)["groups"][0]["comparisons"][0]["speed"]["time_to_first_fix"]
    assert (time["ratio"], time["degenerate"], time["ci95"]) == (2.0, True, [None, None])


@pytest.mark.parametrize("change,measure", [
    ({"first_green_s": 5000, "agent_s": None}, "seconds"), ({"first_green_s": 5000, "agent_s": float("nan")}, "seconds"),
    ({"first_green_s": 5000, "agent_s": 0}, "seconds"), ({"first_green_turn": 999, "turns": None}, "turns"),
    ({"first_green_turn": 999, "turns": 1.5}, "turns"),
])
def test_a_speed_value_without_a_valid_episode_end_cannot_be_checked(change, measure):
    values, missing = ta.run_speed({**timed("mcp", "a", 1, 2, 10.0), **change})
    assert measure not in values and "cannot be checked" in missing[measure]


@pytest.mark.parametrize("spec", ["uniform:1.1:1.1", "uniform:nan:nan", "uniform:-0.1:0.5", "uniform:0.8:0.2",
                                  "beta:0:1", "beta:inf:1", "uniform:0.1"])
def test_a_baseline_outside_the_probability_domain_is_refused(spec):
    with pytest.raises(ValueError):
        ta.baseline_sampler(spec)


def test_the_effect_models_never_give_a_probability_outside_0_1():
    import random
    with pytest.raises(ValueError):
        ta.treated(0.2, -0.5, "share", random.Random(1))  # 0.2 - 0.5 x 0.8 < 0
    with pytest.raises(ValueError, match="share"):
        ta.simulate(tasks=4, runs_per_arm=2, replicates=2, resamples=10, effects=(-0.5,), effect_model="share")


def test_the_simulation_keeps_integer_counts_and_coverage_given_an_interval():
    [none] = ta.simulate(tasks=4, runs_per_arm=1, replicates=200, effects=(0.0,), resamples=50, seed=3)
    counts = none["counts"]
    assert counts["replicates"] == 200
    assert counts["t_excludes"] + counts["t_covers"] + counts["no_interval"] == 200  # at a true gain of 0
    assert none["t_interval_covers_truth_given_interval"] == round(counts["t_covers"] / (200 - counts["no_interval"]), 3)


def test_a_commit_is_recorded_only_for_the_committed_files(tmp_path):
    import shutil
    import subprocess
    source = Path(ta.__file__).resolve().parent
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("copied/\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "outer"], check=True)
    for folder in ("copied", "tracked"):
        (tmp_path / folder).mkdir()
        for name in ("task_analysis.py", "compare_arms.py"):
            shutil.copy(source / name, tmp_path / folder / name)
    assert ta.code_commit(tmp_path / "copied")["commit"] is None  # an ignored copy is not the outer commit
    subprocess.run([*git, "add", "tracked"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "tracked"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert ta.code_commit(tmp_path / "tracked")["commit"] == head
    (tmp_path / "tracked" / "compare_arms.py").write_text("# changed\n")
    assert "differs" in ta.code_commit(tmp_path / "tracked")["commit_status"]


# The confirmatory family: paired t-test p-values and Holm's procedure.

GAIN = {"a": (0, 1), "b": (1, 2), "c": (0, 2), "d": (2, 3), "e": (1, 2)}  # differences 1/3, 1/3, 2/3, 1/3, 1/3: t = 6
NONE = {"a": (0, 2), "b": (1, 1), "c": (3, 3), "d": (2, 0)}  # differences 2/3, 0, 0, -2/3: mean 0
SOME = {"a": (0, 1), "b": (1, 1), "c": (0, 1), "d": (0, 2)}  # differences 1/3, 0, 1/3, 2/3: t = sqrt(6)
P_GAIN = 1 - (3 / 10 ** 0.5) * 1.05  # 4 degrees of freedom, t = 6: 0.0038825...
P_SOME = 1 - (2 / 3.141592653589793) * (0.9553166181245093 + 2 ** 0.5 / 3)  # 3 degrees of freedom, t = sqrt(6): 0.0917...


def model_rows(model, tasks, **extra):
    return [r for case, (before, after) in tasks.items()
            for r in task("baseline", case, before, model=model, **extra) + task("mcp", case, after, model=model, **extra)]


def family(*members):
    return {"members": [{"model": model, "protocol": protocol, "tasks": list(tasks)} for model, protocol, tasks in members]}


PROTOCOL = ta.ca.protocol(row("baseline", "a", True))


def test_the_paired_t_test_p_value_has_its_closed_form_values():
    import math
    assert ta.t_test_p([1.0, 3.0]) == pytest.approx(1 - 2 / math.pi * math.atan(2.0), abs=1e-12)  # 1 df, t = 2
    assert ta.t_test_p([0.0, 1.0, 2.0]) == pytest.approx(1 - math.sqrt(3 / 5), abs=1e-12)  # 2 df, t = sqrt(3)
    assert ta.t_test_p([1 / 3, 1 / 3, 2 / 3, 1 / 3, 1 / 3]) == pytest.approx(P_GAIN, abs=1e-12)
    assert ta.t_test_p([1 / 3, 0.0, 1 / 3, 2 / 3]) == pytest.approx(P_SOME, abs=1e-12)
    assert ta.t_test_p([0.0, -1.0, -2.0]) == pytest.approx(ta.t_test_p([0.0, 1.0, 2.0]), abs=1e-15)  # two-sided
    assert ta.t_test_p([-1.0, 1.0]) == 1.0  # a mean of exactly 0
    # no test where there is no interval: one task, or every task the same within the rounding of a float
    assert ta.t_test_p([0.25]) is None and ta.t_test_p([2 / 3 - 1 / 3, 1 / 3 - 0, 1 - 2 / 3]) is None


def test_the_p_value_matches_scipy_where_scipy_is_installed():
    stats = pytest.importorskip("scipy.stats")
    import random
    rng = random.Random(4)
    for _ in range(300):
        values = [rng.choice([-1, -2 / 3, -1 / 3, 0, 1 / 3, 2 / 3, 1]) for _ in range(rng.randint(2, 14))]
        if max(values) - min(values) > 1e-9:
            assert ta.t_test_p(values) == pytest.approx(stats.ttest_1samp(values, 0.0).pvalue, abs=1e-12)


def test_the_p_value_and_the_interval_decide_alike_outside_the_tables_rounding():
    import math
    import statistics
    for df in range(1, 61):  # at the tabulated 97.5% point the exact p-value is 0.05 within the table's rounding
        assert abs(ta.incomplete_beta(df / 2, 0.5, df / (df + ta.t975(df) ** 2)) - 0.05) < 6e-5
    for n in range(2, 14):
        spread = [i - (n - 1) / 2 for i in range(n)]  # mean 0
        for factor, excludes in ((1.01, True), (0.99, False)):
            mean = factor * ta.t975(n - 1) * statistics.stdev(spread) / math.sqrt(n)  # t = factor x the tabulated point
            values = [value + mean for value in spread]
            low, high = ta.t_bounds(values)
            assert (low > 0 or high < 0) is excludes and (ta.t_test_p(values) < 0.05) is excludes


def test_holm_ranks_from_the_smallest_and_stops_at_the_first_that_fails():
    decisions = ta.holm([0.01, 0.04, 0.03])
    assert [d["rank"] for d in decisions] == [1, 3, 2]
    assert [round(d["p_holm"], 12) for d in decisions] == [0.03, 0.06, 0.06]  # 3 x 0.01; 2 x 0.03; not below it
    assert [d["rejected"] for d in decisions] == [True, False, False]
    assert [d["rejected"] for d in ta.holm([0.01, 0.02, 0.03])] == [True, True, True]  # 0.03, 0.04, 0.04
    # 3 x 0.02 fails at the first rank, so the second is not rejected although 2 x 0.02 alone would pass
    stopped = ta.holm([0.02, 0.9, 0.02])
    assert [d["rejected"] for d in stopped] == [False, False, False]
    assert [round(d["p_holm"], 12) for d in stopped] == [0.06, 0.9, 0.06]
    assert ta.holm([0.05]) == [{"rank": 1, "p_holm": 0.05, "rejected": True}]  # no more than alpha
    assert ta.holm([]) == []


def test_a_member_without_a_p_value_stays_in_the_family_and_is_not_rejected():
    kept = ta.holm([0.02, None, 0.04])
    assert [d["rejected"] for d in kept] == [False, False, False] and round(kept[0]["p_holm"], 12) == 0.06  # k is 3
    assert kept[1] == {"rank": 3, "p_holm": 1.0, "rejected": False}
    assert [d["rejected"] for d in ta.holm([0.02, 0.04])] == [True, True]  # what dropping it would have given


@pytest.mark.parametrize("bad", [1.2, -0.1, float("nan"), True, "0.01"])
def test_holm_refuses_what_is_not_a_p_value(bad):
    with pytest.raises(ValueError, match="p-value"):
        ta.holm([0.01, bad])


@pytest.mark.parametrize("alpha", [0, 1, 1.5, -0.05, True, "0.05"])
def test_holm_needs_an_alpha_between_0_and_1(alpha):
    with pytest.raises(ValueError, match="alpha"):  # at 1 a member that could not be estimated would be rejected
        ta.holm([0.01, None], alpha)


def test_the_family_is_decided_by_holm_on_the_registered_models():
    rows = model_rows("m1", GAIN) + model_rows("m2", NONE) + model_rows("m3", SOME)
    members = family(("m1", PROTOCOL, GAIN), ("m2", PROTOCOL, NONE), ("m3", PROTOCOL, SOME))
    result = ta.analyse(rows, resamples=100, family=members)
    family_result = result["confirmatory"]
    assert (family_result["k"], family_result["alpha"], family_result["rejected"]) == (3, 0.05, 1)
    assert family_result["comparison"] == {"first": "baseline", "second": "mcp"} and family_result["kind"] == "real"
    m1, m2, m3 = family_result["members"]
    assert m1["p"] == pytest.approx(P_GAIN, abs=1e-12) and m2["p"] == 1.0 and m3["p"] == pytest.approx(P_SOME, abs=1e-12)
    assert (m1["rank"], m3["rank"], m2["rank"]) == (1, 2, 3)
    assert m1["p_holm"] == pytest.approx(3 * P_GAIN, abs=1e-12) and m1["rejected"] is True
    assert m3["p_holm"] == pytest.approx(2 * P_SOME, abs=1e-12) and m3["rejected"] is False
    assert m2["p_holm"] == 1.0 and m2["rejected"] is False
    # the interval is the usual one of the group's main comparison, not adjusted
    main = next(g for g in result["groups"] if g["model"] == "m1")["comparisons"][0]
    assert (m1["mean_difference"], m1["ci95"], m1["interval_excludes_zero"]) == (main["mean_difference"], main["ci95"], True)
    assert m1["ci95"] == [0.215, 0.585] and m3["interval_excludes_zero"] is False
    assert (m1["tasks_used"], m1["tasks_registered"], m1["tasks_missing"], m1["tasks_not_registered"]) == (list(GAIN), 5, [], [])
    text = ta.markdown(result)
    assert text.startswith("Confirmatory family, as registered before the run: mcp − baseline on real projects")
    assert "are not adjusted" in text and "adjusted interval" not in text
    assert "| m1 | " + PROTOCOL + " | 5 / 5 | 0.4 (0.215 to 0.585) | 0.00388254 | 1 | 0.0116476 | rejects no effect |" in text
    assert "| 3 | 1 | does not reject no effect |" in text
    assert "confirmatory" not in ta.analyse(rows, resamples=100) and "Confirmatory" not in ta.markdown(ta.analyse(rows, resamples=100))


def test_a_member_that_cannot_be_estimated_is_kept_and_counts_as_not_rejected():
    same = {case: (0, 1) for case in "abcd"}  # every task +1/3: no interval, so no test
    rows = model_rows("m1", GAIN) + model_rows("m3", same) + model_rows("m4", {"a": (0, 3)})
    members = family(("m1", PROTOCOL, GAIN), ("m2", PROTOCOL, NONE), ("m3", PROTOCOL, same), ("m4", PROTOCOL, ["a", "b"]))
    m1, m2, m3, m4 = ta.analyse(rows, resamples=100, family=members)["confirmatory"]["members"]
    assert m1["p_holm"] == pytest.approx(4 * P_GAIN, abs=1e-12) and m1["rejected"] is True  # k stays 4
    assert (m2["p"], m2["not_estimable"], m2["rejected"]) == (None, "no graded runs of this model under this protocol", False)
    assert (m3["p"], m3["ci95"], m3["mean_difference"]) == (None, [None, None], 0.333)
    assert m3["not_estimable"] == "every task differs by the same amount, so there is no test" and m3["rejected"] is False
    assert m4["not_estimable"] == "fewer than two registered tasks were graded in both arms"
    assert m4["tasks_missing"] == [{"case": "b", "reason": "no graded run in baseline or mcp"}]
    assert [m["p_holm"] for m in (m2, m3, m4)] == [1.0, 1.0, 1.0]
    text = ta.markdown(ta.analyse(rows, resamples=100, family=members))
    assert "not estimable (no graded runs of this model under this protocol); counts as not rejected" in text


def test_the_family_uses_the_registered_tasks_only_and_lists_the_rest():
    rows = model_rows("m1", GAIN) + model_rows("m1", {"x": (3, 0)}) + task("baseline", "y", 1, model="m1")
    members = family(("m1", PROTOCOL, [*GAIN, "y", "z"]))
    result = ta.analyse(rows, resamples=100, family=members)
    [m1] = result["confirmatory"]["members"]
    assert (m1["mean_difference"], m1["tasks_used"], m1["tasks_registered"]) == (0.4, list(GAIN), 7)
    assert m1["tasks_missing"] == [{"case": "y", "reason": "no graded run in mcp"},
                                   {"case": "z", "reason": "no graded run in baseline or mcp"}]
    assert m1["tasks_not_registered"] == ["x"] and m1["p"] == pytest.approx(P_GAIN, abs=1e-12)
    main = result["groups"][0]["comparisons"][0]
    assert main["tasks"] == 6 and main["mean_difference"] == 0.167  # the exploratory table still has x
    text = ta.markdown(result)
    assert ("Registered tasks of m1 not used: y (no graded run in mcp); z (no graded run in baseline or mcp). Its estimate "
            "and p-value are over the tasks used, not over its whole registered set.") in text
    assert "Tasks of m1 in the data but not registered (not used in the family): x" in text


def test_groups_outside_the_registered_family_are_listed_as_exploratory():
    rows = (model_rows("m1", GAIN) + model_rows("other", SOME) + model_rows("m1", GAIN, kind="generated")
            + model_rows("m2", NONE, settings={"max_turns": 5}))
    members = family(("m1", PROTOCOL, GAIN), ("m2", PROTOCOL, NONE))  # m2 was run under another protocol
    result = ta.analyse(rows, resamples=100, family=members)["confirmatory"]
    m2 = result["members"][1]
    assert (m2["p"], m2["not_estimable"]) == (None, "no graded runs of this model under this protocol")
    other_protocol = ta.ca.protocol(row("baseline", "a", True, settings={"max_turns": 5}))
    assert result["outside_the_family"] == [{"model": "m2", "protocol": other_protocol}, {"model": "other", "protocol": PROTOCOL}]


def test_generated_cases_under_the_same_protocol_are_no_part_of_the_family():
    harness = {"harness_commit": "h" * 40}  # real projects and generated cases of one run share the protocol id
    hard = {"g1": (0, 2), "g2": (1, 1), "g3": (3, 3), "g4": (2, 0)}
    rows = model_rows("m1", GAIN, **harness) + model_rows("m1", hard, kind="generated")
    shared = ta.ca.protocol(row("baseline", "a", True, **harness))
    assert {ta.ca.protocol(r) for r in rows} == {shared} and {r["kind"] for r in rows} == {"real", "generated"}
    result = ta.analyse(rows, resamples=100, family=family(("m1", shared, [*GAIN, *hard])))["confirmatory"]
    [m1] = result["members"]
    assert m1["tasks_used"] == list(GAIN) and m1["p"] == pytest.approx(P_GAIN, abs=1e-12)  # the real projects only
    assert [t["case"] for t in m1["tasks_missing"]] == list(hard) and result["outside_the_family"] == []


@pytest.mark.parametrize("spec", [
    [], {}, {"members": []}, {"members": "m1"}, {"members": [{"model": "m1", "protocol": "p", "tasks": ["a"]}], "alpha": 0.1},
    {"members": [{"model": "m1", "protocol": "p"}]}, {"members": [{"model": "m1", "protocol": "p", "tasks": ["a"], "arm": "facts"}]},
    {"members": [{"model": "", "protocol": "p", "tasks": ["a"]}]}, {"members": [{"model": "m1", "protocol": " p", "tasks": ["a"]}]},
    {"members": [{"model": "m1", "protocol": "p", "tasks": []}]}, {"members": [{"model": "m1", "protocol": "p", "tasks": "a"}]},
    {"members": [{"model": "m1", "protocol": "p", "tasks": ["a", "a"]}]}, {"members": [{"model": "m1", "protocol": "p", "tasks": [1]}]},
    {"members": [{"model": "m1", "protocol": "p", "tasks": ["a"]}, {"model": "m1", "protocol": "q", "tasks": ["a"]}]},
])
def test_a_family_that_is_not_one_comparison_per_model_with_its_tasks_is_refused(spec):
    with pytest.raises(ValueError, match="family|member|model|tasks"):
        ta.analyse(model_rows("m1", GAIN), resamples=100, family=spec)


def test_the_command_line_takes_the_registered_family_and_records_its_digest(tmp_path, capsys):
    results, registered = tmp_path / "results.jsonl", tmp_path / "family.json"
    results.write_text("".join(json.dumps(r) + "\n" for r in model_rows("m1", GAIN)))
    registered.write_text(json.dumps({**family(("m1", PROTOCOL, GAIN)), "note": "registered before the run"}))
    ta.main([str(results), "--family", str(registered), "--json", str(tmp_path / "out.json"), "--resamples", "100"])
    assert capsys.readouterr().out.startswith("Confirmatory family, as registered before the run")
    written = json.loads((tmp_path / "out.json").read_text())
    assert written["confirmatory"]["members"][0]["p"] == pytest.approx(P_GAIN, abs=1e-12)  # full precision in the JSON
    assert written["provenance"]["family"] == {"name": "family.json", "sha256": ta.file_sha256(registered)}
    registered.write_text(json.dumps({"members": []}))
    for arguments in ([str(results), "--family", str(registered)], [str(results), "--family-runs", "3", "3"],
                      ["--simulate", "--independent-tasks"], ["--simulate", "--family", str(registered)],
                      ["--simulate", "--family-runs", "3", "3", "--effects", "0"]):
        with pytest.raises(SystemExit) as stopped:
            ta.main(arguments)
        assert stopped.value.code == 2
    ta.main([str(results), "--json", str(tmp_path / "plain.json"), "--resamples", "100"])  # without a family: as before
    assert "family" not in json.loads((tmp_path / "plain.json").read_text())["provenance"]


def test_the_family_simulation_is_reproducible_and_counts_false_rejections_only_where_the_truth_is_zero():
    settings = dict(runs_per_model=(5, 5, 3), tasks=8, replicates=80, seed=5)
    null = ta.simulate_family(effects=(0.0, 0.0, 0.0), **settings)
    assert null == ta.simulate_family(effects=(0.0, 0.0, 0.0), **settings)
    assert [m["null_true"] for m in null["models"]] == [True, True, True] and [m["runs_per_arm"] for m in null["models"]] == [5, 5, 3]
    assert null["every_false_null_rejected_after_holm"] is None  # there is none
    counts = null["counts"]
    assert counts["replicates"] == 80 and counts["any_false_rejection"] == counts["any_rejection"] <= counts["any_p_below_alpha"]
    assert null["any_false_rejection_after_holm"] == round(counts["any_false_rejection"] / 80, 3)
    assert all(m["counts"]["rejected"] <= m["counts"]["p_below_alpha"] for m in null["models"])  # Holm never rejects more
    mixed = ta.simulate_family(effects=(0.0, 0.8, 0.0), baseline="uniform:0:0.1", **settings)
    assert [m["null_true"] for m in mixed["models"]] == [True, False, True]
    assert mixed["models"][1]["true_mean_difference"] == 0.8 and mixed["models"][1]["rejected_after_holm"] >= 0.9
    assert mixed["every_false_null_rejected_after_holm"] == mixed["models"][1]["rejected_after_holm"]
    assert mixed["counts"]["any_false_rejection"] < mixed["counts"]["any_rejection"]  # the helped model is no false one
    capped = ta.simulate_family(effects=(0.2, 0.2), runs_per_model=(3, 3), baseline="uniform:1:1", tasks=4, replicates=5, seed=5)
    assert [m["null_true"] for m in capped["models"]] == [True, True]  # nothing left to gain: the truth is 0
    assert capped["models"][0]["not_estimable"] == 1.0 and capped["any_rejection_after_holm"] == 0.0
    assert capped["any_false_rejection_after_holm"] == 0.0 and capped["every_false_null_rejected_after_holm"] is None


@pytest.mark.parametrize("shared,draws", [(True, 2 * 4), (False, 2 * 4 * 3)])
def test_the_models_of_the_family_simulation_meet_the_same_tasks_unless_told_otherwise(monkeypatch, shared, draws):
    calls = []
    monkeypatch.setattr(ta, "baseline_sampler", lambda spec: lambda rng: calls.append(1) or 0.5)
    ta.simulate_family(runs_per_model=(2, 2, 2), effects=(0.0, 0.0, 0.0), tasks=4, replicates=2, shared_tasks=shared)
    assert len(calls) - 200000 == draws  # beyond the population sample: one baseline per task, or per task and model


@pytest.mark.parametrize("change", [{"effects": (0.0, 0.0)}, {"runs_per_model": ()}, {"runs_per_model": (3, 0, 3)}, {"tasks": 1},
                                    {"replicates": 0}, {"correlation": 2}, {"effect_model": "none"},
                                    {"effect_model": "share", "effects": (0.0, -0.1, 0.0)}])
def test_bad_family_simulation_settings_are_refused(change):
    with pytest.raises(ValueError):
        ta.simulate_family(**{"runs_per_model": (5, 5, 3), "effects": (0.0, 0.0, 0.0), "replicates": 2, **change})
