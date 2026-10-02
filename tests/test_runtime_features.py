"""Raw candidate features must not borrow diagnoses or neighbouring failures."""

import hashlib
import json
from pathlib import Path

import pytest

from fixfirst.classification import default_model, predict_tree, validate_model
from fixfirst.evidence import FEATURE_LAYOUTS, FEATURE_NAMES, observations
from fixfirst.models import Event, Issue, Run, Session
from fixfirst.runner import environment_id
from fixfirst.runtime_features import FEATURE_NAMES as NEW_NAMES, feature_values, release


ROOT = "/project"
PYTHON = "/env/bin/python"
SITE = "/env/lib/python3.12/site-packages"
STDLIB = "/python/lib/python3.12"


def saved_case(kind="DeprecationWarning", message="a deprecated operation", *, owner="_pytest/assertion/rewrite.py"):
    identity = environment_id(PYTHON)
    path = SITE + "/" + owner
    frames = [{"file": ROOT + "/test_case.py", "line": 2, "function": "test_case"},
              {"file": path, "line": 3, "function": "operation"}]
    record = {"type": "exception", "nodeid": "test_case.py::test_case", "stage": "call",
              "exception_type": kind, "exception_message": message, "exception_module": "builtins",
              "source_file": path, "source_line": 3, "traceback_frames": frames}
    failure = {"type": "failure", "nodeid": record["nodeid"], "stage": "call",
               "message": f'{ROOT}/test_case.py:2: in test_case\n    call()\n{path}:3: in operation\nE   {kind}: {message}\n'}
    environment = {"python_version": "3.12.13", "paths": {"purelib": SITE, "platlib": SITE, "stdlib": STDLIB},
                   "packages": [{"name": "pytest", "version": "8.3.5"}, {"name": "py", "version": "1.11.0"},
                                {"name": "Django", "version": "5.2.1"}],
                   "import_distributions": {"_pytest": ["pytest"], "py": ["py"], "django": ["Django"]},
                   "_run_id": "env", "_environment_id": identity}
    env = Run(run_id="env", tool="environment", environment_id=identity, cwd=ROOT, scope="environment", exit_code=0,
              stdout=json.dumps({k: v for k, v in environment.items() if not k.startswith("_")}))
    project = Run(run_id="project", tool="project", environment_id=identity, cwd=ROOT,
                  scope="declarations:project", exit_code=0,
                  stdout=json.dumps({"environment_run_id": "env", "local_modules": [], "declarations": []}))
    failed = Run(run_id="failed", tool="pytest_run", environment_id=identity, cwd=ROOT,
                 scope="tests:project", exit_code=1, tool_version="8.3.5", records=[failure, record])
    event = Event(event_id="event", run_id="failed", tool="pytest_run", stage="call", kind="test_runtime_error",
                  message=message, code=kind, evidence_refs=["failed:probe:0"])
    issue = Issue(issue_id="issue", fingerprint="fixture", tool="pytest_run", stage="call", kind="test_runtime_error",
                  title="fixture", event_ids=["event"], evidence_refs=event.evidence_refs,
                  member_keys=[], scope="tests:project", environment_id=identity)
    session = Session(name="arbitrary", project_root=ROOT, target_python=PYTHON, goal="pass_tests", use_classifier=False,
                      environment=environment, runs=[env, project, failed], events=[event], issues=[issue])
    return session, issue, session.runs[-1].records[1]


def test_terminal_warning_and_actual_tool_operation_are_independent_values():
    session, issue, record = saved_case()
    record["traceback_frames"].append({"file": STDLIB + "/ast.py", "line": 4, "function": "__new__"})
    record["source_file"] = STDLIB + "/ast.py"
    result = feature_values(session, issue)
    assert result["raw_terminal_warning"] == result["raw_operation_test_tool_owned"] == 1
    record["traceback_frames"][-2]["file"] = ROOT + "/own_warning.py"
    assert feature_values(session, issue)["raw_operation_test_tool_owned"] == 0
    assert feature_values(session, issue)["raw_terminal_warning"] == 1


@pytest.mark.parametrize("bad", ["foreign", "shadow", "provider", "last_frame"])
def test_tool_ownership_needs_current_provider_and_actual_operation(bad):
    session, issue, record = saved_case()
    if bad == "foreign":
        record["source_file"] = record["traceback_frames"][-1]["file"] = "/foreign/site-packages/_pytest/assertion/rewrite.py"
    elif bad == "shadow":
        project = json.loads(session.runs[1].stdout)
        project["local_modules"] = [{"name": "_pytest", "path": "_pytest.py"}]
        session.runs[1].stdout = json.dumps(project)
    elif bad == "provider":
        session.environment["import_distributions"]["_pytest"].append("other")
    else:
        record["source_file"] = ROOT + "/elsewhere.py"
    assert feature_values(session, issue)["raw_operation_test_tool_owned"] == -1


@pytest.mark.parametrize("bad", ["imported", "success", "truncated", "environment_after", "environment_id",
                                 "project_scope", "project_cwd", "runner_version", "missing_packages", "old_event",
                                 "empty_cwd", "env_scope", "env_cwd"])
def test_unknown_provenance_cannot_become_observed_absence(bad):
    session, issue, _ = saved_case()
    if bad == "imported":
        session.runs[-1].source = "imported"
    elif bad == "success":
        session.runs[-1].exit_code = 0
    elif bad == "truncated":
        session.runs[-1].truncated = True
    elif bad == "environment_after":
        session.runs = [session.runs[-1], *session.runs[:-1]]
    elif bad == "environment_id":
        session.environment["_environment_id"] = "stale"
    elif bad == "project_scope":
        session.runs[1].scope = "foreign"
    elif bad == "project_cwd":
        session.runs[1].cwd = "/another-project"
    elif bad == "runner_version":
        session.runs[-1].tool_version = "7.2.2"
    elif bad == "missing_packages":
        del session.environment["packages"]
    elif bad == "empty_cwd":
        session.runs[-1].cwd = ""
    elif bad == "env_scope":
        session.runs[0].scope = "unknown"
    elif bad == "env_cwd":
        session.runs[0].cwd = "/other"
    else:
        session.events[0].run_id = "old-run"
    assert set(feature_values(session, issue).values()) == {-1}


def test_missing_terminal_record_does_not_turn_a_warning_summary_into_an_exception():
    session, issue, _ = saved_case()
    session.runs[-1].records = [{"type": "warning", "category": "DeprecationWarning", "message": "notice"}]
    result = feature_values(session, issue)
    assert result["raw_terminal_warning"] == -1
    assert result["raw_setuptools_installed"] == 0  # Independently known snapshot absence.


def test_pkg_resources_missing_and_package_versions_are_raw_independent_facts():
    session, issue, _ = saved_case("ModuleNotFoundError", "No module named 'pkg_resources'", owner="some_library.py")
    absent = feature_values(session, issue)
    assert absent["raw_missing_pkg_resources"] == 1 and absent["raw_setuptools_installed"] == 0
    assert absent["raw_setuptools_release"] == -1
    session.environment["packages"].append({"name": "setuptools", "version": "84.0.0"})
    installed = feature_values(session, issue)
    assert installed["raw_missing_pkg_resources"] == installed["raw_setuptools_installed"] == 1
    assert installed["raw_setuptools_release"] == 84_000_000


@pytest.mark.parametrize("version", [None, "bad", "1.2a1", "1.2.dev0", "1.2.post1", "1.2+patched", "1!1.2", "1.2.3.4", "1.1000.0"])
def test_nonstable_or_ambiguous_release_coordinates_are_unknown(version):
    assert release(version) == -1


def test_release_coordinates_keep_semver_component_order():
    assert release("7.3.1") < release("7.3.2") < release("7.10.0") < release("8")
    assert release("3.12.13") == 3_012_013


def test_django_message_is_only_a_text_signal_and_registry_needs_global_identity():
    session, issue, record = saved_case("AppRegistryNotReady", "Apps aren't loaded yet.", owner="django/apps/registry.py")
    record["exception_module"] = "django.core.exceptions"
    record["traceback_frames"][-1]["function"] = "check_apps_ready"
    assert feature_values(session, issue)["raw_message_apps_not_ready"] == 1
    assert feature_values(session, issue)["raw_global_registry_apps_ready"] == -1
    record["django_registry"] = {"global_registry": True, "apps_ready": False, "loading": True}
    values = feature_values(session, issue)
    assert values["raw_global_registry_apps_ready"] == 0
    assert values["raw_global_registry_loading"] == 1  # During setup remains distinguishable.
    record["django_registry"]["global_registry"] = False
    assert feature_values(session, issue)["raw_global_registry_apps_ready"] == -1
    record["django_registry"].update(global_registry=True, apps_ready=0)
    assert feature_values(session, issue)["raw_global_registry_apps_ready"] == -1


def test_settings_message_does_not_claim_a_project_exception_is_framework_owned():
    message = ("Requested setting DEBUG, but settings are not configured. You must either define the environment "
               "variable DJANGO_SETTINGS_MODULE or call settings.configure() before accessing settings.")
    session, issue, record = saved_case("ImproperlyConfigured", message)
    record["source_file"] = record["traceback_frames"][-1]["file"] = ROOT + "/own_exception.py"
    values = feature_values(session, issue)
    assert values["raw_message_settings_unconfigured"] == 1
    assert values["raw_operation_test_tool_owned"] == 0
    assert values["raw_global_registry_apps_ready"] == -1


def test_mixed_members_cannot_borrow_terminal_signal_or_tool_frame():
    session, issue, record = saved_case()
    failure2 = dict(session.runs[-1].records[0], nodeid="second")
    record2 = {**record, "nodeid": "second", "exception_type": "RuntimeError", "exception_message": "unrelated",
               "source_file": ROOT + "/own.py", "traceback_frames": [{"file": ROOT + "/own.py"}]}
    session.runs[-1].records += [failure2, record2]
    session.events.append(session.events[0].model_copy(update={"event_id": "second", "code": "RuntimeError",
                                                              "evidence_refs": ["failed:probe:2"]}))
    issue.event_ids.append("second")
    values = feature_values(session, issue)
    assert values["raw_terminal_warning"] == values["raw_operation_test_tool_owned"] == -1
    issue.event_ids = ["event"]
    session.events[0].evidence_refs.append("failed:probe:2")
    assert feature_values(session, issue)["raw_terminal_warning"] == -1


def test_case_labels_rule_results_and_names_are_not_feature_inputs():
    session, issue, _ = saved_case()
    expected = feature_values(session, issue)
    session.name = "config_missing--repair-by-setup"
    issue.diagnosis, issue.diagnosis_rule, issue.prediction = "config_missing", "D52", "code_defect"
    issue.kind, issue.title, issue.fingerprint, issue.issue_id = "other_unknown", "label", "other", "new-case-id"
    session.events[0].event_id = "renamed-event"
    issue.event_ids = ["renamed-event"]
    assert feature_values(session, issue) == expected


def test_schema_append_preserves_old_models_and_the_frozen_default_bytes():
    assert len(FEATURE_LAYOUTS[3]) == 44 and len(FEATURE_LAYOUTS[8]) == 81 and len(FEATURE_NAMES) == 93
    assert FEATURE_NAMES[:81] == FEATURE_LAYOUTS[8] and FEATURE_NAMES[81:] == NEW_NAMES
    session, issue, _ = saved_case()
    _, details = observations(session, [issue])
    vector = details[issue.issue_id]["features"]
    assert len(vector) == 93 and vector[81:] == list(feature_values(session, issue).values())
    model = default_model()
    assert predict_tree(vector, model) == predict_tree(vector[:44], model)
    previous = validate_model({"schema_version": 8, "task": "root_cause", "feature_names": FEATURE_LAYOUTS[8],
                               "classes": ["code_defect"], "nodes": [{"left": -1, "values": [1]}]})
    assert predict_tree(vector, previous) == predict_tree(vector[:81], previous)
    path = Path(__file__).resolve().parents[1] / "src/fixfirst/knowledge/diagnosis_tree.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3"
