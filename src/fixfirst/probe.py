"""Copied into an isolated temporary directory; imports only stdlib in the target env."""

import json
import os


def emit(data):
    path = os.environ.get("FIXFIRST_PROBE")
    if not path:
        return
    if os.path.exists(path) and os.path.getsize(path) > 800000:
        return
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=True) + "\n")


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
    if report.failed:
        emit(
            {
                "type": "failure",
                "stage": report.when,
                "nodeid": report.nodeid,
                "message": str(report.longrepr)[:32000],
            }
        )


def pytest_sessionfinish(session, exitstatus):
    emit({"type": "finish", "exit_code": int(exitstatus), "collected": session.testscollected})
