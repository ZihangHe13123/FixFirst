"""Offline scoring: synthetic answers only, never load real model responses."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "diagnosis_baseline"))

import generated_baseline as baseline  # noqa: E402
import generated_scores as scoring  # noqa: E402


def label_manifest():
    cases = [{"case_id": f"d-{i}", "suite": "diagnosis", "label": label}
             for i, label in enumerate(baseline.CAUSES)]
    cases += [{"case_id": f"h-{i}", "suite": "hard", "label": label}
              for i, label in enumerate(["version_incompatibility"] * 25 + ["local_module"] * 5)]
    return {"schema_version": 1, "protocol": "b3-generated-labels-v1", "cases": cases,
            "supported_labels": {"diagnosis": list(baseline.CAUSES),
                                 "hard": list(scoring.HARD_SUPPORT)}}


def fake_row(case, *, model="fake", prediction=None, status="ok", step="Inspect the reported error."):
    return {"model": model, "case_id": case["case_id"], "root_cause": prediction or case["label"],
            "first_step": step, "answer_status": status}


def test_perfect_hard_has_two_class_one_and_fixed_five_point_four():
    cases = [case for case in label_manifest()["cases"] if case["suite"] == "hard"]
    result = scoring._metrics([fake_row(case) for case in cases],
                              {case["case_id"]: case["label"] for case in cases},
                              list(scoring.HARD_SUPPORT))
    assert result["n"] == result["correct"] == 30
    assert result["accuracy"] == result["macro_f1_registered_support"] == 1
    assert result["macro_f1_fixed_five"] == 0.4
    assert result["fixed_five_f1_perfect_prediction_ceiling"] == 0.4
    assert result["per_label"]["version_incompatibility"]["support"] == 25
    assert result["per_label"]["local_module"]["support"] == 5


def test_perfect_diagnosis_five_class_f1_is_one():
    cases = [case for case in label_manifest()["cases"] if case["suite"] == "diagnosis"]
    result = scoring._metrics([fake_row(case) for case in cases],
                              {case["case_id"]: case["label"] for case in cases},
                              list(baseline.CAUSES))
    assert result["macro_f1_fixed_five"] == result["accuracy"] == 1


def test_wrong_outside_support_prediction_cannot_change_hard_support():
    cases = [{"case_id": "v", "label": "version_incompatibility"},
             {"case_id": "l", "label": "local_module"}]
    result = scoring._metrics([fake_row(cases[0], prediction="code_defect"), fake_row(cases[1])],
                              {case["case_id"]: case["label"] for case in cases},
                              list(scoring.HARD_SUPPORT))
    assert result["accuracy"] == result["macro_f1_registered_support"] == 0.5
    assert result["macro_f1_fixed_five"] == 0.2
    assert result["registered_support"] == ["local_module", "version_incompatibility"]
    assert result["per_label"]["code_defect"]["fp"] == 1
    assert result["per_label"]["version_incompatibility"]["fn"] == 1


def test_missing_root_and_failed_request_stay_in_denominator():
    cases = label_manifest()["cases"][:5]
    rows = [fake_row(case) for case in cases]
    rows[0].update(root_cause=None, first_step=None, answer_status="request_error")
    rows[1].update(root_cause=None, answer_status="invalid")
    result = scoring._metrics(rows, {case["case_id"]: case["label"] for case in cases},
                              list(baseline.CAUSES))
    assert result["n"] == 5 and result["correct"] == 3
    assert result["accuracy"] == result["macro_f1_fixed_five"] == 0.6
    assert result["no_valid_root_cause"] == 2
    assert result["answer_status_counts"] == {"ok": 3, "invalid": 1, "request_error": 1}


def test_missing_first_step_is_not_automatic_root_failure_or_quality_judgment():
    case = {"case_id": "v", "label": "version_incompatibility"}
    result = scoring._metrics([fake_row(case, status="invalid", step=None)],
                              {"v": case["label"]}, [case["label"]])
    assert result["accuracy"] == 1
    assert result["root_cause_without_first_step"] == 1
    assert result["complete_answers"] == 0


@pytest.mark.parametrize("change", [
    lambda labels: labels["cases"].append(labels["cases"][0]),
    lambda labels: labels["cases"].pop(),
    lambda labels: labels["cases"].reverse(),
    lambda labels: labels["cases"][0].update(label="healthy"),
    lambda labels: labels["cases"][0].update(suite="real"),
    lambda labels: labels["cases"][0].update(recommended_root_cause="code_defect"),
    lambda labels: labels["supported_labels"].update(hard=list(baseline.CAUSES)),
    lambda labels: labels["supported_labels"]["hard"].reverse(),
    lambda labels: labels["supported_labels"].update(hard=[]),
    lambda labels: labels.update(protocol="real-labels"),
])
def test_label_manifest_rejects_unregistered_cases_classes_or_support(change):
    labels = label_manifest()
    ids = [case["case_id"] for case in labels["cases"]]
    change(labels)
    with pytest.raises(ValueError):
        scoring._labels(baseline.canonical(labels), ids)


def test_labels_accept_only_registered_injection_truth():
    labels = label_manifest()
    assert scoring._labels(baseline.canonical(labels),
                           [case["case_id"] for case in labels["cases"]]) == labels


def test_labels_never_opened_before_answer_seal_verification(tmp_path, monkeypatch):
    def reject(_):
        raise ValueError("missing model/case answers")

    monkeypatch.setattr(baseline, "load_sealed_answers", reject)
    missing = tmp_path / "labels-were-not-created.json"
    with pytest.raises(ValueError, match="missing model/case"):
        scoring.score(tmp_path, missing)


def _stub_batch(tmp_path, monkeypatch, labels=None):
    """Scoring-only fixture; separate integration tests exercise the real seal loader."""
    labels = labels or label_manifest()
    data = baseline.canonical(labels) + b"\n"
    labels_path = tmp_path / "labels.json"
    labels_path.write_bytes(data)
    (tmp_path / "input-manifest.json").write_bytes(baseline.canonical({
        "labels_sha256": baseline.digest(data)}))
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    manifest = {"case_ids": [case["case_id"] for case in labels["cases"]],
                "models": ["fake-a", "fake-b"], "input_batch_sha256": "a" * 64}
    rows = [fake_row(case, model=model) for model in manifest["models"] for case in labels["cases"]]
    monkeypatch.setattr(baseline, "load_sealed_answers", lambda _: (manifest, rows))
    return labels_path


def test_two_suites_and_models_reported_separately_without_first_step_grades(tmp_path, monkeypatch):
    labels_path = _stub_batch(tmp_path, monkeypatch)
    result = scoring.score(tmp_path, labels_path)
    assert set(result["suites"]) == {"diagnosis", "hard"}
    assert "combined_accuracy" not in result
    assert result["first_step_quality"]["status"] == "unscored"
    for model in ("fake-a", "fake-b"):
        assert result["suites"]["diagnosis"]["models"][model]["n"] == 5
        assert result["suites"]["hard"]["models"][model]["n"] == 30
        assert result["suites"]["hard"]["models"][model]["macro_f1_fixed_five"] == 0.4


def test_post_answer_label_change_rejected(tmp_path, monkeypatch):
    labels_path = _stub_batch(tmp_path, monkeypatch)
    labels = json.loads(labels_path.read_bytes())
    labels["cases"][0]["label"] = "code_defect"
    labels_path.write_bytes(baseline.canonical(labels))
    with pytest.raises(ValueError, match="pre-answer input registration"):
        scoring.score(tmp_path, labels_path)


def test_missing_labels_binding_rejected_before_open(tmp_path, monkeypatch):
    _stub_batch(tmp_path, monkeypatch)
    (tmp_path / "input-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="valid labels digest"):
        scoring.score(tmp_path, tmp_path / "missing-labels.json")


def test_output_cannot_overwrite_a_sealed_file(tmp_path, monkeypatch):
    labels_path = _stub_batch(tmp_path, monkeypatch)
    original = labels_path.read_bytes()
    with pytest.raises(SystemExit) as error:
        scoring.main([str(tmp_path), str(labels_path), "--output", str(labels_path)])
    assert error.value.code == 2
    assert labels_path.read_bytes() == original


@pytest.fixture
def sealed_fake_batch(tmp_path, monkeypatch):
    """Reuse public input shapes, but every completion is a deterministic local fake."""
    datasets = {}
    selected_cases = []
    for suite, filename in (("diagnosis", "diagnosis-dataset"), ("hard", "hard-dataset")):
        source = ROOT / "examples" / filename
        selected, seen = [], set()
        for line in (source / "cases.jsonl").read_bytes().splitlines():
            row = baseline.read_json(line)
            if row["label"] not in seen:
                selected.append(row)
                seen.add(row["label"])
        directory = tmp_path / suite
        directory.mkdir()
        (directory / "environment.json").write_bytes((source / "environment.json").read_bytes())
        (directory / "cases.jsonl").write_bytes(b"".join(baseline.canonical(row) + b"\n"
                                                       for row in selected))
        selected_cases.extend(selected)
        datasets[suite] = directory
    inputs, answers, labels = tmp_path / "inputs", tmp_path / "answers", tmp_path / "gold.json"
    baseline.prepare(datasets, inputs, labels)
    calls = []

    def fake_ask(model, messages, seed):
        case = selected_cases[len(calls) % len(selected_cases)]
        calls.append((model, messages, seed))
        return {"choices": [{"message": {"content": json.dumps({
            "root_cause": case["label"], "first_step": "Synthetic fixture response."})}}]}

    monkeypatch.setattr(baseline.one_shot, "ask", fake_ask)
    baseline.run(inputs, ["fake-a", "fake-b"], answers)
    assert len(calls) == 14
    return answers, labels


def _rewrite_results_with_seal(answers, mutate):
    """Repair outer checksums so malformed pair/content tests reach structural checks."""
    rows = [baseline.read_json(line) for line in (answers / "results.jsonl").read_bytes().splitlines()]
    mutate(rows)
    results = b"".join(baseline.canonical(row) + b"\n" for row in rows)
    (answers / "results.jsonl").write_bytes(results)
    manifest = baseline.read_json((answers / "manifest.json").read_bytes())
    manifest["results_sha256"] = baseline.digest(results)
    data = baseline.canonical(manifest) + b"\n"
    (answers / "manifest.json").write_bytes(data)
    (answers / "SEALED.json").write_bytes(baseline.canonical({
        "manifest_sha256": baseline.digest(data)}) + b"\n")


def test_real_seal_roundtrip_uses_all_registered_model_case_pairs(sealed_fake_batch):
    answers, labels = sealed_fake_batch
    result = scoring.score(answers, labels)
    for suite in scoring.SUITES:
        for model in ("fake-a", "fake-b"):
            assert result["suites"][suite]["models"][model]["accuracy"] == 1
    assert result["suites"]["hard"]["models"]["fake-a"]["macro_f1_fixed_five"] == 0.4


@pytest.mark.parametrize("mutation", [
    lambda rows: rows.pop(),
    lambda rows: rows.append(rows[0]),
    lambda rows: rows[0].update(model="unregistered-model"),
    lambda rows: rows[0].update(case_id="unregistered-case"),
    lambda rows: rows[0].update(input_sha256="0" * 64),
    lambda rows: rows[0].update(input_batch_sha256="0" * 64),
    lambda rows: rows[0].update(root_cause="healthy"),
    lambda rows: rows[0].update(answer_status="request_error"),
])
def test_pair_or_input_damage_rejected_before_reading_labels(sealed_fake_batch, mutation):
    answers, labels = sealed_fake_batch
    _rewrite_results_with_seal(answers, mutation)
    labels.unlink()
    with pytest.raises(ValueError):
        scoring.score(answers, labels)


def test_incomplete_answer_directory_rejects_without_opening_labels(sealed_fake_batch):
    answers, labels = sealed_fake_batch
    (answers / "SEALED.json").unlink()
    labels.unlink()
    with pytest.raises(FileNotFoundError) as error:
        scoring.score(answers, labels)
    assert "SEALED.json" in str(error.value)


def test_changed_input_snapshot_rejected_before_labels(sealed_fake_batch):
    answers, labels = sealed_fake_batch
    with (answers / "input-cases.jsonl").open("ab") as stream:
        stream.write(b"\n")
    labels.unlink()
    with pytest.raises(ValueError):
        scoring.score(answers, labels)
