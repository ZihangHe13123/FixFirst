"""Bounded observations of specific test-tool failures and their repair context.

No classifier features are added here. Raw signatures and actual failing frames
are observed first; source-cited version intervals are matched by the rule engine.
Older text-only conftest reports that hide the tool frame remain unconfirmed.
"""

import posixpath
import re

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .runner import environment_id


def _normal(path, root):
    path = str(path).replace("\\", "/")
    if path.startswith("<"):
        return path
    if not path.startswith("/") and not re.match(r"^[A-Za-z]:/", path):
        path = root.replace("\\", "/").rstrip("/") + "/" + path
    path = posixpath.normpath(path)
    return path.casefold() if re.match(r"^[A-Za-z]:/", path) else path


def _package_file(path, relative, root, environment):
    path = _normal(path, root)
    return any(path == _normal(base.rstrip("/\\") + "/" + relative, root)
               for name, base in environment.get("paths", {}).items()
               if name in {"purelib", "platlib"} and isinstance(base, str) and base)


def _stable(value):
    try:
        version = Version(value)
    except (InvalidVersion, TypeError):
        return False
    return not (version.is_prerelease or version.is_devrelease or version.local or version.is_postrelease)


def _context(session, issue, run):
    """Use only this issue's referenced failure and matching exception records."""
    from .evidence import frames_in

    pieces, paths, refs = [], [], []
    events = [e for e in session.events if e.event_id in issue.event_ids]
    if len(events) != 1 or {e.run_id for e in events} != {run.run_id}:
        return None
    for event in events:
        for ref in event.evidence_refs:
            prefix, _, index = ref.partition(":probe:")
            if prefix == run.run_id and index.isdigit() and int(index) < len(run.records):
                record = run.records[int(index)]
                if record.get("type") != "failure":
                    continue
                text = record.get("message", "")
                if not isinstance(text, str) or len(text) >= 32000:
                    return None
                pieces.append(text)
                refs.append(ref)
                matches = [(n, r) for n, r in enumerate(run.records)
                           if r.get("type") == "exception" and r.get("nodeid") == record.get("nodeid")
                           and r.get("stage") == record.get("stage")]
                if len(matches) > 1:
                    return None
                paths += [path for path, _ in frames_in(text)]
                if matches:
                    n, record = matches[0]
                    paths += [r["file"] for r in record.get("traceback_frames", [])
                              if isinstance(r, dict) and isinstance(r.get("file"), str)]
                    if record.get("source_file"):
                        paths.append(record["source_file"])
                    refs.append(f"{run.run_id}:probe:{n}")
            else:
                parts = ref.split(":")
                if (len(parts) != 3 or parts[0] != run.run_id or parts[1] not in {"stdout", "stderr"}
                        or not parts[2].isdigit()):
                    continue
                lines = getattr(run, parts[1]).splitlines()
                end = int(parts[2])
                if not 0 < end <= len(lines):
                    return None
                # Keep the complete current error block, never a neighbouring failure.
                start = 0
                for n, line in enumerate(lines[:end]):
                    if ("ERROR collecting " in line or line.startswith("ImportError while loading conftest")
                            or line == "Traceback (most recent call last):"):
                        start = n
                text = "\n".join(lines[start:end])
                if len(text) > 64000:
                    return None
                pieces.append(text)
                paths += [path for path, _ in frames_in(text)]
                refs.append(ref)
    text = "\n".join(pieces)
    if len(pieces) != 1 or not text or not paths or re.search(r"\.\.\. (?:\d+ )?(?:frames|lines|characters).*?(?:omitted|hidden|skipped)", text):
        return None
    return text, paths, list(dict.fromkeys(refs)), events


def _signature(context, session, environment, py_provider):
    from .evidence import classify_path

    if not context:
        return None
    text, paths, refs, events = context
    codes = {e.code for e in events}
    root = session.project_root
    nonstdlib = [p for p in paths if classify_path(p, root, environment) != "stdlib"]
    if not nonstdlib:
        return None
    last = nonstdlib[-1]
    if (codes == {"AttributeError"} and py_provider
            and re.search(r"(?:^|\n)(?:E\s+)?AttributeError:\s*['\"]?__spec__['\"]?\s*$", text)
            and _package_file(last, "py/_vendored_packages/apipkg/__init__.py", root, environment)
            and "__makeattr" in text):
        return "py-apipkg-spec", "py", refs
    if (codes == {"DeprecationWarning"}
            and re.search(r"(?:^|\n)(?:E\s+)?DeprecationWarning:\s*ast\.Str is deprecated\b[^\n]*use ast\.Constant instead", text)
            and _package_file(last, "_pytest/assertion/rewrite.py", root, environment)
            and any(classify_path(p, root, environment) == "stdlib"
                    and _normal(p, root).endswith("/ast.py") for p in paths)):
        return "pytest-ast-str", "pytest", refs
    return None


def observations(session, issues):
    from .evidence import current_environment, observed, project_index

    environment = current_environment(session)
    project_run, project = project_index(session)
    current = environment_id(session.target_python)
    env_run = next((r for r in session.runs if r.run_id == environment.get("_run_id")), None)
    if not (project_run and env_run and env_run.source == "executed" and env_run.status == "completed"
            and env_run.exit_code == 0 and not env_run.truncated and project_run.status == "completed"
            and project_run.exit_code == 0 and not project_run.truncated):
        return [], {}
    packages = {}
    for package in environment.get("packages", []):
        packages.setdefault(canonicalize_name(package.get("name", "")), []).append(package.get("version", ""))
    local = {r.get("name") for r in project.get("local_modules", [])}
    providers = environment.get("import_distributions", {})

    def provider(module, distribution):
        return (module not in local and len(packages.get(distribution, [])) == 1
                and _stable(packages[distribution][0])
                and {canonicalize_name(x) for x in providers.get(module, [])} == {distribution})

    if not provider("_pytest", "pytest") or not _stable(environment.get("python_version", "")):
        return [], {}
    facts, details = [], {}
    for issue in issues:
        if issue.tool not in {"pytest", "pytest_run"} or issue.environment_id != current:
            continue
        run = next((r for r in reversed(session.runs) if r.tool == issue.tool), None)
        if (not run or run.environment_id != current or run.source != "executed"
                or run.status != "completed" or run.truncated or run.exit_code in (None, 0)
                or run.scope != issue.scope):
            continue
        if session.runs.index(env_run) >= session.runs.index(run):
            continue
        if run.tool_version not in ("", "unknown", packages["pytest"][0]):
            continue
        # A grouped issue must not borrow the message from one failure and the
        # tool frame from another. Each member must independently match the same
        # mechanism; one unknown/conflicting member prevents the strong diagnosis.
        matches = [_signature(_context(session, issue.model_copy(update={"event_ids": [event_id]}), run),
                              session, environment, provider("py", "py")) for event_id in issue.event_ids]
        if not matches or any(m is None for m in matches) or len({m[:2] for m in matches}) != 1:
            continue
        key, distribution = matches[0][:2]
        refs = list(dict.fromkeys(ref for match in matches for ref in match[2]))
        refs += [f"{env_run.run_id}:stdout:1", f"{project_run.run_id}:stdout:1"]
        entity = "tool-failure:" + key
        facts += [observed(issue.issue_id, "tool_failure_symptom", entity, refs),
                  observed(issue.issue_id, "tool_failure_provider", "dist:" + distribution, refs)]
        details[issue.issue_id] = {"entity": entity, "distribution": distribution,
                                   "version": packages[distribution][0],
                                   "python": environment["python_version"],
                                   "warning_filters": project.get("pytest_warning_filters", [])}
    return facts, details


def refine(session, actions, details, facts):
    """Explain only observed filter settings, retaining constraint-refined actions."""
    for action in actions:
        if "P85" not in action.rule_ids:
            continue
        matches = [details[i].get("tool_failure") for i in action.issue_ids if i in details]
        matches = [m for m in matches if m]
        if not matches:
            continue
        match = matches[0]
        if match["entity"] == "tool-failure:pytest-ast-str":
            action.explanation += (
                " The deprecation warning terminated this check as an exception. "
                "Do not delete the warning policy merely to make the check pass.")
            rows = match.get("warning_filters", [])
            recorded = [f"{r['source']}: {', '.join(r['filters'])}" for r in rows
                        if isinstance(r, dict) and isinstance(r.get("source"), str)
                        and isinstance(r.get("filters"), list) and all(isinstance(v, str) for v in r["filters"])]
            if recorded:
                action.explanation += " Recorded project filterwarnings settings: " + "; ".join(recorded) + "."
            action.explanation += " Command-line or environment filters can also affect this; their source is not inferred from the exception."
        action.explanation += (
            " A separate environment on an older Python is a second route if the legacy stack must remain; "
            "its availability and this project's success have not been verified here. "
            "After changing the named package, rerun pip check and the original command, preserving its warning filters.")
    return actions
