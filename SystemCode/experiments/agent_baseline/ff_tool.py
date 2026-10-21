"""fixfirst_check for the pilot: scan (or re-scan) a case and print a short plan.

Run inside the sandbox: python ff_tool.py <case_dir> <state.json> <target_python>
The session is kept in state.json so a re-check can close issues it covers.
"""

import sys
from pathlib import Path

from fixfirst.models import Session
from fixfirst.service import create_session, scan

SOURCES = {
    "rule": "confirmed by a rule",
    "heuristic": "likely, not confirmed",
    "model": "possible, not confirmed (model suggestion)",
}


def summary(session: Session) -> str:
    lines = [f"Goal: the full test suite passes. Status: {session.goal_status}."]
    lines.append("Problems:")
    for issue in session.issues[:10]:
        line = f"- [{issue.status}] {issue.title[:200]}"
        if issue.diagnosis:
            rule = f", rule {issue.diagnosis_rule}" if issue.diagnosis_rule else ""
            line += f"\n  cause: {issue.diagnosis} ({SOURCES.get(issue.diagnosis_source, issue.diagnosis_source)}{rule})"
        lines.append(line)
    if not session.issues:
        lines.append("- none found")
    lines.append("Next steps, most important first:")
    for action in session.actions[:3]:
        lines.append(f"{action.priority}. {action.title}")
        if action.explanation:
            lines.append(f"   why: {action.explanation[:500]}")
        if action.verification:
            lines.append(f"   how to confirm: {action.verification[:250]}")
        if action.command:
            lines.append(f"   command: {' '.join(action.command)}")
    return "\n".join(lines)


def main():
    case, state, python = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    if state.exists():
        session = Session.model_validate_json(state.read_text(encoding="utf-8"))
    else:
        session = create_session(case, python, "pilot", goal="pass_tests")
    scan(session)
    state.write_text(session.model_dump_json(), encoding="utf-8")
    print(summary(session))


if __name__ == "__main__":
    main()
