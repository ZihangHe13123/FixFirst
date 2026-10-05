"""Copied into the grader, loaded before project collection. No FixFirst imports."""

import json
import os
from pathlib import Path
import shlex

ALLOWED = {"pythonpath", "DJANGO_SETTINGS_MODULE"}
_record = {"schema": 1, "policy": "h5-v1", "started": True, "complete": False,
           "errors": [], "nodes": [], "outcomes": {}}
_root = None


def _value(value):
    if isinstance(value, dict):
        return {str(k): _value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_value(v) for v in value]
    if isinstance(value, Path) or type(value).__name__ == "LocalPath":
        try:
            return {"project_path": Path(str(value)).relative_to(_root).as_posix()}
        except ValueError:
            return {"external_path": str(value)}
    # pytest 9 wraps each raw value in ConfigValue; pytest <=8 uses strings/lists.
    if type(value).__name__ == "ConfigValue" and hasattr(value, "value"):
        return _value(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"cannot record configuration value of type {type(value).__name__}")


def _save():
    path = Path(os.environ["FIXFIRST_H5_REPORT"])
    path.write_text(json.dumps(_record, sort_keys=True), encoding="utf-8")


_save()  # A broken/missing pytest is a failed check, even before its hooks can run.
import pytest  # noqa: E402


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    global _root
    _root = Path.cwd()
    try:
        ini = getattr(config, "inipath", None) or getattr(config, "inifile", None)
        name = Path(str(ini)).relative_to(_root).as_posix() if ini else None
        raw, effective = {}, {}
        for key, value in config.inicfg.items():
            if key in ALLOWED:
                continue
            raw[key] = _value(value)
            if key == "addopts" and isinstance(raw[key], str):
                raw[key] = shlex.split(raw[key])
            try:
                effective[key] = {"registered": True, "value": _value(config.getini(key))}
            except ValueError as error:
                if key in config._parser._inidict:
                    raise error
                effective[key] = {"registered": False, "value": _value(value)}
        _record["config"] = {"file": name, "raw": raw, "effective": effective}
    except (ValueError, TypeError, AttributeError) as error:
        _record["errors"].append(f"configuration: {type(error).__name__}: {error}")
    _save()


@pytest.hookimpl(trylast=True)
def pytest_collection_finish(session):
    _record["nodes"] = [item.nodeid for item in session.items]
    _save()


def pytest_runtest_logreport(report):
    previous = _record["outcomes"].get(report.nodeid)
    if report.failed:
        outcome = "failed" if report.when == "call" else "error"
    elif report.skipped:
        outcome = "xfailed" if hasattr(report, "wasxfail") else "skipped"
    elif report.when == "call":
        outcome = "xpassed" if hasattr(report, "wasxfail") else "passed"
    else:
        return
    if previous not in {"failed", "error"}:
        _record["outcomes"][report.nodeid] = outcome


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    _record.update(complete=True, exit_code=int(exitstatus))
    _save()
