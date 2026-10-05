import codecs
import locale
from pathlib import Path
import os

from .grouping import group_events, digest, member_key
from .models import Run, Session, now, GOAL_CHECKS
from .parsers import parse
from . import integrity
from .reasoning import infer_and_plan
from .test_results import pytest_options_limited, pytest_options_note
from .runner import (
    DEFAULT_CHECKS,
    DEFAULT_TIMEOUT,
    MAX_OUTPUT,
    collect,
    environment_id,
    redact,
    validate_targets,
)


def create_session(
    project, python, name=None, goal="collect_tests", grouping="tfidf", model=None, sbert_model=None,
    execution=None, *, structured_evidence=False, bounded_actions=False,
):
    root = Path(project).expanduser().resolve()
    interpreter = Path(os.path.abspath(os.path.expanduser(python)))
    if os.name == "nt" and not interpreter.suffix and interpreter.with_suffix(".exe").is_file():
        interpreter = interpreter.with_suffix(".exe")
    if not root.is_dir():
        raise ValueError("Project directory does not exist")
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise ValueError("Python interpreter does not exist or is not executable")
    from .execution import choose_execution

    goal, execution = choose_execution(root, goal, execution)
    if grouping == "sbert" and not sbert_model:
        raise ValueError("SBERT grouping needs a local model path")
    if model:
        model = str(Path(model).expanduser().resolve())
        if not Path(model).is_file():
            raise ValueError("Classifier model file does not exist")
    if sbert_model:
        sbert_model = str(Path(sbert_model).expanduser().resolve())
        if not Path(sbert_model).is_dir():
            raise ValueError("Semantic model directory does not exist")
    return Session(
        name=name or root.name,
        project_root=str(root),
        target_python=str(interpreter),
        goal=goal,
        execution=execution,
        grouping=grouping,
        model_path=model,
        structured_evidence=structured_evidence,
        bounded_actions=bounded_actions,
        sbert_model=sbert_model,
    )


def ingest(session: Session, runs: list[Run]):
    fresh = []
    event_batch = []
    for run in runs:
        events = parse(run)
        event_batch.extend(events)
        fresh.extend(
            group_events(events, run, session.grouping, session.threshold, session.sbert_model)
        )
    updated_tools = {r.tool for r in runs}
    previous = session.issues
    by_id = {i.issue_id: i for i in previous}
    claimed = set()
    for issue in fresh:
        # The same text in different interpreters must not overwrite the prior environment.
        if issue.issue_id in by_id and (
            by_id[issue.issue_id].environment_id != issue.environment_id
            or (issue.tool in ("python_run", "unittest_run") and by_id[issue.issue_id].scope != issue.scope)
        ):
            issue.issue_id = "issue-" + digest(issue.fingerprint + issue.environment_id + issue.scope)
        if issue.tool not in ("pytest_run", "unittest_run") or not issue.targets:
            continue
        candidates = [
            old
            for old in previous
            if old.issue_id not in claimed
            and (old.tool, old.environment_id, old.kind, old.stage, old.component)
            == (issue.tool, issue.environment_id, issue.kind, issue.stage, issue.component)
            and set(old.targets) & set(issue.targets)
            and (issue.tool != "unittest_run" or old.scope == issue.scope)
        ]
        if len(candidates) != 1:
            continue
        old = candidates[0]
        issue.issue_id, issue.first_seen = old.issue_id, old.first_seen
        claimed.add(old.issue_id)
        passed = {
            node
            for run in runs
            if run.tool == issue.tool
            and run.environment_id == issue.environment_id
            and run.source == "executed"
            for node in run.passed_nodes
        }
        represented = {
            node
            for other in fresh
            if other.tool == issue.tool
            and other.environment_id == issue.environment_id
            and other.kind == issue.kind
            and other.stage == issue.stage
            and other.component == issue.component
            for node in other.targets
        }
        pending = set(old.targets) - passed - represented if old.status != "resolved" else set()
        carried = [
            e for e in session.events if e.event_id in old.event_ids and e.location in pending
        ]
        if carried:
            issue.targets = sorted(set(issue.targets) | pending)
            issue.event_ids += [e.event_id for e in carried]
            issue.evidence_refs = sorted(
                set(issue.evidence_refs) | {ref for e in carried for ref in e.evidence_refs}
            )
            issue.member_keys = sorted(set(issue.member_keys) | {member_key(e) for e in carried})
            issue.note = f"Only some members were re-observed; {len(pending)} node(s) keep their earlier unverified evidence"
    fresh_ids = {i.issue_id for i in fresh}
    changes = []
    for issue in fresh:
        if issue.issue_id in by_id:
            old = by_id[issue.issue_id]
            issue.first_seen = old.first_seen
            changes.append(
                {
                    "issue_id": issue.issue_id,
                    "change": "reopened" if old.status == "resolved" else "persisting",
                }
            )
        else:
            changes.append({"issue_id": issue.issue_id, "change": "new"})
    for old in previous:
        if old.issue_id in fresh_ids:
            continue
        copy = old.model_copy(deep=True)
        matching = [
            r
            for r in runs
            if r.tool == old.tool
            and r.scope == old.scope
            and r.environment_id == old.environment_id
        ]
        # Imported logs never assert that an executed project's old failure was fixed.
        passed = any(
            r.verified_pass and r.coverage_complete and r.source == "executed" for r in matching
        )
        if old.tool in ("ruff", "pip_check"):
            # Both list every finding in a complete run, so one they no longer report is fixed
            # even while other findings remain.
            passed = any(r.coverage_complete and r.source == "executed" for r in matching)
        if old.tool == "project":
            from .project import declaration_verified

            passed = declaration_verified(old, session.runs, runs)
        if old.tool == "pytest_run" and old.stage == "collect" and not old.targets:
            # A complete project run collected every module without collection errors, even
            # if some tests then failed; that settles earlier collection issues.
            passed = passed or any(
                r.tool == old.tool
                and r.environment_id == old.environment_id
                and r.source == "executed"
                and r.scope == "tests:project"
                and r.coverage_complete
                for r in runs
            )
        if old.tool in ("pytest_run", "unittest_run") and old.targets:
            passed = any(
                r.tool == old.tool
                and r.environment_id == old.environment_id
                and r.source == "executed"
                and (old.tool != "unittest_run" or r.scope == old.scope)
                and r.coverage_complete
                and set(old.targets).issubset(r.passed_nodes)
                for r in runs
            )
        limited = next((r for r in runs if r.tool == old.tool and r.environment_id == old.environment_id
                        and r.source == "executed" and pytest_options_limited(r)), None)
        if passed and limited:
            copy.status, copy.verification = "awaiting_verification", "unverifiable"
            copy.note = "The recorded check passed. " + pytest_options_note(limited)
        elif passed and integrity.affects(session, old.tool):
            # The run passed, but not against the tests the problem was found with, or FixFirst
            # cannot tell whether they are the same.
            check = session.baseline_check
            if check["state"] == "changed":
                copy.status, copy.verification = "awaiting_verification", "not_comparable"
                copy.note = (
                    "Passes now, but tests or their settings changed since the baseline ("
                    + integrity.describe(check["changed"])
                    + "): restore them, or accept the new baseline, to verify the original problem"
                )
            else:
                copy.status, copy.verification = "awaiting_verification", "unverifiable"
                copy.note = (
                    "Passes now, but FixFirst cannot confirm that the tests are the ones of the baseline ("
                    + integrity.describe(check["unverifiable"], 2) + ")"
                )
        elif passed:
            copy.status, copy.verification = "resolved", "comparable"
            copy.note = (
                "All related test nodes passed in the same environment"
                if old.targets
                else "Each original declaration was verified as satisfied in the same environment"
                if old.tool == "project"
                else "Passed for real in the same environment and check scope"
            )
            baseline = integrity.current_baseline(session)
            if baseline.get("reason") == "accepted by the user" and old.tool in integrity.tools_of(
                    integrity.scope_of(session)):
                copy.note += (" (against the tests and settings accepted as the new baseline on "
                              + baseline["recorded_at"] + ")")
        elif (old.status != "resolved" and old.tool in updated_tools
              and (old.tool != "pip_install" or matching)):
            # Only a check of the same tool can fail to observe an issue; a round that ran
            # other checks (a release search, an environment snapshot) leaves it as it was.
            copy.status = "not_observed" if old.status != "awaiting_verification" else old.status
            copy.note = "Not covered by this round, or the check did not complete; earlier evidence is kept"
            if old.tool in updated_tools and not matching:
                copy.note = "Different environment or check scope; not directly comparable"
        if copy.status != old.status:
            changes.append({"issue_id": old.issue_id, "change": copy.status})
        fresh.append(copy)
    session.runs.extend(runs)
    session.events.extend(event_batch)
    session.issues = fresh
    session.history.append(
        {"time": now(), "kind": "checks", "run_ids": [r.run_id for r in runs], "changes": changes}
    )
    infer_and_plan(session)
    # A pass after the tests changed is a fact about that run, not a verified goal.
    if session.goal_status == "achieved" and integrity.affects(session, GOAL_CHECKS[session.goal]):
        session.goal_status = "unknown"
    # Prevent stale success after changing the target interpreter.
    target = GOAL_CHECKS[session.goal]
    last = next((r for r in reversed(session.runs) if r.tool == target), None)
    if last and last.environment_id != environment_id(session.target_python):
        session.goal_status = "unknown"


def scan(session, checks=None, timeout=DEFAULT_TIMEOUT, targets=None):
    if session.stopped:
        raise ValueError("This session is stopped; use resume before running checks")
    if checks is None:
        if session.goal in ("run_project", "pass_unittest", "check_style"):
            checks = ["environment", "project", GOAL_CHECKS[session.goal], "pip_check"]
            if session.goal != "check_style":
                checks.append("ruff")
        else:
            checks = [
                "pytest_run" if c == "pytest" and session.goal == "pass_tests" else c
                for c in DEFAULT_CHECKS
            ]
        optional_tools = session.goal in ("run_project", "pass_unittest")
    else:
        optional_tools = False
    if targets:
        if list(checks) not in (["pytest_run"], ["version_search"], ["dependency_resolve"]):
            raise ValueError("--nodes must be used on its own with --checks pytest_run")
        if checks == ["pytest_run"]:
            validate_targets(session, targets)
    if len(checks) != len(set(checks)):
        raise ValueError("The same check cannot appear twice in one batch")
    runs = []
    # The baseline is taken before any project code runs, and compared before and after the checks.
    before = integrity.before_checks(session)
    for check in checks:
        if check == "dependency_resolve":
            # The explicit trial must use today's declarations and interpreter,
            # even if it was selected from yesterday's report.
            refresh = [collect(session, "environment", timeout), collect(session, "project", timeout)]
            ingest(session, refresh)
        if optional_tools and check in ("pip_check", "ruff"):
            package = "pip" if check == "pip_check" else "ruff"
            if not any(p.get("name", "").lower() == package
                       for p in session.environment.get("packages", [])):
                continue
        if check in ("pytest", "pytest_run"):
            # A test-only rescan must not reuse declarations the user may have
            # edited since the previous scan. Planning continues to use records.
            if not any(r.tool == "environment" for r in runs):
                runs.append(collect(session, "environment", timeout))
            if not any(r.tool == "project" for r in runs):
                runs.append(collect(session, "project", timeout))
        # Declaration checks compare installed metadata. Always refresh that metadata as part
        # of this operation, including when a user runs the single project action after a fix.
        if check == "project" and not any(r.tool == "environment" for r in runs):
            runs.append(collect(session, "environment", timeout))
        run = collect(session, check, timeout, targets=targets)
        runs.append(run)
        if run.status == "cancelled":
            break
    from .install_feedback import collect_feedback
    from .evidence import project_index

    # Read only logs bound to suggested manual commands. Environment and project
    # checks above have refreshed the context; imported output cannot verify a goal.
    project_run = next((r for r in reversed(runs) if r.tool == "project"), None)
    if project_run:
        import json
        try:
            project = json.loads(project_run.stdout)
        except ValueError:
            project = {}
    else:
        _, project = project_index(session)
    runs.extend(collect_feedback(session, project))
    integrity.after_checks(session, before)
    ingest(session, runs)


def import_log(session, path, tool, exit_code=None):
    file = Path(path)
    if file.stat().st_size > MAX_OUTPUT:
        raise ValueError("Log is larger than 1 MB; split it by check run first")
    raw = file.read_bytes()
    # PowerShell 5.1 saves `pytest > log` as UTF-16; under cmd.exe it is in the ANSI code page.
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = raw.decode("utf-16", errors="replace")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode(locale.getpreferredencoding(False), errors="replace")
    text = redact(text.replace("\r\n", "\n").replace("\r", "\n"))
    run = Run(
        tool=tool,
        source="imported",
        stdout=text,
        exit_code=exit_code,
        cwd=session.project_root,
        scope="imported:" + file.name,
        environment_id="unknown",
    )
    run.notes.append("Imported log: its environment and full scope are unverified, so it never closes earlier issues.")
    ingest(session, [run])


def mark_fixed(session, issue_id):
    issue = next((i for i in session.issues if i.issue_id == issue_id), None)
    if issue is None:
        raise ValueError("No issue with this id")
    if issue.status == "resolved":
        raise ValueError("This issue is already verified as resolved")
    issue.status = "awaiting_verification"
    session.history.append({"time": now(), "kind": "manual_change", "issue_id": issue_id})
    infer_and_plan(session)
