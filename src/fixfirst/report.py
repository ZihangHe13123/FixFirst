import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from jinja2 import Environment, PackageLoader, select_autoescape

from . import domain
from .knowledge_graph import build_graph, query_graph
from .models import Session
from .runner import redact
from .storage import atomic_write

GOALS = {
    "collect_tests": "Restore test collection",
    "check_style": "Pass the code check",
    "pass_tests": "Pass the test suite",
}
STATES = {
    "open": "Still failing",
    "resolved": "Verified fixed",
    "not_observed": "Not checked this round",
    "awaiting_verification": "Awaiting verification",
    "unknown": "Not enough information",
}
TOOL_NAMES = {
    "environment": "Environment snapshot",
    "project": "Project declarations",
    "pip_check": "Dependency consistency",
    "pip_install": "Installation log",
    "pytest": "Test collection",
    "pytest_run": "Test run",
    "ruff": "Code check",
}
DEPENDENCY_STATES = {
    "satisfied": "Satisfied",
    "missing": "Required dependency missing",
    "version_mismatch": "Version does not match",
    "python_mismatch": "Python version does not match",
    "inactive_marker": "Environment marker not active",
    "optional": "Optional group, not assumed enabled",
    "constraint_only": "Constraint file, not an install list",
    "direct_reference": "Direct reference, not verified",
    "ambiguous_install": "Several versions found; check",
    "unknown": "Not enough evidence",
}
ENV = Environment(loader=PackageLoader("fixfirst", "templates"), autoescape=select_autoescape(["html"]))


def shell(argv: list[str]) -> str:
    """Quote a command for the user's own terminal."""
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


ENV.filters["shell"] = shell


def public_data(session: Session):
    replacements = [(session.project_root, "<project>"), (session.target_python, "<python>")]

    def clean(value):
        if isinstance(value, str):
            for private, alias in replacements:
                value = value.replace(private, alias)
            value = re.sub(r"/(?:Users|home)/[^/\s]+", "<home>", value)
            value = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", "<home>", value)
            return redact(value)
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value

    data = clean(session.model_dump())
    data["model_path"] = "<local-model>" if session.model_path else None
    data["sbert_model"] = "<local-model>" if session.sbert_model else None
    return data


def html(session: Session, store_root: Path, public=False, live: dict | None = None) -> tuple[str, dict, dict]:
    """Render the report page; ``live`` enables the local web interface's controls."""
    from .reasoning import rule_base

    data = public_data(session) if public else session.model_dump()
    graph = build_graph(Session.model_validate(data))
    views = [
        query_graph(graph, "why", n["id"])
        for n in graph["nodes"]
        if n["type"] in ("Goal", "Action", "Issue")
    ]
    counts = {state: sum(i.status == state for i in session.issues) for state in STATES}
    command_prefix = shell([sys.executable, "-m", "fixfirst", "--store", str(store_root)])
    commands = {}
    for action in session.actions:
        if action.check and not action.blocked_reasons and not public:
            commands[action.action_id] = f"{command_prefix} run {session.session_id} {action.action_id}"
    latest = {}
    for run in data["runs"]:
        latest[run["tool"]] = run
    project = {}
    if "project" in latest:
        try:
            project = json.loads(latest["project"]["stdout"])
            if not isinstance(project, dict):
                project = {}
        except ValueError:
            pass
    rules = {r.rule_id: {"description": r.description, "phase": r.phase} for r in rule_base()}
    sources = {}
    for fact in session.facts:
        for ref in fact.evidence_refs:
            if domain.source(ref):
                sources[ref] = domain.source(ref)
    text = ENV.get_template("report.html").render(
        session=data,
        goal_name=GOALS[session.goal],
        goals=GOALS,
        states=STATES,
        tools=TOOL_NAMES,
        counts=counts,
        commands=commands,
        latest=latest,
        public=public,
        live=live,
        graph=graph,
        graph_views=views,
        project=project,
        rules=rules,
        sources=sources,
        causes=domain.load()["causes"],
        dependency_states=DEPENDENCY_STATES,
    )
    return text, data, graph


def render(session: Session, store_root: Path, output: Path, public=False):
    text, data, graph = html(session, store_root, public)
    atomic_write(output, text)
    atomic_write(output.with_suffix(".json"), json.dumps(data, ensure_ascii=False, indent=2))
    atomic_write(output.with_suffix(".graph.json"), json.dumps(graph, ensure_ascii=False, indent=2))
    return output
