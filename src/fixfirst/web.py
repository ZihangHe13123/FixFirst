"""Local web interface over the same service functions as the CLI.

Pages: the start page (choose a project and a goal), a workspace per project (status, the
next steps, one "Check again" button) and a read-only technical report. Binds to 127.0.0.1
only. Every request that reads folders or changes state must carry the per-launch token that
is embedded in the served pages, and the Host header must name this server (a guard against
DNS rebinding). Checks run synchronously in the request thread; the session lock rejects a
second concurrent change to the same session.
"""

from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sys
import webbrowser

from .knowledge_graph import build_graph, query_graph
from .models import Session, now
from .processes import ProcessScope
from .reasoning import infer_and_plan
from .report import ENV, GOALS, html, public_data, public_question
from .service import create_session, mark_fixed, scan
from .storage import Store
from .workspace import GOAL_CHOICES, browse, build_view, inspect_folder

MAX_BODY = 64_000
PAGE = re.compile(r"^/sessions/(session-[a-f0-9]{12})(/details|/export)?$")
API_PATH = re.compile(r"^/api/sessions/(session-[a-f0-9]{12})/([a-z-]+)$")


class App:
    def __init__(self, store_root: Path, workbench: Path):
        self.store = Store(store_root)
        self.workbench = workbench
        self.token = secrets.token_urlsafe(24)
        self.port = 0
        self.processes = ProcessScope()

    def index(self) -> str:
        rows = sorted(self.store.list(), key=lambda r: r.get("created_at") or "", reverse=True)
        return ENV.get_template("index.html").render(
            sessions=rows, goals=GOALS, choices=GOAL_CHOICES, token=self.token
        )

    def workspace(self, session_id: str) -> str:
        session = self.store.load(session_id)
        return ENV.get_template("workspace.html").render(
            view=build_view(session), goals={key: name for key, name, _ in GOAL_CHOICES},
            session_id=session_id, token=self.token,
        )

    def details(self, session_id: str) -> str:
        return html(self.store.load(session_id), self.store.root, live={"token": self.token})[0]

    def export(self, session_id: str) -> tuple[str, str]:
        session = self.store.load(session_id)
        name = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(session.project_root).name) or "project"
        return html(session, self.store.root, public=True)[0], f"fixfirst-{name}.html"

    def create(self, body: dict) -> Session:
        session = create_session(
            body.get("project", ""),
            body.get("python") or sys.executable,
            goal=body.get("goal") if body.get("goal") in GOALS else "collect_tests",
        )
        with self.store.lock(session.session_id):
            infer_and_plan(session)
            self.store.save(session)
        return session

    def start(self, body: dict) -> dict:
        """Create a session and run its first check in one step."""
        session = self.create(body)
        with self.store.lock(session.session_id):
            scan(session)
            self.store.save(session)
        return {"session_id": session.session_id}

    def sample(self) -> dict:
        from .playground import playground

        output = self.workbench / ("sample-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        return {"session_id": playground(output, self.store).session_id}

    def act(self, session_id: str, op: str, body: dict) -> dict:
        if op == "ask":
            session = self.store.load(session_id)
            graph = build_graph(Session.model_validate(public_data(session)))
            question = public_question(session, str(body.get("question", ""))[:500])
            return query_graph(graph, question)
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

    def post(self, path: str, body: dict) -> dict:
        if path == "/api/folder":
            return inspect_folder(str(body.get("path", "")), body.get("python") or None)
        if path == "/api/browse":
            return browse(body.get("path"))
        if path == "/api/start":
            return self.start(body)
        if path == "/api/sample":
            return self.sample()
        if path == "/api/sessions":
            return {"session_id": self.create(body).session_id}
        match = API_PATH.match(path)
        if not match:
            raise KeyError(path)
        return self.act(match[1], match[2], body)


def handler_for(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FixFirst"

        def handle(self):
            with app.processes.activate():
                super().handle()

        def log_message(self, format, *args):
            return

        def reply(self, status, body: str, content_type="text/html; charset=utf-8", filename=None):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
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
                match = PAGE.match(path)
                if match and match[2] == "/details":
                    return self.reply(HTTPStatus.OK, app.details(match[1]))
                if match and match[2] == "/export":
                    text, filename = app.export(match[1])
                    return self.reply(HTTPStatus.OK, text, filename=filename)
                if match:
                    return self.reply(HTTPStatus.OK, app.workspace(match[1]))
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
                return self.json_reply(HTTPStatus.OK, app.post(self.path.split("?", 1)[0], body))
            except KeyError:
                return self.json_reply(HTTPStatus.NOT_FOUND, {"error": "Unknown operation"})
            except (ValueError, OSError) as exc:
                status = HTTPStatus.CONFLICT if "already running" in str(exc) else HTTPStatus.BAD_REQUEST
                return self.json_reply(status, {"error": str(exc)})

    return Handler


def make_server(store_root: Path, port=0, workbench: Path | None = None):
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    app = App(Path(store_root), Path(workbench or "workbench").resolve())

    class Server(ThreadingHTTPServer):
        allow_reuse_address = os.name != "nt"

        def server_close(self):
            app.processes.cancel()
            super().server_close()

    server = Server(("127.0.0.1", port), handler_for(app))
    app.port = server.server_address[1]
    return server, app


def serve(store_root: Path, port=0, open_browser=True) -> int:
    server, app = make_server(store_root, port)
    url = f"http://127.0.0.1:{app.port}/"
    print(f"FixFirst is running at {url} (Ctrl+C to stop). Only this computer can reach it.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()
    return 0
