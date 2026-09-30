import hashlib
import json
import os
from pathlib import Path
import re
import shlex
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
    "run_project": "Run the program successfully",
    "pass_unittest": "Pass the unittest suite",
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
    "python_run": "Program execution",
    "unittest_run": "Unittest run",
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
    """Quote a command for the user's own terminal (PowerShell on Windows, as in the README)."""
    if os.name != "nt":
        return shlex.join(argv)
    words = []
    for word in argv:
        if not re.fullmatch(r"[\w.:\\/=+-]+", word):
            # PowerShell single quotes; it also reads typographic quotes as quotes.
            word = "'" + re.sub("(['‘-‛])", r"\1\1", word) + "'"
        words.append(word)
    # A quoted first word is only a string in PowerShell: the call operator runs it.
    return ("& " if words and words[0].startswith("'") else "") + " ".join(words)


ENV.filters["shell"] = shell
ENV.globals["command_shell"] = "PowerShell" if os.name == "nt" else "a terminal"


def public_entity(session: Session, entity: str | None):
    if entity in {a.action_id for a in session.actions}:
        return "action-" + hashlib.sha256(entity.encode("utf-8")).hexdigest()[:24]
    return entity


def public_question(session: Session, question: str) -> str:
    """Keep references to local actions usable in a question about the public graph."""
    ids = {a.action_id: public_entity(session, a.action_id) for a in session.actions}
    if not ids:
        return question
    # Match a complete ID once: an action ID can be a prefix of another one, and
    # public IDs already copied from an exported graph must remain unchanged.
    # IDs use ASCII word characters; adjacent Chinese prose is not part of an ID.
    choices = "|".join(re.escape(key) for key in sorted(ids, key=len, reverse=True))
    return re.sub(r"(?<![A-Za-z0-9_.-])(?:" + choices + r")(?![A-Za-z0-9_-]|\.[A-Za-z0-9_-])",
                  lambda match: ids[match[0]], question)


_PATH_ROOT = re.compile(r"[A-Za-z]:[\\/]|/|\\\\|<(?:project|python)>")
_QUOTED_PATH_START = re.compile(r"""['"](?:[A-Za-z]:[\\/]|/|\\\\|<(?:project|python)>)""")


def _quoted_path_spans(value):
    """Scan disjoint spans, including unfinished paths, without retrying suffixes.

    A single quote followed by a space may still be inside a name (O' Brien).
    Defer that boundary until the rest of the path is seen. A new absolute path,
    a separately quoted phrase or field value, or a newline bounds the search.
    Every scanned character is consumed even when there is no closing quote.
    """
    cursor = 0
    while match := _QUOTED_PATH_START.search(value, cursor):
        start = match.start()
        quote = value[start]
        closing = None
        cursor = match.end()
        while cursor < len(value) and value[cursor] not in "\r\n":
            char = value[cursor]
            if closing is not None and char in "\"'":
                # A quoted field or collection entry starts a new value, even
                # with a different quote type, an empty value or leading spaces.
                # Only revisit the whitespace immediately before this quote.
                previous = cursor - 1
                while previous > closing and value[previous].isspace():
                    previous -= 1
                if value[previous] in "=:([{,":
                    break
            if char == quote:
                # Adjacent malformed path fragments also start a fresh span.
                if _PATH_ROOT.match(value, cursor + 1):
                    break
                if (closing is not None and value[cursor - 1].isspace()
                        and cursor + 1 < len(value) and not value[cursor + 1].isspace()):
                    break
                if (quote == '"' or cursor + 1 == len(value)
                        or not (value[cursor + 1].isalnum() or value[cursor + 1] in "_\\/")):
                    closing = cursor
                    if quote == '"':
                        cursor += 1
                        break
            elif (closing is not None and value[cursor - 1].isspace()
                  and _PATH_ROOT.match(value, cursor)):
                break
            cursor += 1
        yield start, cursor, closing


def public_data(session: Session):
    replacements = sorted([(session.project_root, "<project>"),
                           (session.target_python, "<python>")], key=lambda p: len(p[0]), reverse=True)
    ids = {a.action_id: public_entity(session, a.action_id) for a in session.actions}
    # Unquoted paths still need to distinguish an internal apostrophe from a
    # trailing quote, while allowing space-containing username components.
    username = r"""[^\\/\r\n"']+(?:'(?=[^\s\\/\r\n"']|[^\\/\r\n"']*[\\/])[^\\/\r\n"']*)*"""

    def replace_path(value, private, alias):
        # Raw text, JSON-escaped text, slash paths and case-insensitive drive paths.
        windows = bool(re.match(r"^[A-Za-z]:[\\/]|^\\\\", private))
        if windows:
            pattern = r"[\\/]+".join(re.escape(p) for p in re.split(r"[\\/]+", private))
            return re.sub(pattern, lambda _: alias, value, flags=re.IGNORECASE)
        return value.replace(private, alias)

    def clean_paths(value, quoted=False):
        if not value:
            return value
        component = r"[^\\/\r\n]+" if quoted else username
        # Consume the drive too before the POSIX spelling can match /Users/.
        value = re.sub(r"(?i)[A-Za-z]:[\\/]+Users[\\/]+(?:" + component + ")", "<home>", value)
        value = re.sub(r"/(?:Users|home)/(?:" + component + ")", "<home>", value)
        return re.sub(r"(?i)([\\/])pytest-of-(?:" + component + ")", r"\1pytest-of-user", value)

    def clean(value):
        if isinstance(value, str):
            if value in ids:
                return ids[value]
            # Environment snapshots and Ruff output contain JSON inside a string.
            # Decode it first so redaction cannot corrupt quotes or escaped paths.
            if value.lstrip().startswith(("{", "[")):
                try:
                    embedded = json.loads(value)
                except ValueError:
                    pass
                else:
                    return json.dumps(clean(embedded), ensure_ascii=False)
            # Known paths have exact bounds, even with ambiguous quotes in names.
            for private, alias in replacements:
                value = replace_path(value, private, alias)
            parts, end = [], 0
            for start, stop, closing in _quoted_path_spans(value):
                parts.append(clean_paths(value[end:start]))
                if closing is None:
                    parts.append(value[start] + clean_paths(value[start + 1:stop]))
                else:
                    parts.append(value[start] + clean_paths(value[start + 1:closing], quoted=True) + value[closing])
                    parts.append(clean_paths(value[closing + 1:stop]))
                end = stop
            parts.append(clean_paths(value[end:]))
            return redact("".join(parts))
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {clean(k): clean(v) for k, v in value.items()}
        return value

    data = clean(session.model_dump())
    if data.get("execution"):
        data["execution"]["stdin"] = "[input omitted]" if session.execution.stdin else ""
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
