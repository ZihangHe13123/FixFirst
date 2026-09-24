"""Local web interface over the same service functions as the CLI.

Binds to 127.0.0.1 only. Every state-changing request must carry the per-launch token that
is embedded in the served pages, and the Host header must name this server (a guard against
DNS rebinding). Checks run synchronously in the request thread; the session lock rejects a
second concurrent change to the same session.
"""

from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sys
import webbrowser

from .knowledge_graph import build_graph, query_graph
from .models import Session, now
from .reasoning import infer_and_plan
from .report import ENV, GOALS, html, public_data
from .service import create_session, mark_fixed, scan
from .storage import Store

MAX_BODY = 64_000
SESSION_PATH = re.compile(r"^/sessions/(session-[a-f0-9]{12})$")
API_PATH = re.compile(r"^/api/sessions/(session-[a-f0-9]{12})/([a-z-]+)$")


class App:
    def __init__(self, store_root: Path, workbench: Path):
        self.store = Store(store_root)
        self.workbench = workbench
        self.token = secrets.token_urlsafe(24)
        self.port = 0

    def index(self) -> str:
        rows = sorted(self.store.list(), key=lambda r: r["session_id"])
        return ENV.get_template("index.html").render(
            sessions=rows, goals=GOALS, token=self.token, python=sys.executable
        )

    def page(self, session_id: str) -> str:
        session = self.store.load(session_id)
        return html(session, self.store.root, live={"token": self.token})[0]

    def create(self, body: dict) -> dict:
        session = create_session(
            body.get("project", ""), body.get("python") or sys.executable,
            goal=body.get("goal", "collect_tests"),
        )
        with self.store.lock(session.session_id):
            infer_and_plan(session)
            self.store.save(session)
        return {"session_id": session.session_id}

    def demo(self, body: dict) -> dict:
        from . import cases, execution_cases
        from .playground import playground

        output = self.workbench / ("web-demo-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        if body.get("scenario") == "playground":
            return {"session_id": playground(output, self.store).session_id}
        module = execution_cases if body.get("scenario") == "execution" else cases
        module.demo(output, self.store)
        project = str((output / "project").resolve())
        for row in self.store.list():
            if self.store.load(row["session_id"]).project_root == project:
                return {"session_id": row["session_id"]}
        raise ValueError("Demo finished but its session was not found")

    def act(self, session_id: str, op: str, body: dict) -> dict:
        if op == "ask":
            session = self.store.load(session_id)
            graph = build_graph(Session.model_validate(public_data(session)))
            return query_graph(graph, str(body.get("question", ""))[:500])
        with self.store.lock(session_id):
            session = self.store.load(session_id)
            if op == "scan":
                scan(session)
            elif op == "run":
                action = next((a for a in session.actions if a.action_id == body.get("action_id")), None)
                if not action or not action.check or action.blocked_reasons:
                    raise ValueError("This action is not a runnable check")
                scan(session, [action.check], targets=action.targets)
            elif op == "mark-fixed":
                for issue_id in body.get("issue_ids", []):
                    issue = next((i for i in session.issues if i.issue_id == issue_id), None)
                    if issue and issue.status != "resolved":
                        mark_fixed(session, issue_id)
            elif op == "goal":
                if body.get("goal") not in GOALS:
                    raise ValueError("Unknown goal")
                session.goal = body["goal"]
                session.history.append({"time": now(), "kind": "goal_change"})
                infer_and_plan(session)
                session.goal_status = "unknown"
            else:
                raise KeyError(op)
            self.store.save(session)
        return {"ok": True}


def handler_for(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FixFirst"

        def log_message(self, format, *args):
            return

        def reply(self, status, body: str, content_type="text/html; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def json_reply(self, status, payload):
            self.reply(status, json.dumps(payload), "application/json")

        def trusted_host(self) -> bool:
            return self.headers.get("Host") in (f"127.0.0.1:{app.port}", f"localhost:{app.port}")

        def do_GET(self):
            if not self.trusted_host():
                return self.reply(HTTPStatus.FORBIDDEN, "Forbidden host")
            path = self.path.split("?", 1)[0]
            try:
                if path == "/":
                    return self.reply(HTTPStatus.OK, app.index())
                match = SESSION_PATH.match(path)
                if match:
                    return self.reply(HTTPStatus.OK, app.page(match[1]))
            except (OSError, ValueError) as exc:
                return self.reply(HTTPStatus.NOT_FOUND, f"Not found: {exc}", "text/plain; charset=utf-8")
            self.reply(HTTPStatus.NOT_FOUND, "Not found", "text/plain; charset=utf-8")

        def do_POST(self):
            if not self.trusted_host() or not secrets.compare_digest(
                self.headers.get("X-FixFirst-Token", ""), app.token
            ):
                return self.json_reply(HTTPStatus.FORBIDDEN, {"error": "Missing or wrong token"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self.json_reply(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Request too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("Expected a JSON object")
                path = self.path.split("?", 1)[0]
                if path == "/api/sessions":
                    return self.json_reply(HTTPStatus.OK, app.create(body))
                if path == "/api/demo":
                    return self.json_reply(HTTPStatus.OK, app.demo(body))
                match = API_PATH.match(path)
                if not match:
                    return self.json_reply(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
                return self.json_reply(HTTPStatus.OK, app.act(match[1], match[2], body))
            except KeyError:
                return self.json_reply(HTTPStatus.NOT_FOUND, {"error": "Unknown operation"})
            except (ValueError, OSError) as exc:
                status = HTTPStatus.CONFLICT if "already running" in str(exc) else HTTPStatus.BAD_REQUEST
                return self.json_reply(status, {"error": str(exc)})

    return Handler


def make_server(store_root: Path, port=0, workbench: Path | None = None):
    app = App(Path(store_root), Path(workbench or "workbench").resolve())
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(app))
    app.port = server.server_address[1]
    return server, app


def serve(store_root: Path, port=0, open_browser=True) -> int:
    server, app = make_server(store_root, port)
    url = f"http://127.0.0.1:{app.port}/"
    print(f"FixFirst is running at {url} (Ctrl+C to stop). Only this computer can reach it.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()
    return 0
