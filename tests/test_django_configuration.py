"""Configuration facts and provenance; no target modules execute in the reader."""

import json
import os

import pytest

from fixfirst.django_configuration import recorded_configuration
from fixfirst.models import Run, Session
from fixfirst.runner import environment_id
from fixfirst.service import ingest


UNCONFIGURED = (
    "Requested setting DEBUG, but settings are not configured. You must either define "
    "the environment variable DJANGO_SETTINGS_MODULE or call settings.configure() before accessing settings."
)


@pytest.mark.parametrize("filename,text,source", [
    ("pytest.ini", "[pytest]\nDJANGO_SETTINGS_MODULE = suite.config\n", "pytest.ini [pytest]"),
    (".pytest.ini", "[pytest]\nDJANGO_SETTINGS_MODULE = suite.config\n", ".pytest.ini [pytest]"),
    ("setup.cfg", "[tool:pytest]\nDJANGO_SETTINGS_MODULE = suite.config\n", "setup.cfg [tool:pytest]"),
    ("tox.ini", "[pytest]\nDJANGO_SETTINGS_MODULE = suite.config\n", "tox.ini [pytest]"),
    ("pyproject.toml", '[tool.pytest.ini_options]\nDJANGO_SETTINGS_MODULE = "suite.config"\n', "pyproject.toml [tool.pytest.ini_options]"),
    ("pyproject.toml", '[tool.pytest]\nDJANGO_SETTINGS_MODULE = "suite.config"\n', "pyproject.toml [tool.pytest]"),
])
def test_records_literal_plugin_settings_without_claiming_precedence(tmp_path, filename, text, source):
    (tmp_path / filename).write_text(text)
    result = recorded_configuration(tmp_path)
    assert result == {"candidates": [{"source": source, "module": "suite.config",
                                     "entrypoint": "pytest-django configuration"}], "unknown_sources": []}


def test_records_tox_makefile_and_runtests_candidates_without_executing(tmp_path):
    (tmp_path / "tox.ini").write_text("[testenv]\nsetenv =\n DJANGO_SETTINGS_MODULE = alpha.settings\ncommands=pytest\n"
                                    "[testenv:other]\nsetenv=DJANGO_SETTINGS_MODULE=beta.settings\n")
    (tmp_path / "Makefile").write_text("test:\n\tDJANGO_SETTINGS_MODULE=gamma.settings python -m pytest\n")
    (tmp_path / "runtests.py").write_text("import os\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', 'delta.settings')\n"
                                        "raise RuntimeError('must never execute')\n")
    result = recorded_configuration(tmp_path)
    assert {r["module"] for r in result["candidates"]} == {
        "alpha.settings", "beta.settings", "gamma.settings", "delta.settings"}
    assert {r["entrypoint"] for r in result["candidates"]} == {"tox [testenv]", "tox [testenv:other]", "make test", "runtests.py"}


@pytest.mark.parametrize("text", [
    "import os\nos.environ['DJANGO_SETTINGS_MODULE'] = choose_settings()\n",
    "import os\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', choose_settings())\n",
    "from helper import configure\nconfigure('DJANGO_SETTINGS_MODULE')\n",
])
def test_dynamic_python_settings_remain_unknown(tmp_path, text):
    (tmp_path / "runtests.py").write_text(text)
    result = recorded_configuration(tmp_path)
    assert not result["candidates"] and result["unknown_sources"]


@pytest.mark.parametrize("filename,text", [
    ("tox.ini", "[testenv]\nsetenv =\n py312: DJANGO_SETTINGS_MODULE = a.settings\n"),
    ("tox.ini", "[testenv]\nsetenv = DJANGO_SETTINGS_MODULE = {env:SETTINGS:a.settings}\n"),
    ("Makefile", "test:\n\tDJANGO_SETTINGS_MODULE=$(SETTINGS) python -m pytest\n"),
    ("pytest.ini", "[pytest]\nDJANGO_SETTINGS_MODULE = a.settings\nDJANGO_SETTINGS_MODULE = b.settings\n"),
    ("pyproject.toml", "[tool.pytest.ini_options]\nDJANGO_SETTINGS_MODULE = 42\n"),
])
def test_substitutions_invalid_or_duplicate_configuration_is_not_guessed(tmp_path, filename, text):
    (tmp_path / filename).write_text(text)
    result = recorded_configuration(tmp_path)
    assert not result["candidates"] and result["unknown_sources"]


@pytest.mark.parametrize("unsafe", ["symlink", "oversized", "directory", "fifo"])
def test_unsafe_files_are_not_read_and_do_not_block_other_candidates(tmp_path, unsafe):
    path = tmp_path / "runtests.py"
    if unsafe == "symlink":
        outside = tmp_path.parent / "outside-django-settings.py"
        outside.write_text("raise RuntimeError('never')")
        path.symlink_to(outside)
    elif unsafe == "oversized":
        path.write_text("x" * 128001)
    elif unsafe == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    (tmp_path / "pytest.ini").write_text("[pytest]\nDJANGO_SETTINGS_MODULE=suite.config\n")
    result = recorded_configuration(tmp_path)
    assert [r["module"] for r in result["candidates"]] == ["suite.config"]
    assert result["unknown_sources"] == ["runtests.py (unreadable or unsafe)"]


def test_ini_defaults_and_commented_shell_text_are_not_assignments(tmp_path):
    (tmp_path / "pytest.ini").write_text("[DEFAULT]\nDJANGO_SETTINGS_MODULE=wrong\n[pytest]\n")
    (tmp_path / "Makefile").write_text("test:\n\techo 'DJANGO_SETTINGS_MODULE=wrong'\n")
    assert not recorded_configuration(tmp_path)["candidates"]


def test_plugin_addopts_and_configuration_classes_cannot_hide_competing_settings(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\nDJANGO_SETTINGS_MODULE=alpha.settings\n"
                                        "addopts=--ds=beta.settings\nDJANGO_CONFIGURATION=Testing\n")
    result = recorded_configuration(tmp_path)
    assert {r["module"] for r in result["candidates"]} == {"alpha.settings", "beta.settings"}
    assert result["unknown_sources"]


def failure_records(root, site, mechanism="settings", *, node="test_config.py", stage="collect"):
    kind = "ImproperlyConfigured" if mechanism == "settings" else "AppRegistryNotReady"
    message = UNCONFIGURED if mechanism == "settings" else "Apps aren't loaded yet."
    filename = site + ("/django/conf/__init__.py" if mechanism == "settings" else "/django/apps/registry.py")
    function = "_setup" if mechanism == "settings" else "check_apps_ready"
    frames = [{"file": root + "/test_config.py", "line": 3, "function": "test_config"},
              {"file": filename, "line": 61, "function": function}]
    text = "Traceback (most recent call last):\n" + "".join(
        f'  File "{f["file"]}", line {f["line"]}, in {f["function"]}\n    access()\n' for f in frames
    ) + f"django.core.exceptions.{kind}: {message}"
    return [{"type": "failure", "nodeid": node, "stage": stage, "message": text},
            {"type": "exception", "nodeid": node, "stage": stage,
             "exception_type": kind, "exception_module": "django.core.exceptions", "exception_message": message,
             "source_file": filename, "source_line": 61, "traceback_frames": frames,
             **({"django_registry": {"global_registry": True, "apps_ready": False, "loading": False, "ready": False}}
                if mechanism == "apps" else {})}]


def saved_case(tmp_path, mechanism="settings", *, windows=False, mutate=None, config=None):
    root = "C:/sample" if windows else str(tmp_path)
    python = root + "/.venv/bin/python"
    site = root + "/.venv/lib/python3.12/site-packages"
    identity = environment_id(python)
    env_run = Run(tool="environment", environment_id=identity, cwd=root, scope="environment", exit_code=0)
    environment = {"python_version": "3.12.13", "paths": {"purelib": site, "platlib": site},
                   "packages": [{"name": "Django", "version": "5.2.1", "requires": []},
                                {"name": "pytest", "version": "8.3.5", "requires": []}],
                   "import_distributions": {"django": ["Django"], "pytest": ["pytest"]}}
    project = {"environment_run_id": env_run.run_id, "local_modules": [], "declarations": [],
               "own_names": [], "python_files": [], "django_configuration": config or {}}
    run = Run(tool="pytest_run", cwd=root, environment_id=identity, scope="tests:project", exit_code=2,
              argv=[python, "-m", "pytest", "-q"], tool_version="8.3.5",
              records=failure_records(root, site, mechanism))
    project_run = Run(tool="project", cwd=root, environment_id=identity, scope="declarations:project", exit_code=0)
    if mutate:
        mutate(environment, project, run)
    env_run.stdout, project_run.stdout = json.dumps(environment), json.dumps(project)
    session = Session(name="synthetic", project_root=root, target_python=python, goal="pass_tests", use_classifier=False,
                      environment={**environment, "_run_id": env_run.run_id, "_environment_id": identity})
    ingest(session, [env_run, project_run, run])
    return session


@pytest.mark.parametrize("tool,field,value", [
    ("project", "cwd", "/different-project"), ("project", "cwd", ""),
    ("project", "scope", "foreign-project-snapshot"),
    ("environment", "cwd", "/different-project"), ("environment", "scope", "foreign-environment"),
])
def test_foreign_snapshot_cannot_supply_settings_advice(tmp_path, tool, field, value):
    from fixfirst.django_configuration import observations

    session = saved_case(tmp_path, config={"candidates": [{"module": "foreign.settings",
                         "source": "tox.ini", "entrypoint": "tox testenv"}]})
    setattr(next(r for r in session.runs if r.tool == tool), field, value)
    assert observations(session, session.issues) == ([], {})


@pytest.mark.parametrize("mechanism,rule", [("settings", "D51"), ("apps", "D52")])
@pytest.mark.parametrize("windows", [False, True])
def test_exact_django_operation_produces_named_diagnosis_and_manual_advice(tmp_path, mechanism, rule, windows):
    session = saved_case(tmp_path, mechanism, windows=windows)
    issue = next(i for i in session.issues if i.tool == "pytest_run")
    assert (issue.diagnosis, issue.diagnosis_rule) == ("config_missing", rule)
    action = next(a for a in session.actions if "P86" in a.rule_ids)
    assert not action.command and "tests.settings" not in action.explanation
    assert "No literal settings candidate" in action.explanation
    if mechanism == "apps":
        assert "does not prove setup was never called" in action.explanation
        assert "Do not add django.setup() to reusable" in action.explanation


@pytest.mark.parametrize("bad", ["missing", "provider", "shadow", "foreign_path", "project_raised", "other_message",
                                 "wrong_class", "stale", "success", "imported", "truncated", "no_exception",
                                 "tool_version", "wrong_cwd"])
def test_incomplete_or_conflicting_provenance_cannot_prove_django_configuration(tmp_path, bad):
    def change(env, project, run):
        record = run.records[1]
        if bad == "missing":
            env["packages"] = [p for p in env["packages"] if p["name"] != "Django"]
        elif bad == "provider":
            env["import_distributions"]["django"].append("other")
        elif bad == "shadow":
            project["local_modules"] = [{"name": "django", "path": "django.py"}]
        elif bad in {"foreign_path", "project_raised"}:
            record["source_file"] = ("/other/site-packages/django/conf/__init__.py" if bad == "foreign_path"
                                     else str(tmp_path / "my_code.py"))
            record["traceback_frames"][-1]["file"] = record["source_file"]
        elif bad == "other_message":
            record["exception_message"] = "The SECRET_KEY setting must not be empty."
        elif bad == "wrong_class":
            record["exception_module"] = "project.exceptions"
        elif bad == "stale":
            run.environment_id = "old"
        elif bad == "success":
            run.exit_code = 0
        elif bad == "imported":
            run.source = "imported"
        elif bad == "truncated":
            run.truncated = True
        elif bad == "no_exception":
            run.records = run.records[:1]
        elif bad == "tool_version":
            run.tool_version = "7.0.0"
        elif bad == "wrong_cwd":
            run.cwd = "/other/project"
    session = saved_case(tmp_path, mutate=change)
    assert all(i.diagnosis_rule not in {"D51", "D52"} for i in session.issues)
    assert not any("P86" in a.rule_ids for a in session.actions)


def test_app_import_during_existing_setup_is_not_missing_configuration(tmp_path):
    def change(env, project, run):
        run.records[1]["traceback_frames"].insert(1, {
            "file": env["paths"]["purelib"] + "/django/apps/registry.py", "function": "populate", "line": 91})
    session = saved_case(tmp_path, "apps", mutate=change)
    assert all(i.diagnosis_rule != "D52" for i in session.issues)


@pytest.mark.parametrize("state", [{}, {"global_registry": False, "apps_ready": False, "loading": False, "ready": False},
                                  {"global_registry": True, "apps_ready": False, "loading": True, "ready": False},
                                  {"global_registry": True, "apps_ready": False, "loading": 0, "ready": False}])
def test_registry_state_must_prove_native_bools_on_the_global_registry(tmp_path, state):
    def change(env, project, run):
        run.records[1]["django_registry"] = state
    session = saved_case(tmp_path, "apps", mutate=change)
    assert all(i.diagnosis_rule != "D52" for i in session.issues)


def test_multiple_independently_matching_failures_keep_their_evidence(tmp_path):
    def change(env, project, run):
        run.records += failure_records(str(tmp_path), env["paths"]["purelib"], node="test_other.py")
    session = saved_case(tmp_path, mutate=change)
    assert all(i.diagnosis_rule == "D51" for i in session.issues if i.tool == "pytest_run")


def test_mixed_grouped_failures_cannot_share_django_signature_and_frame(tmp_path):
    from fixfirst.django_configuration import observations

    session = saved_case(tmp_path)
    run = session.runs[-1]
    event = session.events[-1]
    issue = next(i for i in session.issues if i.tool == "pytest_run")
    extra = failure_records(str(tmp_path), str(tmp_path) + "/.venv/lib/python3.12/site-packages", node="second")
    extra[1]["exception_message"] = "The SECRET_KEY setting must not be empty."
    run.records += extra
    second = event.model_copy(update={"event_id": "second", "evidence_refs": [f"{run.run_id}:probe:2"]})
    session.events.append(second)
    issue.event_ids.append(second.event_id)
    assert observations(session, [issue]) == ([], {})
    # One event referencing two failures must not bypass independent matching.
    issue.event_ids = [event.event_id]
    event.evidence_refs.append(f"{run.run_id}:probe:2")
    assert observations(session, [issue]) == ([], {})


def test_environment_snapshot_taken_after_failure_is_not_failure_context(tmp_path):
    from fixfirst.django_configuration import observations

    session = saved_case(tmp_path)
    env, project, failure = session.runs
    session.runs = [failure, env, project]
    assert observations(session, session.issues) == ([], {})


def test_registry_observation_never_calls_a_user_dict_property(monkeypatch):
    import sys
    import types
    from fixfirst._runtime_evidence import django_registry_state

    calls = []
    class Apps:
        @property
        def __dict__(self):
            calls.append("property")
            raise AssertionError("must not inspect through user code")

        def check_apps_ready(self):
            return django_registry_state(types.SimpleNamespace(tb_frame=sys._getframe()))

    module = types.ModuleType("django.apps.registry")
    module.Apps, module.apps = Apps, Apps()
    monkeypatch.setitem(sys.modules, "django.apps.registry", module)
    assert module.apps.check_apps_ready() == {}
    assert not calls


def test_settings_candidate_names_the_project_entrypoint_and_not_a_default(tmp_path):
    config = {"candidates": [{"module": "suite.config", "source": "tox.ini [testenv] setenv", "entrypoint": "tox [testenv]"}],
              "unknown_sources": []}
    session = saved_case(tmp_path, config=config)
    action = next(a for a in session.actions if "P86" in a.rule_ids)
    assert "DJANGO_SETTINGS_MODULE=suite.config" in action.title
    assert "tox.ini [testenv]" in action.explanation and "may bypass tox" in action.explanation
    assert "confirmed module" in action.explanation and not action.command


def test_multiple_settings_sources_never_select_one_module(tmp_path):
    config = {"candidates": [{"module": value, "source": "tox.ini [testenv:" + value + "]",
                              "entrypoint": "tox"} for value in ("alpha.settings", "beta.settings")]}
    session = saved_case(tmp_path, config=config)
    action = next(a for a in session.actions if "P86" in a.rule_ids)
    assert "Multiple or unresolved" in action.explanation
    assert "alpha.settings" in action.explanation and "beta.settings" in action.explanation
    assert "DJANGO_SETTINGS_MODULE=" not in action.title


@pytest.mark.parametrize("plugin", [False, True])
def test_plugin_configuration_is_not_effective_merely_because_it_exists(tmp_path, plugin):
    config = {"candidates": [{"module": "suite.config", "source": "pytest.ini [pytest]",
                              "entrypoint": "pytest-django configuration"}]}
    def change(env, project, run):
        if plugin:
            env["packages"].append({"name": "pytest-django", "version": "4.11.1", "requires": []})
    session = saved_case(tmp_path, config=config, mutate=change)
    action = next(a for a in session.actions if "P86" in a.rule_ids)
    expected = "check that it is loaded" if plugin else "config option alone does not configure plain pytest"
    assert expected in action.explanation


def django_actions():
    from fixfirst.models import Action
    actions = [Action(action_id=f"review-{i}", kind="inspect", title="Review Django settings", explanation="same",
                      verification="rerun original tests", issue_ids=[f"issue-{i}"], reason_refs=[f"evidence-{i}"],
                      preconditions=[f"fact-{i}"], rule_ids=["P86"], cause="config_missing",
                      goal_impact=i, evidence_rank=i + 1, cost=4 - i) for i in range(3)]
    context = {"mechanism": "settings_unconfigured", "configuration": {
        "candidates": [{"module": "suite.config", "source": "tox.ini [testenv]", "entrypoint": "tox"}],
        "unknown_sources": []}, "plugin_installed": False, "argv": ["python", "-m", "pytest", "-q"]}
    details = {f"issue-{i}": {"django_configuration": json.loads(json.dumps(context))} for i in range(3)}
    return actions, details


def test_identical_django_reviews_keep_every_issue_evidence_and_precondition():
    from fixfirst.django_configuration import _group_identical
    from fixfirst.models import Fact
    from fixfirst.reasoning import order_actions
    actions, details = django_actions()
    result = _group_identical(actions, details)
    assert len(result) == 1 and result[0].action_id == "review-0"
    action = result[0]
    assert action.issue_ids == [f"issue-{i}" for i in range(3)]
    assert action.reason_refs == [f"evidence-{i}" for i in range(3)]
    assert action.preconditions == [f"fact-{i}" for i in range(3)]
    assert (action.goal_impact, action.evidence_rank, action.cost) == (2, 3, 2)
    facts = [Fact(fact_id=f"fact-{i}", subject="x", predicate="x", value="x") for i in range(2)]
    assert order_actions(result, facts)[0].blocked_reasons == ["fact-2"]
    assert _group_identical(result, details) == result


@pytest.mark.parametrize("field,value", [
    ("mechanism", "apps_not_ready"), ("configuration", {"candidates": []}),
    ("plugin_installed", True), ("argv", ["python", "-m", "pytest", "-c", "different.ini"]),
    ("configuration", {"candidates": [], "unknown_sources": ["dynamic runner"]}),
])
def test_equal_titles_with_different_configuration_evidence_are_not_merged(field, value):
    from fixfirst.django_configuration import _group_identical
    actions, details = django_actions()
    details["issue-1"]["django_configuration"][field] = value
    result = _group_identical(actions, details)
    assert [a.issue_ids for a in result] == [["issue-0", "issue-2"], ["issue-1"]]


@pytest.mark.parametrize("field,value", [
    ("explanation", "different next step"), ("verification", "different runner"),
    ("command", ["python", "-m", "pip", "install", "pytest-django"]),
    ("targets", ["different.ini"]), ("declaration_edits", [{"file": "requirements.txt"}]),
    ("rule_ids", ["P86", "other"]), ("kind", "manual_fix"),
])
def test_equal_titles_with_different_repairs_are_not_merged(field, value):
    from fixfirst.django_configuration import _group_identical
    actions, details = django_actions()
    setattr(actions[1], field, value)
    result = _group_identical(actions, details)
    assert [a.issue_ids for a in result] == [["issue-0", "issue-2"], ["issue-1"]]


def test_missing_evidence_and_other_rules_remain_separate():
    from fixfirst.django_configuration import _group_identical
    actions, details = django_actions()
    del details["issue-1"]
    actions[2].rule_ids = ["P12"]
    assert _group_identical(actions, details) == actions


REAL_PYTHON = os.environ.get("FIXFIRST_DJANGO_PYTHON")


@pytest.mark.skipif(not REAL_PYTHON, reason="requires an explicitly supplied isolated Django interpreter")
@pytest.mark.parametrize("case", ["settings", "settings_collect", "apps", "apps_collect", "healthy",
                                  "other_config", "early_import", "custom_registry", "missing_django", "local_shadow"])
def test_real_django_mechanisms_in_an_independent_environment(tmp_path, monkeypatch, case):
    from fixfirst.service import create_session, scan

    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    (tmp_path / "suite_config.py").write_text("SECRET_KEY='synthetic-only'\nINSTALLED_APPS=[]\n")
    (tmp_path / "tox.ini").write_text("[testenv]\nsetenv=DJANGO_SETTINGS_MODULE=suite_config\ncommands=pytest\n")
    if case in {"apps", "apps_collect", "healthy", "other_config", "early_import", "custom_registry"}:
        monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "suite_config")
    code = "from django.conf import settings\ndef test_value():\n    assert settings.DEBUG is False\n"
    if case == "settings_collect":
        code = "from django.conf import settings\nFLAG = settings.DEBUG\ndef test_value():\n    assert FLAG is False\n"
    if case in {"apps", "healthy"}:
        code = "from django.apps import apps\ndef test_value():\n    assert list(apps.get_app_configs()) == []\n"
    if case == "apps_collect":
        code = "from django.apps import apps\nCONFIGS = list(apps.get_app_configs())\ndef test_value():\n    assert CONFIGS == []\n"
    if case == "healthy":
        (tmp_path / "conftest.py").write_text("import django\ndjango.setup()\n")
    elif case == "other_config":
        (tmp_path / "suite_config.py").write_text("SECRET_KEY=''\nINSTALLED_APPS=[]\n")
        code = "from django.conf import settings\ndef test_value():\n    assert settings.SECRET_KEY\n"
    elif case == "early_import":
        (tmp_path / "suite_config.py").write_text("SECRET_KEY='synthetic-only'\nINSTALLED_APPS=['bad_app']\n")
        (tmp_path / "bad_app").mkdir()
        (tmp_path / "bad_app" / "__init__.py").write_text("from django.apps import apps\nlist(apps.get_app_configs())\n")
        (tmp_path / "conftest.py").write_text("import django\ndjango.setup()\n")
    elif case == "custom_registry":
        code = ("from django.apps.registry import Apps\ndef test_value():\n"
                "    custom = Apps([])\n    custom.apps_ready = False\n    custom.check_apps_ready()\n")
    elif case == "local_shadow":
        (tmp_path / "django.py").write_text("# synthetic project shadow\n")
    (tmp_path / "test_config.py").write_text(code)
    import sys
    session = create_session(tmp_path, sys.executable if case == "missing_django" else REAL_PYTHON, goal="pass_tests")
    session.use_classifier = False
    scan(session, ["environment", "project", "pytest_run"])
    run = next(r for r in session.runs if r.tool == "pytest_run")
    diagnoses = [i.diagnosis_rule for i in session.issues if i.tool == "pytest_run"]
    if case in {"settings", "settings_collect", "apps", "apps_collect"}:
        expected = "D51" if case.startswith("settings") else "D52"
        assert expected in diagnoses, [(r.get("exception_type"), len(r.get("traceback_frames", []))) for r in run.records]
        if case.startswith("settings"):
            monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "suite_config")
        else:
            (tmp_path / "conftest.py").write_text("import django\ndjango.setup()\n")
        scan(session, ["pytest_run"])
        assert next(r for r in reversed(session.runs) if r.tool == "pytest_run").verified_pass
    else:
        assert not ({"D51", "D52"} & set(diagnoses))
        assert (run.exit_code == 0) is (case == "healthy")
