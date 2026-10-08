"""Synthetic records only: sealed-answer ordering, model blinding and human-only scores."""

import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "diagnosis_baseline"))
sys.path.insert(0, str(ROOT / "scripts"))

import blind_scores  # noqa: E402
import heldout  # noqa: E402
import real_baseline  # noqa: E402


@pytest.fixture
def sealed(monkeypatch):
    manifest = {
        "schema_version": 1, "protocol": "b3-real-answers-v1",
        "input_batch_sha256": "a" * 64, "case_ids": ["sample-two", "sample-one"],
        "models": ["private-model-alpha", "private-model-beta", "private-model-gamma"],
        "results_file": "results.jsonl", "results_sha256": "b" * 64,
        "protocol_sha256": "c" * 64,
    }
    rows = [
        {
            "case_id": case_id, "model": model, "input_sha256": "d" * 64,
            "answer_status": "ok", "raw_response": f"MODEL-IDENTITY {model}",
            "root_cause": "healthy", "first_step": "无需修复，保留当前检查范围。",
            "error": None, "latency_s": 0.01, "usage": {},
        }
        for model in manifest["models"] for case_id in manifest["case_ids"]
    ]
    rows[2].update(answer_status="invalid", root_cause="code_defect", first_step=None)
    rows[5].update(answer_status="request_error", root_cause=None, first_step=None,
                   error="Failed at private-model-gamma endpoint")
    monkeypatch.setattr(blind_scores, "load_sealed_answers", lambda path: (manifest, rows))
    monkeypatch.setattr(blind_scores.secrets, "SystemRandom",
                        lambda: SimpleNamespace(shuffle=lambda values: values.reverse()))
    return manifest, rows


def labels_rows():
    return [
        {"id": "sample-one", "root_cause": "missing_dependency", "first_step": "Install demo",
         "also_acceptable": "Install declared dependencies", "partial_if": "Only identify demo",
         "wrong_if": "Change unrelated source"},
        {"id": "sample-two", "root_cause": "healthy", "first_step": "No change, keep scope\n继续检查",
         "also_acceptable": "", "partial_if": "", "wrong_if": ""},
    ]


def write_labels(path, rows=None, kind="csv", batch=None):
    rows = labels_rows() if rows is None else rows
    if kind == "csv":
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    else:
        data = rows if kind == "list" else {"cases": rows}
        if batch is not None:
            data["input_batch_sha256"] = batch
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def read_sheet(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize("kind", ["csv", "list", "object"])
def test_export_preserves_ids_statuses_and_blank_human_scores(sealed, tmp_path, kind):
    manifest, _ = sealed
    labels = write_labels(tmp_path / ("labels.csv" if kind == "csv" else "labels.json"), kind=kind)
    output, mapping_path = tmp_path / "sheets", tmp_path / "private" / "mapping.json"
    report = blind_scores.export_scores(tmp_path / "answers", labels, output, mapping_path)
    mapping = json.loads(mapping_path.read_text())
    assert mapping["model_mapping"] == {
        "model-1": "private-model-gamma", "model-2": "private-model-beta",
        "model-3": "private-model-alpha",
    }
    assert mapping["input_batch_sha256"] == manifest["input_batch_sha256"]
    assert len(report["sheets"]) == 6
    assert not mapping_path.is_relative_to(output)
    for name, digest in report["sheets"].items():
        data = (output / name).read_bytes()
        assert data.startswith(b"\xef\xbb\xbf")
        assert hashlib.sha256(data).hexdigest() == digest
        sheet = read_sheet(output / name)
        assert [r["id"] for r in sheet] == manifest["case_ids"]
        assert sheet[0]["label_first_step"] == "No change, keep scope\n继续检查"
        for row in sheet:
            assert row["score"] == row["scored_by"] == row["notes"] == ""
            if row["answer_status"] != "ok":
                assert row["model_root_cause"] == row["model_first_step"] == ""
        assert (output / name.replace("-A.csv", "-C.csv")).read_bytes() == data
    assert read_sheet(output / "model-1-A.csv")[1]["answer_status"] == "request_error"
    assert read_sheet(output / "model-2-A.csv")[0]["answer_status"] == "invalid"
    public = "\n".join(path.read_text(encoding="utf-8-sig") for path in output.iterdir())
    assert "MODEL-IDENTITY" not in public
    assert "endpoint" not in public
    assert all(model not in public for model in manifest["models"])
    assert "model_mapping" not in public


def test_labels_are_not_read_until_seal_validation_succeeds(tmp_path, monkeypatch):
    def reject(_):
        raise ValueError("unsealed or mixed answer batch")
    monkeypatch.setattr(blind_scores, "load_sealed_answers", reject)
    monkeypatch.setattr(blind_scores, "read_labels",
                        lambda *args: pytest.fail("Labels were read before validation"))
    with pytest.raises(ValueError, match="unsealed or mixed"):
        blind_scores.export_scores(tmp_path / "answers", tmp_path / "secret-labels.json",
                                   tmp_path / "sheets", tmp_path / "mapping.json")
    assert not (tmp_path / "sheets").exists()
    assert not (tmp_path / "mapping.json").exists()


@pytest.mark.parametrize("problem", [
    "duplicate", "missing", "extra", "unknown", "empty_step", "empty_healthy_step", "bad_type",
])
def test_bad_labels_are_rejected_without_outputs(sealed, tmp_path, problem):
    rows = labels_rows()
    if problem == "duplicate":
        rows.append(rows[0].copy())
    elif problem == "missing":
        rows.pop()
    elif problem == "extra":
        rows.append({**rows[0], "id": "other-batch"})
    elif problem == "unknown":
        rows[0]["root_cause"] = "not-a-cause"
    elif problem == "empty_step":
        rows[0]["first_step"] = " "
    elif problem == "empty_healthy_step":
        rows[1]["first_step"] = " "
    else:
        rows[0]["partial_if"] = ["not text"]
    labels = write_labels(tmp_path / "labels.json", rows, kind="list")
    with pytest.raises(ValueError):
        blind_scores.export_scores(tmp_path / "answers", labels, tmp_path / "sheets",
                                   tmp_path / "mapping.json")
    assert not (tmp_path / "sheets").exists()
    assert not (tmp_path / "mapping.json").exists()


@pytest.mark.parametrize("where", ["envelope", "row"])
def test_labels_from_another_identified_batch_are_rejected(sealed, tmp_path, where):
    rows = labels_rows()
    if where == "row":
        rows[0]["input_batch_sha256"] = "e" * 64
    labels = write_labels(tmp_path / "labels.json", rows, kind="object",
                          batch="e" * 64 if where == "envelope" else None)
    with pytest.raises(ValueError, match="input_batch_sha256"):
        blind_scores.export_scores(tmp_path / "answers", labels, tmp_path / "sheets",
                                   tmp_path / "mapping.json")


def test_csv_duplicate_ids_are_rejected(sealed, tmp_path):
    labels = write_labels(tmp_path / "labels.csv", [labels_rows()[0]] * 2)
    with pytest.raises(ValueError, match="Duplicate label id"):
        blind_scores.export_scores(tmp_path / "answers", labels, tmp_path / "sheets",
                                   tmp_path / "mapping.json")


@pytest.mark.parametrize("location", ["inside", "same", "symlink_inside"])
def test_mapping_must_be_outside_scoring_directory(sealed, tmp_path, location):
    output = tmp_path / "sheets"
    if location == "inside":
        mapping = output / "mapping.json"
    elif location == "same":
        mapping = output
    else:
        (tmp_path / "shortcut").symlink_to(output, target_is_directory=True)
        mapping = tmp_path / "shortcut" / "mapping.json"
    with pytest.raises(ValueError, match="outside"):
        blind_scores.export_scores(tmp_path / "answers", tmp_path / "labels.csv", output, mapping)
    assert not output.exists()


@pytest.mark.parametrize("existing", ["scores", "mapping"])
def test_existing_work_is_never_overwritten(sealed, tmp_path, existing):
    output, mapping = tmp_path / "sheets", tmp_path / "mapping.json"
    if existing == "scores":
        output.mkdir()
        kept = output / "human-scores.csv"
    else:
        kept = mapping
    kept.write_text("preserve existing work")
    with pytest.raises(ValueError, match="already exists"):
        blind_scores.export_scores(tmp_path / "answers", tmp_path / "labels.csv", output, mapping)
    assert kept.read_text() == "preserve existing work"


def test_scoring_sheets_remain_compatible_with_heldout_tools(sealed, tmp_path, capsys):
    labels = write_labels(tmp_path / "labels.csv")
    output = tmp_path / "sheets"
    assert blind_scores.main([str(tmp_path / "answers"), str(labels), str(output),
                              str(tmp_path / "mapping.json")]) == 0
    first, second = output / "model-1-A.csv", output / "model-1-C.csv"
    assert heldout.summary(SimpleNamespace(scores=first)) == 1  # Still unscored.
    for path in (first, second):
        rows = read_sheet(path)
        for row in rows:
            row.update(score="partial", scored_by="synthetic reviewer")
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=blind_scores.SHEET_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    assert heldout.summary(SimpleNamespace(scores=first)) == 0
    assert heldout.agree(SimpleNamespace(first=first, second=second, column="score")) == 0
    report = capsys.readouterr().out
    assert "Partial 2" in report and "Same score: 2 of 2" in report


def test_synthetic_bundle_through_runner_and_sealed_export(tmp_path, monkeypatch):
    """Only the network ask is replaced: preparation bytes, seals and export are real."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    cases = []
    for case_id, exit_code, stdout in [
        ("sample-two", 0, "1 passed"), ("sample-one", 2, "No module named demo"),
    ]:
        evidence = {"protocol": "b3-real-evidence-v1", "goal": "pass_tests", "runs": [{
            "tool": "pytest_run", "scope": "tests:project", "status": "completed",
            "exit_code": exit_code, "stdout": stdout, "stderr": "", "records": [],
        }], "environment": {"python_version": "3.12.0"},
            "project": {"python_files": ["test_demo.py"]}, "truncation": []}
        cases.append({"case_id": case_id, "evidence": evidence,
                      "evidence_sha256": real_baseline.digest(real_baseline.canonical(evidence)),
                      "source_sha256": "d" * 64})
    case_bytes = b"".join(real_baseline.canonical(case) + b"\n" for case in cases)
    (inputs / "cases.jsonl").write_bytes(case_bytes)
    (inputs / "manifest.json").write_bytes(real_baseline.canonical({
        "schema_version": 1, "protocol": "b3-real-evidence-v1", "cases_file": "cases.jsonl",
        "cases_sha256": real_baseline.digest(case_bytes), "case_ids": [c["case_id"] for c in cases],
    }))
    models = ["synthetic-empty", "synthetic-no-step", "synthetic-timeout"]
    calls = []

    def ask(model, messages, seed):
        calls.append((model, messages, seed))
        evidence = json.loads(messages[1]["content"])
        if evidence["runs"][0]["exit_code"] == 0:
            text = json.dumps({"root_cause": "healthy", "first_step": "No fix within this scope."})
        elif model == "synthetic-empty":
            text = ""
        elif model == "synthetic-no-step":
            text = '{"root_cause":"missing_dependency"}'
        else:
            raise TimeoutError("SYNTHETIC_PRIVATE_ENDPOINT")
        return {"model": model, "choices": [{"message": {"content": text}}],
                "usage": {"prompt_tokens": 30, "completion_tokens": 8}}

    monkeypatch.setattr(real_baseline.one_shot, "ask", ask)
    answers = tmp_path / "answers"
    answer_manifest = real_baseline.run(inputs, models, answers)
    loaded_manifest, answers_rows = real_baseline.load_sealed_answers(answers)
    assert loaded_manifest == answer_manifest
    assert len(answers_rows) == len(calls) == 6
    assert {r["answer_status"] for r in answers_rows} == {"ok", "invalid", "request_error"}
    # Labels are introduced only after all calls and answer sealing have completed.
    labels = labels_rows()
    labels[0]["first_step"] = "PRIVATE_REFERENCE_STEP"
    label_path = write_labels(tmp_path / "labels.json", labels, kind="object",
                              batch=answer_manifest["input_batch_sha256"])
    output, mapping_path = tmp_path / "sheets", tmp_path / "private-key.json"
    report = blind_scores.export_scores(answers, label_path, output, mapping_path)
    assert report["answers_sha256"] == answer_manifest["results_sha256"]
    mapping = json.loads(mapping_path.read_text())["model_mapping"]
    for alias, model in mapping.items():
        for scorer in ("A", "C"):
            rows = read_sheet(output / f"{alias}-{scorer}.csv")
            assert [row["id"] for row in rows] == ["sample-two", "sample-one"]
            assert rows[0]["answer_status"] == "ok"
            assert rows[0]["model_root_cause"] == "healthy"
            assert rows[0]["model_first_step"] == "No fix within this scope."
            assert rows[1]["answer_status"] == (
                "request_error" if model == "synthetic-timeout" else "invalid")
            assert rows[1]["model_root_cause"] == rows[1]["model_first_step"] == ""
            assert rows[1]["label_first_step"] == "PRIVATE_REFERENCE_STEP"
            assert all(row[field] == "" for row in rows for field in ("score", "scored_by", "notes"))
    for _, messages, seed in calls:
        assert seed == real_baseline.SEED
        assert "PRIVATE_REFERENCE_STEP" not in str(messages)
        assert all(case["case_id"] not in str(messages) for case in cases)
    public = "\n".join(path.read_text(encoding="utf-8-sig") for path in output.iterdir())
    assert "SYNTHETIC_PRIVATE_ENDPOINT" not in public
    assert all(model not in public for model in models)
