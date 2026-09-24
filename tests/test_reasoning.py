import json
import sys

import pytest

from fixfirst import diagnosis_cases as cases
from fixfirst.evaluation import evaluate
from fixfirst.evidence import classify_path, executed_lines
from fixfirst.knowledge_graph import build_graph, query_graph
from fixfirst.reasoning import rule_base
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view

SCENARIOS = {s.scenario_id: s for s in cases.SCENARIOS}
FLAT = cases.TEMPLATES[0]


def run_scenario(tmp_path, scenario_id, template=FLAT, index=0):
    root = tmp_path / scenario_id
    cases.build_template(root, template)
    SCENARIOS[scenario_id].apply(cases.Project(root, template, index))
    session = create_session(root, sys.executable, goal="pass_tests")
    session.use_classifier = False
    scan(session, cases.CHECKS)
    issue = next(i for i in session.issues if i.status == "open" and i.tool == "pytest_run")
    return session, issue


@pytest.mark.parametrize(
    "scenario, cause, rule, action",
    [
        ("vi_stdlib_module", "version_incompatibility", "D01", "update-imp"),
        ("vi_numpy_alias", "version_incompatibility", "D02", "update-numpy.float"),
        ("vi_numpy2", "version_incompatibility", "D02", "update-numpy.nan"),
        ("cm_environ", "config_missing", "D30", "configure-shop_api_token"),
        ("lm_shadow_library", "local_module", "D10", "rename-jinja2.py"),
        ("lm_renamed", "local_module", "D16", "fix-import-helper"),
        ("md_known_import", "missing_dependency", "D21", "install-requests"),
        ("cd_local_kwarg", "code_defect", "D43", "review-test_runtime_error"),
    ],
)
def test_rules_and_knowledge_diagnose_real_failures(tmp_path, scenario, cause, rule, action):
    # Variant 2 of the shadowing scenario uses Jinja2, a FixFirst dependency, so the shadowed
    # library is installed on every machine that runs these tests.
    session, issue = run_scenario(tmp_path, scenario, index=2 if scenario == "lm_shadow_library" else 0)
    assert (issue.diagnosis, issue.diagnosis_source, issue.diagnosis_rule) == (cause, "rule", rule)
    assert session.actions[0].action_id == action
    assert session.actions[0].cause == (None if cause == "code_defect" else cause)


def test_knowledge_backed_advice_cites_its_source(tmp_path):
    session, issue = run_scenario(tmp_path, "vi_stdlib_module")
    action = session.actions[0]
    assert "importlib" in action.explanation and "3.12" in action.title
    knowledge = [f for f in session.facts if f.fact_id in action.reason_refs and f.status == "knowledge"]
    assert knowledge and all(ref == "kb:python-3.12" for f in knowledge for ref in f.evidence_refs)
    graph = build_graph(session)
    assert any(n["type"] == "Source" and "3.12" in n["label"] for n in graph["nodes"])
    answer = query_graph(graph, "What is the root cause?")
    assert answer["supported"] and "Version incompatibility" in answer["answer"] and "D01" in answer["answer"]


def test_unlisted_removal_is_only_a_likely_cause(tmp_path):
    # numpy.msort is not in the knowledge base: no rule may confirm the cause, but the
    # heuristic phase marks a version change as likely and says so.
    session, issue = run_scenario(tmp_path, "vi_unknown_attribute")
    assert (issue.diagnosis, issue.diagnosis_source, issue.diagnosis_rule) == (
        "version_incompatibility",
        "heuristic",
        "H02",
    )
    step = build_view(session)["steps"][0]
    assert step["title"].startswith("Try an older numpy") and "msort" in step["title"]
    assert step["cause"] is None and step["possible"] == "Version incompatibility"
    # numpy.msort was removed in 2.0, so stepping back one series is the right first try.
    assert step["command"].endswith("-m pip install 'numpy<2'")


def test_environment_snapshot_survives_a_project_file_that_shadows_the_stdlib(tmp_path):
    (tmp_path / "random.py").write_text("VALUE = 1\n")
    session = create_session(tmp_path, sys.executable)
    scan(session, ["environment", "pip_check"])
    assert all(run.verified_pass for run in session.runs)
    assert "random" in session.environment["stdlib_modules"]


def test_graph_answers_questions_in_english_and_chinese(tmp_path):
    session, _ = run_scenario(tmp_path, "cm_environ")
    graph = build_graph(session)
    for question in ("why is this recommended", "为什么推荐这个行动"):
        answer = query_graph(graph, question)
        assert answer["supported"] and answer["entity"] == session.actions[0].action_id
    provider = query_graph(graph, "Which package provides cv2?")
    assert "opencv-python" in provider["answer"]
    removed = query_graph(graph, "was numpy.float removed?")
    assert "1.24" in removed["answer"] and "numpy.org" in removed["answer"]
    assert not query_graph(graph, "what is the weather tomorrow")["supported"]


def test_rule_base_is_stratified_and_every_rule_is_documented():
    rules = rule_base()
    assert len({r.rule_id for r in rules}) == len(rules)
    assert all(r.description for r in rules)


def test_evidence_helpers_handle_portable_and_pytest_paths():
    env = {"paths": {"stdlib": "/home/user/python/lib/python3.12"}}
    assert classify_path("/project/app.py", "/project", env) == "project"
    assert classify_path("/project/tests/test_app.py", "/project", env) == "test"
    assert classify_path("<project>/app.py", "<project>", env) == "project"
    assert classify_path("/venv/lib/python3.12/site-packages/numpy/__init__.py", "/project", env) == "third_party"
    assert classify_path("<frozen os>", "/project", env) == "stdlib"
    assert classify_path("../../.cache/python/lib/python3.12/subprocess.py", "/p", env) == "stdlib"
    traceback = "app.py:2: in <module>\n    from pydantic import BaseSettings\n>       raise ImportError(msg)"
    assert executed_lines(traceback) == ["from pydantic import BaseSettings", "raise ImportError(msg)"]


def test_diagnosis_dataset_and_cross_validation_end_to_end(tmp_path):
    chosen = [SCENARIOS[s] for s in ("cm_environ", "cd_assertion", "vi_stdlib_module", "md_known_import")]
    manifest = cases.build_dataset(tmp_path / "data", templates=cases.TEMPLATES[:2], scenarios=chosen)
    data = json.loads(manifest.read_text())
    assert len(data["cases"]) == 8 and not data["rejected"]
    assert "/Users/" not in (tmp_path / "data" / "cases.jsonl").read_text()
    report = evaluate(tmp_path / "data", tmp_path / "evaluation")
    metrics = json.loads(report.with_name("metrics.json").read_text())
    rules = metrics["protocols"]["leave_one_template_out"]["overall"]["rules"]
    assert rules["accuracy"] == 1.0
    assert (tmp_path / "evaluation" / "decision_tree.txt").exists()


def test_install_advice_comes_with_a_command_for_the_project_interpreter(tmp_path):
    session, _ = run_scenario(tmp_path, "md_known_import")
    action = session.actions[0]
    assert action.action_id == "install-requests"
    assert action.command == [session.target_python, "-m", "pip", "install", "requests"]
    step = build_view(session)["steps"][0]
    assert step["command"].endswith("-m pip install requests")


def test_removed_usage_is_recognised_by_its_error_message(tmp_path):
    # pytest.warns(None) was removed in pytest 8; the error never names `warns`.
    (tmp_path / "test_old.py").write_text(
        "import pytest\n\ndef test_old_style():\n    with pytest.warns(None):\n        pass\n"
    )
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    session.use_classifier = False
    scan(session, cases.CHECKS)
    issue = next(i for i in session.issues if i.status == "open" and i.tool == "pytest_run")
    assert (issue.diagnosis, issue.diagnosis_rule) == ("version_incompatibility", "D07")
    assert session.actions[0].title == "Replace pytest.warns(None): removed in pytest 8.0"


def test_setup_py_without_setuptools_suggests_installing_it():
    from fixfirst import engine
    from fixfirst.models import Fact
    from fixfirst.reasoning import rule_base

    facts = [
        Fact(fact_id="a", subject="issue-1", predicate="runs", value="setup.py"),
        Fact(fact_id="b", subject="dist:setuptools", predicate="not_installed", value="yes"),
    ]
    base = engine.run(rule_base(), facts)
    assert ("issue-1", "likely", "missing_dependency") in base.keys
    action = next(p for p in engine.propose(rule_base(), base) if p.action_id == "install-setuptools")
    assert action.template["pip_install"] == "{?d}"
