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

from . import domain, engine, integrity
from .evidence import issue_evidence
from .models import Session, GOAL_CHECKS, check_scope
from .processes import ManagedProcess
from .report import GOALS, TOOL_NAMES, shell
from .test_results import pytest_options_limited, pytest_options_note

GOAL_DONE = {
    "collect_tests": "All tests load",
    "check_style": "The code check passes",
    "pass_tests": "All tests pass",
    "run_project": "Program completed successfully",
    "pass_unittest": "All tests pass",
}
GOAL_CHOICES = [
    ("run_project", "Run my program", "Run a Python script, module or notebook and explain its errors."),
    ("pass_tests", "Make my tests pass", "Runs your tests to see whether the code works, and explains every failure."),
    ("pass_unittest", "Run unittest tests", "Run standard-library unittest tests; pytest is not required."),
    ("collect_tests", "Just get the tests to load", "Stops before running test code; for import and setup errors."),
    ("check_style", "Clean up code-check warnings",
     "Reads your code without running it (Ruff): likely bugs must be fixed, style suggestions are optional."),
]
ENV_DIRS = (".venv", "venv", "env", ".env")
PROJECT_MARKERS = ("pyproject.toml", "setup.cfg", "setup.py", "requirements.txt", "pytest.ini", "tox.ini")


def cause_name(label: str | None) -> str | None:
    return domain.cause(label).get("label", label) if label else None


def build_view(session: Session) -> dict:
    """Status headline, ordered steps and fixed issues for one session."""
    issues = {i.issue_id: i for i in session.issues}
    from .test_selection import comparable_scopes
    events = {e.event_id: e for e in session.events}
    facts = {f.fact_id: f for f in session.facts}
    rule_text = _rule_descriptions()
    known: dict[tuple, list[str]] = {}
    for fact in session.facts:
        known.setdefault((fact.subject, fact.predicate), []).append(fact.value)
    # Failures the rules judged not to change how the code runs (for example a test that
    # only counts warnings) are optional: they never count as problems in the headline.
    optional_ids = {i for (i, p), values in known.items() if p == "affects_running" and "no" in values}
    # Rules behind the lint classification and the future-risk note, shown under Details.
    explained: dict[str, list[str]] = {}
    for fact in session.facts:
        if fact.predicate in ("lint_finding", "breaks_in_future") and fact.rule_id:
            explained.setdefault(fact.subject, []).append(fact.rule_id)
    steps, optional, other = [], [], []
    for action in session.actions:
        if action.kind == "rerun":
            continue  # "Check again" covers every verification re-run
        # Issues the latest run could not reach are re-checked later, not worked on now.
        related = [
            issues[i] for i in action.issue_ids
            if i in issues and issues[i].status in ("open", "awaiting_verification")
        ]
        if action.issue_ids and not related:
            continue
        where, errors, rules = [], [], []
        for issue in related:
            location = issue_evidence(session, issue).get("where") if issue.tool in (
                "pytest", "pytest_run", "python_run", "unittest_run") else ""
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
            rules += [f"{r}: {rule_text[r]}" for r in explained.get(issue.issue_id, []) if r in rule_text]
        sources = []
        for fact_id in action.reason_refs:
            for ref in getattr(facts.get(fact_id), "evidence_refs", []):
                cited = domain.source(ref)
                if cited and cited not in sources:
                    sources.append(cited)
        suspected = action.action_id.startswith("consider-")
        # A heuristic (not a rule) produced this cause: say "likely", not certain.
        hedged = not suspected and any(
            i.diagnosis_source == "heuristic" and i.diagnosis == action.cause for i in related
        )
        is_optional = bool(related) and all(i.issue_id in optional_ids for i in related)
        lint = [i for i in related if i.tool == "ruff"]
        impact = _impact(related, known) if is_optional and not lint else {}
        breakdown = _breakdown(lint, events) if is_optional and lint else []
        target = other if action.goal_impact <= 0 else optional if is_optional else steps
        target.append(
            {
                "id": action.action_id,
                "issue_ids": [i.issue_id for i in related],
                "possible": cause_name(action.cause) if hedged else None,
                "title": action.title,
                "explanation": action.explanation,
                "instructions": action.instructions,
                "confirmed_code_defect": bool(related) and all(
                    i.diagnosis == "code_defect" and i.diagnosis_source == "rule" for i in related
                ),
                "command": shell(action.command) if action.command else None,
                "confirm": action.verification,
                # Only a rule's conclusion is shown as the cause; guesses are marked as such.
                "cause": None if hedged else cause_name(action.cause or next(
                    (i.diagnosis for i in related if i.diagnosis and i.diagnosis_source == "rule"), None
                )),
                "suspected": suspected,
                "gather": action.kind == "inspect" and not suspected and action.check not in ("version_search", "dependency_resolve"),
                # A release search downloads packages, so it runs only when the user asks.
                "search": action.check == "version_search",
                "resolve": action.check == "dependency_resolve",
                "where": where,
                "errors": list(dict.fromkeys(errors)),
                "rules": list(dict.fromkeys(rules)),
                "sources": sources,
                "optional": is_optional,
                "impact": impact.get("now"),
                "risk": impact.get("later"),
                "warnings": impact.get("warnings", []),
                "breakdown": breakdown,
            }
        )
    steps, optional, other = _fold_suggestions(steps), _fold_suggestions(optional), _fold_suggestions(other)
    fixed = [
        {"title": i.title, "cause": cause_name(i.diagnosis), "note": i.note}
        for i in session.issues
        if i.status == "resolved" and (i.tool != "pytest_run" or comparable_scopes(
            i.scope, check_scope(session, "pytest_run")))
    ]
    pending = [i.title for i in session.issues if i.status in ("not_observed", "unknown")
               and (i.tool not in ("python_run", "unittest_run")
                    or i.scope == check_scope(session, i.tool))
               and (i.tool != "pytest_run" or comparable_scopes(i.scope, check_scope(session, "pytest_run")))]
    # Only problems that stand between the user and the chosen goal count in the headline.
    blocking = {f.subject for f in session.facts if f.predicate == "affects" and f.value == session.goal}
    open_issues = [
        i for i in session.issues
        if i.status in ("open", "awaiting_verification") and i.issue_id in blocking
    ]
    must = [i for i in open_issues if i.issue_id not in optional_ids]
    optional_issues = [i for i in open_issues if i.issue_id in optional_ids]
    status = _status(session, steps, must, optional_issues)
    goal_run = _goal_run(session)
    if goal_run and status["kind"] != "scope_limited" and (note := pytest_options_note(goal_run)):
        status["detail"] += " " + note
    return {
        "project": session.name or Path(session.project_root).name,
        "project_root": session.project_root,
        "python": session.target_python,
        "goal": session.goal,
        "execution": session.execution.model_dump() if session.execution else None,
        "tests": list(session.test_targets),
        "goal_name": GOALS[session.goal],
        "goal_note": next(note for key, _, note in GOAL_CHOICES if key == session.goal),
        "status": status,
        "steps": steps,
        "optional": optional,
        "other": other,
        "fixed": fixed,
        "pending": pending,
        "checked": bool(session.runs),
        "last_checked": session.runs[-1].started_at if session.runs else None,
        "baseline": {
            "state": session.baseline_check.get("state"),
            "changed": [key.split(":", 1)[1] for key in session.baseline_check.get("changed", [])],
            "unverifiable": session.baseline_check.get("unverifiable", []),
            "recorded_at": integrity.current_baseline(session).get("recorded_at"),
            "accepted": integrity.current_baseline(session).get("reason") == "accepted by the user",
        },
    }


def _breakdown(issues, events: dict) -> list[dict]:
    """Code-check findings counted by plain-language family, largest first."""
    counts: dict[str, dict] = {}
    for issue in issues:
        for event_id in issue.event_ids:
            event = events.get(event_id)
            if not event:
                continue
            name = domain.lint_category(event.code or issue.component or "")
            row = counts.setdefault(name, {"name": name, "count": 0, "codes": []})
            row["count"] += 1
            if event.code and event.code not in row["codes"]:
                row["codes"].append(event.code)
    return sorted(counts.values(), key=lambda r: (-r["count"], r["name"]))


def _impact(issues, known: dict) -> dict:
    """Plain-language impact of failures that do not change how the code runs."""

    def first(subject, predicate):
        values = known.get((subject, predicate))
        return values[0] if values else None

    several = len(issues) != 1
    result = {
        "now": "Your code runs normally. Only "
        + ("these tests fail" if several else "this test fails")
        + ", because "
        + ("they count" if several else "it counts")
        + " warnings and a newer Python or library adds some.",
        "later": None,
        "warnings": [],
    }
    for issue in issues:
        name = first(issue.issue_id, "extra_warning")
        text = first(name, "warning_text") if name else None
        if text and text not in result["warnings"]:
            result["warnings"].append(f"{first(name, 'emitted_at')}: {text}")
        future = first(issue.issue_id, "breaks_in_future")
        if future and not result["later"]:
            owner = first(future, "deprecated_in") or ""
            release = f"{engine.display(owner)} {first(future, 'scheduled_removal')}"
            head = f"{release} removes {engine.display(future)}"
            user = first(future, "emitted_by") or ""
            if user == "project":
                result["later"] = f"{head}, so your code at {first(future, 'emitted_at')} will stop working on {release}."
            elif user.startswith("dist:") and user != owner:
                version = first(user, "installed_version")
                used_by = engine.display(user) + (f" {version}" if version else "")
                result["later"] = f"{head}. {used_by} uses it in code your tests run, so that code will fail on {release}."
            else:
                result["later"] = f"{head}. Code your tests run uses it, so it will fail on {release}."
    return result


def _fold_suggestions(steps: list[dict]) -> list[dict]:
    """Show a classifier suggestion as a hint on the step for the same issue, not as a step."""
    kept = []
    for step in steps:
        if step["suspected"]:
            hosts = [s for s in steps if not s["suspected"] and set(step["issue_ids"]) <= set(s["issue_ids"])]
            if hosts:
                for host in hosts:
                    if host["cause"] != step["cause"]:
                        host["possible"] = step["cause"]
                continue
        kept.append(step)
    return kept


def _relative(location: str, root: str) -> str:
    shown, base = location.replace("\\", "/"), root.replace("\\", "/").rstrip("/") + "/"
    return shown[len(base):] if shown.startswith(base) else shown


def _rule_descriptions() -> dict:
    from .reasoning import rule_base

    return {r.rule_id: r.description for r in rule_base()}


def _goal_run(session):
    from .test_selection import comparable_scopes

    target = GOAL_CHECKS[session.goal]
    return next((r for r in reversed(session.runs) if r.tool == target and (
        target != "pytest_run" or comparable_scopes(r.scope, check_scope(session, target)))), None)


def _status(session: Session, steps, open_issues, optional_issues=()) -> dict:
    if not session.runs:
        return {
            "kind": "new",
            "headline": "Not checked yet",
            "detail": "FixFirst will run your project's checks and explain what it finds. "
            "Nothing is changed or installed.",
        }
    if integrity.affects(session, GOAL_CHECKS[session.goal]):
        # Execution result, baseline change and verification are three different things.
        target, check = GOAL_CHECKS[session.goal], session.baseline_check
        run = _goal_run(session)
        passed = run.test_summary.get("passed") if run else None
        result = (
            "The last check passed" + (f" ({passed} test{'s' if passed != 1 else ''})" if passed else "")
            if run and run.verified_pass else "The last check did not pass"
        )
        what = "Ruff's settings" if target == "ruff" else "the tests or their settings"
        if check["state"] == "unverifiable":
            return {
                "kind": "baseline_unverifiable",
                "headline": "The tests could not be verified",
                "detail": f"{result}, but FixFirst cannot confirm that {what} are the ones of the baseline ("
                f"{integrity.describe(check['unverifiable'], 2)}). A pass does not show that the original "
                "problem is fixed.",
            }
        return {
            "kind": "baseline_changed",
            "headline": "The code-check settings changed" if target == "ruff" else "The tests changed",
            "detail": f"{result}, but {what} changed since the baseline ({integrity.describe(check['changed'])}). "
            "A pass now does not show that the original problem is fixed. Restore them, or accept the changes "
            "as the new baseline if they are intended.",
        }
    goal_run = _goal_run(session)
    if goal_run and goal_run.verified_pass and pytest_options_limited(goal_run):
        count = goal_run.test_summary.get("passed")
        return {
            "kind": "scope_limited",
            "headline": "The checked tests passed" if goal_run.tool == "pytest_run" else "The checked tests load",
            "detail": (f"{count} test{'s' if count != 1 else ''} passed. " if count else "")
            + pytest_options_note(goal_run),
        }
    if session.goal_status == "achieved":
        target = GOAL_CHECKS[session.goal]
        run = _goal_run(session)
        summary = run.test_summary if run else {}
        detail = f"Verified by {TOOL_NAMES[target].lower()}"
        if summary.get("passed"):
            detail += f": {summary['passed']} test{'s' if summary['passed'] != 1 else ''} passed"
        if session.goal == "run_project":
            detail += ". The selected entry completed with exit code 0 using the saved arguments and input"
        if session.goal == "pass_tests" and session.test_targets:
            detail += ". This verifies only the saved test selection: " + ", ".join(session.test_targets)
        headline = "The selected tests pass" if session.goal == "pass_tests" and session.test_targets else GOAL_DONE[session.goal]
        return {"kind": "done", "headline": headline, "detail": detail + "."}
    # Count problems, not steps: steps merge issues that share a remedy, and one problem can
    # have a step that gathers evidence as well as one that fixes it.
    count = len({tuple(sorted(s["issue_ids"])) for s in steps}) if steps else len(open_issues)
    fixed = sum(i.status == "resolved" for i in session.issues)
    progress = f"{fixed} fixed so far. " if fixed else ""
    waiting = len(optional_issues)
    lint = session.goal == "check_style"
    if lint:
        # Code-check issues group findings by rule and file; count the findings themselves.
        waiting = sum(len(i.event_ids) or 1 for i in optional_issues)
    if count:
        if not waiting:
            extra = ""
        elif lint:
            extra = (
                f" Ruff also has {waiting} clean-up suggestion{'s' if waiting != 1 else ''} "
                "below (optional): they do not change how your code runs."
            )
        else:
            extra = (
                f" {waiting} more failing test{'s' if waiting != 1 else ''} below "
                f"{'do' if waiting != 1 else 'does'} not affect how your code runs (optional)."
            )
        return {
            "kind": "todo",
            "headline": f"{count} problem{'s' if count != 1 else ''} to fix",
            "detail": progress + "Start with step 1. After changing your code, press Check "
            "again: a step only counts as fixed when a real check passes." + extra,
        }
    if waiting and lint:
        return {
            "kind": "advisory",
            "headline": "No problems that affect your code",
            "detail": progress
            + f"Ruff still has {waiting} clean-up suggestion{'s' if waiting != 1 else ''} about "
            "style, layout and syntax. They do not change how your code runs; fix them only if "
            "you want the code check to pass.",
        }
    if waiting:
        several = waiting != 1
        return {
            "kind": "advisory",
            "headline": "No problems that affect your code",
            "detail": progress
            + f"{waiting} test{'s' if several else ''} still fail{'' if several else 's'}, but for a "
            "reason that does not change how your code runs. The optional step below makes "
            + ("them" if several else "it")
            + " pass if you want every test to pass.",
        }
    others = sum(i.status != "resolved" for i in session.issues)
    return {
        "kind": "unknown",
        "headline": "The goal is not confirmed yet",
        "detail": (
            f"None of the {others} finding{'s' if others != 1 else ''} below is known to block "
            "this goal. Press Check again to run the full check."
            if others
            else "Press Check again to run the full check for this goal."
        ),
    }


def _probe(python: str) -> dict:
    """Version of an interpreter and whether it can run pytest and Ruff."""
    code = (
        "import sys, importlib.util as u; print(sys.version.split()[0]); "
        "print(bool(u.find_spec('pytest'))); print(bool(u.find_spec('ruff')))"
    )
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            with ManagedProcess([python, "-c", code], cwd=directory, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as done:
                stdout, _ = done.communicate(timeout=15)
        version, pytest, ruff = stdout.split()[:3]
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
        entry.suffix in (".py", ".ipynb") for _, entry in zip(range(300), root.iterdir())
    )
    candidates = []
    for name in ENV_DIRS:
        for relative in ("bin/python", "Scripts/python.exe", "python.exe"):
            candidate = root / name / relative
            if candidate.is_file():
                candidates.append((str(candidate), f"the project's {name} environment"))
    if python:
        chosen = os.path.abspath(os.path.expanduser(python.strip().strip("'\"")))
        origin = "chosen by you"
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
    from .execution import discover

    discovery = discover(root)
    if interpreter["version"] and not interpreter["pytest"] and discovery["suggested_goal"] == "pass_tests":
        warnings.append(
            "pytest is not installed in this Python, so tests cannot run. Install it in your "
            f"project's environment ({shell([chosen, '-m', 'pip', 'install', 'pytest'])}) "
            "or choose another interpreter."
        )
    return {
        "ok": interpreter["version"] is not None,
        "path": str(root),
        "name": root.name,
        "markers": markers,
        "python": interpreter,
        "warnings": warnings,
        "discovery": discovery,
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
    if os.name == "nt" and parent is None:
        import ctypes

        mask = ctypes.windll.kernel32.GetLogicalDrives()
        entries += [
            {"name": f"{letter}:\\", "path": f"{letter}:\\", "project": False}
            for bit, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            if mask >> bit & 1 and f"{letter}:\\" != str(root)
        ]
    return {"path": str(root), "parent": parent, "entries": entries}
