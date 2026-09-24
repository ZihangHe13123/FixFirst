import json
import sys

import pytest

from fixfirst import engine
from fixfirst.classification import load_model, predict_tree, train_tree
from fixfirst.evidence import FEATURE_NAMES
from fixfirst.grouping import complete_link, group_events
from fixfirst.models import Event, Fact, Run
from fixfirst.parsers import parse
from fixfirst.reasoning import forward_chain
from fixfirst.report import public_data, render
from fixfirst.runner import execute, environment_id, redact
from fixfirst.service import create_session, ingest, mark_fixed, import_log
from fixfirst.storage import Store


@pytest.fixture
def session(tmp_path):
    return create_session(tmp_path, sys.executable)


def failed_pytest(session, component="requests"):
    return Run(
        tool="pytest",
        scope="collect:project",
        exit_code=2,
        environment_id=environment_id(session.target_python),
        records=[
            {
                "type": "failure",
                "stage": "collect",
                "nodeid": "tests/test_a.py",
                "message": f"ModuleNotFoundError: No module named '{component}'",
            },
            {"type": "finish", "collected": 0, "exit_code": 2},
        ],
    )


def passed_pytest(session):
    return Run(
        tool="pytest",
        scope="collect:project",
        exit_code=0,
        environment_id=environment_id(session.target_python),
        records=[{"type": "finish", "collected": 2, "exit_code": 0}],
    )


def ruff_run(session, code=None):
    rows = (
        []
        if code is None
        else [{"code": code, "message": "example", "filename": "a.py", "location": {"row": 1}}]
    )
    return Run(
        tool="ruff",
        scope="lint:project",
        exit_code=int(bool(rows)),
        environment_id=environment_id(session.target_python),
        stdout=json.dumps(rows),
    )


def test_partial_rerun_never_resolves_pytest(session):
    ingest(session, [failed_pytest(session), ruff_run(session, "E501")])
    ingest(session, [ruff_run(session)])
    # A Ruff-only round says nothing about the pytest issue: it stays open, never resolved.
    assert next(i for i in session.issues if i.tool == "pytest").status == "open"
    assert next(i for i in session.issues if i.tool == "ruff").status == "resolved"
    assert session.goal_status == "blocked"


def test_successful_collection_resolves_same_scope(session):
    ingest(session, [failed_pytest(session)])
    ingest(session, [passed_pytest(session)])
    assert session.issues[0].status == "resolved"
    assert session.goal_status == "achieved"
    assert not any(f.value == "environment_check" for f in session.facts)


@pytest.mark.parametrize("status", ["timeout", "cancelled", "launch_failed", "output_limit"])
def test_incomplete_check_cannot_close_issue(session, status):
    ingest(session, [failed_pytest(session)])
    run = passed_pytest(session)
    run.status = status
    ingest(session, [run])
    assert not any(i.status == "resolved" for i in session.issues)
    assert session.goal_status != "achieved"


@pytest.mark.parametrize("code", [1, 2, 3, 4, 5, None])
def test_pytest_exit_without_coverage_not_success(code):
    run = Run(tool="pytest", exit_code=code, stdout="")
    assert parse(run)
    assert not run.verified_pass


def test_no_tests_not_success(session):
    run = passed_pytest(session)
    run.records[0]["collected"] = 0
    assert parse(run)
    assert not run.verified_pass


def test_different_env_never_closes_old_issue(session):
    ingest(session, [failed_pytest(session)])
    run = passed_pytest(session)
    run.environment_id = "other-env"
    ingest(session, [run])
    assert session.issues[0].status == "not_observed"
    assert session.goal_status == "unknown"


def test_manual_fixed_waits_for_verification(session):
    ingest(session, [failed_pytest(session)])
    mark_fixed(session, session.issues[0].issue_id)
    assert session.issues[0].status == "awaiting_verification"
    assert session.goal_status == "unknown"


def test_ruff_diagnostics_not_all_format(session):
    assert parse(ruff_run(session, "F821"))[0].kind == "code_check"
    assert parse(ruff_run(session, "E501"))[0].kind == "style_issue"


@pytest.mark.parametrize("value", ["{}", "garbage", "[{}]", "[1]", "null"])
def test_malformed_ruff_retained(value):
    run = Run(tool="ruff", exit_code=0, stdout=value)
    assert parse(run)[0].kind == "tool_failure"
    assert not run.verified_pass
    assert not run.coverage_complete


def test_failed_ruff_output_cannot_verify_an_earlier_finding(session):
    session.goal = "check_style"
    ingest(session, [ruff_run(session, "F821")])
    issue_id = session.issues[0].issue_id
    failed = ruff_run(session)
    failed.exit_code = 1  # Empty findings contradict the nonzero exit code.

    ingest(session, [failed])

    assert not failed.coverage_complete and not failed.verified_pass
    assert next(i for i in session.issues if i.issue_id == issue_id).status == "not_observed"
    assert any(i.kind == "tool_failure" and i.status == "open" for i in session.issues)
    assert session.goal_status != "achieved"


def test_missing_tool_not_project_import_error():
    run = Run(
        tool="pytest",
        argv=["python", "-m", "pytest"],
        exit_code=1,
        stderr="/venv/bin/python: No module named pytest",
    )
    assert parse(run)[0].kind == "tool_failure"


def test_network_error_not_version_conflict():
    run = Run(tool="pip_install", source="imported", stdout="ERROR: Could not connect to server")
    assert parse(run)[0].kind == "install_failure"


def test_pip_check_observed_conflict():
    run = Run(
        tool="pip_check",
        exit_code=1,
        stdout="alpha 1.0 has requirement packaging<1, but you have packaging 26.0.",
    )
    assert parse(run)[0].kind == "dependency_conflict"


def test_unknown_pip_output_retained():
    assert parse(Run(tool="pip_check", exit_code=1, stderr="???"))[0].kind == "other_unknown"


def test_group_keeps_different_modules_apart(session):
    run = failed_pytest(session)
    a = parse(run)[0]
    b = a.model_copy(
        update={
            "event_id": "b",
            "component": "yaml",
            "message": "ModuleNotFoundError: No module named 'yaml'",
        }
    )
    assert len(group_events([a, b], run, threshold=0.01)) == 2


def test_same_symptom_across_files_can_group(session):
    run = failed_pytest(session)
    a = parse(run)[0]
    b = a.model_copy(update={"event_id": "b", "location": "tests/test_b.py"})
    assert len(group_events([a, b], run)) == 1


def test_versions_not_discarded(session):
    run = Run(tool="pip_check", scope="deps")
    base = dict(
        run_id=run.run_id,
        tool="pip_check",
        stage="dependency",
        kind="dependency_conflict",
        component="alpha",
    )
    a = Event(**base, message="requires alpha==1.0")
    b = Event(**base, message="requires alpha==2.0")
    assert len(group_events([a, b], run, threshold=0)) == 2


def test_complete_link_prevents_chaining():
    matrix = [[1, 0.9, 0.2], [0.9, 1, 0.9], [0.2, 0.9, 1]]
    assert complete_link(matrix, 0.8) == [[0, 1], [2]]


def rule(rule_id, when, then, phase="derive"):
    return {"id": rule_id, "phase": phase, "when": when, "then": then}


def test_rule_chain_and_cycle_terminate():
    fact = Fact(fact_id="f1", subject="x", predicate="a", value="yes")
    rules = engine.load_rules(
        {
            "rule": [
                rule("a-b", [["?s", "a", "yes"]], [["?s", "b", "yes"]]),
                rule("b-c", [["?s", "b", "yes"]], [["?s", "c", "yes"]]),
                rule("c-a", [["?s", "c", "yes"]], [["?s", "a", "yes"]]),
            ]
        }
    )
    facts = forward_chain([fact], rules)
    assert len(facts) == 3
    assert facts[-1].inputs == ["x:b:yes"]
    assert forward_chain([], rules) == []


def test_rule_engine_joins_variables_and_rejects_unstratified_negation():
    facts = [
        Fact(fact_id="1", subject="i1", predicate="module", value="module:m"),
        Fact(fact_id="2", subject="module:m", predicate="is_local", value="m.py"),
        Fact(fact_id="3", subject="i2", predicate="module", value="module:n"),
    ]
    when = [["?i", "module", "?m"], ["?m", "is_local", "?p"], ["not", "?m", "provided_by", "?_"]]
    rules = engine.load_rules({"rule": [rule("r", when, [["?i", "local", "?p"]], "diagnose")]})
    base = engine.run(rules, facts)
    assert ("i1", "local", "m.py") in base.keys
    assert not any(f.subject == "i2" and f.predicate == "local" for f in base.facts)
    assert base.facts[-1].inputs == ["1", "2"]
    with pytest.raises(ValueError, match="unstratified"):
        engine.load_rules(
            {
                "rule": [
                    rule("x", [["?i", "kind", "k"], ["not", "?i", "diagnosis", "?_"]],
                         [["?i", "diagnosis", "d"]], "diagnose")
                ]
            }
        )


def test_no_environment_mismatch_invented(session):
    ingest(session, [failed_pytest(session)])
    assert session.actions[0].action_id == "inspect-environment"
    assert not any(f.value == "environment_mismatch" for f in session.facts)


def test_goal_changes_priority(session):
    ingest(session, [failed_pytest(session), ruff_run(session, "E501")])
    from fixfirst.reasoning import infer_and_plan

    session.goal = "check_style"
    infer_and_plan(session)
    # Direct current-goal actions must precede unrelated import inspection.
    assert session.actions[0].action_id != "inspect-environment"


def test_store_validates_ids(tmp_path, session):
    store = Store(tmp_path / "store")
    with pytest.raises(ValueError):
        store.load("../../etc/passwd")
    store.save(session)
    assert store.load(session.session_id) == session


def test_export_redacts_and_html_escapes(tmp_path, session):
    session.name = "<script>alert('x')</script>"
    session.runs.append(
        Run(tool="pip_install", stdout="password=secret123\n/Users/alice/private/a.py")
    )
    data = public_data(session)
    assert "secret123" not in json.dumps(data)
    assert "/Users/alice" not in json.dumps(data)
    path = render(session, tmp_path, tmp_path / "report.html", public=True)
    html = path.read_text()
    assert "<script>alert('x')</script>" not in html
    assert "&lt;script&gt;" in html


def test_imported_pass_never_closes_executed(session, tmp_path):
    ingest(session, [ruff_run(session, "E501")])
    path = tmp_path / "ruff.json"
    path.write_text("[]")
    import_log(session, path, "ruff", 0)
    assert session.issues[0].status != "resolved"


def test_gini_model_roundtrip(tmp_path):
    local = [0.0] * len(FEATURE_NAMES)
    local[FEATURE_NAMES.index("module_local")] = 1.0
    missing = [0.0] * len(FEATURE_NAMES)
    rows = [{"features": local, "label": "local_module"}] * 2
    rows += [{"features": missing, "label": "missing_dependency"}] * 2
    train_tree(rows, tmp_path / "model.json", min_samples_leaf=1)
    model = load_model(tmp_path / "model.json")
    assert predict_tree(local, model) == ("local_module", 1.0)
    assert predict_tree(missing, model)[0] == "missing_dependency"
    assert "kind" not in " ".join(model["feature_names"])


def test_runner_timeout_and_output_bound(tmp_path):
    run = execute(
        [sys.executable, "-c", "import time;print('start',flush=True);time.sleep(9)"],
        str(tmp_path),
        "pytest",
        "test",
        sys.executable,
        timeout=0.2,
    )
    assert run.status == "timeout"
    assert "start" in run.stdout
    run = execute(
        [sys.executable, "-c", "print('a'*100000)"],
        str(tmp_path),
        "pytest",
        "test",
        sys.executable,
        max_output=200,
    )
    assert run.status == "output_limit"
    assert len(run.stdout.encode()) <= 200


def test_runner_launch_failure(tmp_path):
    run = execute(["/nonexistent/python"], str(tmp_path), "pytest", "test", "/nonexistent/python")
    assert run.status == "launch_failed"
    assert run.exit_code is None


def test_redact_preserves_ordinary_text():
    value = "version=1.2.3 password=hello https://me:secret@host/a API_KEY=abc"
    result = redact(value)
    assert "version=1.2.3" in result
    assert "hello" not in result and "secret@" not in result and "abc" not in result


def test_redact_environment_dumps_and_secret_dict_values():
    text = "self = environ({'USER': 'alice', 'AWS_SECRET_ACCESS_KEY': 'abc123'})\nkey = 'X'"
    cleaned = redact(text)
    assert "alice" not in cleaned and "abc123" not in cleaned and "key = 'X'" in cleaned
    assert redact("{'api_token': 'hunter2', 'name': 'shop'}") == "{'api_token': '[credential]', 'name': 'shop'}"


def process_alive(pid: int) -> bool:
    import os
    import subprocess

    if os.name == "nt":
        found = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        )
        return str(pid) in found.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_timeout_stops_the_whole_process_tree(tmp_path):
    import time

    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "print('started', flush=True)\n"
        "time.sleep(60)\n"
    )
    began = time.monotonic()
    run = execute([sys.executable, "-c", script], str(tmp_path), "pytest", "test", sys.executable,
                  timeout=3)
    assert run.status == "timeout" and "started" in run.stdout
    assert time.monotonic() - began < 15
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not process_alive(pid)


def test_windows_paths_are_classified_like_posix_paths():
    from fixfirst.evidence import classify_path

    env = {"paths": {"stdlib": "C:\\Python312\\Lib"}}
    root = "C:\\Users\\wang\\shop"
    assert classify_path("C:\\Users\\wang\\shop\\app.py", root, env) == "project"
    assert classify_path("c:\\users\\wang\\shop\\tests\\test_app.py", root, env) == "test"
    assert classify_path("tests\\test_app.py", root, env) == "test"
    assert classify_path("C:\\Python312\\Lib\\json\\decoder.py", root, env) == "stdlib"
    assert classify_path("C:\\shop\\.venv\\Lib\\site-packages\\numpy\\x.py", root, env) == "third_party"
    assert classify_path("D:\\elsewhere\\x.py", root, env) == "unknown"


def test_complete_ruff_run_closes_only_the_findings_it_no_longer_reports(session):
    first = ruff_run(session, "E501")
    rows = json.loads(first.stdout) + [
        {"code": "F401", "message": "unused import", "filename": "b.py", "location": {"row": 1}}
    ]
    first.stdout, first.exit_code = json.dumps(rows), 1
    ingest(session, [first])
    assert len(session.issues) == 2
    ingest(session, [ruff_run(session, "E501")])
    status = {i.component: i.status for i in session.issues}
    assert status == {"E501": "open", "F401": "resolved"}
