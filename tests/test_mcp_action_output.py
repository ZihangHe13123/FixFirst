"""An agent must receive the operation before the context, without truncation."""

import pytest

from fixfirst.mcp_server import _step


def step(**changes):
    return {
        "title": "Replace the removed operation", "optional": False, "impact": None,
        "where": ["app.py:8"], "rules": ["D02: observed removal"],
        "suspected": False, "cause": "Version incompatibility", "possible": None,
        "explanation": "Context. " * 200, "instructions": "", "command": None,
        "gather": False, "search": False, "confirm": "Run the original checks",
        **changes,
    }


def test_command_precedes_the_location_cause_and_limited_rationale():
    command = "'/a project/.venv/bin/python' -m pip install 'setuptools>=66.1,<82'"
    lines = _step(1, step(command=command))
    assert lines[1] == "   Command: " + command
    assert lines.index("   Where: app.py:8") > 1
    assert any("explain shows the rest" in line for line in lines)


def test_long_operation_retains_its_condition_and_complete_last_statement():
    instructions = "For standard data only: " + "keep(value); " * 160 + "return result"
    lines = _step(1, step(instructions=instructions))
    assert lines[1] == "   Action: " + instructions
    assert lines.index("   Where: app.py:8") > 1
    assert lines[1].endswith("return result")
    assert any("explain shows the rest" in line for line in lines[2:])


def test_old_saved_action_keeps_its_entire_only_recipe():
    text = "Observe. " * 100 + "app.py:8: replace old_call with new_call"
    old = step(explanation=text)
    old.pop("instructions")
    lines = _step(1, old)
    assert lines[1] == "   Action: " + text
    assert not any("explain shows the rest" in line for line in lines)


@pytest.mark.parametrize("confirmed", [False, True])
def test_environment_boundary_is_only_stated_for_confirmed_code_defects(confirmed):
    lines = _step(1, step(confirmed_code_defect=confirmed, cause="Defect in project code or tests"))
    assert any("FixFirst suggests no environment change for this failure" in line
               for line in lines) is confirmed
    assert not any("not an environment problem" in line or "will not repair" in line for line in lines)


def test_web_button_instruction_is_translated_in_the_operation():
    lines = _step(1, step(instructions="Set the variable, then press Check again."))
    assert lines[1] == "   Action: Set the variable, then call check_again."
