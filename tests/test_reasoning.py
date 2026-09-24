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


def scan_project(root):
    session = create_session(root, sys.executable, goal="pass_tests")
    session.use_classifier = False
    scan(session, cases.CHECKS)
    return session, [i for i in session.issues if i.status == "open" and i.tool == "pytest_run"]


def test_missing_plugin_fixture_names_the_declared_plugin(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1"\n\n'
        '[project.optional-dependencies]\ntests = ["pytest-httpx"]\n'
    )
    (tmp_path / "test_http.py").write_text("def test_get(httpx_mock):\n    pass\n")
    session, issues = scan_project(tmp_path)
    assert [(i.diagnosis, i.diagnosis_rule) for i in issues] == [("missing_dependency", "D23")]
    step = build_view(session)["steps"][0]
    assert step["title"] == "Install pytest-httpx: the tests use its httpx_mock fixture"
    assert step["command"].endswith("-m pip install pytest-httpx")
    assert step["where"] == ["test_http.py:1"]
    assert "[project.optional-dependencies.tests]" in step["explanation"]
    assert step["sources"] == [{"title": "pytest-httpx on PyPI", "url": "https://pypi.org/project/pytest-httpx/"}]


def test_fixture_defined_out_of_reach_is_a_project_problem(tmp_path):
    (tmp_path / "helpers.py").write_text(
        "import pytest\n\n@pytest.fixture\ndef shop_client():\n    return object()\n"
    )
    (tmp_path / "test_shop.py").write_text("def test_list(shop_client):\n    pass\n")
    (tmp_path / "test_other.py").write_text("def test_other(unheard_of_fixture):\n    pass\n")
    session, issues = scan_project(tmp_path)
    found = {i.title.split("::")[-1]: (i.diagnosis, i.diagnosis_source, i.diagnosis_rule) for i in issues}
    assert found["test_list"] == ("code_defect", "rule", "D24")
    # Unknown to the knowledge base and not defined anywhere: only a likely plugin.
    assert found["test_other"] == ("missing_dependency", "heuristic", "H04")
    titles = [s["title"] for s in build_view(session)["steps"]]
    assert "Make the shop_client fixture visible to the test" in titles
    assert "Install the pytest plugin that provides the unheard_of_fixture fixture" in titles


def test_library_deprecation_warnings_that_break_a_warning_count(tmp_path):
    library = tmp_path / "vendor" / "site-packages" / "oldlib"
    library.mkdir(parents=True)
    (library / "__init__.py").write_text(
        "import warnings\n\ndef build():\n"
        "    warnings.warn('oldlib.tree is deprecated and will be removed in Python 3.99; "
        "use oldlib.graph instead', DeprecationWarning)\n"
    )
    (tmp_path / "test_count.py").write_text(
        "import pathlib, sys, warnings\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).parent / 'vendor' / 'site-packages'))\n"
        "import oldlib\n\n"
        "def test_one_warning(recwarn):\n"
        "    oldlib.build()\n"
        "    warnings.warn('cookie is too large', UserWarning)\n"
        "    assert len(recwarn) == 1\n\n"
        "def test_plain_assertion():\n"
        "    assert 1 + 1 == 3\n"
    )
    session, issues = scan_project(tmp_path)
    found = {i.title.split("::")[-1]: (i.diagnosis, i.diagnosis_rule) for i in issues}
    assert found == {
        "test_one_warning": ("version_incompatibility", "D45"),
        "test_plain_assertion": ("code_defect", "D40"),
    }
    view = build_view(session)
    # The plain assertion is a problem to fix; the warning count does not affect running.
    assert view["status"]["headline"] == "1 problem to fix"
    assert "1 more failing test below does not affect how your code runs" in view["status"]["detail"]
    assert [s["id"] for s in view["steps"]] == ["review-test_assertion"]
    step = view["optional"][0]
    assert step["title"] == "Make the test ignore oldlib's oldlib.tree deprecation warnings"
    assert "make up 1 of the 2 it recorded" in step["explanation"]
    assert "oldlib.tree at oldlib/__init__.py:4" in step["explanation"]
    assert step["where"] == ["test_count.py:8"] and step["optional"]
    assert step["impact"].startswith("Your code runs normally. Only this test fails")
    assert step["risk"] is None  # not in the knowledge base: no removal date to warn about
    assert step["warnings"] == [
        "oldlib/__init__.py:4: oldlib.tree is deprecated and will be removed in Python 3.99; "
        "use oldlib.graph instead"
    ]


def test_only_optional_failures_left_is_not_a_problem(tmp_path):
    library = tmp_path / "vendor" / "site-packages" / "routes"
    library.mkdir(parents=True)
    (library / "__init__.py").write_text(
        "import warnings\n\ndef compile_rule():\n"
        "    warnings.warn('ast.Str is deprecated and will be removed in Python 3.14; "
        "use ast.Constant instead', DeprecationWarning)\n"
    )
    (tmp_path / "test_cookie.py").write_text(
        "import pathlib, sys, warnings\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).parent / 'vendor' / 'site-packages'))\n"
        "import routes\n\n"
        "def test_cookie(recwarn):\n"
        "    routes.compile_rule()\n"
        "    warnings.warn('cookie is too large', UserWarning)\n"
        "    assert len(recwarn) == 1\n"
    )
    session, issues = scan_project(tmp_path)
    assert [(i.diagnosis, i.diagnosis_rule) for i in issues] == [("version_incompatibility", "D45")]
    view = build_view(session)
    assert view["status"]["kind"] == "advisory"
    assert view["status"]["headline"] == "No problems that affect your code"
    assert view["steps"] == [] and len(view["optional"]) == 1
    step = view["optional"][0]
    # The knowledge base knows Python 3.14 removes ast.Str (rule D46).
    assert step["risk"] == (
        "Python 3.14 removes ast.Str. routes uses it in code your tests run, so that code will fail on Python 3.14."
    )
    assert any(rule.startswith("D46:") for rule in step["rules"])


def test_deprecation_knowledge_and_project_origin_choose_the_fix():
    from fixfirst import domain, engine
    from fixfirst.models import Fact

    def fact(s, p, v):
        return Fact(fact_id=f"{s}:{p}:{v}", subject=s, predicate=p, value=v)

    def plan(emitted_by, origin):
        facts = [
            fact("issue-1", "exception", "AssertionError"),
            fact("issue-1", "asserts_on", "recorded_warnings"),
            fact("issue-1", "recorded_warning_count", "4"),
            fact("issue-1", "extra_warning_count", "3"),
            fact("issue-1", "extra_warning", "api:ast.Str"),
            fact("api:ast.Str", "emitted_by", emitted_by),
            fact("api:ast.Str", "emitted_at", origin),
            fact("api:ast.Str", "warning_text", "ast.Str is deprecated"),
            fact("dist:python", "installed_version", "3.12.4"),
            *domain.facts_for({"api:ast.Str"}),
        ]
        base = engine.run(rule_base(), facts)
        return base, engine.propose(rule_base(), base)

    base, proposals = plan("dist:werkzeug", "werkzeug/routing.py:957")
    assert ("issue-1", "diagnosis", "code_defect") not in base.keys
    action = next(p for p in proposals if p.action_id == "count-expected-warnings-ast.str")
    assert action.rule_ids == ["P33"]
    text = engine.render(action.template["explanation"], action.bindings)
    assert "which warns about ast.Str since 3.12" in text and "Python older than 3.12" in text
    assert ("issue-1", "affects_running", "no") in base.keys
    assert ("issue-1", "breaks_in_future", "api:ast.Str") in base.keys
    _, proposals = plan("project", "src/app.py:12")
    assert [p.action_id for p in proposals if p.rule_ids == ["P34"]] == ["replace-deprecated-ast.str"]


def test_lint_knowledge_separates_possible_bugs_from_clean_up():
    from fixfirst import domain

    assert [c for c in ("F821", "E999", "F632", "B006", "PLE0101", "F524") if domain.likely_bug(c)] == [
        "F821", "E999", "F632", "B006", "PLE0101", "F524",
    ]
    # Unused imports, unused .format() arguments and modernisation never break running code.
    assert not any(domain.likely_bug(c) for c in ("F401", "F522", "F541", "F811", "UP031", "I001", "E501"))
    assert domain.lint_category("UP031") == "Outdated syntax that newer Python can write more simply"
    assert domain.lint_category("SIM118") == "Code that could be simpler"  # longest prefix, not S
    assert domain.lint_category("PLR0913") == "Pylint refactoring hints"


def test_project_lint_settings_are_detected(tmp_path):
    from fixfirst.project import lint_settings

    assert lint_settings(tmp_path) == {"ruff": None, "other": None}
    (tmp_path / "setup.cfg").write_text("[flake8]\nmax-line-length = 100\n")
    assert lint_settings(tmp_path) == {"ruff": None, "other": "setup.cfg [flake8]"}
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    assert lint_settings(tmp_path)["ruff"] == "pyproject.toml [tool.ruff]"


def test_code_check_goal_counts_only_findings_that_may_be_bugs(tmp_path):
    (tmp_path / "setup.cfg").write_text("[flake8]\nmax-line-length = 100\n")
    (tmp_path / "app.py").write_text("import os\nimport sys\n\n\ndef total():\n    return subtotal + 1\n")
    session = create_session(tmp_path, sys.executable, goal="check_style")
    scan(session, ["environment", "project", "ruff"])
    view = build_view(session)
    assert [s["id"] for s in view["steps"]] == ["review-code_check"]  # F821 undefined name
    assert view["steps"][0]["where"] == ["app.py:6"]
    assert view["status"]["headline"] == "1 problem to fix"
    assert "Ruff also has 2 clean-up suggestions below (optional)" in view["status"]["detail"]
    cleanup = view["optional"][0]
    assert cleanup["id"] == "cleanup-code" and cleanup["optional"]
    assert "configures its linter in setup.cfg [flake8], not Ruff" in cleanup["explanation"]
    assert cleanup["breakdown"] == [{"name": "Unused imports", "count": 2, "codes": ["F401"]}]

    (tmp_path / "app.py").write_text("import os\nimport sys\n\n\ndef total():\n    return 1\n")
    scan(session, ["ruff"])
    view = build_view(session)
    assert view["steps"] == [] and view["status"]["kind"] == "advisory"
    assert view["status"]["headline"] == "No problems that affect your code"
    assert "Ruff still has 2 clean-up suggestions" in view["status"]["detail"]
