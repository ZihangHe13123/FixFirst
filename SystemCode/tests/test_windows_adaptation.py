"""Regression coverage for Windows integration failures (portable where possible)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from fixfirst.models import Action, Fact, Run, Session
from fixfirst.processes import ManagedProcess, ProcessCancelled, ProcessScope
from fixfirst.project import read_project
from fixfirst.report import public_data, public_entity, public_question, shell
from fixfirst.runner import execute
from fixfirst.service import create_session, import_log
from fixfirst.versions import Sandbox
from fixfirst.web import App, make_server


def test_orphan_cannot_hold_check_pipes_open(tmp_path):
    marker = tmp_path / "orphan-survived"
    grandchild = f"import time; from pathlib import Path; time.sleep(6); Path({str(marker)!r}).touch()"
    code = f"import subprocess,sys; subprocess.Popen([sys.executable, '-c', {grandchild!r}]); print('done')"
    started = time.monotonic()
    result = execute([sys.executable, "-c", code], str(tmp_path), "pytest", ".", sys.executable, 5)
    assert result.status == "completed" and result.exit_code == 0 and "done" in result.stdout
    # Generous for slow machines, still far below the grandchild's 6 seconds.
    assert time.monotonic() - started < 4
    time.sleep(max(0.0, started + 6.5 - time.monotonic()))
    assert not marker.exists()


def test_scope_shutdown_kills_running_check_and_refuses_new_launches(tmp_path):
    scope = ProcessScope()
    with scope.activate():
        with ManagedProcess([sys.executable, "-c", "import time; time.sleep(60)"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as proc:
            thread = threading.Thread(target=scope.cancel)
            thread.start()
            thread.join(3)
            assert not thread.is_alive()
            assert proc.wait(timeout=3) != 0
        with pytest.raises(ProcessCancelled):
            ManagedProcess([sys.executable, "-c", "pass"])
    assert not scope.children


def test_sandbox_timeout_does_not_wait_for_descendants(tmp_path):
    box = Sandbox.__new__(Sandbox)
    box.folder, box.timeout = tmp_path, 0.5
    code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time;time.sleep(8)']);time.sleep(8)"
    start = time.monotonic()
    assert box._run([sys.executable, "-c", code]) == -1
    assert time.monotonic() - start < 5


def test_powershell_utf16_requirements_and_imported_log(tmp_path):
    (tmp_path / "requirements.txt").write_text("# 中文\nnumpy<2\n", encoding="utf-16")
    assert read_project(tmp_path)["declarations"][0]["requirement"] == "numpy<2"
    session = create_session(tmp_path, sys.executable)
    log = tmp_path / "pytest.log"
    log.write_text("E   AssertionError: 水果不相同\n", encoding="utf-16")
    import_log(session, log, "pytest_run", 1)
    assert "水果不相同" in session.runs[-1].stdout
    assert "\x00" not in session.runs[-1].stdout
    assert session.runs[-1].source == "imported"


@pytest.mark.parametrize("username", ["John Smith", "O' Brien"])
def test_public_windows_paths_and_unique_action_references(username):
    session = Session(name="demo", project_root=rf"C:\Users\{username}\PrivateProject",
                      target_python=rf"C:\Users\{username}\PrivateProject\.venv\Scripts\python.exe")
    ids = ["action-c-users-john-smith-privateproject-a", "action-c-users-john-smith-privateproject-b"]
    session.actions = [Action(action_id=i, kind="inspect", title="inspect", explanation="why",
                              verification="check") for i in ids]
    session.facts = [Fact(fact_id="fact-1", subject=ids[0], predicate="supports", value=ids[1])]
    session.runs = [Run(tool="environment", stdout=json.dumps({
        "path": f"c:/USERS/{username}/PrivateProject/test.py",
        "python": session.target_python,
        "other": rf"C:\Users\{username}\Elsewhere\file.py",
        "description": f"Project '{session.project_root}' uses '{session.target_python}'",
    }))]
    data = public_data(session)
    text = json.dumps(data).lower()
    assert username.lower() not in text and "john-smith" not in text and "privateproject" not in text
    snapshot = json.loads(data["runs"][0]["stdout"])
    assert snapshot["python"] == "<python>"
    assert snapshot["path"] == "<project>/test.py"
    assert snapshot["description"] == "Project '<project>' uses '<python>'"
    public_ids = [a["action_id"] for a in data["actions"]]
    assert len(set(public_ids)) == 2
    assert data["facts"][0]["subject"] == public_ids[0]
    assert data["facts"][0]["value"] == public_ids[1]
    assert public_entity(session, ids[0]) == public_ids[0]


@pytest.mark.parametrize("entry_point", ["web", "cli"])
@pytest.mark.parametrize("question_format", [
    "Why `{}`?", "Explain {}.", "为什么 {}？", "为什么{}？", "{}为什么排在这里？",
])
def test_questions_keep_requested_action_after_redaction(tmp_path, capsys, entry_point, question_format):
    app = App(tmp_path / "store", tmp_path / "work")
    session = Session(name="questions", project_root=str(tmp_path), target_python=sys.executable)
    session.actions = [
        Action(action_id=f"inspect-{name}", kind="inspect", title=f"Inspect {name}",
               explanation=f"Reason for {name}", verification="Check the result", priority=rank)
        for rank, name in enumerate(["alpha", "beta", "beta-detail"], 1)
    ]
    app.store.save(session)
    for action in session.actions[1:]:
        public_id = public_entity(session, action.action_id)
        questions = [question_format.format(reference) for reference in (action.action_id, public_id)]
        for question in questions:
            if entry_point == "web":
                answer = app.act(session.session_id, "ask", {"question": question})
            else:
                from fixfirst.cli import main

                assert main(["--store", str(app.store.root), "ask", session.session_id,
                             question, "--json"]) == 0
                answer = json.loads(capsys.readouterr().out)
            assert answer["entity"] == public_id
            assert f"Action: {action.title} (" in answer["answer"]
            assert action.explanation in answer["answer"]
            assert action.action_id not in answer["answer"]


def test_questions_do_not_replace_id_fragments():
    session = Session(name="questions", project_root=".", target_python=sys.executable)
    action = Action(action_id="inspect-beta", kind="inspect", title="Inspect beta",
                    explanation="Reason for beta", verification="Check the result")
    session.actions = [action]
    for reference in ("inspect-beta-detail", "inspect-beta.other", "inspect-beta_other",
                      "pre-inspect-beta", "pre.inspect-beta", "xinspect-beta"):
        question = f"为什么{reference}？"
        assert public_question(session, question) == question


@pytest.mark.parametrize("path, expected", [
    (r"C:\Users\O'Brien\OtherProject\data.csv", r"<home>\OtherProject\data.csv"),
    ("c:/USERS/O'Brien/OtherProject/data.csv", "<home>/OtherProject/data.csv"),
    ("/Users/O'Brien/OtherProject/data.csv", "<home>/OtherProject/data.csv"),
    (r"C:\Temp\pytest-of-O'Brien\pytest-0\data.csv",
     r"C:\Temp\pytest-of-user\pytest-0\data.csv"),
    (r"C:\Users\O'Brien", "<home>"),
    (r"'C:\Users\O'Brien'", "'<home>'"),
    (r"C:\Users\O' Brien\OtherProject\O'Brien.csv", r"<home>\OtherProject\O'Brien.csv"),
])
def test_export_redacts_usernames_with_apostrophes(path, expected):
    session = Session(name="export", project_root=r"D:\project",
                      target_python=r"C:\Python312\python.exe")
    note = "O'Brien is mentioned outside a path"
    session.runs = [
        Run(tool="pytest", stdout=f"File: {path}\nKeep this diagnosis"),
        Run(tool="environment", stdout=json.dumps({"path": path, "note": note})),
    ]
    data = public_data(session)
    assert data["runs"][0]["stdout"] == f"File: {expected}\nKeep this diagnosis"
    assert json.loads(data["runs"][1]["stdout"]) == {"path": expected, "note": note}


@pytest.mark.parametrize("path, expected", [
    (r"'C:\Users\Alice'", "'<home>'"),
    (r"'C:\Users\O'Brien'", "'<home>'"),
    ('"C:\\Users\\O\' Brien"', '"<home>"'),
    ("'/Users/O'Brien'", "'<home>'"),
    (r"'C:\Temp\pytest-of-O'Brien'", r"'C:\Temp\pytest-of-user'"),
    (r"'C:\Users\O' Brien\OtherProject\data.csv'", r"'<home>\OtherProject\data.csv'"),
    ("'c:/USERS/O' Brien/OtherProject/data.csv'", "'<home>/OtherProject/data.csv'"),
    ("'/Users/O' Brien/OtherProject/data.csv'", "'<home>/OtherProject/data.csv'"),
    ("'/home/O' Brien/OtherProject/data.csv'", "'<home>/OtherProject/data.csv'"),
    (r"'C:\Temp\pytest-of-O' Brien\pytest-0\data.csv'",
     r"'C:\Temp\pytest-of-user\pytest-0\data.csv'"),
    (r"'C:\Users\O' Brien'", "'<home>'"),
])
@pytest.mark.parametrize("other_path", ["/tmp/project", "'/tmp/project'"])
def test_export_keeps_text_between_quoted_paths(path, expected, other_path):
    session = Session(name="export", project_root=r"D:\project",
                      target_python=r"C:\Python312\python.exe")
    diagnostic = f"Home {path} is not inside {other_path}"
    redacted = f"Home {expected} is not inside {other_path}"
    session.runs = [
        Run(tool="pytest", stdout=diagnostic),
        Run(tool="environment", stdout=json.dumps({"error": diagnostic})),
    ]
    data = public_data(session)
    assert data["runs"][0]["stdout"] == redacted
    assert json.loads(data["runs"][1]["stdout"]) == {"error": redacted}


@pytest.mark.parametrize("diagnostic, expected", [
    (r"Access denied: 'C:\Users\O' Brien': permission denied",
     "Access denied: '<home>': permission denied"),
    (r"Home 'C:\Users\Alice' says 'bad user' near /tmp/project",
     "Home '<home>' says 'bad user' near /tmp/project"),
    (r"Home 'C:\Users\Alice' is not inside D:\other",
     r"Home '<home>' is not inside D:\other"),
    ('''Home 'C:/Users/Alice' is not inside "relative/project"''',
     '''Home '<home>' is not inside "relative/project"'''),
])
def test_export_preserves_diagnostic_suffixes(diagnostic, expected):
    session = Session(name="export", project_root=r"D:\project",
                      target_python=r"C:\Python312\python.exe")
    session.runs = [Run(tool="pytest", stdout=diagnostic)]
    assert public_data(session)["runs"][0]["stdout"] == expected


@pytest.mark.parametrize("path", [r"C:\Users\Alice", r"C:\Users\O' Brien", "/home/O' Brien"])
@pytest.mark.parametrize("suffix, expected_suffix", [
    (": mode='r'", ": mode='r'"),
    (": error='permission denied'", ": error='permission denied'"),
    (" mode='r'", " mode='r'"),
    (": mode = ' r ', note='', error='permission denied'",
     ": mode = ' r ', note='', error='permission denied'"),
    (": options={'mode': 'r'}", ": options={'mode': 'r'}"),
    (''': error="O' Brien cannot open"''', ''': error="O' Brien cannot open"'''),
    (r": mode='r', file='C:\Users\Bob\config.json'",
     r": mode='r', file='<home>\config.json'"),
])
def test_export_keeps_fields_after_quoted_home(path, suffix, expected_suffix):
    session = Session(name="export", project_root=r"D:\project",
                      target_python=r"C:\Python312\python.exe")
    diagnostic = f"Cannot open '{path}'{suffix}"
    expected = f"Cannot open '<home>'{expected_suffix}"
    session.runs = [
        Run(tool="pytest", stdout=diagnostic),
        Run(tool="environment", stdout=json.dumps({"error": diagnostic})),
    ]
    data = public_data(session)
    assert data["runs"][0]["stdout"] == expected
    assert json.loads(data["runs"][1]["stdout"]) == {"error": expected}


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_export_large_unterminated_paths_finish_within_deadline(separator):
    # Run in a disposable process: a regex regression must not hang the suite.
    code = """
import sys, time
from fixfirst.models import Run, Session
from fixfirst.report import public_data
from fixfirst.runner import MAX_OUTPUT
fragment = "'C:" + sys.argv[1] + "Users" + sys.argv[1] + "Alice"
count = MAX_OUTPUT // len(fragment)
session = Session(name="export", project_root="D:/project", target_python="D:/python.exe")
session.runs = [Run(tool="pytest", stdout=fragment * count)]
started = time.monotonic()
result = public_data(session)["runs"][0]["stdout"]
elapsed = time.monotonic() - started
assert result == "'<home>" * count
assert elapsed < 4, elapsed
"""
    source = str(Path(__file__).resolve().parents[1] / "src")
    # Load this checkout first without dropping dependency paths used by the
    # isolated Windows/GBK validation interpreter.
    pythonpath = os.pathsep.join(filter(None, [source, os.environ.get("PYTHONPATH")]))
    env = dict(os.environ, PYTHONPATH=pythonpath)
    result = subprocess.run([sys.executable, "-c", code, separator], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell quoting")
def test_powershell_exact_native_arguments(tmp_path):
    echo = tmp_path / "参数 脚本.py"
    echo.write_text("import json,sys;print(json.dumps(sys.argv[1:]))", encoding="utf-8")
    args = ["numpy<2", "requests[socks]>=2.0", "flask>=2,<3", "C:\\O'Brien 目录\\file.txt"]
    script = tmp_path / "command.ps1"
    script.write_text(shell([sys.executable, str(echo), *args]), encoding="utf-8-sig")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                            capture_output=True, timeout=15, check=True)
    assert json.loads(result.stdout) == args


def test_port_validation_and_shutdown_scope(tmp_path):
    with pytest.raises(ValueError, match="Port"):
        make_server(tmp_path, 65536)
    server, app = make_server(tmp_path, 0)
    try:
        with pytest.raises(OSError):
            other, _ = make_server(tmp_path / "other", app.port)
            other.server_close()
    finally:
        server.server_close()
    assert app.processes.cancelled


def test_pytest_child_encoding_matches_user_policy(tmp_path, monkeypatch):
    from fixfirst.runner import collect

    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    (tmp_path / "test_child.py").write_text(
        "import os\ndef test_child():\n    assert 'PYTHONIOENCODING' not in os.environ\n", encoding="utf-8"
    )
    result = collect(create_session(tmp_path, sys.executable), "pytest_run", timeout=20)
    assert result.status == "completed" and result.exit_code == 0
