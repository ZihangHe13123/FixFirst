"""Explain narrowly observed limits of an executed pytest check."""

from .models import Action, GOAL_CHECKS
from .runner import environment_id


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
    if not incomplete and not unsupported and not internal_error:
        return actions
    issues = [i for i in session.issues if i.tool == target and i.status == "open"
              and any(e.run_id == run.run_id and e.event_id in i.event_ids for e in session.events)]
    if not issues:
        return actions
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
