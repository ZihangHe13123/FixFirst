"""The task-level analysis held to a frozen selection of hard instances
(experiments/agent_baseline/task_analysis.py --hard-selection), on rows whose answers are known."""

import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "agent_baseline"))

import task_analysis as ta  # noqa: E402

SELECTION_SHA = "5" * 64
YAML, REPR, ALIAS = "flat-shop:vb_yaml_loader", "src-billing:vb_numpy_repr", "fixture-orders:ml_renamed_then_alias"
INSTANCES = {YAML: "a" * 64, REPR: "b" * 64, ALIAS: "c" * 64}
RECORD = {"selection": {  # as qualify_hard.py writes it: per scenario the formal and the development instance
    "vb_yaml_loader": {"formal": {"template": "flat-shop", "candidate": 1, "digest": "a" * 64},
                       "development": {"template": "pkg-inventory", "candidate": 2, "digest": "d" * 64}},
    "vb_numpy_repr": {"formal": {"template": "src-billing", "candidate": 1, "digest": "b" * 64}, "development": None},
    "ml_renamed_then_alias": {"formal": {"template": "fixture-orders", "candidate": 1, "digest": "c" * 64},
                              "development": {"template": "flat-shop", "candidate": 2, "digest": "e" * 64}}}}
SELECTION = ta.read_hard_selection(RECORD, SELECTION_SHA, "hard-selection.json")


def row(arm, case, fixed, run=1, attempt="a", grading="graded", kind="generated", **extra):
    """One run's row as the harness writes it; a formal instance's row records the selection, the formal
    role and its instance unless told otherwise (None drops the field)."""
    hard = {"hard_selection": SELECTION_SHA, "hard_role": "formal", "hard_instance": INSTANCES[case]} if case in INSTANCES else {}
    data = {"model": "m", "call_policy": "server", "attempt": attempt, "arm": arm, "case": case, "run": run, "kind": kind,
            "grading": grading, "fixed": fixed if grading == "graded" else None,
            **({"commit": "c" * 40} if kind == "real" else {"harness_commit": "h" * 40}), **hard, **extra}
    return {key: value for key, value in data.items() if value is not DROP}


DROP = object()  # a field the row does not have at all


def at(minute):
    return f"20261001T10{minute:02d}00Z-abc123"


def group(result, kind):
    [found] = [g for g in result["groups"] if g["kind"] == kind]
    return found


def test_the_frozen_selection_gives_the_hard_scenarios_and_each_formal_instance():
    assert SELECTION == {"name": "hard-selection.json", "sha256": SELECTION_SHA, "formal": INSTANCES, "cannot_run": [],
                         "scenarios": ["ml_renamed_then_alias", "vb_numpy_repr", "vb_yaml_loader"]}
    none = {"selection": {**RECORD["selection"], "vb_click_mix_stderr": {"formal": None, "development": None}}}
    read = ta.read_hard_selection(none, SELECTION_SHA, "s.json")
    assert read["cannot_run"] == ["vb_click_mix_stderr"] and read["formal"] == INSTANCES and len(read["scenarios"]) == 4


@pytest.mark.parametrize("record", [
    None, [], {}, {"selection": {}}, {"selection": []}, {"selection": {"vb_yaml_loader": None}},
    {"selection": {"vb_yaml_loader": {"development": None}}},  # no formal entry at all
    {"selection": {"vb_yaml_loader": {"formal": {"template": "flat-shop"}}}},  # no digest
    {"selection": {"vb_yaml_loader": {"formal": {"template": "flat-shop", "digest": "a" * 63}}}},
    {"selection": {"vb_yaml_loader": {"formal": {"template": "flat-shop", "digest": "A" * 64}}}},
    {"selection": {"vb_yaml_loader": {"formal": {"template": "flat-shop", "digest": None}}}},
    {"selection": {"vb_yaml_loader": {"formal": {"template": "", "digest": "a" * 64}}}},
    {"selection": {"vb_yaml_loader": {"formal": {"template": "flat:shop", "digest": "a" * 64}}}},
    {"selection": {"vb_yaml_loader": {"formal": "flat-shop"}}},
    {"selection": {"": {"formal": None}}}, {"selection": {"a:b": {"formal": None}}}])
def test_a_selection_that_does_not_name_each_scenarios_formal_instance_is_refused(record):
    with pytest.raises(ValueError, match="hard selection|formal instance"):
        ta.read_hard_selection(record, SELECTION_SHA, "s.json")


def test_formal_instances_are_a_kind_of_their_own_and_everything_else_is_as_without_the_selection():
    hard = [row(arm, case, fixed, run=n) for case, gain in ((YAML, True), (REPR, False)) for n in (1, 2)
            for arm, fixed in (("baseline", False), ("mcp", gain))]
    other = [row(arm, "src-billing:vi_numpy2", arm == "mcp", run=n) for n in (1, 2) for arm in ("baseline", "mcp")]
    real = [row(arm, "cachetools", True, kind="real") for arm in ("baseline", "mcp")]
    held = ta.analyse(hard + other + real, resamples=200, hard=SELECTION)
    assert [g["kind"] for g in held["groups"]] == ["generated", "hard", "real"]
    [main] = group(held, "hard")["comparisons"]
    assert main["tasks"] == 2 and main["per_task"] == {YAML: 1.0, REPR: 0.0}
    assert group(held, "hard")["ledger"]["mcp"] == {"rows_read": 4, "rows_kept": 4, "runs_used": 4, "runs_never_graded": 0,
                                                    "runs_retried_once": 0, "runs_left_out": 0}
    plain = ta.analyse(other + real, resamples=200)
    assert [group(held, kind) for kind in ("generated", "real")] == plain["groups"]  # untouched by the selection
    assert held["deviations"] == [] and held["rows_read"] == 14 and "hard" not in plain
    report = held["hard"]
    assert report["selection"] == {"name": "hard-selection.json", "sha256": SELECTION_SHA, "formal_instances": INSTANCES,
                                   "scenarios": SELECTION["scenarios"], "cannot_run": []}
    assert (report["rows_read"], report["rows_kept"], report["runs_used"], report["runs_left_out"]) == (8, 8, 8, 0)
    assert report["outside"] == {"rows_read": 0, "rows_kept": 0, "cases": {}} and report["attempts_without_an_instance"] == 0
    [coverage] = report["coverage"]
    assert coverage["runs_used"] == {ALIAS: {"baseline": 0, "mcp": 0}, YAML: {"baseline": 2, "mcp": 2},
                                     REPR: {"baseline": 2, "mcp": 2}}
    assert coverage["instances_without_a_run_used"] == [ALIAS]  # the selection says what was to be run, not the rows


def test_rows_of_one_case_under_two_selections_are_not_one_task():
    """Codex r10: the same model, case, harness and budget, but the two arms ran other instances."""
    rows = [row("baseline", YAML, False),
            row("mcp", YAML, True, hard_selection="d" * 64, hard_instance="c" * 64, hard_role="development")]
    unchecked = ta.analyse(rows, resamples=200)
    [mixed] = unchecked["groups"][0]["comparisons"]
    assert mixed["per_task"] == {YAML: 1.0} and unchecked["deviations"] == []  # what happens without the selection
    assert unchecked["hard"] == {"selection": None, "rows_with_hard_fields": 2}  # and the report says it is unchecked
    held = ta.analyse(rows, resamples=200, hard=SELECTION)
    [only] = held["groups"]
    assert only["kind"] == "hard" and only["tasks"] == {YAML: {"baseline": [0, 1]}}
    assert only["comparisons"] == [{"first": "baseline", "second": "mcp", "tasks": 0, "no_graded_runs_in": ["mcp"]}]
    assert only["ledger"]["mcp"]["runs_used"] == 0 and only["ledger"]["mcp"]["runs_left_out"] == 1
    [listed] = held["deviations"]
    assert (listed["case"], listed["arm"], listed["run"], listed["kind"]) == (YAML, "mcp", 1, "hard")
    assert listed["reason"] == ("hard instance: an attempt ran under another selection (dddddddddddd); an attempt's role is "
                                "development, not formal; an attempt's instance is cccccccccccc, not the selection's aaaaaaaaaaaa")
    assert (held["hard"]["runs_used"], held["hard"]["runs_left_out"]) == (1, 1)


@pytest.mark.parametrize("change,reason", [
    ({"hard_selection": "d" * 64}, "ran under another selection (dddddddddddd)"),
    ({"hard_selection": None}, "ran under no selection"),
    ({"hard_selection": DROP}, "ran under no selection"),
    ({"hard_selection": SELECTION_SHA[:12]}, "ran under another selection (555555555555)"),  # the whole digest, not its start
    ({"hard_selection": 5}, "ran under another selection (5)"),
    ({"hard_role": "development"}, "role is development, not formal"),
    ({"hard_role": None}, "role is None, not formal"),
    ({"hard_role": DROP}, "role is None, not formal"),
    ({"hard_instance": "f" * 64}, "instance is ffffffffffff, not the selection's aaaaaaaaaaaa"),
    ({"hard_instance": ""}, "instance is , not the selection's aaaaaaaaaaaa"),
    ({"hard_instance": INSTANCES[REPR]}, "instance is bbbbbbbbbbbb, not the selection's aaaaaaaaaaaa"),  # another case's
    ({"hard_instance": None}, "was graded without recording its instance"),
    ({"hard_instance": DROP}, "was graded without recording its instance"),
    ({"hard_selection": DROP, "hard_role": DROP, "hard_instance": DROP}, "ran under no selection")])
def test_a_formal_instances_run_counts_only_with_the_selection_the_role_and_the_instance(change, reason):
    rows = [row("baseline", YAML, False), row("mcp", YAML, True), row("baseline", YAML, True, run=2),
            row("mcp", YAML, True, run=2, **change)]
    held = ta.analyse(rows, resamples=200, hard=SELECTION)
    [only] = held["groups"]
    assert only["kind"] == "hard" and only["tasks"] == {YAML: {"baseline": [1, 2], "mcp": [1, 1]}}  # the other runs stay
    [listed] = held["deviations"]
    assert (listed["arm"], listed["run"]) == ("mcp", 2) and reason in listed["reason"]
    assert only["ledger"]["mcp"] == {"rows_read": 2, "rows_kept": 2, "runs_used": 1, "runs_never_graded": 0,
                                     "runs_retried_once": 0, "runs_left_out": 1}


def test_a_formal_instance_without_its_fields_is_not_an_ordinary_generated_case():
    bare = {"hard_selection": DROP, "hard_role": DROP, "hard_instance": DROP}
    rows = [row(arm, YAML, arm == "mcp", **bare) for arm in ("baseline", "mcp")]
    assert "hard" not in ta.analyse(rows, resamples=200)  # nothing marks them, so without the selection nothing is said
    held = ta.analyse(rows, resamples=200, hard=SELECTION)
    [only] = held["groups"]
    assert only["kind"] == "hard" and only["tasks"] == {} and len(held["deviations"]) == 2
    assert held["hard"]["runs_used"] == 0 and held["hard"]["runs_left_out"] == 2


def test_an_attempt_that_failed_before_its_instance_was_built_confirms_and_contradicts_nothing():
    early = row("mcp", YAML, None, attempt=at(1), grading="not_graded", end="setup_failed", hard_instance=None)
    rows = [row("baseline", YAML, False, attempt=at(1)), early, row("mcp", YAML, True, attempt=at(2))]
    held = ta.analyse(rows, resamples=200, hard=SELECTION)
    [only] = held["groups"]
    assert only["tasks"] == {YAML: {"baseline": [0, 1], "mcp": [1, 1]}} and held["deviations"] == []
    assert [item["attempts"] for item in held["retried"]] == [["setup_failed", "graded"]]
    assert held["hard"]["attempts_without_an_instance"] == 1 and held["hard"]["runs_used"] == 2
    alone = ta.analyse([row("baseline", YAML, False, attempt=at(1)), early], resamples=200, hard=SELECTION)
    assert alone["deviations"] == [] and [item["ends"] for item in alone["never_graded"]] == [["setup_failed"]]
    assert alone["hard"]["attempts_without_an_instance"] == 1  # unknown, and no result either


@pytest.mark.parametrize("first,second", [
    ({"hard_selection": "d" * 64}, {}),  # the failed attempt ran under another selection
    ({"hard_instance": "f" * 64}, {}),  # or built another instance
    ({"hard_role": "development"}, {}),
    ({}, {"hard_selection": "d" * 64}),  # or the retry did
    ({"hard_instance": None}, {"hard_instance": "f" * 64})])
def test_a_retry_does_not_undo_what_another_attempt_of_the_run_recorded(first, second):
    rows = [row("baseline", YAML, False, attempt=at(1)),
            row("mcp", YAML, None, attempt=at(1), grading="not_graded", end="setup_failed", **first),
            row("mcp", YAML, True, attempt=at(2), **second)]
    held = ta.analyse(rows, resamples=200, hard=SELECTION)
    [only] = held["groups"]
    assert only["tasks"] == {YAML: {"baseline": [0, 1]}}  # the retried run is not used
    [listed] = held["deviations"]
    assert listed["arm"] == "mcp" and listed["reason"].startswith("hard instance: ")
    assert only["ledger"]["mcp"] == {"rows_read": 2, "rows_kept": 2, "runs_used": 0, "runs_never_graded": 0,
                                     "runs_retried_once": 1, "runs_left_out": 1}  # every attempt stays in the ledger
    assert [item["attempts"] for item in held["retried"]] == [["setup_failed", "graded"]]


def test_a_run_that_was_not_used_anyway_is_listed_and_counted_once():
    never = row("mcp", YAML, None, grading="not_graded", end="setup_failed", hard_selection="d" * 64)
    twice = [row("mcp", REPR, True, attempt=at(1), hard_role="development"), row("mcp", REPR, True, attempt=at(2))]
    held = ta.analyse([row("baseline", YAML, False), never, row("baseline", REPR, False), *twice], resamples=200, hard=SELECTION)
    by_case = {item["case"]: item for item in held["deviations"] if item["reason"].startswith("hard instance")}
    assert by_case[YAML]["not_used_anyway"] is True and by_case[REPR]["not_used_anyway"] is True
    assert sum("graded run is never rerun" in item["reason"] for item in held["deviations"]) == 1  # the retry rule's own entry
    ledger = group(held, "hard")["ledger"]["mcp"]
    assert (ledger["runs_used"], ledger["runs_never_graded"], ledger["runs_left_out"]) == (0, 1, 1)  # not counted twice
    assert held["hard"]["runs_left_out"] == 0 and held["hard"]["identity_problems_in_runs_not_used"] == 2


def test_hard_cases_outside_the_selections_formal_instances_are_counted_and_analysed_nowhere():
    development = [row(arm, "pkg-inventory:vb_yaml_loader", True, hard_selection=SELECTION_SHA, hard_role="development",
                       hard_instance="d" * 64) for arm in ("baseline", "mcp")]
    unselected = [row("baseline", "unittest-grades:vb_numpy_repr", True, hard_selection=None, hard_role=None, hard_instance="9" * 64),
                  row("mcp", "unittest-grades:vb_numpy_repr", True)]  # a hard scenario on another template, fields or not
    marked = [row("mcp", "somewhere:else", True, hard_role="formal")]  # any row that carries a hard field
    formal = [row(arm, YAML, arm == "mcp") for arm in ("baseline", "mcp")]
    ordinary = [row(arm, "src-billing:vi_numpy2", True) for arm in ("baseline", "mcp")]
    rows = formal + development + unselected + marked + ordinary + [development[0]]  # one row read twice
    held = ta.analyse(rows, resamples=200, hard=SELECTION)
    assert sorted(g["kind"] for g in held["groups"]) == ["generated", "hard"]
    assert group(held, "generated")["tasks"] == {"src-billing:vi_numpy2": {"baseline": [1, 1], "mcp": [1, 1]}}
    assert group(held, "hard")["tasks"] == {YAML: {"baseline": [0, 1], "mcp": [1, 1]}}
    assert held["hard"]["outside"] == {"rows_read": 6, "rows_kept": 5, "cases": {
        "pkg-inventory:vb_yaml_loader": {"rows": 3, "roles": ["development"]},
        "somewhere:else": {"rows": 1, "roles": ["formal"]},
        "unittest-grades:vb_numpy_repr": {"rows": 2, "roles": ["None"]}}}
    assert held["rows_read"] == 10 and held["duplicates"] == 1 and held["deviations"] == []
    in_groups = sum(n["rows_read"] for g in held["groups"] for n in g["ledger"].values())
    assert in_groups + held["hard"]["outside"]["rows_read"] == held["rows_read"]  # every row read is accounted for


def test_budgets_stay_apart_and_a_real_project_is_never_a_hard_case():
    formal = [row(arm, YAML, arm == "mcp", settings={"run_timeout": timeout}) for timeout in (900, 1800)
              for arm in ("baseline", "mcp")]
    real = [row(arm, YAML, True, kind="real", hard_selection=DROP, hard_role=DROP, hard_instance=DROP)
            for arm in ("baseline", "mcp")]  # a real project that happens to have the name
    held = ta.analyse(formal + real, resamples=200, hard=SELECTION)
    assert sorted(g["kind"] for g in held["groups"]) == ["hard", "hard", "real"]
    assert len({g["protocol"] for g in held["groups"] if g["kind"] == "hard"}) == 2  # a rehearsal's budget is another protocol
    assert held["hard"]["rows_read"] == 4 and len(held["hard"]["coverage"]) == 2 and held["deviations"] == []


def test_the_reports_own_kind_is_refused_in_the_input():
    with pytest.raises(ValueError, match="this report's own name"):
        ta.analyse([row("baseline", YAML, True, kind="hard")], resamples=100, hard=SELECTION)
    with pytest.raises(ValueError, match="this report's own name"):
        ta.analyse([row("baseline", "a", True, kind="hard")], resamples=100)


def test_the_report_names_the_selection_and_says_what_was_left_out():
    rows = [row("baseline", YAML, False), row("mcp", YAML, True, hard_instance="f" * 64),
            row("mcp", "pkg-inventory:vb_yaml_loader", True, hard_role="development", hard_instance="d" * 64)]
    record = {"selection": {**RECORD["selection"], "vb_click_mix_stderr": {"formal": None, "development": None}}}
    text = ta.markdown(ta.analyse(rows, resamples=200, hard=ta.read_hard_selection(record, SELECTION_SHA, "hard-selection.json")))
    assert f"held to the frozen selection hard-selection.json (SHA-256 {SELECTION_SHA}): 3 formal instances" in text
    assert "no template qualified for vb_click_mix_stderr" in text
    assert "Rows of formal instances: 2 read, 2 kept; runs used: 1; left out for their identity: 1" in text
    assert "analysed nowhere here: 1; pkg-inventory:vb_yaml_loader (1, role development)." in text
    assert f"Formal instances of m {ta.ca.protocol(rows[0])} without a run used: {ALIAS}, {REPR}" in text
    assert "| hard | mcp − baseline | 0 | no graded runs in: mcp |" in text
    unchecked = ta.markdown(ta.analyse(rows, resamples=200))
    assert "3 rows carry hard-instance fields and no frozen selection was given" in unchecked
    assert "nothing about their instances was checked" in unchecked and "held to the frozen selection" not in unchecked


def test_the_command_line_takes_the_selection_with_its_registered_digest(tmp_path, capsys):
    results, selection, out = tmp_path / "results.jsonl", tmp_path / "hard-selection.json", tmp_path / "out.json"
    selection.write_text(json.dumps(RECORD))
    digest = hashlib.sha256(selection.read_bytes()).hexdigest()
    rows = [row(arm, YAML, arm == "mcp", hard_selection=digest) for arm in ("baseline", "mcp")]
    results.write_text("".join(json.dumps(r) + "\n" for r in rows))
    ta.main([str(results), "--hard-selection", str(selection), "--hard-selection-sha256", digest.upper(), "--resamples", "200",
             "--json", str(out)])
    assert f"held to the frozen selection hard-selection.json (SHA-256 {digest})" in capsys.readouterr().out
    written = json.loads(out.read_text())
    assert written["provenance"]["hard_selection"] == {"name": "hard-selection.json", "sha256": digest}
    assert written["hard"]["runs_used"] == 2 and written["groups"][0]["kind"] == "hard"
    refused = [(["--hard-selection", str(selection)], "go together"),
               (["--hard-selection-sha256", digest], "go together"),
               (["--hard-selection", str(selection), "--hard-selection-sha256", "5" * 64], "not the registered"),
               (["--hard-selection", str(selection), "--hard-selection-sha256", digest[:12]], "64 hexadecimal digits")]
    for extra, message in refused:
        with pytest.raises(SystemExit) as stopped:
            ta.main([str(results), *extra])
        assert stopped.value.code == 2 and message in capsys.readouterr().err
    with pytest.raises(SystemExit):  # the simulation reads no results
        ta.main(["--simulate", "--hard-selection", str(selection), "--hard-selection-sha256", digest])
    assert "reads no results" in capsys.readouterr().err
    selection.write_text(json.dumps({"selection": {}}))  # the registered digest of a file that is no selection
    with pytest.raises(SystemExit):
        ta.main([str(results), "--hard-selection", str(selection), "--hard-selection-sha256",
                 hashlib.sha256(selection.read_bytes()).hexdigest()])
    assert "non-empty" in capsys.readouterr().err
