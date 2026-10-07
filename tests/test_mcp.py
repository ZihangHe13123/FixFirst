import json
from pathlib import Path
import subprocess
import sys

import pytest

from fixfirst.cli import default_store
from fixfirst.mcp_server import PROTOCOL_VERSIONS, Server, TOOLS


def call(server, name, arguments=None):
    answer = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": name, "arguments": arguments or {}}})
    result = answer["result"]
    return result["content"][0]["text"], result["isError"]


def failing_project(tmp_path):
    project = tmp_path / "shop"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "shop"\nversion = "0"\n')
    # The defect is in the project, so fixing it leaves the tests as they were.
    (project / "app.py").write_text("def ready():\n    return 1 == 2\n")
    (project / "test_app.py").write_text("from app import ready\n\n\ndef test_app():\n    assert ready()\n")
    return project


def test_handshake_negotiates_the_version_and_lists_three_tools(tmp_path):
    server = Server(tmp_path / "store")
    hello = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}
    result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": hello})["result"]
    assert result["protocolVersion"] == "2025-06-18" and result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "fixfirst" and "check_again" in result["instructions"]
    newer = {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2099-01-01"}}
    assert server.handle(newer)["result"]["protocolVersion"] == PROTOCOL_VERSIONS[0]
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
    assert [t["name"] for t in tools] == ["diagnose", "check_again", "explain"]
    assert all(t["inputSchema"]["type"] == "object" for t in tools)
    assert server.handle({"jsonrpc": "2.0", "id": 4, "method": "ping"})["result"] == {}
    assert server.handle({"jsonrpc": "2.0", "id": 5, "method": "resources/list"})["error"]["code"] == -32601
    unknown = {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "fix_it"}}
    assert server.handle(unknown)["error"]["code"] == -32602
    assert server.handle({"id": 7, "method": "ping"})["error"]["code"] == -32600


def test_mistakes_come_back_as_tool_errors_and_leave_no_records(tmp_path):
    server = Server(tmp_path / "store")
    text, failed = call(server, "check_again")
    assert failed and "call diagnose" in text
    text, failed = call(server, "check_again", {"session_id": "session-000000000000"})
    assert failed and "Unknown session" in text
    assert not (tmp_path / "store").exists()  # no lock directory for an unknown session
    text, failed = call(server, "diagnose", {"folder": str(tmp_path)})
    assert failed and "unknown folder" in text and "missing project" in text
    text, failed = call(server, "diagnose", {"project": str(tmp_path / "missing")})
    assert failed and "does not exist" in text
    text, failed = call(server, "diagnose", {"project": str(tmp_path), "goal": "fast"})
    assert failed and "Unknown goal" in text


@pytest.mark.parametrize("mode,tool", [("full", "diagnose"), ("facts", "observe")])
@pytest.mark.parametrize("goal", ["pass_tests", "collect_tests", "check_style"])
def test_execution_for_test_goals_tells_the_agent_to_remove_it_without_scanning(tmp_path, monkeypatch, mode, tool, goal):
    from fixfirst import mcp_server

    def unexpected(*args, **kwargs):
        raise AssertionError("incompatible execution must be rejected before any project check")
    monkeypatch.setattr(mcp_server, "inspect_folder", unexpected)
    server = Server(tmp_path / "store", mode=mode)
    text, failed = call(server, tool, {"project": str(tmp_path), "goal": goal,
                                     "execution": {"kind": "module", "entry": "pytest"}})
    assert failed and "remove the execution parameter" in text and "same goal" in text
    assert goal in text and server.latest is None and not (tmp_path / "store").exists()


def test_execution_help_and_auto_and_native_goals_keep_their_contract():
    from fixfirst.mcp_server import _check_execution_goal

    help_text = TOOLS[0]["inputSchema"]["properties"]["execution"]["description"]
    assert "Omit execution for pass_tests" in help_text
    for goal in ("auto", "run_project", "pass_unittest"):
        _check_execution_goal(goal, {"kind": "module", "entry": "app"})
    _check_execution_goal("pass_tests", None)


def test_diagnose_check_again_and_explain_follow_one_fix(tmp_path):
    server = Server(tmp_path / "store")
    project = failing_project(tmp_path)
    text, failed = call(server, "diagnose", {"project": str(project), "python": sys.executable})
    assert not failed and "1 problem to fix" in text and "call check_again" in text
    assert "1. " in text and "test_app.py:5" in text and "Defect in project code or tests" in text
    # An unrelated lint finding is available on request, not in every diagnosis.
    assert "Other findings that do not block" not in text
    assert "FixFirst suggests no environment change for this failure" in text
    assert "Look at the project's own code or tests" in text
    assert "not an environment problem" not in text
    assert "will not repair" not in text
    session_id = text.split()[2]
    assert (tmp_path / "store" / session_id / "session.json").is_file()
    explained, failed = call(server, "explain", {"step": 1})
    assert not failed and "Error:" in explained and "pytest_run" in explained
    assert "Other findings that do not block this goal (1)" in explained
    assert call(server, "explain", {"step": 9})[1]
    (project / "app.py").write_text("def ready():\n    return 1 == 1\n")
    text, failed = call(server, "check_again", {"session_id": session_id})
    assert not failed and "All tests pass" in text and "Nothing else is needed" in text
    assert "Fixed since the last check" in text and "Fixed and verified (2)" in text
    assert "Steps, most important first" not in text
    # Diagnosing the same project again continues the session instead of starting over.
    text, _ = call(server, "diagnose", {"project": str(project), "python": sys.executable})
    assert session_id in text and "Continuing the session" in text


def test_a_rule_backed_cause_names_its_rule_and_source(tmp_path):
    project = tmp_path / "legacy"
    project.mkdir()
    (project / "shapes.py").write_text("from collections import Mapping\n\n\ndef area():\n    return 1\n")
    (project / "test_shapes.py").write_text("from shapes import area\n\n\ndef test_area():\n    assert area() == 1\n")
    server = Server(tmp_path / "store")
    text, failed = call(server, "diagnose", {"project": str(project), "python": sys.executable})
    assert not failed and "Mapping" in text and "rule D02" in text
    explained, _ = call(server, "explain")
    assert "Rule D02:" in explained and "docs.python.org" in explained


def test_stdio_server_answers_line_by_line(tmp_path):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in messages) + "not json\n"
    done = subprocess.run(
        [sys.executable, "-m", "fixfirst", "--store", str(tmp_path / "store"), "mcp"],
        input=stdin, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0 and "ready" in done.stderr
    answers = [json.loads(line) for line in done.stdout.splitlines()]
    assert [a.get("id") for a in answers] == [1, 2, None]
    assert answers[2]["error"]["code"] == -32700
    assert Path(default_store("mcp")) == Path.home() / ".fixfirst" / "sessions"
    assert default_store("scan") == ".fixfirst"
