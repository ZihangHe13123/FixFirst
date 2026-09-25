"""Copied into an isolated temporary directory; imports only stdlib in the target env."""

import json
import os

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
