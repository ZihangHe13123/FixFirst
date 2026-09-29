"""Checks of the agent harness with scripted replies instead of a model (macOS: sandbox-exec).

Run explicitly (not part of the main suite, which also runs on Windows):
  .venv/bin/python -m pytest -q experiments/agent_baseline/test_harness.py
Generated cases only, offline; real projects need the network and are checked by hand (README).
"""

import json
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_pilot  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("sandbox-exec") is None, reason="needs macOS sandbox-exec")
CASE = "pkg-inventory:lm_renamed"  # inventory/utils/numbers.py was renamed to number.py
FIX = "mv inventory/utils/number.py inventory/utils/numbers.py"


def run(tmp_path, steps, arms=("baseline",), case=CASE, extra=()):
    script = tmp_path / "script.json"
    script.write_text(json.dumps(steps))
    out = tmp_path / "out"
    agent_pilot.main(["--model", f"fake:{script}", "--cases", case, "--arms", *arms, "--out", str(out),
                      "--max-turns", "6", *extra])
    return [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]


def call(name, **arguments):
    return {"call": name, "arguments": arguments}


def test_a_real_fix_is_fixed_and_the_first_green_turn_is_found(tmp_path):
    [row] = run(tmp_path, [call("run_command", command="python -m pytest -q"), call("run_command", command=FIX),
                           call("finish", summary="renamed the module back")])
    assert (row["fixed"], row["first_green_turn"], row["end"], row["tests_changed"]) == (True, 2, "finish", [])


def test_editing_a_test_file_is_never_fixed_even_if_the_originals_pass(tmp_path):
    edit = 'f=$(ls tests/test_*.py | head -1); echo "" >> "$f"'
    [row] = run(tmp_path, [call("run_command", command=FIX), call("run_command", command=edit),
                           call("finish", summary="done")])
    assert row["passes_with_original_tests"] is True
    assert row["fixed"] is False and row["tests_changed"] and "tests changed" in row["reasons"][0]
    assert row["first_green_turn"] == 1  # green before the test was edited, not after


def test_a_pass_that_needs_an_environment_variable_is_not_fixed(tmp_path):
    steps = [call("run_command", command="PYTHONPATH=src python -m pytest -q"), call("finish", summary="passes")]
    [row] = run(tmp_path, steps, case="flat-shop:lm_src_layout")
    assert row["fixed"] is False and row["first_green_turn"] is None


def test_a_model_error_is_recorded_and_the_run_is_still_graded(tmp_path):
    [row] = run(tmp_path, [call("run_command", command="ls"), {"fail": "HTTP 500"}])
    assert row["end"] == "model_error" and "HTTP 500" in row["error"] and row["fixed"] is False


def test_the_mcp_arm_talks_to_fixfirst_and_both_arms_start_alike(tmp_path):
    steps = [call("diagnose", project="."), call("run_command", command=FIX), call("check_again"),
             call("finish", summary="renamed back")]
    rows = run(tmp_path, steps, arms=("mcp", "baseline"))
    assert [r["arm"] for r in rows] == ["mcp", "baseline"] and [r["order"] for r in rows] == [1, 2]
    mcp, baseline = rows
    assert mcp["fixfirst_calls"] == 2 and mcp["fixed"] is True
    assert baseline["fixfirst_calls"] == 0 and baseline["fixed"] is True  # its own copy, not the mcp arm's


def test_arms_alternate_between_cases_and_runs():
    assert agent_pilot.arm_order(["baseline", "mcp"], 0, 0) == ["baseline", "mcp"]
    assert agent_pilot.arm_order(["baseline", "mcp"], 1, 0) == ["mcp", "baseline"]
    assert agent_pilot.arm_order(["baseline", "mcp"], 1, 1) == ["baseline", "mcp"]
