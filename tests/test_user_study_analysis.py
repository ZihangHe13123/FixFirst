"""The user-study analysis (task B13): hand-calculated numbers on the fictional DEMO tables, and
the rules for missing, excluded and contradictory records."""

import csv
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "docs" / "user-study"
FIXTURES = STUDY / "fixtures"
spec = importlib.util.spec_from_file_location("user_study_analysis", STUDY / "analysis.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)

SESSION_HEADER = ["participant", "date", "order", "fixfirst_set", "task", "condition", "start_time", "seconds",
                  "success", "false_done_claims", "tests_modified", "confidence_1to5", "cause_explanation", "notes"]
QUESTIONNAIRE_HEADER = list(analysis.QUESTIONNAIRE_COLUMNS)
DEMO = ["--sessions", str(FIXTURES / "demo_sessions.csv"), "--questionnaire", str(FIXTURES / "demo_questionnaire.csv"),
        "--causes", str(FIXTURES / "demo_cause_scores.csv")]


def rows_for(person, fixfirst_set, fixfirst, baseline):
    """Task rows for one participant; a time of 720 means the task was not completed."""
    other = "B" if fixfirst_set == "A" else "A"
    rows = []
    for condition, chosen, times in (("fixfirst", fixfirst_set, fixfirst), ("baseline", other, baseline)):
        for task, seconds in zip(analysis.SETS[chosen], times):
            rows.append({"participant": person, "fixfirst_set": fixfirst_set, "task": task, "condition": condition,
                         "seconds": str(seconds), "success": "no" if seconds == 720 else "yes",
                         "false_done_claims": "0", "tests_modified": "no", "confidence_1to5": "4",
                         "cause_explanation": "x"})
    return rows


def write(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return path


def run(tmp_path, rows, per_condition=2, causes=None):
    args = SimpleNamespace(sessions=str(write(tmp_path / "sessions.csv", SESSION_HEADER, rows)),
                           questionnaire=str(tmp_path / "questionnaire.csv"), causes=str(tmp_path / "causes.csv"))
    if causes is not None:
        write(tmp_path / "causes.csv", ["participant", "task", "cause_score", "scorer"], causes)
    config = analysis.Config(tasks_per_condition=per_condition)
    data = analysis.load(args, config)
    return data, analysis.analyse(data, config)


def demo():
    args = SimpleNamespace(sessions=DEMO[1], questionnaire=DEMO[3], causes=DEMO[5])
    config = analysis.Config()
    data = analysis.load(args, config)
    return data, analysis.analyse(data, config)


def test_the_demo_numbers_match_the_hand_calculations():
    _, results = demo()
    ff, base = results["conditions"]["fixfirst"], results["conditions"]["baseline"]
    assert (ff["completed"], ff["tasks"], base["completed"], base["tasks"]) == (10, 12, 7, 10)
    assert (ff["median_solved_seconds"], base["median_solved_seconds"]) == (265, 550)
    assert (ff["median_seconds_unfinished_as_limit"], base["median_seconds_unfinished_as_limit"]) == (290, 605)
    assert results["time_target"]["reduction"] == pytest.approx(285 / 550)
    assert results["unfinished_as_limit_reduction"] == pytest.approx(315 / 605)
    assert results["completion_target"]["met"] is True
    paired = results["paired"]
    assert [(who, d) for who, _, _, d in paired["pairs"]] == [
        ("P01", -360), ("P02", -200), ("P03", -150), ("P04", -350), ("P05", -365)]
    assert (paired["median_difference"], paired["mean_difference"]) == (-350, -285)
    assert paired["excluded"] == [("P06", "baseline: 0 of 2 tasks usable (1 withdrawn, 1 not in the table)")]
    assert paired["wilcoxon"]["statistic"] == 0 and paired["wilcoxon"]["p_value"] == pytest.approx(0.0625)
    assert ff["false_done_claims"] == {"total": 5, "tasks_with_claims": 4, "n": 12, "missing": 0}
    assert base["false_done_claims"] == {"total": 8, "tasks_with_claims": 5, "n": 10, "missing": 0}
    assert (ff["tests_modified"]["yes"], base["tests_modified"]["yes"]) == (0, 1)
    assert (ff["confidence"]["median"], base["confidence"]["median"]) == (4, 3.5)
    assert {k: ff["cause_scores"][k] for k in ("correct", "partly", "wrong", "unscored")} == {
        "correct": 8, "partly": 2, "wrong": 1, "unscored": 1}
    assert {k: base["cause_scores"][k] for k in ("correct", "partly", "wrong", "unscored")} == {
        "correct": 4, "partly": 2, "wrong": 3, "unscored": 1}
    sus = results["sus"]
    assert sus["scores"] == {"P01": 100, "P02": 75, "P03": 50, "P04": 82.5}
    assert sus["excluded"] == {"P06": ["sus_7 missing"]}
    assert (sus["mean"], sus["median"]) == (76.875, 78.75)
    assert sus["sd"] == pytest.approx((1292.1875 / 3) ** 0.5)
    background = results["background"]
    assert background["without_questionnaire"] == ["P05"]
    assert background["python_years"]["median"] == 2 and background["used_pytest"]["yes"] == 3
    reasons = {(p, t): r for _, _, p, t, r in results["excluded"]}
    assert reasons[("PILOT1", "T1")].startswith("pilot or example") and reasons[("P06", "T1")] == "withdrawn from the study"
    assert ("P00-EXAMPLE", "T1") in reasons


def test_the_committed_demo_output_is_current(tmp_path):
    out = tmp_path / "DEMO_RESULTS.md"
    assert analysis.main([*DEMO, "--demo", "--output", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# DEMO: fictional data")
    assert text == (FIXTURES / "DEMO_RESULTS.md").read_text(encoding="utf-8")
    assert "/Users/" not in text and "\\Users\\" not in text


@pytest.mark.parametrize("change,message", [
    (lambda rows: rows.append(dict(rows[0])), "is also on line"),
    (lambda rows: rows[0].update(condition="ff"), "is not fixfirst or baseline"),
    (lambda rows: rows[0].update(task="T9"), "is not one of"),
    (lambda rows: rows[0].update(fixfirst_set="C"), "is not A or B"),
    (lambda rows: rows[0].update(seconds="-5"), "is negative"),
    (lambda rows: rows[0].update(seconds="3.5"), "is not a whole number"),
    (lambda rows: rows[3].update(seconds="800"), "above the time limit"),
    (lambda rows: rows[0].update(seconds="800"), "success after the time limit"),
    (lambda rows: rows[0].update(seconds=""), "a completed task needs its time"),
    (lambda rows: rows[3].update(seconds="300"), "recorded as 720 s"),
    (lambda rows: rows[0].update(tests_modified="yes"), "success with modified tests"),
    (lambda rows: rows[0].update(success="maybe"), "is not yes, no or withdrawn"),
    (lambda rows: rows[0].update(false_done_claims="-1"), "is not a count"),
    (lambda rows: rows[0].update(confidence_1to5="6"), "is not 1 to 5"),
    (lambda rows: rows[1].update(task="T3"), "not in set A"),
])
def test_contradictory_records_stop_the_analysis(tmp_path, change, message):
    rows = rows_for("P01", "A", [300, 200], [500, 720])
    change(rows)
    with pytest.raises(analysis.DataError) as error:
        run(tmp_path, rows)
    assert any(message in problem for problem in error.value.problems), error.value.problems


def test_more_tasks_than_configured_stop_the_analysis(tmp_path):
    with pytest.raises(analysis.DataError, match="the configuration allows 1 per condition"):
        run(tmp_path, rows_for("P01", "A", [300, 200], [500, 720]), per_condition=1)


def test_a_missing_value_is_neither_zero_seconds_nor_a_success(tmp_path):
    rows = rows_for("P01", "A", [300, 200], [500, 720]) + rows_for("P02", "B", [250, 350], [400, 600])
    rows[4].update(success="", seconds="")
    data, results = run(tmp_path, rows)
    ff = results["conditions"]["fixfirst"]
    assert (ff["completed"], ff["tasks"], ff["median_solved_seconds"]) == (3, 3, 300)
    assert ("P02", "T3", "success not recorded") in [(p, t, r) for _, _, p, t, r in results["excluded"]]
    assert [who for who, *_ in results["paired"]["pairs"]] == ["P01"]
    assert results["paired"]["excluded"] == [("P02", "fixfirst: 1 of 2 tasks usable (1 success not recorded)")]


def test_no_completed_task_is_reported_without_a_verdict(tmp_path):
    _, results = run(tmp_path, rows_for("P01", "A", [720, 720], [720, 720]))
    ff = results["conditions"]["fixfirst"]
    assert ff["median_solved_seconds"] is None and results["time_target"]["reduction"] is None
    assert results["completion_target"]["met"] is False
    text = analysis.render(results, meta(2))
    assert "not assessable: a condition has no completed task" in text
    assert "Wilcoxon signed-rank test: not computed (every difference is zero)" in text


def test_without_pairs_there_is_no_paired_comparison(tmp_path):
    rows = [r for r in rows_for("P01", "A", [300, 200], [500, 720]) if r["condition"] == "fixfirst"]
    _, results = run(tmp_path, rows)
    assert results["paired"]["pairs"] == [] and results["paired"]["n"] == 0
    assert results["paired"]["wilcoxon"] == {"computed": False, "reason": "no participant has both conditions complete"}
    text = analysis.render(results, meta(2))
    assert "No participant has the configured number of tasks in both conditions." in text
    assert "target met" not in text


def test_all_zero_differences_are_not_tested(tmp_path):
    rows = rows_for("P01", "A", [300, 400], [400, 300]) + rows_for("P02", "B", [500, 100], [100, 500])
    _, results = run(tmp_path, rows)
    assert [d for *_, d in results["paired"]["pairs"]] == [0, 0]
    assert results["paired"]["wilcoxon"] == {"computed": False, "reason": "every difference is zero"}


def test_a_baseline_median_of_zero_gives_no_reduction():
    assert analysis.reduction(0, 10) is None
    assert analysis.reduction(None, 10) is None and analysis.reduction(100, None) is None
    assert analysis.reduction(100, 80) == pytest.approx(0.2)


def test_sus_items_are_never_filled_in():
    complete = {f"sus_{n}": "3" for n in range(1, 11)}
    assert analysis.sus_score(complete) == (50, [])
    assert analysis.sus_score({**complete, "sus_3": ""}) == (None, ["sus_3 missing"])
    score, reasons = analysis.sus_score({**complete, "sus_2": "6", "sus_9": "3.5"})
    assert score is None and len(reasons) == 2 and "sus_2 = '6'" in reasons[0] and "sus_9" in reasons[1]


def test_one_task_per_condition_is_an_explicit_configuration(tmp_path):
    rows = rows_for("P01", "A", [300], [500])  # T1 with FixFirst, T3 without
    _, default = run(tmp_path, rows)
    assert default["paired"]["excluded"][0][1].startswith("fixfirst: 1 of 2 tasks usable (1 not in the table)")
    _, one = run(tmp_path, rows, per_condition=1)
    assert [(who, d) for who, *_, d in one["paired"]["pairs"]] == [("P01", -200)]
    out = tmp_path / "one.md"
    assert analysis.main(["--sessions", str(tmp_path / "sessions.csv"), "--questionnaire", str(tmp_path / "q.csv"),
                          "--causes", str(tmp_path / "c.csv"), "--tasks-per-condition", "1",
                          "--output", str(out)]) == 0
    assert "Tasks per condition: 1" in out.read_text(encoding="utf-8")


def test_cause_scores_come_from_a_person(tmp_path):
    rows = rows_for("P01", "A", [300, 200], [500, 720])
    data, results = run(tmp_path, rows)
    assert results["conditions"]["fixfirst"]["cause_scores"]["unscored"] == 2
    assert any("no cause explanation has been scored yet" in note for note in results["notes"])
    with pytest.raises(analysis.DataError, match="is not correct, partly or wrong"):
        run(tmp_path, rows, causes=[{"participant": "P01", "task": "T1", "cause_score": "maybe", "scorer": "x"}])
    with pytest.raises(analysis.DataError, match="has no usable task record"):
        run(tmp_path, rows, causes=[{"participant": "P09", "task": "T1", "cause_score": "wrong", "scorer": "x"}])
    _, scored = run(tmp_path, rows, causes=[{"participant": "P01", "task": "T1", "cause_score": "Partly", "scorer": "x"}])
    assert scored["conditions"]["fixfirst"]["cause_scores"]["partly"] == 1


def test_the_cause_sheet_hides_the_condition(tmp_path):
    sheet = tmp_path / "sheet.csv"
    assert analysis.main([*DEMO, "--demo", "--cause-sheet", str(sheet)]) == 0
    with sheet.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert "condition" not in rows[0] and len(rows) == 22
    assert rows[0]["known_cause"] == analysis.KNOWN_CAUSES[rows[0]["task"]] and rows[0]["cause_score"] == ""


def test_demo_output_is_never_written_as_the_results(tmp_path):
    with pytest.raises(SystemExit):
        analysis.main([*DEMO, "--demo", "--output", str(tmp_path / "RESULTS.md")])
    with pytest.raises(SystemExit):
        analysis.main([*DEMO, "--output", str(tmp_path / "out.md")])  # fixtures without --demo


def test_every_problem_is_listed_and_nothing_is_analysed(tmp_path, capsys):
    rows = rows_for("P01", "A", [300, 200], [500, 720])
    rows[0].update(condition="ff")
    rows[3].update(seconds="300")
    write(tmp_path / "sessions.csv", SESSION_HEADER, rows)
    out = tmp_path / "out.md"
    assert analysis.main(["--sessions", str(tmp_path / "sessions.csv"), "--output", str(out)]) == 1
    error = capsys.readouterr().err
    assert "is not fixfirst or baseline" in error and "recorded as 720 s" in error
    assert not out.exists()


def meta(per_condition):
    return {"demo": False, "tasks_per_condition": per_condition, "time_limit": 720, "protocol_version": "test",
            "script_sha256": "0" * 64, "inputs": {}}


def test_session_and_questionnaire_problems_are_listed_together(tmp_path):
    rows = rows_for("P01", "A", [300, 200], [500, 720])
    rows[0].update(condition="ff")
    write(tmp_path / "sessions.csv", SESSION_HEADER, rows)
    answers = {c: "" for c in QUESTIONNAIRE_HEADER}
    write(tmp_path / "questionnaire.csv", QUESTIONNAIRE_HEADER,
          [{**answers, "participant": "P01", "used_pytest": "maybe"}, {**answers, "participant": "P01"}])
    args = SimpleNamespace(sessions=str(tmp_path / "sessions.csv"), questionnaire=str(tmp_path / "questionnaire.csv"),
                           causes=str(tmp_path / "causes.csv"))
    with pytest.raises(analysis.DataError) as error:
        analysis.load(args, analysis.Config())
    problems = "\n".join(error.value.problems)
    assert "is not fixfirst or baseline" in problems and "used_pytest 'maybe'" in problems
    assert "P01 is also on line 2" in problems
