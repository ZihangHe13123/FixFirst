"""Candidate classifier inputs from raw failures and current environment data.

No knowledge table, diagnosis, issue category, rule result or repair is read.
Unknown is -1, including missing old probe fields; observed false is 0.
"""

import re

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .runner import environment_id
from .tool_compatibility import _normal


FEATURE_NAMES = [
    "raw_terminal_warning",
    "raw_operation_test_tool_owned",
    "raw_message_settings_unconfigured",
    "raw_message_apps_not_ready",
    "raw_global_registry_apps_ready",
    "raw_global_registry_loading",
    "raw_missing_pkg_resources",
    "raw_setuptools_installed",
    "raw_python_release",
    "raw_pytest_release",
    "raw_py_release",
    "raw_setuptools_release",
]
TOOLS = {"_pytest": "pytest", "pytest": "pytest", "py": "py", "pluggy": "pluggy"}
SETTINGS_MESSAGE = re.compile(
    r"Requested (?:setting [A-Za-z_]\w*|settings), but settings are not configured\. "
    r"You must either define the environment variable DJANGO_SETTINGS_MODULE "
    r"or call settings\.configure\(\) before accessing settings\."
)


def release(value):
    """Stable major*1_000_000 + minor*1_000 + patch; no affected-version table.

    Each component must be <1000, at most three components are accepted, and
    epoch/pre/dev/post/local versions are unknown. Missing components are zero.
    """
    try:
        version = Version(value)
    except (InvalidVersion, TypeError):
        return -1.0
    if (version.epoch or version.is_prerelease or version.is_devrelease or version.is_postrelease
            or version.local or len(version.release) > 3 or any(v >= 1000 for v in version.release)):
        return -1.0
    major, minor, patch = (*version.release, 0, 0)[:3]
    return float(major * 1_000_000 + minor * 1_000 + patch)


def _under(path, base, root):
    return bool(base) and _normal(path, root).startswith(_normal(base, root).rstrip("/") + "/")


def _provider(environment, project, module, distribution):
    installed = [p for p in environment.get("packages", []) if canonicalize_name(p.get("name", "")) == distribution]
    providers = {canonicalize_name(p) for p in environment.get("import_distributions", {}).get(module, [])}
    return (len(installed) == 1 and providers == {distribution}
            and module not in {p.get("name") for p in project.get("local_modules", [])})


def _package_path(path, environment, root):
    normal = _normal(path, root)
    for key in ("purelib", "platlib"):
        base = environment.get("paths", {}).get(key)
        if isinstance(base, str) and _under(path, base, root):
            return normal[len(_normal(base, root).rstrip("/")) + 1:]
    return None


def _operation(record, environment, project, root):
    frames = record.get("traceback_frames")
    if (not isinstance(frames, list) or not frames or not all(isinstance(f, dict) for f in frames)
            or frames[-1].get("file") != record.get("source_file")):
        return -1.0
    for frame in reversed(frames):
        path = frame.get("file")
        if not isinstance(path, str) or not path:
            return -1.0
        relative = _package_path(path, environment, root)
        if relative is not None:
            module = re.split(r"[/\\.]", relative)[0]
            if module not in TOOLS:
                return 0.0
            return 1.0 if _provider(environment, project, module, TOOLS[module]) else -1.0
        if _under(path, environment.get("paths", {}).get("stdlib", ""), root) or path.startswith("<frozen "):
            continue
        if _under(path, root, root):
            return 0.0
        return -1.0  # An external prefix is not the selected interpreter's tool.
    return -1.0


def _exception(event, run):
    refs = [ref for ref in event.evidence_refs if ref.startswith(run.run_id + ":probe:")]
    records = []
    for ref in refs:
        index = ref.rsplit(":", 1)[-1]
        if not index.isdigit() or int(index) >= len(run.records):
            return None
        records.append(run.records[int(index)])
    failures = [r for r in records if r.get("type") == "failure"]
    if len(failures) > 1:
        return None
    if failures:
        failure = failures[0]
        matches = [r for r in run.records if r.get("type") == "exception"
                   and (r.get("nodeid"), r.get("stage")) == (failure.get("nodeid"), failure.get("stage"))]
    else:
        matches = [r for r in records if r.get("type") == "exception"]
    if len(matches) != 1:
        return None
    record = matches[0]
    kind, message = record.get("exception_type"), record.get("exception_message")
    if (not isinstance(kind, str) or not isinstance(message, str) or len(message) >= 16000
            or not kind or kind == "CollectError" or kind != event.code):
        return None
    return record


def _member(record, environment, project, root):
    values = {name: -1.0 for name in FEATURE_NAMES}
    if record is None:
        return values
    kind, message = record["exception_type"], record["exception_message"]
    values["raw_terminal_warning"] = float(kind.endswith("Warning"))
    values["raw_message_settings_unconfigured"] = float(bool(SETTINGS_MESSAGE.fullmatch(message)))
    values["raw_message_apps_not_ready"] = float(message == "Apps aren't loaded yet.")
    values["raw_missing_pkg_resources"] = float(kind == "ModuleNotFoundError" and message == "No module named 'pkg_resources'")
    values["raw_operation_test_tool_owned"] = _operation(record, environment, project, root)
    registry = record.get("django_registry")
    frames = record.get("traceback_frames", [])
    if (isinstance(registry, dict) and registry.get("global_registry") is True
            and frames and isinstance(frames[-1], dict)
            and frames[-1].get("function") == "check_apps_ready"
            and frames[-1].get("file") == record.get("source_file")
            and _package_path(record.get("source_file", ""), environment, root) == "django/apps/registry.py"
            and _provider(environment, project, "django", "django")):
        for source, target in (("apps_ready", "raw_global_registry_apps_ready"), ("loading", "raw_global_registry_loading")):
            if type(registry.get(source)) is bool:
                values[target] = float(registry[source])
    return values


def feature_values(session, issue):
    """Each failure supplies its own values; mixed or missing members are unknown."""
    from .evidence import current_environment, project_index

    unknown = {name: -1.0 for name in FEATURE_NAMES}
    current = environment_id(session.target_python)
    if issue.tool not in {"pytest", "pytest_run"} or issue.environment_id != current:
        return unknown
    environment = current_environment(session)
    project_run, project = project_index(session)
    env_run = next((r for r in session.runs if r.run_id == environment.get("_run_id")), None)
    run = next((r for r in reversed(session.runs) if r.tool == issue.tool), None)
    if (not env_run or not project_run or not run or env_run.environment_id != current
            or not isinstance(environment.get("packages"), list)
            or any(r.source != "executed" or r.status != "completed" or r.truncated for r in (env_run, project_run, run))
            or env_run.exit_code != 0 or project_run.exit_code != 0 or run.exit_code in (None, 0)
            or run.environment_id != current or run.scope != issue.scope
            or project_run.scope != "declarations:project" or env_run.scope != "environment"
            or any(not r.cwd or _normal(r.cwd, session.project_root) != _normal(session.project_root, session.project_root)
                   for r in (env_run, project_run, run))
            or session.runs.index(env_run) >= session.runs.index(run)):
        return unknown
    events = [e for e in session.events if e.event_id in issue.event_ids]
    if (not events or len(events) != len(set(issue.event_ids))
            or any(e.run_id != run.run_id for e in events)):
        return unknown
    packages = {}
    for package in environment.get("packages", []):
        packages.setdefault(canonicalize_name(package.get("name", "")), []).append(package.get("version"))
    if run.tool_version not in ("", "unknown") and packages.get("pytest") != [run.tool_version]:
        return unknown
    members = [_member(_exception(event, run), environment, project, session.project_root) for event in events]
    values = {key: members[0][key] if all(m[key] == members[0][key] for m in members) else -1.0 for key in FEATURE_NAMES}
    values["raw_python_release"] = release(environment.get("python_version"))
    for distribution in ("pytest", "py", "setuptools"):
        versions = packages.get(distribution, [])
        values[f"raw_{distribution}_release"] = release(versions[0]) if len(versions) == 1 else -1.0
    versions = packages.get("setuptools", [])
    values["raw_setuptools_installed"] = -1.0 if len(versions) > 1 else float(bool(versions))
    return values
