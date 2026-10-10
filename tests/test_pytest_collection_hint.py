import sys

import pytest

from fixfirst.models import Action, Event, Issue, Run
from fixfirst.pytest_diagnostics import COLLECTION_HINT, refine
from fixfirst.runner import environment_id
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def example(tmp_path):
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    run = Run(tool="pytest_run", scope="tests:project", exit_code=2,
              environment_id=environment_id(sys.executable))
    event = Event(run_id=run.run_id, tool="pytest_run", stage="collect", kind="import_failure",
                  message="ModuleNotFoundError: No module named 'a_missing_library'")
    issue = Issue(issue_id="missing", fingerprint="missing", tool="pytest_run", stage="collect",
                  kind="import_failure", title=event.message, event_ids=[event.event_id],
                  evidence_refs=[], member_keys=[], scope=run.scope, environment_id=run.environment_id,
                  status="open", diagnosis="missing_dependency", diagnosis_source="rule")
    session.runs, session.events, session.issues = [run], [event], [issue]
    actions = [Action(action_id="install", kind="manual_fix", title="Install a_missing_library",
                      explanation="The library is missing.", instructions="Install the declared dependency.",
                      verification="Check again", command=[sys.executable, "-m", "pip", "install", "a_missing_library"],
                      issue_ids=[issue.issue_id], cause="missing_dependency"),
               Action(action_id="other", kind="inspect", title="Another issue", explanation="Unrelated.",
                      instructions="Inspect it.", verification="Check again", issue_ids=["unrelated"])]
    return session, actions


def test_hint_only_appends_to_the_related_step_and_is_idempotent(tmp_path):
    session, actions = example(tmp_path)
    originals = [a.model_dump() for a in actions]
    issue_before = session.issues[0].model_dump()
    result = refine(session, actions)
    assert [a.action_id for a in result] == [a.action_id for a in actions]
    expected = originals[0] | {"instructions": originals[0]["instructions"] + " " + COLLECTION_HINT}
    assert result[0].model_dump() == expected
    assert result[1].model_dump() == originals[1]
    assert session.issues[0].model_dump() == issue_before
    assert [a.model_dump() for a in refine(session, result)] == [a.model_dump() for a in result]
    assert [a.model_dump() for a in actions] == originals


@pytest.mark.parametrize("command", [[], [sys.executable, "-m", "pip", "install", "a_missing_library"]])
@pytest.mark.parametrize("instructions", ["", "The library is missing.", "Install the declared dependency."])
def test_mcp_text_only_gains_the_hint_even_near_the_explanation_limit(tmp_path, command, instructions):
    from fixfirst.mcp_server import _step

    session, actions = example(tmp_path)
    original = actions[0].model_copy(update={"command": command, "instructions": instructions,
        "explanation": "The library is missing. " + "Read the original output carefully. " * 15})

    def render(action):
        return _step(1, {"title": action.title, "optional": False, "command": " ".join(action.command),
            "instructions": action.instructions, "explanation": action.explanation, "where": [],
            "rules": [], "suspected": False, "cause": action.cause, "possible": None,
            "gather": False, "search": False, "confirm": action.verification})

    before = render(original)
    after = render(refine(session, [original])[0])
    stripped = [line.replace(" " + COLLECTION_HINT, "").replace(COLLECTION_HINT, "") for line in after]
    stripped = [line for line in stripped if line.strip() != "Action:"]
    assert stripped == before


@pytest.mark.parametrize("change", ["imported", "selected", "executed_tests", "wrong_exit",
                                    "old_environment", "old_event", "non_missing_import", "setup_failure"])
def test_other_checks_keep_their_steps(tmp_path, change):
    session, actions = example(tmp_path)
    run, event = session.runs[0], session.events[0]
    if change == "imported":
        run.source = "imported"
    elif change == "selected":
        session.test_targets = ["tests/test_app.py"]
        run.scope = "tests:requested:example"
    elif change == "executed_tests":
        run.records = [{"type": "outcome", "stage": "call", "outcome": "passed", "nodeid": "test_ok.py::test_ok"}]
    elif change == "wrong_exit":
        run.exit_code = 1
    elif change == "old_environment":
        run.environment_id = "another-interpreter"
    elif change == "old_event":
        event.run_id = "old-run"
    elif change == "non_missing_import":
        event.message = "ImportError: cannot import name 'x'"
    elif change == "setup_failure":
        event.stage = "setup"
    assert [a.model_dump() for a in refine(session, actions)] == [a.model_dump() for a in actions]


def test_default_real_collection_failure_gets_the_hint(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    (tmp_path / "test_app.py").write_text("import a_missing_library\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    assert session.runs[-1].exit_code == 2
    assert any(COLLECTION_HINT in step["instructions"] for step in build_view(session)["steps"])
    assert session.goal_status != "achieved"
