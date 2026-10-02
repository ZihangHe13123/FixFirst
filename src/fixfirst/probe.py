"""Copied into an isolated temporary directory; imports only stdlib in the target env."""

import json
import os
import importlib.util
from pathlib import Path
import traceback

_runtime_spec = importlib.util.spec_from_file_location(
    "_fixfirst_runtime_evidence", Path(__file__).with_name("_runtime_evidence.py"))
_runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(_runtime)

_dropped = False

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
    path = os.environ.get("FIXFIRST_PROBE")
    if not path:
        return
    text = json.dumps(data, ensure_ascii=True) + "\n"
    if not final and (
        len(text) > 100000 or (os.path.exists(path) and os.path.getsize(path) + len(text) > 800000)
    ):
        _dropped = True
        return
    with open(path, "a", encoding="utf-8") as file:
        file.write(text)


def pytest_load_initial_conftests():
    """Retain the actual startup exception before pytest hides its internal frames.

    The hook wrapper observes the existing outcome; it never retries, suppresses,
    or replaces the failure. In particular a project's own warning stays a
    project warning even when pytest's displayed traceback is shortened.
    """
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
