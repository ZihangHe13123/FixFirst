"""Copied into an isolated temporary directory; imports only stdlib in the target env."""

import json
import os

_dropped = False


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
        emit(
            {
                "type": "exception",
                "nodeid": report.nodeid,
                "stage": getattr(report, "when", "collect"),
                "exception_type": call.excinfo.type.__name__,
            }
        )


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
