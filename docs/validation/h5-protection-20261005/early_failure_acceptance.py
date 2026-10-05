"""Count a real pytest 6.2.5 / py 1.10.0 startup failure on Python 3.12, with no model."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "experiments" / "agent_baseline"))
import agent_pilot as ap  # noqa: E402
import isolation as iso  # noqa: E402
import pytest_policy as pp  # noqa: E402
import real_cases as rc  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True, help="disposable environment with the old pytest and py")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    problem = ap.check_output_folder(out, pp.H5)
    if problem or out.exists():
        parser.error(problem or "output already exists")
    out.mkdir(parents=True)
    ctx = ap.Context(out, "scripted-startup-failure", "synthetic", False,
                     denied=(Path.home(), out, ap.FIXFIRST, *iso.SYSTEM_TEMP), grading_policy=pp.H5)

    def build(name, python):
        run = ap.Run(ctx, out / name, False, True, python, ap.interpreters(python.parent.parent))
        run.project.mkdir()
        (run.project / "test_value.py").write_text("def test_value(): assert True\n", encoding="utf-8")
        run.set_baseline()
        return run

    ref = build("reference", ap.PYTHON)
    data = ref.suite()
    data.update(ref.reference_fields(data))
    data["problems"] = rc.validate_reference(data)
    assert not data["problems"], data["problems"]
    candidate = build("candidate", args.python.absolute())
    script = out / "script.json"
    rc.write_json(script, [{"call": "finish", "arguments": {"summary": "scripted claim without repairing pytest"}}])
    row = {}
    try:
        ap.play(ctx.model, "baseline", candidate, ap.Settings(max_turns=1, run_timeout=60), script, data, row,
                lambda: rc.workspace_digest(candidate.project, None))
    finally:
        ap.close_run(candidate, row)
    suite = json.loads((candidate.folder / row["h5_grader_report"]).read_text())
    assert suite["exit_code"] == 1 and suite["summary"] == "AttributeError: __spec__", suite
    assert suite["h5_observation"]["started"] is True and suite["h5_observation"]["complete"] is False
    assert row["grading"] == "graded" and row["fixed"] is False and not row["violations"], row
    payload = {"synthetic": True, "language_model_started": False, "grading_policy_sha256": pp.identity(),
               "packages": rc.freeze(candidate.python), "row": row, "suite": suite}
    (out / "SUMMARY.json").write_text(ap.redact(json.dumps(payload, indent=2), out) + "\n", encoding="utf-8")
    print("Old pytest startup failure is graded false, not excluded as ungraded")


if __name__ == "__main__":
    main()
