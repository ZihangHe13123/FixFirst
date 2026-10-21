"""Explain narrowly observed limits of an executed pytest check."""

from .models import Action, GOAL_CHECKS
from .parsers import IMPORT
from .runner import environment_id


COLLECTION_HINT = (
    "This check stopped during collection and no tests ran; if you only need a particular test, "
    "you can specify its test range."
)


def refine(session, actions):
    target = GOAL_CHECKS[session.goal]
    if target not in ("pytest", "pytest_run"):
        return actions
    run = next((r for r in reversed(session.runs) if r.tool == target), None)
    if not run or run.source != "executed" or run.environment_id != environment_id(session.target_python):
        return actions
    incomplete = (any(r.get("type") == "finish" and r.get("records_dropped") is True for r in run.records)
                  or "Structured test events were incomplete" in run.notes)
    unsupported = run.pytest_options.get("support_error") == "minimum_pytest_version"
    internal_error = run.status == "completed" and run.exit_code == 3
    collection_events = {
        event.event_id for event in session.events
        if event.run_id == run.run_id and event.stage == "collect" and event.kind == "import_failure"
        and "No module named" in event.message
    }
    missing_modules = {match.group(1) for event in session.events if event.event_id in collection_events
                       for match in [IMPORT.search(event.message)] if match}
    collection_stopped = (
        session.goal == "pass_tests" and not session.test_targets and run.scope == "tests:project"
        and run.status == "completed" and run.exit_code == 2 and len(missing_modules) >= 2
        and not any(record.get("type") == "outcome" for record in run.records)
    )
    if not incomplete and not unsupported and not internal_error and not collection_stopped:
        return actions
    issues = [i for i in session.issues if i.tool == target and i.status == "open"
              and any(e.run_id == run.run_id and e.event_id in i.event_ids for e in session.events)]
    if not issues:
        return actions
    if collection_stopped and not (incomplete or unsupported or internal_error):
        missing_ids = {issue.issue_id for issue in issues if collection_events.intersection(issue.event_ids)}
        hinted = []
        for action in actions:
            if missing_ids.intersection(action.issue_ids) and COLLECTION_HINT not in action.instructions:
                # Preserve the renderer's existing fallback and duplicate-text suppression.
                # Changing a separate explanation would also change its truncation boundary.
                value = action.instructions or (action.explanation if not action.command else "")
                update = {"instructions": (value + " " if value else "") + COLLECTION_HINT}
                if value and action.explanation == value:
                    update["explanation"] = update["instructions"]
                action = action.model_copy(update=update)
            hinted.append(action)
        return hinted
    ids = {i.issue_id for i in issues}
    kept = []
    for action in actions:
        remaining = [key for key in action.issue_ids if key not in ids]
        if action.issue_ids and not remaining:
            continue
        if remaining != action.issue_ids:
            action = action.model_copy(update={"issue_ids": remaining})
        kept.append(action)
    if unsupported:
        text = ("The target environment's pytest is too old for FixFirst's recorded check. "
                "The minimum supported pytest version is 3.2.1. Use a compatible environment "
                "with pytest 3.2.1 or newer, then repeat the same check. No tests ran and no fix was confirmed.")
        step = Action(action_id="pytest-minimum-version", kind="manual_fix", issue_ids=sorted(ids),
                      title=f"pytest {run.tool_version} is too old for this check", explanation=text,
                      instructions=text, verification="Repeat the same check with a supported pytest", goal_impact=1)
        return [step, *kept]
    if internal_error:
        text = ("pytest stopped with an internal error (exit code 3), so it did not produce a complete "
                "test run. A cause or fix is not confirmed by this check. Inspect the saved pytest "
                "internal-error output. To check a particular test, use fixfirst configure SESSION "
                "--tests path/to/tests.py, then scan SESSION; with MCP, call diagnose with tests: "
                "[\"path/to/tests.py\"].")
        for issue in issues:
            if issue.diagnosis_source == "rule":
                issue.diagnosis_source = "heuristic"
                issue.prediction_note = "The pytest check ended with an internal error; this cause is not confirmed."
            issue.note = text
        for fact in session.facts:
            if fact.subject in ids and fact.predicate == "diagnosis" and fact.status == "derived":
                fact.status = "hypothesis"
        step = Action(action_id="pytest-internal-error", kind="manual_fix", issue_ids=sorted(ids),
                      title="pytest stopped with an internal error", explanation=text, instructions=text,
                      verification="Run the selected tests again after reviewing the pytest error", goal_impact=1)
        return [step, *kept]
    text = ("Test records are incomplete. Observed failures are retained, but this check cannot "
            "confirm that the original tests passed. Select a smaller test file or pytest node ID: "
            "use fixfirst configure SESSION --tests path/to/tests.py, then scan SESSION; "
            "with MCP, call diagnose with tests: [\"path/to/tests.py\"].")
    for issue in issues:
        issue.note = (issue.note + " " if issue.note else "") + text
    step = Action(action_id="pytest-incomplete-records", kind="manual_fix", issue_ids=sorted(ids),
                  title="Test records are incomplete; select a smaller test range", explanation=text,
                  instructions=text, verification="Run the saved test selection again", goal_impact=1)
    return [step, *actions]
