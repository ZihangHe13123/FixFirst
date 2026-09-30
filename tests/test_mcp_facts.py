"""The facts-only MCP mode (facts.py): what the checks showed, and nothing FixFirst concluded."""

import json
from pathlib import Path
import re
import subprocess
import sys

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import fixfirst
from fixfirst.facts import TOP_LEVEL_KEYS, facts_view
from fixfirst.mcp_server import Server
from fixfirst.models import Event, Fact, Issue, Run, Session

KNOWLEDGE = tomllib.loads((Path(fixfirst.__file__).parent / "knowledge" / "domain.toml").read_text(encoding="utf-8"))
CAUSES = tuple(KNOWLEDGE["causes"])  # the root-cause labels
CAUSE_NAMES = tuple(cause["label"].lower() for cause in KNOWLEDGE["causes"].values())  # as people read them
FAILURE_KEYS = {"check", "tests", "more_tests", "exception", "message", "stage", "raised_in", "where",
                "source_location", "library",
                "names", "recorded_warnings"}


def call(server, name, arguments=None):
    answer = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": name, "arguments": arguments or {}}})
    if "error" in answer:
        return answer["error"]["message"], True
    return answer["result"]["content"][0]["text"], answer["result"]["isError"]


def assert_no_conclusions(text: str):
    """Nothing the full diagnosis adds may appear: causes, rules, categories, predictions, advice."""
    lowered = text.lower()
    assert len(CAUSES) == 5 and not [cause for cause in CAUSES + CAUSE_NAMES if cause in lowered]
    assert not re.search(r"\b[DFGHP]\d{2}\b", text)  # rule ids
    for word in ("diagnosis", "category", "prediction", "hypothesis", "confidence", "remedy", "pip install",
                 "command", "step", "suggest", "provided_until_release", "install_below"):
        assert word not in lowered, word


def missing_module_project(tmp_path):
    project = tmp_path / "shop"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "shop"\nversion = "0"\nrequires-python = ">=3.8"\n')
    (project / "test_app.py").write_text("import notinstalled_zz\n\n\ndef test_app():\n    assert notinstalled_zz\n")
    return project


def test_the_facts_mode_offers_one_neutral_tool(tmp_path):
    server = Server(tmp_path / "store", mode="facts")
    hello = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})["result"]
    assert "no diagnosis and no advice" in hello["instructions"] and "diagnose" not in hello["instructions"]
    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert [t["name"] for t in tools] == ["observe"]
    for name in ("diagnose", "check_again", "explain"):
        text, failed = call(server, name, {"project": str(tmp_path)})
        assert failed and "Unknown tool" in text
    text, failed = call(server, "observe", {"folder": str(tmp_path)})
    assert failed and "unknown folder" in text


def test_observe_reports_what_the_checks_showed_without_any_conclusion(tmp_path):
    project = missing_module_project(tmp_path)
    full, failed = call(Server(tmp_path / "full"), "diagnose", {"project": str(project), "python": sys.executable})
    # The full mode concludes something about this failure and advises what to do.
    assert not failed and "cause" in full.lower() and "Why:" in full and "Confirm:" in full
    server = Server(tmp_path / "facts", mode="facts")
    text, failed = call(server, "observe", {"project": str(project), "python": sys.executable})
    assert not failed
    assert_no_conclusions(text)
    view = json.loads(text)
    assert view["facts_only"] is True and set(view) <= set(TOP_LEVEL_KEYS)
    assert view["python"]["path"] == sys.executable and view["declared_python"] == [
        ">=3.8 in pyproject.toml [project.requires-python]"]
    [failure] = view["failures"]
    assert set(failure) <= FAILURE_KEYS
    assert failure["exception"] == "ModuleNotFoundError" and "notinstalled_zz" in failure["message"]
    assert failure["where"].startswith("test_app.py:1") and failure["names"]["missing_module"] == "notinstalled_zz"
    assert view["modules"]["notinstalled_zz"] == {"installed": []}  # no installed distribution provides it
    run = next(c for c in view["checks"] if c["check"] == "pytest_run")
    assert run["exit_code"] not in (0, None)
    # After a change, observe runs the checks again: the failure is gone, the passing run is a fact.
    (project / "test_app.py").write_text("def test_app():\n    assert True\n")
    view = json.loads(call(server, "observe", {"project": str(project), "python": sys.executable})[0])
    assert view["failures"] == [] and "modules" not in view
    run = next(c for c in view["checks"] if c["check"] == "pytest_run")
    assert run["exit_code"] == 0 and run["counts"]["passed"] == 1


def test_diagnoses_knowledge_and_release_searches_never_reach_the_facts(tmp_path):
    session = Session(name="t", project_root=str(tmp_path), target_python=sys.executable, goal="pass_tests")
    run = Run(tool="pytest_run", exit_code=1, stdout="E   AttributeError: module 'numpy' has no attribute 'float'")
    search = Run(tool="version_search", stdout=json.dumps({"api": "numpy.float", "dist": "numpy", "provides": "1.23.5",
                                                           "below": "1.24", "status": "found"}), verified_pass=True)
    event = Event(run_id=run.run_id, tool="pytest_run", stage="run", kind="attribute_error", code="AttributeError",
                  message="module 'numpy' has no attribute 'float'", location="tests/test_a.py::test_a")
    issue = Issue(issue_id="issue-1", fingerprint="f", tool="pytest_run", stage="run", kind="attribute_error",
                  title="numpy.float was removed", event_ids=[event.event_id], evidence_refs=[], member_keys=[],
                  scope="tests:project", environment_id="unknown", category="version_incompatibility",
                  diagnosis="version_incompatibility", diagnosis_source="rule", diagnosis_rule="D02",
                  prediction="version_incompatibility", prediction_confidence=0.9, targets=["tests/test_a.py::test_a"])
    session.runs += [run, search]
    session.events.append(event)
    session.issues.append(issue)
    session.facts += [Fact(fact_id="k", subject="api:numpy.float", predicate="removed_in_version", value="1.24",
                           status="knowledge"),
                      Fact(fact_id="d", subject="issue-1", predicate="diagnosis", value="version_incompatibility",
                           status="derived", rule_id="D02")]
    text = json.dumps(facts_view(session))
    assert_no_conclusions(text)
    assert "1.23.5" not in text and "removed" not in text and "numpy.float was removed" not in text
    view = json.loads(text)
    assert [c["check"] for c in view["checks"]] == ["pytest_run"]  # the release search is not a fact here
    assert view["failures"][0]["exception"] == "AttributeError"


def test_the_facts_server_starts_over_stdio_and_writes_no_store(tmp_path):
    store = tmp_path / "store"
    answer = subprocess.run(
        [sys.executable, "-m", "fixfirst", "--store", str(store), "mcp", "--facts"],
        input='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n', capture_output=True, text=True, timeout=60)
    assert json.loads(answer.stdout)["result"]["serverInfo"]["name"] == "fixfirst"
    assert "sessions in memory only" in answer.stderr and not store.exists()


def test_observe_keeps_its_sessions_in_memory_only(tmp_path):
    project = missing_module_project(tmp_path)
    server = Server(tmp_path / "store", mode="facts")
    call(server, "observe", {"project": str(project), "python": sys.executable})
    call(server, "observe", {"project": str(project), "python": sys.executable})
    assert not (tmp_path / "store").exists() and len(server.memory) == 1  # the second call continues it
    assert not list(tmp_path.rglob("session.json"))
