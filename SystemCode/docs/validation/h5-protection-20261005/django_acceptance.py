"""Synthetic H5/Django sandbox acceptance with scripted replies, not a language model.

Run with FixFirst's dev interpreter; --python names a separate environment containing
Django, pytest-django and pytest. --out must be a new directory outside the repository.
"""

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

FILES = {"fixture_settings.py": "SECRET_KEY='synthetic-h5'\nINSTALLED_APPS=[]\n",
         "test_config.py": "from django.conf import settings\n"
                           "def test_config(): assert settings.SECRET_KEY=='synthetic-h5'\n"}
CONFIG = "[pytest]\nDJANGO_SETTINGS_MODULE=fixture_settings\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out, python = args.out.resolve(), args.python.absolute()  # do not resolve the venv interpreter symlink
    problem = ap.check_output_folder(out, pp.H5)
    if problem or out.exists():
        parser.error(problem or "output already exists")
    out.mkdir(parents=True)
    ctx = ap.Context(out, "scripted-h5-django", "synthetic", False,
                     denied=(Path.home(), out, ap.FIXFIRST, *iso.SYSTEM_TEMP), grading_policy=pp.H5)

    def build(name):
        run = ap.Run(ctx, out / name, False, True, python, ap.interpreters(python.parent.parent))
        for name, text in FILES.items():
            path = run.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        run.set_baseline()
        return run

    ref = build("reference")
    initial = ref.suite()
    assert initial["exit_code"] != 0, "the synthetic start must fail without settings"
    (ref.project / "pytest.ini").write_text(CONFIG, encoding="utf-8")
    data = ref.suite()
    data.update(ref.reference_fields(data))
    data["problems"] = rc.validate_reference(data)
    assert not data["problems"], data["problems"]
    rc.write_json(out / "reference.json", data)
    script = out / "script.json"
    rc.write_json(script, [{"call": "write_file", "arguments": {"path": "pytest.ini", "content": CONFIG}},
                           {"call": "finish", "arguments": {"summary": "saved settings module"}}])
    rows = []
    for arm in ("baseline", "facts", "mcp"):
        run, row = build(arm), {"arm": arm}
        try:
            ap.play(ctx.model, arm, run, ap.Settings(max_turns=3, run_timeout=60), script, data, row,
                    lambda: rc.workspace_digest(run.project, None))
        finally:
            ap.close_run(run, row)
        assert row["grading"] == "graded" and row["fixed"] is True and not row["violations"], row
        rows.append(row)
    payload = {"synthetic": True, "language_model_started": False, "grading_policy": pp.H5,
               "grading_policy_sha256": pp.identity(), "packages": rc.freeze(python),
               "start_exit_code": initial["exit_code"], "rows": rows}
    text = ap.redact(json.dumps(payload, indent=2), out)
    (out / "SUMMARY.json").write_text(text + "\n", encoding="utf-8")
    print("3/3 arms accept persisted Django settings, in fresh sandboxed grader processes")


if __name__ == "__main__":
    main()
