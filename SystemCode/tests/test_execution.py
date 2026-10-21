import json
import sys

import pytest

from fixfirst.classification import validate_model
from fixfirst.knowledge_graph import build_graph, query_graph, RELATIONS
from fixfirst.models import Run
from fixfirst.parsers import parse
from fixfirst.report import render
from fixfirst.service import create_session, scan
from fixfirst.storage import Store
from test_integration import cli


def write_test_source(root, first=False, second=False, decoration=""):
    # The fix is in the project (cart.py); the tests stay the same unless a decoration is asked for.
    (root / "cart.py").write_text(f"DISCOUNT = {10 if first else 15}\nTAX = {20 if second else 25}\n")
    (root / "test_cart.py").write_text(
        "import pytest\n\nimport cart\n\n\n"
        + decoration
        + "def test_discount():\n    assert cart.DISCOUNT == 10\n\n\n"
        + "def test_tax():\n    assert cart.TAX == 20\n"
    )


def test_collection_success_is_not_test_execution_success(tmp_path):
    write_test_source(tmp_path)
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest"])
    assert session.goal_status == "unknown"
    scan(session, ["pytest_run"])
    assert session.goal_status == "blocked"
    assert {i.kind for i in session.issues} == {"test_assertion"}
    assert len(session.issues) == 2
    assert session.runs[-1].test_summary["failed"] == 2
    assert session.runs[-1].coverage_complete
    assert session.actions[0].action_id == "review-test_assertion"


def test_selected_pass_only_closes_that_node_then_full_pass(tmp_path):
    write_test_source(tmp_path)
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    initial = {i.targets[0]: i.issue_id for i in session.issues}
    write_test_source(tmp_path, first=True)
    scan(session, ["pytest_run"], targets=["test_cart.py::test_discount"])
    by_id = {i.issue_id: i for i in session.issues}
    assert by_id[initial["test_cart.py::test_discount"]].status == "resolved"
    assert by_id[initial["test_cart.py::test_tax"]].status == "not_observed"
    assert session.goal_status == "unknown"
    scan(session, ["pytest_run"])
    assert len(session.issues) == 2
    assert session.goal_status == "blocked"
    write_test_source(tmp_path, True, True)
    scan(session, ["pytest_run"])
    assert session.goal_status == "achieved"
    assert all(i.status == "resolved" for i in session.issues)


@pytest.mark.parametrize(
    "decoration", ["@pytest.mark.skip(reason='later')\n", "@pytest.mark.xfail(reason='later')\n"]
)
def test_skip_and_xfail_do_not_close_previous_failure(tmp_path, decoration):
    write_test_source(tmp_path, second=True)
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    old_id = session.issues[0].issue_id
    write_test_source(tmp_path, second=True, decoration=decoration)
    scan(session, ["pytest_run"])
    assert next(i for i in session.issues if i.issue_id == old_id).status != "resolved"
    assert session.goal_status == "unknown"
    assert session.runs[-1].passed_nodes == ["test_cart.py::test_tax"]


@pytest.mark.parametrize("stage", ["setup", "teardown"])
def test_fixture_phase_recorded_and_recovered(tmp_path, stage):
    body = (
        "    raise RuntimeError('fixture failed')\n    yield\n"
        if stage == "setup"
        else "    yield\n    raise RuntimeError('cleanup failed')\n"
    )
    # The fixture's work is in the project (resources.py), so the fix does not touch the tests.
    (tmp_path / "resources.py").write_text("def use():\n" + body)
    (tmp_path / "test_fixture.py").write_text(
        "import pytest\n\nimport resources\n\n\n@pytest.fixture\ndef resource():\n"
        "    yield from resources.use()\n\n\ndef test_using(resource):\n    assert True\n"
    )
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    assert session.issues[0].stage == stage
    assert session.issues[0].kind == "test_runtime_error"
    assert session.runs[-1].passed_nodes == []
    (tmp_path / "resources.py").write_text("def use():\n    yield\n")
    scan(session, ["pytest_run"])
    assert session.issues[0].status == "resolved"


def test_deleting_or_deselecting_failed_test_is_not_a_fix(tmp_path):
    write_test_source(tmp_path, second=True)
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    old_id = session.issues[0].issue_id
    (tmp_path / "test_cart.py").write_text("def test_tax():\n    assert True\n")
    scan(session, ["pytest_run"])
    assert next(i for i in session.issues if i.issue_id == old_id).status != "resolved"
    assert session.goal_status == "unknown"


def test_same_group_partial_observation_keeps_unchecked_member(tmp_path):
    (tmp_path / "test_group.py").write_text(
        "def test_a():\n    import fixfirst_missing_fixture\n\ndef test_b():\n    import fixfirst_missing_fixture\n"
    )
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    assert len(session.issues) == 1 and len(session.issues[0].targets) == 2
    original_id = session.issues[0].issue_id
    scan(session, ["pytest_run"], targets=["test_group.py::test_a"])
    assert len(session.issues) == 1 and len(session.issues[0].targets) == 2
    (tmp_path / "test_group.py").write_text(
        "def test_a():\n    assert True\n\ndef test_b():\n    import fixfirst_missing_fixture\n"
    )
    scan(session, ["pytest_run"])
    assert len(session.issues) == 1
    assert session.issues[0].issue_id == original_id
    assert session.issues[0].targets == ["test_group.py::test_b"]


def test_bad_or_foreign_nodes_rejected_before_execution(tmp_path):
    write_test_source(tmp_path)
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    count = len(session.runs)
    for target in [
        "--help",
        "../outside.py::test",
        "test_cart.py::unseen",
        "test_cart.py::test_tax\n",
    ]:
        with pytest.raises(ValueError):
            scan(session, ["pytest_run"], targets=[target])
    session.target_python = str(tmp_path / "different-python")
    with pytest.raises(ValueError):
        scan(session, ["pytest_run"], targets=["test_cart.py::test_tax"])
    assert len(session.runs) == count


def test_finish_without_node_outcomes_does_not_prove_execution():
    run = Run(
        tool="pytest_run",
        exit_code=0,
        records=[
            {
                "type": "finish",
                "exit_code": 0,
                "collected": 1,
                "nodes": ["test_a.py::test"],
                "collect_only": False,
                "records_dropped": False,
            }
        ],
    )
    parse(run)
    assert not run.verified_pass and not run.coverage_complete


def test_default_collection_scan_does_not_run_test_body(tmp_path):
    (tmp_path / "test_side_effect.py").write_text(
        "from pathlib import Path\ndef test_example():\n    Path('BODY_RAN').touch()\n"
    )
    session = create_session(tmp_path, sys.executable)
    scan(session)
    assert not (tmp_path / "BODY_RAN").exists()


def test_graph_queries_trace_real_execution_and_export(tmp_path):
    write_test_source(tmp_path)
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    graph = build_graph(session)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert all(
        (nodes[e["source"]]["type"], nodes[e["target"]]["type"]) == RELATIONS[e["relation"]]
        for e in graph["edges"]
    )
    answer = query_graph(graph, "为什么推荐这个行动")
    assert answer["supported"] and answer["paths"]
    assert all(nodes[p[-1]["target"]]["type"] == "Run" for p in answer["paths"])
    assert session.runs[-1].run_id in answer["answer"]
    assert not query_graph(graph, "明天的天气如何")["supported"]
    assert query_graph(graph, "依据", session.runs[-1].run_id)["supported"]
    output = tmp_path / "share.html"
    render(session, tmp_path / "store", output, public=True)
    exported = json.loads(output.with_suffix(".graph.json").read_text())
    assert session.project_root not in json.dumps(exported)
    assert len(exported["nodes"]) == len(graph["nodes"])


def test_cli_execution_targets_and_graph(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    write_test_source(project)
    store = Store(tmp_path / "store")
    session = create_session(project, sys.executable, goal="pass_tests")
    store.save(session)
    result = cli(store.root, "scan", session.session_id, "--checks", "pytest_run")
    assert result.returncode == 0, result.stderr
    assert cli(store.root, "ask", session.session_id, "为什么推荐这个行动").returncode == 0
    assert (
        cli(
            store.root, "graph", session.session_id, "--output", str(tmp_path / "kg.json")
        ).returncode
        == 0
    )
    assert cli(store.root, "run", session.session_id, "check-failed-tests").returncode == 0
    assert (
        cli(store.root, "scan", session.session_id, "--nodes", "test_cart.py::test_tax").returncode
        == 2
    )


def test_category_models_from_v03_are_rejected():
    # v0.3 trees learned the parser's own category (label leakage); they must be retrained.
    with pytest.raises(ValueError, match="retrain"):
        validate_model({"schema_version": 2, "feature_names": [], "classes": [], "nodes": []})


def test_old_environment_failure_does_not_override_current_pass(tmp_path):
    write_test_source(tmp_path)
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    for issue in session.issues:
        issue.environment_id = "previous-environment"
    for run in session.runs:
        run.environment_id = "previous-environment"
    write_test_source(tmp_path, True, True)
    scan(session, ["pytest_run"])
    assert session.goal_status == "achieved"
    assert all(i.status != "resolved" for i in session.issues)
    assert not any(a.kind == "manual_fix" for a in session.actions)


def test_all_skipped_is_not_a_successful_test_execution(tmp_path):
    (tmp_path / "test_skipped.py").write_text(
        "import pytest\n@pytest.mark.skip(reason='unavailable')\ndef test_one():\n    assert True\n"
    )
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    assert session.runs[-1].test_summary["skipped"] == 1
    assert session.runs[-1].passed_nodes == []
    assert session.goal_status == "unknown"
