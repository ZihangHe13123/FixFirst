import http.client
import json
import sys
import threading

import pytest

from fixfirst.web import make_server


@pytest.fixture
def server(tmp_path):
    server, app = make_server(tmp_path / "store", workbench=tmp_path / "workbench")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield app
    server.shutdown()
    server.server_close()


def request(app, method, path, body=None, token=None, host=None):
    connection = http.client.HTTPConnection("127.0.0.1", app.port, timeout=60)
    headers = {"Host": host or f"127.0.0.1:{app.port}", "Content-Type": "application/json"}
    if token:
        headers["X-FixFirst-Token"] = token
    connection.request(method, path, json.dumps(body) if body is not None else None, headers)
    response = connection.getresponse()
    return response.status, response.read().decode(), dict(response.getheaders())


def api(app, path, body):
    status, text, _ = request(app, "POST", path, body, token=app.token)
    return status, json.loads(text)


def failing_project(tmp_path):
    project = tmp_path / "shop"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "shop"\nversion = "0"\n')
    # The defect is in the project, so fixing it leaves the tests as they were.
    (project / "app.py").write_text("def ready():\n    return 1 == 2\n")
    (project / "test_app.py").write_text("from app import ready\n\n\ndef test_app():\n    assert ready()\n")
    return project


def test_every_change_needs_the_token_and_a_local_host(server, tmp_path):
    status, page, _ = request(server, "GET", "/")
    assert status == 200 and server.token in page and "Check my project" in page
    assert request(server, "GET", "/", host="attacker.example:80")[0] == 403
    body = {"project": str(failing_project(tmp_path)), "python": sys.executable}
    for path in ("/api/start", "/api/folder", "/api/browse", "/api/sessions"):
        assert request(server, "POST", path, body)[0] == 403
        assert request(server, "POST", path, body, token="wrong")[0] == 403


def test_folder_check_finds_the_project_and_its_python(server, tmp_path):
    project = failing_project(tmp_path)
    status, info = api(server, "/api/folder", {"path": str(project), "python": sys.executable})
    assert status == 200 and info["ok"] and "pyproject.toml" in info["markers"]
    assert info["python"]["version"] and info["python"]["pytest"]
    assert api(server, "/api/folder", {"path": str(tmp_path / "missing")})[1]["ok"] is False
    listing = api(server, "/api/browse", {"path": str(tmp_path)})[1]
    assert {"name": "shop", "path": str(project.resolve()), "project": True} in listing["entries"]


def test_start_checks_the_project_and_shows_the_next_step(server, tmp_path):
    project = failing_project(tmp_path)
    status, created = api(
        server, "/api/start", {"project": str(project), "python": sys.executable, "goal": "pass_tests"}
    )
    assert status == 200
    session = created["session_id"]
    status, page, _ = request(server, "GET", f"/sessions/{session}")
    assert status == 200 and "1 problem to fix" in page and "Check again" in page
    assert "test_app.py:5" in page and "Defect in project code or tests" in page
    # Ruff's finding on `1 == 2` is listed, but it does not count against the test goal.
    assert "Other findings that do not block this goal (1)" in page
    status, answer = api(server, f"/api/sessions/{session}/ask", {"question": "what is the root cause"})
    assert status == 200 and "Defect in project code" in answer["answer"]
    status, details, _ = request(server, "GET", f"/sessions/{session}/details")
    assert status == 200 and "Evidence graph" in details and "connect-src 'self'" in details
    status, exported, headers = request(server, "GET", f"/sessions/{session}/export")
    assert status == 200 and "attachment" in headers["Content-Disposition"]
    assert str(project) not in exported
    (project / "app.py").write_text("def ready():\n    return 1 == 1\n")
    assert api(server, f"/api/sessions/{session}/scan", {})[0] == 200
    page = request(server, "GET", f"/sessions/{session}")[1]
    # The failing test is fixed, and Ruff's finding about `1 == 2` no longer appears in a
    # complete Ruff run, so both are verified (Ruff now reports `1 == 1` instead).
    assert "All tests pass" in page and "Fixed and verified (2)" in page
    status, error = api(server, f"/api/sessions/{session}/run", {"action_id": "nope"})
    assert status == 400 and "not a runnable check" in error["error"]
