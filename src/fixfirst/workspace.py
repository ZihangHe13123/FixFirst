"""Plain-language view of a session for the web interface, plus folder helpers.

The report (report.py) shows everything FixFirst recorded. This module answers only what a
first-time user needs: is the goal reached, what should I change next and where, and how do
I confirm it. Technical detail stays one click away.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import domain
from .evidence import issue_evidence
from .models import Session
from .report import GOALS, TOOL_NAMES

GOAL_DONE = {
    "collect_tests": "All tests load",
    "check_style": "The code check passes",
    "pass_tests": "All tests pass",
}
GOAL_CHOICES = [
    ("pass_tests", "Make my tests pass", "Runs your tests and explains every failure."),
    ("collect_tests", "Just get the tests to load", "Stops before running test code; for import and setup errors."),
    ("check_style", "Clean up code-check warnings", "Runs Ruff with your project's settings."),
]
ENV_DIRS = (".venv", "venv", "env", ".env")
PROJECT_MARKERS = ("pyproject.toml", "setup.cfg", "setup.py", "requirements.txt", "pytest.ini", "tox.ini")


def cause_name(label: str | None) -> str | None:
    return domain.cause(label).get("label", label) if label else None


def build_view(session: Session) -> dict:
    """Status headline, ordered steps and fixed issues for one session."""
    issues = {i.issue_id: i for i in session.issues}
    events = {e.event_id: e for e in session.events}
    facts = {f.fact_id: f for f in session.facts}
    rule_text = _rule_descriptions()
    steps, other = [], []
    for action in session.actions:
        if action.kind == "rerun":
            continue  # "Check again" covers every verification re-run
        related = [issues[i] for i in action.issue_ids if i in issues and issues[i].status != "resolved"]
        if action.kind == "manual_fix" and not related:
            continue
        where, errors, rules = [], [], []
        for issue in related:
            location = issue_evidence(session, issue).get("where") if issue.tool in ("pytest", "pytest_run") else ""
            if not location:
                event = next((events[e] for e in issue.event_ids if e in events), None)
                location = _relative(event.location, session.project_root) if event else ""
                if location and event.tool == "ruff" and event.line:
                    location += f":{event.line}"
            if location and location not in where:
                where.append(location)
            errors.append(issue.title)
            if issue.diagnosis_rule and issue.diagnosis_rule in rule_text:
                rules.append(f"{issue.diagnosis_rule}: {rule_text[issue.diagnosis_rule]}")
        sources = []
        for fact_id in action.reason_refs:
            for ref in getattr(facts.get(fact_id), "evidence_refs", []):
                cited = domain.source(ref)
                if cited and cited not in sources:
                    sources.append(cited)
        suspected = action.action_id.startswith("consider-")
        (steps if action.goal_impact > 0 else other).append(
            {
                "id": action.action_id,
                "title": action.title,
                "explanation": action.explanation,
                "confirm": action.verification,
                "cause": cause_name(action.cause or next((i.diagnosis for i in related if i.diagnosis), None)),
                "suspected": suspected,
                "gather": action.kind == "inspect" and not suspected,
                "where": where,
                "errors": list(dict.fromkeys(errors)),
                "rules": list(dict.fromkeys(rules)),
                "sources": sources,
            }
        )
    fixed = [
        {"title": i.title, "cause": cause_name(i.diagnosis), "note": i.note}
        for i in session.issues
        if i.status == "resolved"
    ]
    # Only problems that stand between the user and the chosen goal count in the headline.
    blocking = {f.subject for f in session.facts if f.predicate == "affects" and f.value == session.goal}
    open_issues = [i for i in session.issues if i.status != "resolved" and i.issue_id in blocking]
    return {
        "project": session.name or Path(session.project_root).name,
        "project_root": session.project_root,
        "python": session.target_python,
        "goal": session.goal,
        "goal_name": GOALS[session.goal],
        "status": _status(session, steps, open_issues),
        "steps": steps,
        "other": other,
        "fixed": fixed,
        "checked": bool(session.runs),
        "last_checked": session.runs[-1].started_at if session.runs else None,
    }


def _relative(location: str, root: str) -> str:
    shown, base = location.replace("\\", "/"), root.replace("\\", "/").rstrip("/") + "/"
    return shown[len(base):] if shown.startswith(base) else shown


def _rule_descriptions() -> dict:
    from .reasoning import rule_base

    return {r.rule_id: r.description for r in rule_base()}


def _status(session: Session, steps, open_issues) -> dict:
    if not session.runs:
        return {
            "kind": "new",
            "headline": "Not checked yet",
            "detail": "FixFirst will run your project's checks and explain what it finds. "
            "Nothing is changed or installed.",
        }
    if session.goal_status == "achieved":
        target = {"collect_tests": "pytest", "check_style": "ruff", "pass_tests": "pytest_run"}[session.goal]
        run = next((r for r in reversed(session.runs) if r.tool == target), None)
        summary = run.test_summary if run else {}
        detail = f"Verified by {TOOL_NAMES[target].lower()}"
        if summary.get("passed"):
            detail += f": {summary['passed']} test{'s' if summary['passed'] != 1 else ''} passed"
        return {"kind": "done", "headline": GOAL_DONE[session.goal], "detail": detail + "."}
    count = len(open_issues)
    fixed = sum(i.status == "resolved" for i in session.issues)
    progress = f"{fixed} fixed so far. " if fixed else ""
    if count:
        return {
            "kind": "todo",
            "headline": f"{count} problem{'s' if count != 1 else ''} to fix",
            "detail": progress + "Start with step 1. After changing your code, press Check "
            "again: a step only counts as fixed when a real check passes.",
        }
    return {
        "kind": "unknown",
        "headline": "Nothing to fix was found, but the goal is not confirmed",
        "detail": "Press Check again to run the full check for this goal.",
    }


def _probe(python: str) -> dict:
    """Version of an interpreter and whether it can run pytest and Ruff."""
    code = (
        "import sys, importlib.util as u; print(sys.version.split()[0]); "
        "print(bool(u.find_spec('pytest'))); print(bool(u.find_spec('ruff')))"
    )
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            done = subprocess.run(
                [python, "-c", code], cwd=directory, capture_output=True, text=True, timeout=15
            )
        version, pytest, ruff = done.stdout.split()[:3]
        return {"path": python, "version": version, "pytest": pytest == "True", "ruff": ruff == "True"}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"path": python, "version": None, "pytest": False, "ruff": False}


def inspect_folder(path: str, python: str | None = None) -> dict:
    """Does this look like a Python project, and which interpreter should check it?"""
    root = Path(os.path.expanduser(path.strip().strip("'\""))) if path.strip() else None
    if root is None or not root.is_dir():
        return {"ok": False, "error": "This folder does not exist."}
    root = root.resolve()
    markers = [name for name in PROJECT_MARKERS if (root / name).is_file()]
    if (root / "tests").is_dir():
        markers.append("tests/")
    has_python = bool(markers) or any(
        entry.suffix == ".py" for _, entry in zip(range(300), root.iterdir())
    )
    candidates = []
    for name in ENV_DIRS:
        for relative in ("bin/python", "Scripts/python.exe"):
            candidate = root / name / relative
            if candidate.is_file():
                candidates.append((str(candidate), f"the project's {name} environment"))
    if python:
        chosen, origin = python, "chosen by you"
    elif candidates:
        chosen, origin = candidates[0]
    else:
        chosen, origin = sys.executable, "FixFirst's own Python (your project's packages may be missing)"
    interpreter = {**_probe(chosen), "origin": origin}
    warnings = []
    if not has_python:
        warnings.append("No Python files or project files were found in this folder.")
    if interpreter["version"] is None:
        warnings.append("This Python interpreter could not be started.")
    elif not interpreter["pytest"]:
        warnings.append(
            "pytest is not installed in this Python, so tests cannot run. Install it in your "
            "project's environment (python -m pip install pytest) or choose another interpreter."
        )
    return {
        "ok": interpreter["version"] is not None,
        "path": str(root),
        "name": root.name,
        "markers": markers,
        "python": interpreter,
        "warnings": warnings,
    }


def browse(path: str | None) -> dict:
    """Sub-folders of a directory, marking the ones that look like Python projects."""
    root = Path(os.path.expanduser(path or "~")).resolve()
    if not root.is_dir():
        root = Path.home()
    entries = []
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        children = []
    for child in children:
        if len(entries) >= 300:
            break
        try:
            if child.name.startswith(".") or not child.is_dir():
                continue
            project = any((child / name).is_file() for name in PROJECT_MARKERS)
        except OSError:
            continue
        entries.append({"name": child.name, "path": str(child), "project": project})
    parent = str(root.parent) if root.parent != root else None
    return {"path": str(root), "parent": parent, "entries": entries}
