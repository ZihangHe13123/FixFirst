"""Snapshot-backed pytest configuration recipes; never change project files."""

import json
import posixpath
import re

from packaging.version import InvalidVersion, Version

from .runner import environment_id
from .test_results import pytest_option_coverage
from .tool_compatibility import _normal, _package_file


SOURCE = "https://docs.pytest.org/en/stable/reference/customize.html"
PLUGIN_SOURCE = "https://pytest-django.readthedocs.io/en/latest/configuring_django.html"
SUPPORT_SOURCE = "https://pytest-django.readthedocs.io/en/latest/changelog.html"


def version(text):
    try:
        result = Version(text)
        return result if not (result.is_prerelease or result.is_devrelease or result.is_postrelease or result.local or result.epoch) else None
    except (InvalidVersion, TypeError):
        return None


def selection(session, action, environment):
    issues = [i for i in session.issues if i.issue_id in action.issue_ids]
    if not issues or len(issues) != len(set(action.issue_ids)):
        return None, "The current failure's pytest configuration was not recorded."
    event_ids = {e for i in issues for e in i.event_ids}
    events = [e for e in session.events if e.event_id in event_ids]
    run_ids = {e.run_id for e in events}
    if (len(events) != len(event_ids) or len(run_ids) != 1
            or any(i.tool not in {"pytest", "pytest_run"} for i in issues)):
        return None, "The failures do not share one observed pytest invocation."
    run = next((r for r in session.runs if r.run_id in run_ids), None)
    current = environment_id(session.target_python)
    if (not run or run.source != "executed" or run.status != "completed" or run.truncated
            or type(run.exit_code) is not int or run.exit_code == 0 or run.cwd != session.project_root or run.environment_id != current
            or any(i.environment_id != current or i.scope != run.scope for i in issues)
            or run is not next((r for r in reversed(session.runs) if r.tool == run.tool and r.scope == run.scope), None)):
        return None, "Recollect the configuration with the current interpreter and original failing scope."
    snapshots = [r for r in session.runs if r.run_id == environment.get("_run_id")]
    project = next((r for r in reversed(session.runs) if r.tool == "project"), None)
    if (not snapshots or not project or any(session.runs.index(r) > session.runs.index(run) for r in [snapshots[0], project])
            or any(e.tool != run.tool for e in events)):
        return None, "The environment snapshot is newer than this failure; rerun the original check."
    if pytest_option_coverage(run) != "equivalent":
        return None, "The bounded check did not establish your original pytest options; confirm its selected configuration with your original command."
    record = run.pytest_options.get("persistent_config")
    if (not isinstance(record, dict) or type(record.get("schema_version")) is not int
            or record["schema_version"] != 1 or record.get("complete") is not True
            or record.get("safe_file") is not True):
        return None, "No complete persistent configuration snapshot was recorded; rerun the original check."
    root = _normal(session.project_root, session.project_root)
    if not isinstance(record.get("rootdir"), str) or _normal(record["rootdir"], session.project_root) != root:
        return None, "The observed pytest root is outside this project; review the intended configuration."
    pytest = version(record.get("pytest_version"))
    if not pytest or pytest < Version("7") or pytest >= Version("10"):
        return None, "This configuration route requires a known pytest release from 7 through 9."
    if not isinstance(environment.get("packages"), list):
        return None, "The environment's pytest version could not be established."
    packages = [p.get("version") for p in environment["packages"]
                if isinstance(p, dict) and str(p.get("name", "")).casefold() == "pytest"]
    if packages != [str(pytest)]:
        return None, "The observed pytest release does not match the environment snapshot."
    file = run.pytest_options.get("config_file")
    if not isinstance(file, str) or len(file) > 4096 or "<" in file or any(ord(c) < 32 for c in file):
        return None, "The selected configuration path is incomplete."
    name = posixpath.relpath(_normal(file, session.project_root), root) if file else "pytest.ini"
    if name == ".." or name.startswith("../") or name in {".", ""}:
        return None, "The selected configuration is outside this project; do not create an overriding file."
    syntax, section = record.get("syntax"), record.get("section")
    expected = ("toml", "pytest") if name.rsplit("/", 1)[-1] in {"pytest.toml", ".pytest.toml"} else (
        ("toml", section) if name.rsplit("/", 1)[-1] == "pyproject.toml" and section in {"tool.pytest", "tool.pytest.ini_options"}
        else ("ini", "tool:pytest") if name.endswith(".cfg") else ("ini", "pytest") if name.endswith(".ini") else None)
    if expected != (syntax, section) or syntax == "toml" and section in {"pytest", "tool.pytest"} and pytest < Version("9"):
        return None, "The selected file's configuration syntax was not confirmed."
    values = record.get("values")
    if (not isinstance(values, dict) or not isinstance(values.get("pythonpath"), list)
            or len(values["pythonpath"]) > 50
            or not all(isinstance(v, str) and len(v) < 4096 and "<" not in v and not any(ord(c) < 32 for c in v) for v in values["pythonpath"])
            or not isinstance(values.get("DJANGO_SETTINGS_MODULE"), str)):
        return None, "Existing configuration values were not completely recorded."
    return {**record, "file": name, "new_file": not bool(file), "run_id": run.run_id}, None


def snippet(config, key, value):
    if config["syntax"] == "toml":
        assignment = f"{key} = {json.dumps(value, ensure_ascii=False)}"
    elif isinstance(value, list):
        assignment = key + " =\n" + "\n".join("    " + json.dumps(v, ensure_ascii=False) for v in value)
    else:
        assignment = f"{key} = {value}"
    return (f"{'Create' if config['new_file'] else 'Update'} {config['file']} [{config['section']}] "
            f"with this {key} option (keep every other option and test unchanged):\n"
            f"```{config['syntax']}\n[{config['section']}]\n{assignment}\n```\n"
            "Update the existing section instead of duplicating its header. ")


def import_recipe(config, relative):
    if (not isinstance(relative, str) or not relative or posixpath.isabs(relative)
            or re.match(r"^[A-Za-z]:", relative) or ".." in relative.split("/") or "\\" in relative
            or any(ord(c) < 32 for c in relative)):
        return None
    candidate = posixpath.relpath(relative, posixpath.dirname(config["file"]) or ".")
    values = config["values"]["pythonpath"]
    directory = posixpath.dirname(config["file"])
    if any(posixpath.normpath(posixpath.join(directory, old)) == relative for old in values):
        return None
    return snippet(config, "pythonpath", [*values, candidate])


def django_plugin_candidate(environment):
    """Fixed, source-cited candidates, not a minimum release or a completed dependency trial."""
    installed = {str(p.get("name", "")).casefold().replace("_", "-"): p.get("version")
                 for p in environment.get("packages", []) if isinstance(p, dict)}
    python, django, pytest = (version(environment.get("python_version")), version(installed.get("django")),
                              version(installed.get("pytest")))
    if not python or not django or not pytest or not Version("7") <= pytest < Version("10"):
        return None
    py = python.release[:2]
    dj = django.release[:2]
    if dj == (4, 2) and (3, 8) <= py <= (3, 12) and (py < (3, 12) or django >= Version("4.2.8")):
        candidate = "4.11.1"
    elif dj == (5, 0) and (3, 10) <= py <= (3, 12):
        candidate = "4.11.1"
    elif dj == (5, 1) and (3, 10) <= py <= (3, 13) and (py < (3, 13) or django >= Version("5.1.3")):
        candidate = "4.11.1"
    elif dj == (5, 2) and (3, 10) <= py <= (3, 14) and (py < (3, 14) or django >= Version("5.2.8")):
        candidate = "4.14.0" if py == (3, 14) else "4.11.1"
    elif dj == (6, 0) and (3, 12) <= py <= (3, 14):
        candidate = "4.14.0"
    else:
        return None
    return [f"pytest-django=={candidate}", f"Django=={django}", f"pytest=={pytest}"]


def django_recipe(config, module, environment, root):
    if (not isinstance(module, str) or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module, re.ASCII)
            or any(not isinstance(config.get(k), str) or config[k] and config[k] != module
                   for k in ("settings_environment", "settings_cli"))
            or config["values"]["DJANGO_SETTINGS_MODULE"] not in {"", module}):
        return None, [], "An existing settings source or override conflicts with this candidate; reconcile it first."
    loaded = (isinstance(environment.get("paths"), dict) and config.get("django_option_registered") is True
              and isinstance(config.get("django_plugin_file"), str)
              and _package_file(config["django_plugin_file"], "pytest_django/plugin.py", root, environment))
    if not loaded and config.get("plugin_autoload_disabled") is not False:
        return None, [], "pytest-django was not loaded and plugin autoload is disabled or unknown; review the intended plugin-loading policy first."
    requirements = []
    if not loaded:
        installed = [p for p in environment.get("packages", []) if isinstance(p, dict)
                     and str(p.get("name", "")).casefold().replace("_", "-") == "pytest-django"]
        if installed:
            return None, [], "pytest-django is installed but was not loaded; correct the runner's plugin policy before adding its configuration."
        requirements = django_plugin_candidate(environment)
        if requirements is None:
            return None, [], "No compatible pytest-django candidate is established for these recorded Python/Django/pytest versions; review the test dependencies together."
    return snippet(config, "DJANGO_SETTINGS_MODULE", module), requirements, None
