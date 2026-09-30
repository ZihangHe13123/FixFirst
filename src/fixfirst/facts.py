"""What FixFirst observed, and nothing it concluded: the facts-only view.

For the agent experiment's "facts" arm (experiments/agent_baseline): the interpreter, the checks
that ran and how they ended, each current failure's exception, message and where it was raised,
the names involved, what the environment snapshot and the project index say about each module,
and pip check's conflicts, as FixFirst recorded them. Left out on purpose: root-cause labels and
parser categories, rule conclusions and knowledge-base facts, model predictions, the order of
importance, release searches (they recommend versions) and fixes. Those are what the full
diagnosis adds; leaving them out separates the value of the evidence from the value of the advice.

The view is built from an allowlist of fields, never by removing fields from the diagnosis, so a
field added to the diagnosis later cannot leak into it.
"""

import json

from packaging.utils import canonicalize_name

from .evidence import current_environment, issue_evidence, module_context, project_index
from .models import Session

FAILING_TOOLS = ("pytest", "pytest_run", "python_run", "unittest_run")
HIDDEN_TOOLS = ("version_search", "pip_install")  # release searches recommend versions
MAX_FAILURES = 8
MAX_TESTS = 5
TEXT_LIMIT = 600
EVIDENCE_KEYS = ("exception", "message", "stage", "raised_in", "where", "source_location", "library")
NAME_KEYS = ("missing_module", "modules", "apis", "attributes", "kwargs", "config_keys", "missing_files", "fixtures")
TOP_LEVEL_KEYS = ("facts_only", "project", "python", "goal", "execution", "checks", "failures", "more_failures",
                  "modules", "declared_python", "pip_conflicts", "check_errors", "lint_findings")


def _clip(text, limit=TEXT_LIMIT) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + " ..."


def _latest_runs(session: Session) -> dict:
    latest = {}
    for run in session.runs:
        if run.source == "executed" and run.tool not in HIDDEN_TOOLS:
            latest[run.tool] = run
    return latest


def facts_view(session: Session) -> dict:
    latest = _latest_runs(session)
    current = {run.run_id for run in latest.values()}
    events = {event.event_id: event for event in session.events}
    environment = current_environment(session)
    _, project = project_index(session)
    versions = {canonicalize_name(p.get("name", "")): p.get("version", "") for p in environment.get("packages", [])}

    failures, conflicts, check_errors, lint = [], [], [], 0
    for issue in session.issues:
        own = [events[e] for e in issue.event_ids if e in events]
        now = [e for e in own if e.run_id in current]  # seen in the latest run of its check
        if not now:
            continue
        if issue.tool == "pip_check":
            conflicts += [_clip(e.message, 300) for e in now]
        elif issue.tool == "ruff":
            lint += len(now)
        elif issue.tool in FAILING_TOOLS and issue.kind != "tool_failure":
            failures.append(issue)
        elif issue.kind == "tool_failure":
            check_errors.append({"check": issue.tool, "message": _clip(now[0].message, 300)})

    items, modules = [], set()
    for issue in failures[:MAX_FAILURES]:
        evidence = issue_evidence(session, issue)
        item = {"check": issue.tool}
        if issue.targets:
            item["tests"] = issue.targets[:MAX_TESTS]
            if len(issue.targets) > MAX_TESTS:
                item["more_tests"] = len(issue.targets) - MAX_TESTS
        item.update({key: _clip(evidence[key]) for key in EVIDENCE_KEYS if evidence.get(key)})
        names = {key: evidence[key] for key in NAME_KEYS if evidence.get(key)}
        if names:
            item["names"] = names
        warnings = [
            {"category": w.get("category", ""), "message": _clip(w.get("message"), 200), "origin": w.get("origin", "")}
            for w in evidence.get("warnings", [])[:3]
        ]
        if warnings:
            item["recorded_warnings"] = warnings
        items.append(item)
        modules.update(evidence.get("modules", []))
        if evidence.get("missing_module"):
            modules.add(evidence["missing_module"])
            modules.add(evidence["missing_module"].split(".")[0])

    module_facts = {}
    declarations = {row["name"]: row for row in project.get("declarations", [])}
    for module in sorted(modules):
        context = module_context(session, module, project)
        entry = {}
        if "." not in module and environment:
            entry["installed"] = [
                f"{name} {versions.get(canonicalize_name(name), '')}".strip() for name in context["installed"]
            ]
        if context["stdlib"]:
            entry["standard_library"] = True
        if context["local"]:
            entry["project_files"] = context["local"]
        if context["similar"]:
            entry["similar_project_files"] = context["similar"]
        declared = [
            f"{row['requirement']} in {row['source']}"
            for name in (module, *context["installed"])
            if (row := declarations.get(canonicalize_name(name)))
        ]
        if declared:
            entry["declared"] = sorted(set(declared))
        module_facts[module] = entry

    view = {
        "facts_only": True,
        "project": session.project_root,
        "python": {"path": session.target_python, "version": environment.get("python_version", "unknown")},
        "goal": session.goal,
        "checks": [
            {"check": run.tool, "status": run.status, "exit_code": run.exit_code,
             **({"counts": counts} if (counts := {k: v for k, v in run.test_summary.items() if isinstance(v, int)})
                else {})}
            for run in latest.values()
        ],
        "failures": items,
    }
    if session.execution:
        execution = session.execution
        view["execution"] = {"kind": execution.kind, "entry": execution.entry, "args": execution.args,
                             "stdin_given": bool(execution.stdin)}
    if len(failures) > MAX_FAILURES:
        view["more_failures"] = len(failures) - MAX_FAILURES
    if module_facts:
        view["modules"] = module_facts
    if project.get("requires_python"):
        view["declared_python"] = [f"{row['specifier']} in {row['source']}" for row in project["requires_python"]]
    if conflicts:
        view["pip_conflicts"] = conflicts
    if check_errors:
        view["check_errors"] = check_errors
    if lint:
        view["lint_findings"] = lint
    return view


def render_facts(session: Session) -> str:
    return json.dumps(facts_view(session), ensure_ascii=False, separators=(",", ":"))
