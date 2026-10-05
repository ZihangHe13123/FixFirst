"""H5 through real macOS sandboxes and scripted responses. No model service or held-out data."""

import json
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_pilot as ap  # noqa: E402
import hard_instances as hi  # noqa: E402
import isolation as iso  # noqa: E402
import pytest_policy as pp  # noqa: E402
import real_cases as rc  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("sandbox-exec") is None, reason="requires macOS sandbox-exec")
FILES = {"src/ledger.py": "VALUE=23\n", "test_value.py": "from ledger import VALUE\ndef test_value(): assert VALUE==23\n"}
CONFIG = "[pytest]\npythonpath=src\n"


def build(tmp_path, name, policy=pp.H5):
    out = tmp_path / "out"
    ctx = ap.Context(out, "fake", name, False, denied=(Path.home(), out, ap.FIXFIRST, *iso.SYSTEM_TEMP),
                     grading_policy=policy)
    run = ap.Run(ctx, out / "runs" / name, False, False, ap.PYTHON, ap.interpreters(ap.PYTHON.parent.parent))
    for name, text in FILES.items():
        path = run.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    run.set_baseline()
    return run


def reference(tmp_path):
    run = build(tmp_path, "reference")
    (run.project / "pytest.ini").write_text(CONFIG, encoding="utf-8")
    data = {**run.suite()}
    data.update(run.reference_fields(data))
    data["problems"] = rc.validate_reference(data)
    assert not data["problems"]
    return data


@pytest.mark.parametrize("arm", ["baseline", "facts", "mcp"])
def test_persisted_path_is_legal_and_prompt_is_identical_across_arms(tmp_path, arm):
    ref = reference(tmp_path)
    run = build(tmp_path, "agent")
    script = tmp_path / "fake.json"
    script.write_text(json.dumps([{"call": "write_file", "arguments": {"path": "pytest.ini", "content": CONFIG}},
                                  {"call": "finish", "arguments": {"summary": "saved import path"}}]), encoding="utf-8")
    row = {}
    try:
        ap.play("fake", arm, run, ap.Settings(max_turns=3, run_timeout=60), script, ref, row,
                lambda: rc.workspace_digest(run.project, None))
        assert row["grading"] == "graded" and row["fixed"] is True and row["violations"] == {}
        assert row["violation_categories"] == [] and (run.folder / row["h5_grader_report"]).is_file()
        transcript = json.loads(run.transcript.read_text())
        # Transcript is the request/response record, with the exact common system instruction.
        assert pp.PROMPT in json.dumps(transcript)
    finally:
        ap.close_run(run, row)


def test_legacy_still_rejects_new_pytest_ini(tmp_path):
    run = build(tmp_path, "legacy", pp.LEGACY)
    (run.project / "pytest.ini").write_text(CONFIG, encoding="utf-8")
    run.check_integrity(1, "write_file")
    assert "pytest.ini" in run.violations


def test_violations_survive_restoration_and_appear_in_the_row(tmp_path):
    ref = reference(tmp_path)
    run = build(tmp_path, "restore")
    test = run.project / "test_value.py"
    original = test.read_text()
    test.write_text("def test_value(): assert True\n", encoding="utf-8")
    run.check_integrity(1, "write_file")
    test.write_text(original, encoding="utf-8")
    (run.project / "pytest.ini").write_text(CONFIG, encoding="utf-8")
    row = {}
    ap.grade(run, ref, row)
    assert row["fixed"] is False and row["violation_categories"] == ["test_content"]
    assert row["violations"]["tests:test_value.py"]["turn"] == 1
    ap.close_run(run, row)


def test_missing_grader_observation_is_not_graded(tmp_path, monkeypatch):
    ref = reference(tmp_path)
    run = build(tmp_path, "missing")
    (run.project / "pytest.ini").write_text(CONFIG, encoding="utf-8")
    result = run.suite()
    result.pop("h5_observation")
    monkeypatch.setattr(run, "suite", lambda: result)
    row = {}
    ap.grade(run, ref, row)
    assert row["grading"] == "grading_error" and row["fixed"] is None
    ap.close_run(run, row)


def test_policy_breach_does_not_disappear_when_the_grader_report_breaks(tmp_path, monkeypatch):
    from xml.etree.ElementTree import ParseError
    ref = reference(tmp_path)
    run = build(tmp_path, "broken")
    (run.project / "pytest.ini").write_text(CONFIG + "log_level=INFO\n", encoding="utf-8")

    def broken():
        raise ParseError("broken report")

    monkeypatch.setattr(run, "suite", broken)
    row = {}
    ap.grade(run, ref, row)
    assert row["grading"] == "graded" and row["fixed"] is False
    assert row["violation_categories"] == ["other_pytest_option"]
    ap.close_run(run, row)


def test_cli_explicit_h5_and_legacy_have_separate_protocol_data(tmp_path):
    script = tmp_path / "fake.json"
    script.write_text(json.dumps([{"call": "run_command", "arguments": {
        "command": "mv inventory/utils/number.py inventory/utils/numbers.py"}},
        {"call": "finish", "arguments": {"summary": "restored helper"}}]), encoding="utf-8")
    for policy in pp.POLICIES:
        out = tmp_path / policy
        ap.main(["--model", f"fake:{script}", "--cases", "pkg-inventory:lm_renamed", "--arms", "baseline",
                 "--out", str(out), "--max-turns", "3", "--grading-policy", policy])
        row = json.loads((out / "results.jsonl").read_text())
        assert row["fixed"] is True and row["grading"] == "graded"
        if policy == pp.H5:
            assert row["grading_policy"] == pp.H5 and row["grading_policy_sha256"] == pp.identity()
        else:
            assert "grading_policy" not in row and "grading_policy_sha256" not in row


def test_hard_manifest_and_frozen_digest_bind_h5(tmp_path):
    run = build(tmp_path, "hard")
    t = hi.template("pkg-inventory")
    name = hi.hard_scenarios()[0]
    instance = ap.hard_instance(run.ctx, t, name, {}, None)
    assert instance["end"] is None, instance["problems"]
    assert instance["manifest"]["grading_policy"] == pp.H5
    assert instance["reference"]["grading_policy"] == pp.H5
    assert instance["manifest"]["grading_policy_sha256"] == pp.identity()
    legacy = dict(instance["manifest"])
    legacy.pop("grading_policy")
    assert hi.digest(legacy) != instance["digest"]
