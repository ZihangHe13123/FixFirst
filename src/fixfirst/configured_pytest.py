"""One bounded confirmation with the project's own pytest addopts.

The fixed-options run remains a fact about that check. A configured run earns
verification only with the same tests, configuration and complete node set.
"""

import configparser
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import time
import re

from . import integrity
from .test_results import _display_only, summarize_tests

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

CONFIG_NAMES = ("pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml",
                "pytest.toml", ".pytest.toml")
REPAIR_KEYS = {"pythonpath", "DJANGO_SETTINGS_MODULE"}
MAX_CONFIG_BYTES = 128000
MAX_CONFIG_FILES = 256
NOTICE = ("This confirmation uses the project's pytest options and may write coverage data "
          "or test reports. Those reports do not replace verification of the original tests.")
TESTS_CHANGED = "The tests or their settings changed, or could not be compared with the baseline."
NOT_STARTED = "The project pytest options check did not start or was interrupted; inspect its recorded output."
BLOCKED = {"--collect-only", "--co", "--setup-only", "--setup-plan", "--help", "-h", "--version", "-V",
           "--pdb", "--trace", "--pdbcls", "--debug", "--rootdir", "--confcutdir", "--noconftest",
           "--override-ini", "--config-file", "-c", "-o", "-p", "--pyargs",
           "--numprocesses", "--dist", "--tx", "--workers", "--tests-per-worker", "--max-worker-restart",
           "--rsyncdir", "--rsyncignore", "--looponfail", "--forked", "--boxed", "-f"}


def words(value):
    if isinstance(value, str):
        try:
            return shlex.split(value)
        except ValueError:
            return None
    return value if isinstance(value, list) and all(isinstance(v, str) for v in value) else None


def blocked_options(tokens):
    for word in tokens:
        if (word == "--" or word.split("=", 1)[0] in BLOCKED
                or word.startswith(("-n", "-c", "-o", "-p"))
                # argparse also permits flag clusters such as -qn2. Do not let
                # clustering hide an execution/configuration/worker switch.
                or re.match(r"^-[qvxs]+[ncophVf]", word)):
            return True
    return False


def read_config(path, root):
    """One bounded, nonblocking read, with no links or project-external paths."""
    path, root = Path(path), Path(root).resolve()
    if not path.is_absolute():
        path = root / path
    if not path.resolve().is_relative_to(root):
        raise ValueError("the pytest configuration is outside the project")
    relative = path.relative_to(root)
    if any((root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
        raise ValueError("the pytest configuration uses a symbolic link")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                 | getattr(os, "O_BINARY", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("the pytest configuration is not a regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(MAX_CONFIG_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > MAX_CONFIG_BYTES:
        raise ValueError("the pytest configuration exceeds the observation limit")
    return data


def _options(path, data):
    text = data.decode("utf-8-sig")
    if path.suffix == ".toml":
        parsed = tomllib.loads(text)
        if path.name in {"pytest.toml", ".pytest.toml"}:
            options = parsed.get("pytest", {})
            relevant = True
        else:
            table = parsed.get("tool", {}).get("pytest")
            relevant = table is not None
            # Keep both native and ini tables, preserving every exact key.
            options = table if table is not None else {}
        if not isinstance(options, dict):
            raise ValueError("the pytest configuration is not a table")
        options = dict(options)
        if isinstance(options.get("ini_options"), dict):
            options["ini_options"] = {k: v for k, v in options["ini_options"].items() if k not in REPAIR_KEYS}
        options = {k: v for k, v in options.items() if k not in REPAIR_KEYS}
    else:
        parser = configparser.RawConfigParser(interpolation=None, strict=True)
        parser.optionxform = str
        parser.read_string(text)
        section = "tool:pytest" if path.name == "setup.cfg" else "pytest"
        relevant = parser.has_section(section) or path.name in {"pytest.ini", ".pytest.ini"}
        options = {k: v.strip() for k, v in parser.items(section) if k not in REPAIR_KEYS} if parser.has_section(section) else {}
    return relevant, hashlib.sha256(json.dumps(options, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def snapshot(session):
    root = Path(session.project_root)
    base = integrity.current_baseline(session)
    folders = {root}
    for name in base.get("files", {}):
        folder = (root / name).parent
        while folder != root and folder.is_relative_to(root):
            folders.add(folder)
            folder = folder.parent
    result = {"settings": {}, "bytes": {}, "problems": []}
    for folder in sorted(folders):
        for name in CONFIG_NAMES:
            path = folder / name
            if not path.exists() and not path.is_symlink():
                continue
            key = path.relative_to(root).as_posix()
            if len(result["bytes"]) >= MAX_CONFIG_FILES:
                result["problems"].append("too many possible pytest configuration files")
                return result
            try:
                data = read_config(path, root)
                result["bytes"][key] = hashlib.sha256(data).hexdigest()
                relevant, options = _options(path, data)
                if relevant:
                    result["settings"][key] = options
            except (OSError, ValueError, configparser.Error, TypeError, AttributeError) as exc:
                result["problems"].append(f"{key}: {exc}")
    return result


def before_checks(session, new_baseline):
    if session.goal != "pass_tests":
        return None
    current = snapshot(session)
    base = integrity.current_baseline(session)
    first_pytest_check = new_baseline and not any(r.tool in {"pytest", "pytest_run"} for r in session.runs)
    if first_pytest_check or base.get("reason") == "accepted by the user" and "configured_pytest" not in base:
        base["configured_pytest"] = {k: current[k] for k in ("settings", "problems")}
    return current


def _integrity_reason(session, before, runs=()):
    base = integrity.current_baseline(session)
    guard = base.get("configured_pytest")
    if not guard:
        return "This older session has no complete pytest configuration baseline; start a new session or accept a new baseline."
    current = snapshot(session)
    if guard["problems"] or before["problems"] or current["problems"]:
        return "The pytest configuration could not be read completely."
    if current["settings"] != guard["settings"] or before["settings"] != guard["settings"]:
        return "The pytest configuration files or protected options changed since the baseline."
    if current["bytes"] != before["bytes"]:
        return "The pytest configuration changed during this check."
    # Include newly collected files when comparing against the original baseline.
    original = session.runs
    try:
        session.runs = [*original, *runs]
        checked = integrity.compare(session, integrity.scope_of(session), base)
    finally:
        session.runs = original
    if checked["changed"] or checked["unverifiable"]:
        return TESTS_CHANGED
    return ""


def _observe_reason(session, run, before):
    opts = run.pytest_options
    path = opts.get("config_file")
    if not path:
        return "The active pytest configuration file could not be identified."
    try:
        digest = hashlib.sha256(read_config(path, session.project_root)).hexdigest()
        key = Path(path).relative_to(session.project_root).as_posix()
    except (OSError, ValueError):
        return "The active pytest configuration is outside the project, unsafe or unreadable."
    if not (digest == before["bytes"].get(key) == opts.get("config_file_sha256")):
        return "The active pytest configuration could not be bound to this check's unchanged file."
    return ""


def _annotate(run, state, reason, **evidence):
    run.pytest_options["configured_verification"] = {"schema_version": 1, "state": state,
                                                     "reason": reason, **evidence}
    if reason and reason not in run.notes:
        run.notes.append(reason)


def _failure_reason(session, first, second, before, reason):
    """Describe an already rejected confirmation; never change its verdict."""
    finish = [row for row in second.records if row.get("type") == "finish"]
    if second.status != "completed" or second.truncated or len(finish) != 1:
        return reason
    final = finish[0]
    nodes = final.get("nodes")
    if (not isinstance(nodes, list) or not all(isinstance(node, str) for node in nodes)
            or len(set(nodes)) != len(nodes) or len(nodes) != final.get("collected")
            or final.get("exit_code") != second.exit_code or final.get("collect_only") is not False
            or final.get("records_dropped") is not False):
        return reason
    if reason == NOT_STARTED and second.exit_code == 5 and not nodes:
        return "The original tests did not run with the project pytest options."
    expected, observed = set(first.passed_nodes), set(nodes)
    if (reason == TESTS_CHANGED and second.exit_code in (0, 1) and observed - expected
            # A source repair can become a newly collected doctest, or a document
            # can be outside the baseline's Python files. Keep actual changes to
            # the original tests/configuration ahead of this node-set explanation.
            and not _integrity_reason(session, before, [first])):
        return (f"The project pytest options ran a different node set: {len(expected - observed)} original node(s) missing, "
                f"{len(observed - expected)} additional node(s).")
    return reason


def follow_up(session, first, before, timeout, started, collect, targets=None):
    """Return at most one real follow-up. No retry, shell or automatic installation."""
    if session.goal != "pass_tests" or first.tool != "pytest_run" or first.source != "executed":
        return None
    from .legacy_pytest import normalize_records

    normalize_records(first)
    summarize_tests(first)
    opts = first.pytest_options
    if (first.status != "completed" or first.truncated or not first.verified_pass or not first.coverage_complete
            or first.test_summary.get("skipped") or first.test_summary.get("xfail_or_xpass")
            or opts.get("config_complete") is not True):
        return None
    if _display_only(opts.get("config_addopts")) is not False:
        return None
    if _display_only(opts.get("environment_addopts")) is not True:
        # External non-display options retain their existing manual boundary.
        return None
    reason = _integrity_reason(session, before, [first]) or _observe_reason(session, first, before)
    tokens = words(opts.get("config_addopts"))
    if not reason and (tokens is None or blocked_options(tokens)):
        reason = "The project pytest options change execution, configuration or parallel workers; verify them manually."
    remaining = timeout - (time.monotonic() - started)
    if not reason and remaining <= 0:
        reason = "No time remains for confirmation with the project pytest options."
    if reason:
        _annotate(first, "blocked", reason)
        return None
    second = collect(session, "pytest_run", remaining, targets=targets, _configured=True)
    normalize_records(second)
    summarize_tests(second)
    proof = {"first_run_id": first.run_id, "config_file_sha256": opts["config_file_sha256"],
             "first_nodes": first.passed_nodes.copy(), "environment_id": first.environment_id,
             "scope": first.scope, "cwd": first.cwd}
    _annotate(first, "superseded", "", followup_run_id=second.run_id)
    second.notes.append(NOTICE)
    reason = _integrity_reason(session, before, [first, second])
    if not reason and second.status != "completed":
        reason = "The project pytest options check did not complete: " + second.status + "."
    if not reason and second.exit_code not in (0, 1):
        reason = NOT_STARTED
    reason = reason or _observe_reason(session, second, before)
    if not reason and (second.environment_id != first.environment_id or second.scope != first.scope
                       or second.cwd != first.cwd or words(second.pytest_options.get("config_addopts")) != tokens):
        reason = "The confirmation did not use the same environment, scope and project options."
    nodes = {node for row in second.records if row.get("type") == "finish"
             and isinstance(row.get("nodes"), list) for node in row["nodes"] if isinstance(node, str)}
    expected = set(first.passed_nodes)
    if not reason:
        if second.status != "completed" or second.truncated:
            reason = "The project pytest options check did not complete: " + second.status + "."
        elif second.exit_code not in (0, 1):
            reason = NOT_STARTED
        elif second.exit_code != 0:
            reason = "Tests still failed with the project pytest options."
        elif nodes != expected:
            reason = (f"The project pytest options ran a different node set: {len(expected - nodes)} original node(s) missing, "
                      f"{len(nodes - expected)} additional node(s).")
        elif not second.coverage_complete or not second.verified_pass or set(second.passed_nodes) != expected:
            reason = "The project pytest options did not prove every original node passed with complete records; skips and xfail are not fixes."
    verdict = "failed" if reason else "confirmed"
    if reason:
        reason = _failure_reason(session, first, second, before, reason)
    _annotate(second, verdict, reason, **proof)
    if not reason:
        second.notes = [n for n in second.notes if not n.startswith("This result covers FixFirst's check without")]
    return second


def state(run):
    data = run.pytest_options.get("configured_verification", {})
    return data if run.source == "executed" and run.tool == "pytest_run" and data.get("schema_version") == 1 else {}


def confirmed(run):
    data = state(run)
    return bool(data.get("state") == "confirmed" and run.status == "completed" and not run.truncated
                and run.exit_code == 0 and run.coverage_complete and run.verified_pass
                and run.pytest_options.get("config_complete") is True
                and run.environment_id == data.get("environment_id") and run.scope == data.get("scope")
                and run.cwd == data.get("cwd") and run.pytest_options.get("config_file_sha256") == data.get("config_file_sha256")
                and set(run.passed_nodes) == set(data.get("first_nodes", [])) and run.passed_nodes
                and not run.test_summary.get("skipped") and not run.test_summary.get("xfail_or_xpass"))


def verification_runs(runs):
    """A failed configured check cannot inherit verification from the first pass."""
    return [run for run in runs if state(run).get("state") not in {"superseded", "failed"}]


def note(run):
    data = state(run)
    if data.get("state") == "confirmed" and confirmed(run):
        return "Verified with the project's pytest options. " + NOTICE
    return data.get("reason", "") if data.get("state") in {"blocked", "failed"} else ""
