"""Explain narrowly observed limits of an executed pytest check."""

from .models import Action, GOAL_CHECKS
from .runner import environment_id


def refine(session, actions):
    target = GOAL_CHECKS[session.goal]
    if target not in ("pytest", "pytest_run"):
        return actions
    run = next((r for r in reversed(session.runs) if r.tool == target), None)
    if (not run or run.source != "executed" or run.environment_id != environment_id(session.target_python)
            or run.pytest_options.get("support_error") != "minimum_pytest_version"):
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
    text = ("The target environment's pytest is too old for FixFirst's recorded check. "
            "The minimum supported pytest version is 3.2.1. Use a compatible environment "
            "with pytest 3.2.1 or newer, then repeat the same check. No tests ran and no fix was confirmed.")
    step = Action(action_id="pytest-minimum-version", kind="manual_fix", issue_ids=sorted(ids),
                  title=f"pytest {run.tool_version} is too old for this check", explanation=text,
                  instructions=text, verification="Repeat the same check with a supported pytest", goal_impact=1)
    return [step, *kept]
