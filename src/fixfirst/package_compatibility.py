"""Narrow, source-backed package repairs from the actual failed operation.

This policy suggests a resolver request, never an automatic installation or a
claim that a whole release interval fixes the application. No model features.
"""

from functools import lru_cache
from importlib import resources
import re

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from .domain import knowledge, tomllib
from .evidence import current_environment, issue_evidence, observed, project_index
from .models import Action, Fact, check_scope
from .runner import environment_id
from .tool_compatibility import _normal, _package_file, _stable

POLICY_ID = "package-compatibility:pkg_resources"
_UNOBSERVED = "The failed import or receiver was not observed"


@lru_cache(maxsize=1)
def load():
    data = tomllib.loads(resources.files("fixfirst").joinpath(
        "knowledge/package_compatibility.toml").read_text("utf-8"))
    entry = data["pkg_resources"]
    if (entry["distribution"] != "setuptools"
            or not Version(entry["fixed_version"]) < Version(entry["provider_removed"])):
        raise ValueError("Invalid pkg_resources compatibility policy")
    SpecifierSet(entry["python_specifier"])
    for field in ("fix_source", "removal_source", "provider_source"):
        if entry[field] not in data["sources"]:
            raise ValueError("Missing package compatibility source")
    return data


def _record(event, run):
    """Join only this event's uniquely matched structured exception."""
    records = []
    for ref in event.evidence_refs:
        prefix, _, index = ref.partition(":probe:")
        if prefix != run.run_id or not index.isdigit() or int(index) >= len(run.records):
            continue
        record = run.records[int(index)]
        if record.get("type") == "exception":
            records.append(record)
        elif record.get("type") == "failure":
            records += [r for r in run.records if r.get("type") == "exception"
                        and r.get("nodeid") == record.get("nodeid")
                        and r.get("stage") == record.get("stage")]
    unique = {id(r): r for r in records}
    return next(iter(unique.values())) if len(unique) == 1 else {}


def _unobserved_review(session, record, event):
    """Explain recorded context without turning it into operation evidence."""
    location = ""
    frames = record.get("traceback_frames", [])
    frames = frames[-20:] if isinstance(frames, list) else []
    root = _normal(session.project_root, session.project_root).rstrip("/") + "/"
    for frame in reversed(frames):
        if not isinstance(frame, dict):
            continue
        path, line = frame.get("file"), frame.get("line")
        if isinstance(path, str) and 0 < len(path) <= 4096 and type(line) is int and line > 0:
            path = _normal(path, session.project_root)
            if path.startswith(root):
                location = f" Inspect the recorded project frame at {path[len(root):]}:{line}."
                break
    if not location:
        path, line = record.get("source_file"), record.get("source_line")
        if isinstance(path, str) and 0 < len(path) <= 4096 and type(line) is int and line > 0:
            path = _normal(path, session.project_root)
            if path.startswith(root):
                path = path[len(root):]
            location = f" Inspect the recorded exception at {path}:{line}."
        elif event.location and len(event.location) <= 4096:
            kind = "collection node" if event.stage == "collect" else "failure location"
            location = f" Recorded {kind}: {event.location}."
    return (_UNOBSERVED + "; a direct pkg_resources import or its failing receiver was not verified."
            + location + " Check whether this code uses __import__ or importlib.import_module, "
            "or an exception was raised again. Trace those calls to the original failure; "
            "these are possibilities to inspect, not observed causes. Traceback text alone "
            "cannot select a setuptools repair.")


def _observation(session, issue, environment, project_run, project):
    """Only current native/probed pytest failures can license a package change."""
    current = environment_id(session.target_python)
    env_run = next((r for r in session.runs if r.run_id == environment.get("_run_id")), None)
    latest_env = next((r for r in reversed(session.runs) if r.tool == "environment"), None)
    run = next((r for r in reversed(session.runs) if r.tool == issue.tool), None)
    if (issue.tool not in {"python_run", "unittest_run", "pytest", "pytest_run"}
            or issue.environment_id != current or not project_run or not env_run or not run
            or latest_env is not env_run
            or any(r.source != "executed" or r.status != "completed" or r.truncated
                   or r.environment_id != current for r in (env_run, project_run, run))
            or env_run.exit_code != 0 or project_run.exit_code != 0
            or run.exit_code in (None, 0) or run.scope != issue.scope
            or (run.tool in {"python_run", "unittest_run"} and run.scope != check_scope(session, run.tool))
            or session.runs.index(env_run) >= session.runs.index(run)):
        return None, "Refresh the selected environment and project, then rerun the original failure."
    local = {r.get("name") for r in project.get("local_modules", [])}
    if local & {"pkg_resources", "setuptools", "pkgutil"}:
        return None, "Project modules shadow pkg_resources, setuptools or pkgutil; inspect the recorded local module first."
    packages = [p for p in environment.get("packages", [])
                if canonicalize_name(p.get("name", "")) == "setuptools"]
    providers = {canonicalize_name(p) for p in environment.get("import_distributions", {}).get("pkg_resources", [])}
    if len(packages) > 1 or (packages and not _stable(packages[0].get("version", ""))):
        return None, "The setuptools installation has ambiguous or unrecognised version metadata."
    version = packages[0]["version"] if packages else ""
    events = [e for e in session.events if e.event_id in issue.event_ids]
    if len(events) != len(issue.event_ids) or not events or any(e.run_id != run.run_id for e in events):
        return None, "The current issue is not linked to one current executed failure."
    matches, refs = [], []
    for event in events:
        record = _record(event, run)
        observed_failure = record.get("package_failure", {})
        if not isinstance(observed_failure, dict) or observed_failure.get("source") != "failed_instruction":
            return None, _unobserved_review(session, record, event)
        mechanism = observed_failure.get("mechanism")
        path = observed_failure.get("file", "")
        if not isinstance(path, str) or not path or type(observed_failure.get("line")) is not int:
            return None, "The failed operation lacks a bounded source location."
        expected = {"pkgutil_impimporter": "AttributeError", "missing_pkg_resources": "ModuleNotFoundError"}.get(mechanism)
        frames = record.get("traceback_frames", [])
        outer_frame = frames[-1] if isinstance(frames, list) and frames else {}
        wrapped = (record.get("exception_type") == "CollectError"
                   and record.get("exception_module") == "_pytest.nodes"
                   and record.get("stage") == "collect" and issue.tool in {"pytest", "pytest_run"}
                   and event.stage == "collect" and event.location == record.get("nodeid")
                   and isinstance(outer_frame, dict)
                   and record.get("source_file") == outer_frame.get("file")
                   and record.get("source_line") == outer_frame.get("line")
                   and observed_failure.get("wrapper") == "pytest_collect_error")
        source_record = record.get("package_failure_exception", {}) if wrapped else record
        if not isinstance(source_record, dict):
            source_record = {}
        message = record.get("exception_message", "")
        expected_message = ("module 'pkgutil' has no attribute 'ImpImporter'" if mechanism == "pkgutil_impimporter"
                            else "No module named 'pkg_resources'")
        if (not expected or observed_failure.get("exception_type") != expected or event.code != expected
                or not isinstance(message, str) or expected_message not in message
                or source_record.get("exception_type") != expected
                or _normal(source_record.get("source_file", ""), session.project_root) != _normal(path, session.project_root)
                or source_record.get("source_line") != observed_failure["line"]):
            return None, "The package observation does not match this exception's type and source location."
        if mechanism == "pkgutil_impimporter":
            stdlib = environment.get("paths", {}).get("stdlib", "")
            module_file = observed_failure.get("module_file", "")
            if (observed_failure.get("module") != "pkgutil" or not stdlib
                    or observed_failure.get("consumer") != "pkg_resources"
                    or not isinstance(module_file, str)
                    or _normal(module_file, session.project_root) != _normal(stdlib + "/pkgutil.py", session.project_root)
                    or not _package_file(path, "pkg_resources/__init__.py", session.project_root, environment)
                    or providers != {"setuptools"} or not version
                    or Version(version) >= Version(load()["pkg_resources"]["fixed_version"])):
                return None, "The failing pkgutil receiver and installed setuptools/pkg_resources owner are not established."
        elif mechanism == "missing_pkg_resources":
            if observed_failure.get("module") != "pkg_resources" or providers:
                return None, "Provider metadata conflicts with the observed missing pkg_resources import."
            if version and Version(version) < Version(load()["pkg_resources"]["provider_removed"]):
                return None, "This setuptools release should provide pkg_resources; inspect an incomplete installation or import path before changing versions."
        else:
            return None, "No supported setuptools failure mechanism was observed."
        matches.append(mechanism)
        refs += event.evidence_refs
        refs += [f"{run.run_id}:probe:{n}" for n, r in enumerate(run.records) if r is record]
    if len(set(matches)) != 1:
        return None, "Grouped failures disagree about the setuptools mechanism; rerun them separately."
    return {"mechanism": matches[0], "version": version,
            "refs": list(dict.fromkeys(refs + [f"{env_run.run_id}:stdout:1", f"{project_run.run_id}:stdout:1"]))}, ""


def _supported(environment):
    entry, python = load()["pkg_resources"], environment.get("python_version", "")
    return (_stable(python) and SpecifierSet(entry["python_specifier"]).contains(python)
            and environment.get("markers", {}).get("implementation_name") == entry["implementation"])


def _cause(match):
    return "missing_dependency" if match["mechanism"] == "missing_pkg_resources" and not match["version"] else "version_incompatibility"


def _knowledge():
    entry = load()["pkg_resources"]
    return [knowledge(POLICY_ID, field, entry[field], entry[source])
            for field, source in (("fixed_version", "fix_source"),
                                  ("provider_removed", "removal_source"),
                                  ("distribution", "provider_source"))]


def diagnoses(session, issues):
    """A deterministic contract, like observed-contract helpers, before planning.

    The stable policy identifier names this helper rather than a numbered engine
    rule. Inputs retain both the actual operation and the cited version bounds.
    """
    environment = current_environment(session)
    if not _supported(environment):
        return []
    project_run, project = project_index(session)
    facts = []
    known = _knowledge()
    for issue in issues:
        match, _ = _observation(session, issue, environment, project_run, project)
        if not match:
            continue
        observation = observed(issue.issue_id, "package_compatibility", match["mechanism"], match["refs"])
        facts += [observation, Fact(fact_id=f"{issue.issue_id}:{POLICY_ID}:diagnosis",
            subject=issue.issue_id, predicate="diagnosis", value=_cause(match), status="derived",
            rule_id=POLICY_ID, inputs=[observation.fact_id, *[f.fact_id for f in known]])]
    return [*known, *facts] if facts else []


def refine(session, actions, by_id, facts):
    environment = current_environment(session)
    project_run, project = project_index(session)
    entry = load()["pkg_resources"]
    candidates = []
    for issue in by_id.values():
        evidence = issue_evidence(session, issue)
        if (evidence.get("missing_module") == "pkg_resources"
                or "pkgutil.ImpImporter" in evidence.get("apis", [])):
            candidates.append(issue)
    if not candidates:
        return actions
    affected = {i.issue_id for i in candidates}
    matches, reasons, refs, confirmed = [], [], [], set()
    for issue in candidates:
        match, reason = _observation(session, issue, environment, project_run, project)
        if match:
            matches.append(match)
            confirmed.add(issue.issue_id)
            refs += match["refs"]
        else:
            reasons.append(reason)
    # Preserve established project-code and shadowing remedies. Only confirmed
    # package mechanisms replace an issue's other remedies; uncertain evidence
    # can suppress a setuptools command but cannot erase unrelated useful advice.
    def package_action(action):
        return (any(re.match(r"^(?:setuptools|pkg[-_]resources)(?:[<>=!~\[]|$)", s, re.I)
                    for s in action.command[4:])
                or (action.check in {"version_search", "dependency_resolve"}
                    and action.targets and canonicalize_name(action.targets[0]) == "setuptools"))
    had_package_action = any(package_action(a) for a in actions)
    if not matches and not had_package_action:
        if (all(i.diagnosis == "local_module" for i in candidates)
                or not any(issue_evidence(session, i).get("missing_module") == "pkg_resources"
                           for i in candidates)):
            return actions
    actions = [a for a in actions if a.kind == "rerun" or not (
        confirmed.intersection(a.issue_ids) or package_action(a))]
    python = environment.get("python_version", "unknown")
    if not _supported(environment):
        reasons.append(f"This repair policy is limited to CPython {entry['python_specifier']}; selected Python: {python}. Review a supported interpreter or migrate the pkg_resources consumer.")
    for row in project.get("requires_python", []):
        try:
            supported = SpecifierSet(row["specifier"]).contains(python)
        except (InvalidSpecifier, ValueError, KeyError, TypeError):
            supported = False
        if not supported:
            reasons.append(f"{row.get('source', 'Project Requires-Python')} requires Python {row.get('specifier', 'unknown')}, incompatible with or unverified for {python}.")
    from .dependency_context import context
    data = context(environment, project)
    if data["notes"]:
        reasons.append("Requirement metadata is incomplete: " + "; ".join(data["notes"]) + ".")
    refs += [ref for i in candidates for ref in i.evidence_refs]
    fact = observed("dist:setuptools", "package_repair_evidence", "; ".join(sorted(set(
        m["mechanism"] for m in matches))) or "unconfirmed", list(dict.fromkeys(refs)))
    knowledge_facts = _knowledge()
    facts += [f for f in [fact, *knowledge_facts] if f.fact_id not in {x.fact_id for x in facts}]
    command = []
    explanation = " ".join(dict.fromkeys(reasons))
    title = "Review pkg_resources ownership and compatibility before changing setuptools"
    if any(reason.startswith(_UNOBSERVED) for reason in reasons):
        title = "Inspect the recorded pkg_resources failure before changing setuptools"
    if not reasons:
        direction = "Install"
        if any(m["mechanism"] == "pkgutil_impimporter" for m in matches):
            direction = "Update"
            explanation = "The actual failure is setuptools' pkg_resources accessing the removed standard-library pkgutil.ImpImporter. "
        elif any(m["version"] for m in matches):
            direction = "Downgrade"
            explanation = "The executed import needs pkg_resources, which was removed from the installed setuptools release. "
        else:
            explanation = "The executed import needs pkg_resources and the selected environment has no recorded setuptools provider. "
        requested = f"setuptools>={entry['fixed_version']},<{entry['provider_removed']}"
        title = f"{direction} setuptools within the pkg_resources compatibility range"
        command = [session.target_python, "-m", "pip", "install", requested]
        explanation += (f"Request {requested}: the lower bound fixes the removed pkgutil API use; "
                        "the upper bound keeps the legacy provider. Migrate the consumer to importlib.metadata "
                        "or importlib.resources when possible. This is a candidate range for the observed "
                        "CPython 3.12 failure, not a guarantee for every release or application.")
    actions.append(Action(action_id="repair-pkg-resources", kind="manual_fix", title=title,
        explanation=explanation, command=command, issue_ids=sorted(affected), rule_ids=[POLICY_ID],
        reason_refs=[f.fact_id for f in [fact, *knowledge_facts]],
        cause=_cause(matches[0]) if len(matches) == len(candidates) and _supported(environment) else None,
        goal_impact=2, evidence_rank=3 if not reasons else 2,
        verification="Check pip output and pip check, then rerun the original check with the same interpreter and execution settings"))
    return actions
