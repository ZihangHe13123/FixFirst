"""All requests use stubs; no model process or server is needed."""

import hashlib
import json
from pathlib import Path
import sys
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/diagnosis_baseline"))
import real_baseline as baseline  # noqa: E402


def inputs(tmp_path):
    directory = tmp_path / "inputs"
    directory.mkdir()
    rows = []
    for name, status in [("case-healthy", 0), ("case-fault", 1)]:
        evidence = {"protocol": "b3-real-evidence-v1", "goal": "pass_tests",
                    "runs": [{"tool": "pytest_run", "exit_code": status,
                              "records": [{"type": "finish", "exit_code": status}]}],
                    "environment": {}, "project": {}, "truncation": []}
        rows.append({"case_id": name, "evidence": evidence,
                     "evidence_sha256": baseline.digest(baseline.canonical(evidence)),
                     "source_sha256": "0" * 64})
    data = b"".join(baseline.canonical(row) + b"\n" for row in rows)
    manifest = {"schema_version": 1, "protocol": "b3-real-evidence-v1",
                "cases_file": "cases.jsonl", "cases_sha256": baseline.digest(data),
                "case_ids": [row["case_id"] for row in rows]}
    (directory / "cases.jsonl").write_bytes(data)
    (directory / "manifest.json").write_bytes(baseline.canonical(manifest))
    return directory


def reply(cause="healthy", step="No fix is needed in this scope."):
    return {"choices": [{"message": {"content": json.dumps({
        "root_cause": cause, "first_step": step})}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def test_requests_have_same_bounded_evidence_without_labels_or_case_ids(tmp_path, monkeypatch):
    calls = []

    def ask(model, messages, seed):
        calls.append((model, messages, seed))
        return reply()

    monkeypatch.setattr(baseline.one_shot, "ask", ask)
    source, output = inputs(tmp_path), tmp_path / "answers"
    baseline.run(source, ["model-a", "model-b"], output)
    assert len(calls) == 4
    for index in range(2):
        assert calls[index][1] == calls[index + 2][1]
        assert calls[index][2] == 20260929
        assert "case-" not in json.dumps(calls[index][1])
        assert len(calls[index][1]) == 2
    manifest, rows = baseline.load_sealed_answers(output)
    assert manifest["case_ids"] == ["case-healthy", "case-fault"]
    assert len(rows) == 4 and all(row["answer_status"] == "ok" for row in rows)
    assert rows[0]["usage"]["prompt_tokens"] == 10
    config = json.loads((output / "config.json").read_text())
    assert config["protocol"]["decoding"] == {"temperature": 0, "top_p": 1, "max_tokens": 1024}
    assert config["protocol"]["thinking"] is False
    assert (output / "input-cases.jsonl").read_bytes() == (source / "cases.jsonl").read_bytes()


@pytest.mark.parametrize("value,expected", [
    ({"choices": []}, "invalid"),
    ({"choices": [{"message": {"content": ""}}]}, "invalid"),
    ({"choices": [{"message": {"content": "not JSON"}}]}, "invalid"),
    ({"choices": [{"message": {"content": '{"root_cause":"healthy"}'}}]}, "invalid"),
    ({"x": float("nan")}, "invalid"),
    (urllib.error.URLError("offline"), "request_error"),
    (TimeoutError("timed out"), "request_error"),
    (baseline.one_shot.BadResponse("non-JSON response"), "invalid"),
])
def test_failed_and_invalid_answers_remain_without_retry(tmp_path, monkeypatch, value, expected):
    calls = []

    def ask(*args):
        calls.append(args)
        if len(calls) == 1:
            if isinstance(value, Exception):
                raise value
            return value
        return reply()

    monkeypatch.setattr(baseline.one_shot, "ask", ask)
    output = tmp_path / "answers"
    baseline.run(inputs(tmp_path), ["fake"], output)
    _, rows = baseline.load_sealed_answers(output)
    assert len(calls) == 2
    assert [r["answer_status"] for r in rows] == [expected, "ok"]
    assert rows[0]["error"]


def test_interruption_leaves_unsealed_answers_not_exportable(tmp_path, monkeypatch):
    def ask(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(baseline.one_shot, "ask", ask)
    output = tmp_path / "answers"
    with pytest.raises(KeyboardInterrupt):
        baseline.run(inputs(tmp_path), ["fake"], output)
    assert not (output / "SEALED.json").exists()
    with pytest.raises(OSError):
        baseline.load_sealed_answers(output)


def reseal(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    for key, filename in [("results_sha256", "results.jsonl"), ("config_sha256", "config.json")]:
        manifest[key] = baseline.digest((directory / filename).read_bytes())
    (directory / "manifest.json").write_bytes(baseline.canonical(manifest))
    (directory / "SEALED.json").write_bytes(baseline.canonical({
        "manifest_sha256": baseline.digest((directory / "manifest.json").read_bytes())}))


@pytest.mark.parametrize("change", ["duplicate", "missing", "input", "batch", "prediction", "status"])
def test_seal_also_validates_semantics_even_if_outer_hash_is_recomputed(tmp_path, monkeypatch, change):
    monkeypatch.setattr(baseline.one_shot, "ask", lambda *args: reply())
    output = tmp_path / "answers"
    baseline.run(inputs(tmp_path), ["fake"], output)
    rows = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    if change == "duplicate":
        rows.append(rows[0])
    elif change == "missing":
        rows.pop()
    elif change == "input":
        rows[0]["input_sha256"] = "0" * 64
    elif change == "batch":
        rows[0]["input_batch_sha256"] = "0" * 64
    elif change == "prediction":
        rows[0]["root_cause"] = "code_defect"
    elif change == "status":
        rows[0]["answer_status"] = "invalid"
    (output / "results.jsonl").write_bytes(b"".join(baseline.canonical(r) + b"\n" for r in rows))
    reseal(output)
    with pytest.raises(ValueError):
        baseline.load_sealed_answers(output)


def test_tampered_input_rejected_before_network_or_output(tmp_path, monkeypatch):
    source = inputs(tmp_path)
    (source / "cases.jsonl").write_text("{}\n")
    monkeypatch.setattr(baseline.one_shot, "ask", lambda *args: pytest.fail("must not call server"))
    with pytest.raises(ValueError):
        baseline.run(source, ["fake"], tmp_path / "answers")
    assert not (tmp_path / "answers").exists()


def test_existing_output_and_duplicate_models_do_not_request_or_overwrite(tmp_path, monkeypatch):
    source = inputs(tmp_path)
    output = tmp_path / "answers"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_text("keep")
    monkeypatch.setattr(baseline.one_shot, "ask", lambda *args: pytest.fail("must not call server"))
    with pytest.raises(FileExistsError):
        baseline.run(source, ["fake"], output)
    with pytest.raises(ValueError):
        baseline.run(source, ["fake", "fake"], tmp_path / "other")
    assert sentinel.read_text() == "keep"


@pytest.mark.parametrize("nested", [False, True])
def test_case_metadata_and_labels_not_allowed_in_prepared_rows(tmp_path, nested):
    source = inputs(tmp_path)
    rows = [json.loads(line) for line in (source / "cases.jsonl").read_text().splitlines()]
    if nested:
        rows[0]["evidence"]["label"] = "SYNTHETIC_REFERENCE_LABEL"
        rows[0]["evidence_sha256"] = baseline.digest(baseline.canonical(rows[0]["evidence"]))
    else:
        rows[0]["label"] = "healthy"
    data = b"".join(baseline.canonical(row) + b"\n" for row in rows)
    (source / "cases.jsonl").write_bytes(data)
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["cases_sha256"] = hashlib.sha256(data).hexdigest()
    (source / "manifest.json").write_bytes(baseline.canonical(manifest))
    with pytest.raises(ValueError):
        baseline.load_input_bundle(source)


def test_healthy_protocol_does_not_change_legacy_five_class_parser():
    text = '{"root_cause":"healthy","first_step":"No fix needed."}'
    assert not baseline.parse(text)["problems"]
    assert baseline.one_shot.parse(text)["problems"]
    assert baseline.parse('{"root_cause":"healthy","root_cause":"code_defect","first_step":"x"}')["problems"]


def test_saved_raw_session_to_sealed_answers_to_unscored_sheets(tmp_path, monkeypatch):
    import csv
    import blind_scores
    import real_evidence
    from test_real_evidence import saved_session, write_inputs

    mapping, sessions, source = write_inputs(tmp_path, saved_session(healthy=True))
    original = source.read_bytes()
    prepared = tmp_path / "prepared"
    real_evidence.prepare(mapping, sessions, prepared)
    sent = []

    def ask(model, messages, seed):
        sent.append(messages)
        return reply()

    monkeypatch.setattr(baseline.one_shot, "ask", ask)
    answers = tmp_path / "answers"
    manifest = baseline.run(prepared, ["first-model", "second-model"], answers)
    assert sent[0] == sent[1]
    assert "SENTINEL" not in json.dumps(sent)
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"input_batch_sha256": manifest["input_batch_sha256"],
                                  "cases": [{"id": "case-private-label", "root_cause": "healthy",
                                             "first_step": "No fix in this scope."}]}))
    report = blind_scores.export_scores(answers, labels, tmp_path / "sheets", tmp_path / "key.json")
    assert len(report["sheets"]) == 4
    for name in report["sheets"]:
        with (tmp_path / "sheets" / name).open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 1 and rows[0]["id"] == "case-private-label"
        assert rows[0]["answer_status"] == "ok" and rows[0]["score"] == ""
    assert source.read_bytes() == original
