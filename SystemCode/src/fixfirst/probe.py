"""Copied into an isolated temporary directory; imports only stdlib in the target env."""

import json
import hashlib
import os
import importlib.util
from pathlib import Path
import shlex
import stat
import sys
import traceback

_runtime_spec = importlib.util.spec_from_file_location(
    "_fixfirst_runtime_evidence", Path(__file__).with_name("_runtime_evidence.py"))
_runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(_runtime)

_dropped = False
# Project fixtures may replace or clear os.environ after the probe is loaded.
_probe_path = os.environ.get("FIXFIRST_PROBE")
_important_path = _probe_path + ".important" if _probe_path else None
IMPORTANT_BYTES = 8_000_000

# Pytest's streams already use UTF-8. Its tests' children must inherit the user's
# encoding policy, not FixFirst's transport setting.
if "FIXFIRST_USER_IOENCODING" in os.environ:
    _encoding = os.environ.pop("FIXFIRST_USER_IOENCODING")
    if _encoding:
        os.environ["PYTHONIOENCODING"] = _encoding
    else:
        os.environ.pop("PYTHONIOENCODING", None)


def emit(data, final=False):
    global _dropped
    path = _probe_path
    if not path:
        return
    text = json.dumps(data, ensure_ascii=True) + "\n"
    over_limit = not final and (
        len(text) > 100000 or (os.path.exists(path) and os.path.getsize(path) + len(text) > 800000)
    )
    if over_limit:
        important = data.get("type") in ("failure", "exception") or (
            data.get("type") == "outcome" and data.get("outcome") == "failed")
        if not important:
            _dropped = True
            return
        # Passing phases cannot spend the independent budget for failure evidence.
        path = _important_path
        if len(text) > IMPORTANT_BYTES or (os.path.exists(path) and os.path.getsize(path) + len(text) > IMPORTANT_BYTES):
            _dropped = True
            return
    with open(path, "a", encoding="utf-8") as file:
        file.write(text)


def record_pytest_options(config):
    """Observe the active file's original addopts, before project conftests run.

    Older pytest keeps original values in inicfg. Newer pytest has already merged
    -o overrides into _inicfg; its own reader can read the one file it selected.
    Never search for a different config or parse options back into the command.
    """
    record = {"type": "pytest_config", "config_complete": False, "config_file": "",
              "config_addopts": None}
    try:
        path = getattr(config, "inipath", None) or getattr(config, "inifile", None)
        record["config_file"] = str(path) if path else ""
        if hasattr(config, "_inicfg"):
            reader = getattr(sys.modules.get("_pytest.config.findpaths"), "load_config_dict_from_file", None)
            if path and reader is None:
                raise ValueError("Active pytest configuration reader is unavailable")
            values = (reader(Path(path)) or {}) if path else {}
        else:
            values = config.inicfg
        value = values.get("addopts", "")
        value = getattr(value, "value", value)  # pytest's newer ConfigValue wrapper
        if not (isinstance(value, str) or isinstance(value, list) and all(isinstance(v, str) for v in value)):
            raise ValueError("Original pytest addopts are not text or a list of text")
        if len(json.dumps(value)) > 16000 or len(record["config_file"]) > 4096:
            raise ValueError("Original pytest options exceed the observation limit")
        record.update(config_addopts=value, config_complete=True)
        if path:
            try:
                path = Path(path)
                if path.is_symlink():
                    raise ValueError("Linked configuration")
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                             | getattr(os, "O_BINARY", 0))
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        raise ValueError("Unsafe configuration")
                    with os.fdopen(fd, "rb", closefd=False) as stream:
                        data = stream.read(128001)
                finally:
                    os.close(fd)
                if len(data) <= 128000:
                    record["config_file_sha256"] = hashlib.sha256(data).hexdigest()
            except BaseException:
                # Optional binding must not change existing option observation.
                pass
        try:
            record["persistent_config"] = persistent_config(config, path, values)
        except BaseException:
            record["persistent_config"] = {"schema_version": 1, "complete": False}
    except BaseException:
        # Observing configuration must not alter the check or its exception outcome.
        record["observation_error"] = "The original pytest options could not be recorded"
    try:
        emit(record)
    except BaseException:
        pass


def persistent_config(config, path, values):
    """Observe only the selected file and two settings; never import project modules."""
    syntax, section, safe = "ini", "pytest", True
    if path:
        path = Path(path)
        safe = not path.is_symlink() and stat.S_ISREG(path.stat().st_mode)
        if not safe or path.stat().st_size > 128000:
            raise ValueError("Unsafe configuration")
        if path.suffix == ".cfg":
            section = "tool:pytest"
        elif path.suffix == ".toml":
            try:
                import tomllib
            except ModuleNotFoundError:
                import tomli as tomllib
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError("Unsafe configuration")
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    text = stream.read(128001)
            finally:
                os.close(fd)
            if len(text) > 128000:
                raise ValueError("Large configuration")
            data = tomllib.loads(text.decode("utf-8"))
            syntax = "toml"
            if path.name in {"pytest.toml", ".pytest.toml"}:
                section = "pytest"
            elif path.name == "pyproject.toml":
                table = data.get("tool", {}).get("pytest", {})
                native = {k: v for k, v in table.items() if k != "ini_options"}
                section = "tool.pytest" if native else "tool.pytest.ini_options"
            else:
                raise ValueError("Unknown TOML configuration")
        elif path.suffix != ".ini":
            raise ValueError("Unknown configuration format")
    selected = {}
    for name, default in (("pythonpath", []), ("DJANGO_SETTINGS_MODULE", "")):
        value = values.get(name, default)
        value = getattr(value, "value", value)
        if name == "pythonpath" and isinstance(value, str):
            value = shlex.split(value)
        if name == "pythonpath":
            if not isinstance(value, list) or len(value) > 50 or not all(isinstance(v, str) for v in value):
                raise ValueError("Unknown import paths")
        elif not isinstance(value, str):
            raise ValueError("Unknown settings module")
        selected[name] = value
    plugins = {id(p): p for _, p in config.pluginmanager.list_name_plugin()
               if getattr(p, "__name__", None) == "pytest_django.plugin"}
    plugin_file = getattr(next(iter(plugins.values())), "__file__", "") if len(plugins) == 1 else ""
    result = {"schema_version": 1, "complete": True, "safe_file": safe,
              "rootdir": str(getattr(config, "rootpath", None) or config.rootdir),
              "pytest_version": str(getattr(sys.modules.get("pytest"), "__version__", "")),
              "syntax": syntax, "section": section, "values": selected,
              "django_plugin_file": plugin_file,
              "django_option_registered": "DJANGO_SETTINGS_MODULE" in config._parser._inidict,
              "plugin_autoload_disabled": bool(os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD")),
              "settings_environment": os.environ.get("DJANGO_SETTINGS_MODULE", ""),
              "settings_cli": getattr(config.option, "ds", None) or ""}
    if len(json.dumps(result)) > 16000:
        raise ValueError("Large configuration observation")
    return result


def pytest_load_initial_conftests(early_config):
    """Retain the actual startup exception before pytest hides its internal frames.

    The hook wrapper observes the existing outcome; it never retries, suppresses,
    or replaces the failure. In particular a project's own warning stays a
    project warning even when pytest's displayed traceback is shortened.
    """
    record_pytest_options(early_config)
    outcome = yield
    try:
        info = outcome.excinfo
        if not info:
            return
        kind, value, tb = info
        # pytest wraps a failed conftest import and later hides the tool frames.
        if kind.__name__ == "ConftestImportFailure" and kind.__module__.startswith("_pytest."):
            inner = getattr(value, "excinfo", None)
            if isinstance(inner, tuple) and len(inner) == 3:
                kind, value, tb = inner
            else:
                cause = getattr(value, "cause", None)
                if isinstance(cause, BaseException):
                    kind, value, tb = type(cause), cause, cause.__traceback__
        if tb is None:
            return
        last = tb
        while last.tb_next:
            last = last.tb_next
        node = "<initial-conftest>"
        emit({"type": "failure", "stage": "collect", "nodeid": node,
              "message": "".join(traceback.format_exception(kind, value, tb))[:32000]})
        emit({"type": "exception", "stage": "collect", "nodeid": node,
              "exception_type": kind.__name__, "exception_module": kind.__module__,
              "exception_message": str(value)[:16000],
              "source_file": last.tb_frame.f_code.co_filename, "source_line": last.tb_lineno,
              **_runtime.exception_metadata(value, tb)})
    except BaseException:
        # An observation failure must not alter pytest's original error outcome.
        pass


# Equivalent to hookimpl(hookwrapper=True, tryfirst=True); retain this copied
# probe's stdlib-only imports, including before conftest loading succeeds.
pytest_load_initial_conftests.pytest_impl = {"hookwrapper": True, "tryfirst": True}


def pytest_collectreport(report):
    if report.failed:
        emit(
            {
                "type": "failure",
                "stage": "collect",
                "nodeid": report.nodeid,
                "message": str(report.longrepr)[:32000],
            }
        )


def pytest_runtest_logreport(report):
    # pytest 9 reports every subtest; thousands of passing ones would crowd out the records
    # that matter. Failing subtests are kept.
    if type(report).__name__ == "SubtestReport" and not report.failed:
        return
    emit(
        {
            "type": "outcome",
            "stage": report.when,
            "nodeid": report.nodeid,
            "outcome": report.outcome,
            "wasxfail": hasattr(report, "wasxfail"),
        }
    )
    if report.failed:
        emit(
            {
                "type": "failure",
                "stage": report.when,
                "nodeid": report.nodeid,
                "message": str(report.longrepr)[:32000],
            }
        )


def pytest_exception_interact(node, call, report):
    if call.excinfo is not None:
        # Structured exception metadata avoids guessing from words inside assertion text or
        # from an earlier, handled exception in a chained traceback.
        entry = call.excinfo.traceback[-1] if call.excinfo.traceback else None
        try:
            message = str(call.excinfo.value)[:16000]
        except Exception:
            message = "The exception text could not be converted; see the full traceback"
        emit(
            {
                "type": "exception",
                "nodeid": report.nodeid,
                "stage": getattr(report, "when", "collect"),
                "exception_type": call.excinfo.type.__name__,
                "exception_message": message,
                "exception_module": call.excinfo.type.__module__,
                "source_file": str(entry.path) if entry else "",
                "source_line": entry.lineno + 1 if entry else None,
                **_runtime.exception_metadata(call.excinfo.value, call.excinfo.value.__traceback__),
                "warnings": recorded_warnings(call.excinfo.traceback),
            }
        )


def recorded_warnings(traceback, limit=20):
    """Warnings held by recwarn / pytest.warns recorders in the failing frames.

    A test that counts warnings fails when the environment adds some; the recorder shows
    which ones they were and where they came from.
    """
    found, seen = [], set()
    try:
        for entry in traceback:
            for name, value in list(entry.frame.f_locals.items()):
                if id(value) in seen or not any(
                    c.__name__ == "WarningsRecorder" for c in type(value).__mro__
                ):
                    continue
                seen.add(id(value))
                for item in list(getattr(value, "list", []))[: limit - len(found)]:
                    found.append(
                        {
                            "recorder": name,
                            "category": getattr(item.category, "__name__", str(item.category)),
                            "message": str(item.message)[:500],
                            "filename": str(item.filename),
                            "lineno": item.lineno,
                        }
                    )
    except Exception:
        pass
    return found


def pytest_sessionfinish(session, exitstatus):
    nodes = [item.nodeid for item in session.items]
    bounded = len(nodes) <= 5000 and sum(len(n) for n in nodes) <= 100000
    emit(
        {
            "type": "finish",
            "exit_code": int(exitstatus),
            "collected": session.testscollected,
            "collect_only": bool(session.config.option.collectonly),
            "nodes": nodes if bounded else [],
            "records_dropped": _dropped or not bounded,
        },
        final=True,
    )
