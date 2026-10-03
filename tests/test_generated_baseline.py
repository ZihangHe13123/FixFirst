"""Only public saved data and fake responses; no model or source project runs."""

import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/diagnosis_baseline"))
import generated_baseline as g  # noqa: E402


def fixture_dataset(tmp_path, *, count=1):
    original = ROOT / "examples/diagnosis-dataset"
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    rows = [g.read_json(line) for line in (original / "cases.jsonl").read_bytes().splitlines()[:count]]
    (dataset / "cases.jsonl").write_bytes(b"".join(g.canonical(r) + b"\n" for r in rows))
    (dataset / "environment.json").write_bytes((original / "environment.json").read_bytes())
    return dataset


def rewrite_rows(dataset, edit):
    rows = [g.read_json(line) for line in (dataset / "cases.jsonl").read_bytes().splitlines()]
    edit(rows)
    (dataset / "cases.jsonl").write_bytes(b"".join(g.canonical(r) + b"\n" for r in rows))


def bundle(tmp_path, *, count=1):
    dataset = fixture_dataset(tmp_path, count=count)
    output, labels = tmp_path / "inputs", tmp_path / "truth.json"
    g.prepare({"diagnosis": dataset}, output, labels)
    return dataset, output, labels


def reply(text='{"root_cause":"missing_dependency","first_step":"Install the missing package."}'):
    return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2}}


def reseal(answers, rows):
    (answers / "results.jsonl").write_bytes(b"".join(g.canonical(r) + b"\n" for r in rows))
    m = g.read_json((answers / "manifest.json").read_bytes())
    m["results_sha256"] = g.digest((answers / "results.jsonl").read_bytes())
    (answers / "manifest.json").write_bytes(g.canonical(m) + b"\n")
    (answers / "SEALED.json").write_bytes(g.canonical({"manifest_sha256": g.digest((answers / "manifest.json").read_bytes())}))


def test_public_saved_datasets_restore_to_strict_raw_allowlist(tmp_path):
    output, labels = tmp_path / "inputs", tmp_path / "truth.json"
    manifest = g.prepare({s: ROOT / f"examples/{s}-dataset" for s in ("diagnosis", "hard")}, output, labels)
    _, cases = g.load_input_bundle(output)
    assert len(cases) == 245
    assert manifest["labels_sha256"] == g.digest(labels.read_bytes())
    assert all(len(p["cases"]) == n for p, n in zip(manifest["input_provenance"], [215, 30]))
    first = cases[0]["evidence"]
    assert any(p["requires"] for p in first["environment"]["packages"])
    assert any(r["type"] == "failure" for c in cases for run in c["evidence"]["runs"] for r in run["records"])
    assert first["project"]["environment_run_id"] == "run-1"
    assert g.SHARED_MARKER not in g.canonical(first).decode()
    assert "healthy" not in g.CAUSES
    assert len(g.CAUSES) == 5


def test_conclusions_and_identity_metadata_do_not_enter_requests(tmp_path):
    dataset = fixture_dataset(tmp_path)
    def add(rows):
        row = rows[0]
        row["knowledge_covered"] = "sentinel-knowledge"
        session = row["session"]
        session["history"] = [{"kind": "sentinel-history"}]
        session["facts"] = []
        session["actions"] = []
        for issue in session["issues"]:
            issue["title"] = "sentinel-conclusion"
        for run in session["runs"]:
            run["notes"] = ["sentinel-notes"]
        project = next(r for r in session["runs"] if r["tool"] == "project")
        snapshot = g.read_json(project["stdout"])
        snapshot["unknown_conclusion"] = "sentinel-derived"
        project["stdout"] = json.dumps(snapshot)
    rewrite_rows(dataset, add)
    g.prepare({"diagnosis": dataset}, tmp_path / "inputs", tmp_path / "truth")
    _, cases = g.load_input_bundle(tmp_path / "inputs")
    text = g.canonical(g.messages(cases[0])).decode()
    assert "sentinel-" not in text
    assert cases[0]["case_id"] not in text
    assert '"label"' not in text
    assert '"case_id"' not in text
    assert '"scenario"' not in text
    assert '"issues"' not in text


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(case_id="other"),
    lambda r: r["session"]["environment"].update({"$shared": "../outside.json"}),
    lambda r: r["session"]["runs"][0].update(stdout="arbitrary snapshot"),
    lambda r: r["session"]["runs"][-1].update(environment_id="wrong"),
    lambda r: r["session"]["runs"][-1].update(source="imported"),
    lambda r: r["session"]["runs"][-1].update(scope="tests:subset", targets=["test_x.py"]),
    lambda r: r["session"]["runs"][-1].update(tool="version_search"),
    lambda r: r["session"]["runs"][-1].update(stdout=r["case_id"]),
    lambda r: r["session"]["runs"][-1].update(stdout=r["scenario"]),
    lambda r: r["session"]["runs"][-1].update(stdout=r["label"]),
])
def test_preparation_rejects_bad_source_or_literal_answer_leak(tmp_path, mutation):
    dataset = fixture_dataset(tmp_path)
    rewrite_rows(dataset, lambda rows: mutation(rows[0]))
    with pytest.raises(ValueError):
        g.prepare({"diagnosis": dataset}, tmp_path / "inputs", tmp_path / "truth")
    assert not (tmp_path / "inputs").exists()


def test_shared_environment_changes_are_reloaded_and_bound(tmp_path):
    dataset = fixture_dataset(tmp_path)
    g.prepare({"diagnosis": dataset}, tmp_path / "before", tmp_path / "truth-before")
    environment = g.read_json((dataset / "environment.json").read_bytes())
    environment["packages"].append({"name": "sentinel-package", "version": "1", "requires": ["other>=2"]})
    (dataset / "environment.json").write_bytes(g.canonical(environment))
    g.prepare({"diagnosis": dataset}, tmp_path / "after", tmp_path / "truth-after")
    before, bc = g.load_input_bundle(tmp_path / "before")
    after, ac = g.load_input_bundle(tmp_path / "after")
    assert before["input_provenance"][0]["environment_sha256"] != after["input_provenance"][0]["environment_sha256"]
    assert bc[0]["evidence_sha256"] != ac[0]["evidence_sha256"]
    assert "sentinel-package" in g.canonical(ac).decode()


def test_labels_must_be_outside_input_and_outputs_cannot_be_overwritten(tmp_path):
    dataset = fixture_dataset(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        g.prepare({"diagnosis": dataset}, tmp_path / "inputs", tmp_path / "inputs/truth")
    g.prepare({"diagnosis": dataset}, tmp_path / "inputs", tmp_path / "truth")
    with pytest.raises(FileExistsError):
        g.prepare({"diagnosis": dataset}, tmp_path / "inputs", tmp_path / "other-truth")


def test_sender_reads_no_labels_and_calls_each_pair_once(tmp_path, monkeypatch):
    _, inputs, labels = bundle(tmp_path, count=2)
    labels.unlink()
    calls = []
    def ask(model, messages, seed):
        calls.append((model, messages, seed))
        return reply()
    monkeypatch.setattr(g.one_shot, "ask", ask)
    output = tmp_path / "answers"
    g.run(inputs, ["fake-a", "fake-b"], output)
    manifest, rows = g.load_sealed_answers(output)
    assert len(calls) == len(rows) == 4
    assert [c[0] for c in calls] == ["fake-a", "fake-a", "fake-b", "fake-b"]
    assert all(c[2] == g.SEED for c in calls)
    assert all(row["answer_status"] == "ok" for row in rows)
    assert all("case_id" not in g.canonical(c[1]).decode() for c in calls)
    assert manifest["protocol"] == g.PROTOCOL
    with pytest.raises(FileExistsError):
        g.run(inputs, ["fake-a"], output)
    assert len(calls) == 4


@pytest.mark.parametrize("text,status,root", [
    ('{"root_cause":"healthy","first_step":"No fix."}', "invalid", None),
    ('{"root_cause":"missing_dependency"}', "invalid", "missing_dependency"),
    ('{"root_cause":"missing_dependency","root_cause":"code_defect","first_step":"Inspect."}', "invalid", None),
    ('{"root_cause":"code_defect","first_step":"Inspect.","extra":NaN}', "invalid", None),
    ('not json', "invalid", None),
])
def test_five_class_parser_preserves_root_scoring_policy(tmp_path, monkeypatch, text, status, root):
    _, inputs, _ = bundle(tmp_path)
    monkeypatch.setattr(g.one_shot, "ask", lambda *a: reply(text))
    g.run(inputs, ["fake"], tmp_path / "answers")
    _, rows = g.load_sealed_answers(tmp_path / "answers")
    assert rows[0]["answer_status"] == status
    assert rows[0]["root_cause"] == root


def test_request_failure_is_recorded_once_without_retry(tmp_path, monkeypatch):
    _, inputs, _ = bundle(tmp_path)
    calls = []
    def fail(*a):
        calls.append(a)
        raise OSError("fake connection failure")
    monkeypatch.setattr(g.one_shot, "ask", fail)
    g.run(inputs, ["fake"], tmp_path / "answers")
    _, rows = g.load_sealed_answers(tmp_path / "answers")
    assert len(calls) == 1 and rows[0]["answer_status"] == "request_error"


def test_interruption_is_unsealed_and_cannot_resume(tmp_path, monkeypatch):
    _, inputs, _ = bundle(tmp_path)
    def interrupt(*a):
        raise KeyboardInterrupt
    monkeypatch.setattr(g.one_shot, "ask", interrupt)
    with pytest.raises(KeyboardInterrupt):
        g.run(inputs, ["fake"], tmp_path / "answers")
    assert not (tmp_path / "answers/SEALED.json").exists()
    with pytest.raises(FileNotFoundError):
        g.load_sealed_answers(tmp_path / "answers")
    with pytest.raises(FileExistsError):
        g.run(inputs, ["fake"], tmp_path / "answers")


@pytest.mark.parametrize("change", [
    lambda rows: rows.pop(),
    lambda rows: rows.append(copy.deepcopy(rows[0])),
    lambda rows: rows.reverse(),
    lambda rows: rows[0].update(root_cause="code_defect"),
    lambda rows: rows[0].update(input_sha256="0" * 64),
    lambda rows: rows[0].update(answer_status="request_error"),
    lambda rows: rows[0]["raw_completion"]["choices"][0]["message"].update(content="different completion"),
])
def test_rehashed_but_incoherent_results_are_rejected(tmp_path, monkeypatch, change):
    _, inputs, _ = bundle(tmp_path, count=2)
    monkeypatch.setattr(g.one_shot, "ask", lambda *a: reply())
    out = tmp_path / "answers"
    g.run(inputs, ["fake"], out)
    _, rows = g.load_sealed_answers(out)
    change(rows)
    reseal(out, rows)
    with pytest.raises(ValueError):
        g.load_sealed_answers(out)


def test_rehashed_unknown_evidence_fields_rejected_before_request(tmp_path, monkeypatch):
    _, inputs, _ = bundle(tmp_path)
    manifest, rows = g.load_input_bundle(inputs)
    rows[0]["evidence"]["environment"]["label"] = "code_defect"
    rows[0]["evidence_sha256"] = g.digest(g.canonical(rows[0]["evidence"]))
    cases_bytes = b"".join(g.canonical(r) + b"\n" for r in rows)
    manifest["cases_sha256"] = g.digest(cases_bytes)
    (inputs / "cases.jsonl").write_bytes(cases_bytes)
    (inputs / "manifest.json").write_bytes(g.canonical(manifest))
    monkeypatch.setattr(g.one_shot, "ask", lambda *a: pytest.fail("must reject before sending"))
    with pytest.raises(ValueError):
        g.run(inputs, ["fake"], tmp_path / "answers")
    assert not (tmp_path / "answers").exists()


@pytest.mark.parametrize("field", ["case_id", "scenario", "label"])
def test_identity_or_label_in_dynamic_project_key_is_rejected(tmp_path, field):
    dataset = fixture_dataset(tmp_path)
    def add(rows):
        row = rows[0]
        run = next(r for r in row["session"]["runs"] if r["tool"] == "project")
        project = g.read_json(run["stdout"])
        project["source_context"] = {"calls": {row[field]: ["value"]}}
        run["stdout"] = json.dumps(project)
    rewrite_rows(dataset, add)
    with pytest.raises(ValueError, match="leaked"):
        g.prepare({"diagnosis": dataset}, tmp_path / "inputs", tmp_path / "truth")
