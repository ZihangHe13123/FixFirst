"""The one-shot LLM baseline (task B3) sees FixFirst's evidence, nothing more, and records every
failure instead of stopping."""

import json
from pathlib import Path
import shutil
import sys
import urllib.error

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "diagnosis_baseline"))

import one_shot  # noqa: E402

from fixfirst.diagnosis_cases import load_session  # noqa: E402
from fixfirst.reasoning import diagnose  # noqa: E402

HARD = ROOT / "examples" / "hard-dataset"
DIAGNOSIS = ROOT / "examples" / "diagnosis-dataset"
TRIAL = ROOT / "experiments" / "diagnosis_baseline" / "dev-trial-2026-09-29"


def case(dataset: Path, case_id: str) -> dict:
    for line in (dataset / "cases.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["case_id"] == case_id:
            return row
    raise KeyError(case_id)


def click_session():
    return load_session(HARD, case(HARD, "flat-shop--vb_click_mix_stderr")["session"])


def with_project(session, change):
    session = session.model_copy(deep=True)
    run = next(r for r in reversed(session.runs) if r.tool == "project")
    data = json.loads(run.stdout)
    change(data)
    run.stdout = json.dumps(data)
    return session


def test_the_model_gets_the_imports_that_fixfirsts_heuristic_reads():
    session = click_session()
    cleared = with_project(session, lambda data: data.update(imported_names={}))
    # The documented call change still needs the project's observed import binding.
    assert [d["likely_rule_id"] for d in diagnose(session).values()] == ["H10"]
    assert [d["likely_rule_id"] for d in diagnose(cleared).values()] == [None]
    # ... so the model must see them too.
    assert '"CliRunner": "click.testing.CliRunner"' in one_shot.evidence(session)
    assert one_shot.evidence(cleared) != one_shot.evidence(session)


def sentinel_like(key, value):
    if key == "packages":
        return [{"name": "sentinel-field", "version": "1.0"}]
    if key == "files":
        return [{"path": "sentinel-field", "bytes": 1, "sha256": "0"}]
    if isinstance(value, list):
        return ["sentinel-field"]
    if isinstance(value, dict):
        return {"sentinel-field": "x"}
    return "sentinel-field"


def test_every_field_of_the_snapshots_reaches_the_model_unless_it_is_listed_as_left_out():
    session = click_session()
    project = json.loads(next(r for r in reversed(session.runs) if r.tool == "project").stdout)
    for key, value in project.items():
        if key in one_shot.OMITTED["project"]:
            continue
        changed = with_project(session, lambda data: data.update({key: sentinel_like(key, value)}))
        assert "sentinel-field" in one_shot.evidence(changed), key
    for key, value in session.environment.items():
        if key in one_shot.OMITTED["environment"]:
            continue
        changed = session.model_copy(deep=True)
        changed.environment[key] = sentinel_like(key, value)
        assert "sentinel-field" in one_shot.evidence(changed), key


def test_fixfirsts_conclusions_and_the_case_definition_never_reach_the_model():
    session = click_session()
    text = one_shot.evidence(session)
    changed = session.model_copy(deep=True)
    changed.name = "sentinel-name"
    for issue in changed.issues:
        issue.title = "sentinel-issue"
    for event in changed.events:
        event.message = "sentinel-event"
    search = changed.runs[0].model_copy(update={"tool": "version_search", "stdout": "sentinel-search"})
    changed.runs.append(search)
    assert one_shot.evidence(changed) == text


def test_the_warnings_a_failing_test_recorded_are_shown():
    session = click_session().model_copy(deep=True)
    run = next(r for r in session.runs if r.tool == "pytest_run")
    record = next(r for r in run.records if r.get("type") == "exception")
    record["warnings"] = [{"recorder": "recwarn", "category": "DeprecationWarning",
                           "message": "sentinel-warning is deprecated", "filename": "/venv/x.py", "lineno": 3}]
    assert "sentinel-warning is deprecated" in one_shot.evidence(session)


def test_long_output_keeps_its_start_and_end_and_says_what_was_cut():
    text = "a" * 30 + "b" * 30
    assert one_shot.clip(text, 20) == "a" * 10 + "\n[... 40 characters left out ...]\n" + "b" * 10
    assert one_shot.trimmed(list(range(4)), items=2) == [0, 1, "[... 2 more left out]"]


def test_no_committed_case_gives_its_answer_away():
    for dataset in (DIAGNOSIS, HARD):
        for line in (dataset / "cases.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            text = one_shot.evidence(load_session(dataset, row["session"]))
            assert one_shot.leaks(text, row) == [], row["case_id"]
            assert "## Project index" in text and "## Environment" in text, row["case_id"]


def test_a_label_in_the_evidence_is_caught_but_a_field_name_is_not():
    row = {"case_id": "flat-shop--lm_renamed", "scenario": "lm_renamed", "label": "local_module"}
    assert one_shot.leaks('local_modules: [{"name": "app"}]', row) == []
    assert one_shot.leaks('defined_names: ["local_module"]', row) == ["local_module"]
    assert one_shot.leaks("E   ImportError: flat-shop--lm_renamed", row) == ["flat-shop--lm_renamed", "lm_renamed"]


@pytest.mark.parametrize("answer,cause,step", [
    ('{"root_cause":"config_missing","first_step":"Set TOKEN using ${TOKEN} in the configuration."}',
     "config_missing", "Set TOKEN using ${TOKEN} in the configuration."),
    ('{"root_cause": "code_defect", "first_step": "Fix the \\"total\\" function."}',
     "code_defect", 'Fix the "total" function.'),
    ('```json\n{"root_cause": "local_module", "first_step": "Rename it back."}\n```',
     "local_module", "Rename it back."),
    ('<think>\nmaybe {x}\n</think>\n{"root_cause": " Version_Incompatibility ", "first_step": "Pin numpy<2."}',
     "version_incompatibility", "Pin numpy<2."),
])
def test_valid_answers_are_read_with_a_json_decoder(answer, cause, step):
    assert one_shot.parse(answer) == {"root_cause": cause, "first_step": step, "problems": []}


@pytest.mark.parametrize("answer,cause", [
    ('{"root_cause": "config_missing"}', "config_missing"),
    ('{"root_cause": "config_missing", "first_step": null}', "config_missing"),
    ('{"root_cause": "config_missing", "first_step": "  "}', "config_missing"),
    ('{"root_cause": "config_missing", "first_step": ["a"]}', "config_missing"),
    ('{"root_cause": "network", "first_step": "Retry."}', None),
    ('{"root_cause": null, "first_step": "Retry."}', None),
])
def test_an_incomplete_answer_is_not_a_complete_one(answer, cause):
    parsed = one_shot.parse(answer)
    assert parsed["root_cause"] == cause
    assert parsed["problems"]
    if cause:
        assert parsed["first_step"] is None


@pytest.mark.parametrize("answer", [
    'The cause is: {"root_cause": "code_defect", "first_step": "Fix it."}',
    '{"root_cause": "code_defect", "first_step": "a"} {"root_cause": "local_module", "first_step": "b"}',
    '["code_defect"]',
    "",
    '```json\n{"root_cause": "code_defect", "first_step": "a"}\n```\n```json\n{"root_cause": "x"}\n```',
])
def test_anything_but_one_json_object_is_not_an_answer(answer):
    assert one_shot.parse(answer) == {"root_cause": None, "first_step": None, "problems": ["not one JSON object"]}


def test_malformed_responses_are_recorded_and_the_run_continues(tmp_path, monkeypatch):
    good = {"choices": [{"message": {"content": '{"root_cause": "missing_dependency", "first_step": "Install it."}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    replies = [
        {"choices": []},
        {"choices": [{"message": None}]},
        {"choices": [{}]},
        {"choices": [{"message": {"content": None}}]},
        ["not", "a", "completion"],
        urllib.error.URLError("connection refused"),
        {"choices": [{"message": {"content": ""}}]},
        good,
    ]

    def fake_ask(model, messages, seed):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(one_shot, "ask", fake_ask)
    ids = [json.loads(line)["case_id"] for line in (DIAGNOSIS / "cases.jsonl").read_text().splitlines()
           if json.loads(line)["label"] == "missing_dependency"][:8]
    output = tmp_path / "run"
    assert one_shot.main([str(DIAGNOSIS), "--models", "fake", "--output", str(output), "--cases", *ids]) == 0
    rows = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    assert [r["error_kind"] for r in rows] == ["bad_response"] * 5 + ["request_failed", None, None]
    assert rows[6]["prediction"] is None and rows[6]["answer_problems"] == ["not one JSON object"]
    assert (rows[7]["prediction"], rows[7]["first_step"], rows[7]["prompt_tokens"]) == (
        "missing_dependency", "Install it.", 10)
    summary = json.loads((output / "summary.json").read_text())["models"]["fake"]
    assert (summary["n"], summary["complete_answers"], summary["invalid_answers"]) == (8, 1, 1)
    assert (summary["bad_responses"], summary["failed_requests"], summary["accuracy"]) == (5, 1, 0.125)


def test_a_response_that_is_not_json_is_a_bad_response(monkeypatch):
    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"<html>busy</html>"

    monkeypatch.setattr(one_shot.urllib.request, "urlopen", lambda request, timeout: Reply())
    with pytest.raises(one_shot.BadResponse, match="not JSON"):
        one_shot.ask("m", [], 1)


def test_the_median_of_an_even_number_of_answers_is_the_mean_of_the_middle_two():
    rows = [{"model": "m", "label": "code_defect", "prediction": "code_defect", "first_step": "x",
             "error_kind": None, "response": "{}", "seconds": s} for s in (1.0, 1.3, 1.36, 9.0)]
    assert one_shot.score(rows)["m"]["median_seconds"] == 1.33


def test_the_saved_trial_is_rescored_from_its_answers(tmp_path):
    copy = tmp_path / "trial"
    shutil.copytree(TRIAL, copy)
    before = (copy / "results.jsonl").read_bytes()
    assert one_shot.main(["--rescore", str(copy)]) == 0
    summary = json.loads((copy / "summary.json").read_text())
    assert summary["rescored"]["answers_read_differently"] == []
    medians = {model: result["median_seconds"] for model, result in summary["models"].items()}
    assert medians == {"Qwen3.6-35B-A3B-6bit": 1.33, "gemma-4-26B-A4B-it-qat-4bit": 1.46}
    assert (copy / "results.jsonl").read_bytes() == before
