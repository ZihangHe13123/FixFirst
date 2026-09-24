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
    return response.status, response.read().decode()


def test_pages_require_local_host_and_changes_require_the_token(server, tmp_path):
    status, page = request(server, "GET", "/")
    assert status == 200 and server.token in page
    assert request(server, "GET", "/", host="attacker.example:80")[0] == 403
    project = tmp_path / "project"
    project.mkdir()
    body = {"project": str(project), "python": sys.executable, "goal": "pass_tests"}
    assert request(server, "POST", "/api/sessions", body)[0] == 403
    assert request(server, "POST", "/api/sessions", body, token="wrong")[0] == 403
    status, text = request(server, "POST", "/api/sessions", body, token=server.token)
    assert status == 200
    session_id = json.loads(text)["session_id"]
    status, page = request(server, "GET", f"/sessions/{session_id}")
    assert status == 200 and "Run the checks for this goal" in page and "connect-src 'self'" in page


def test_web_runs_checks_and_answers_questions(server, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_app.py").write_text("def test_app():\n    assert 1 == 2\n")
    body = {"project": str(project), "python": sys.executable, "goal": "pass_tests"}
    session_id = json.loads(request(server, "POST", "/api/sessions", body, token=server.token)[1])[
        "session_id"
    ]
    status, _ = request(server, "POST", f"/api/sessions/{session_id}/scan", {}, token=server.token)
    assert status == 200
    status, text = request(
        server, "POST", f"/api/sessions/{session_id}/ask", {"question": "what is the root cause"},
        token=server.token,
    )
    assert status == 200 and "Defect in project code" in json.loads(text)["answer"]
    status, text = request(server, "POST", f"/api/sessions/{session_id}/run", {"action_id": "nope"},
                           token=server.token)
    assert status == 400 and "not a runnable check" in json.loads(text)["error"]
