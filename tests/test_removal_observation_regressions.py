"""Migration imports and legacy ownership stay tied to executed observations."""

import json
from pathlib import Path
import sys
import types

import pytest

from fixfirst._runtime_evidence import exception_metadata
from fixfirst.diagnosis_cases import load_session
from fixfirst.reasoning import infer_and_plan
from fixfirst.service import create_session, scan
from fixfirst.symbol_context import valid_record


def run_failure(root, source, *, collection=False):
    (root / "app.py").write_text(source)
    (root / "test_app.py").write_text(
        "import app\ndef test_failure():\n    app.fail()\n" if not collection else
        "import app\ndef test_import():\n    assert app\n")
    session = create_session(root, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    return session, issue


@pytest.mark.parametrize("module,member,replacement", [
    ("sklearn.datasets", "load_boston", "fetch_california_housing"),
    ("pydantic", "BaseSettings", "pydantic_settings"),
])
@pytest.mark.parametrize("collection", [False, True])
def test_real_library_migration_import_restores_d02_and_named_first_action(
        tmp_path, module, member, replacement, collection):
    source = f"from {module} import {member}\n" if collection else f"def fail():\n    from {module} import {member}\n"
    session, issue = run_failure(tmp_path, source, collection=collection)
    assert issue.diagnosis_rule == "D02" and issue.diagnosis_source == "rule"
    assert session.actions[0].action_id == f"update-{module}.{member}".lower()
    assert replacement in session.actions[0].explanation
    assert any(f.subject == issue.issue_id and f.predicate == "removal_owner"
               and f.value == f"api:{module}.{member}" for f in session.facts)
    run = next(r for r in session.runs if r.tool == "pytest_run")
    record = next(row["symbol_observation"] for row in run.records if row.get("symbol_observation"))
    assert valid_record(record) and record["operation"] == "IMPORT_NAME"
    assert record["module"] == module and record["name"] == member
    assert record["import_getattr"]["argument"] == member
    assert record["import_getattr"]["module_file"] == record["import_getattr"]["getter_file"]


@pytest.mark.parametrize("operation", [
    "raise ImportError('`load_boston` has been removed from scikit-learn since version 1.2.')",
    "raise ImportError('`BaseSettings` has been moved to the `pydantic-settings` package.')",
    "pydantic.__getattr__('BaseSettings')",
    "getattr(pydantic, 'BaseSettings')",
    "__import__('pydantic', fromlist=('BaseSettings',))",
    "importlib.import_module('pydantic').BaseSettings",
])
def test_messages_direct_getter_and_dynamic_import_are_not_import_ownership(tmp_path, operation):
    session, issue = run_failure(tmp_path, "import pydantic\nimport importlib\ndef fail():\n    " + operation + "\n")
    assert issue.diagnosis_rule != "D02"
    assert not any(f.predicate == "removal_owner" for f in session.facts)
    assert not any(a.action_id.startswith("update-pydantic") or a.action_id.startswith("update-sklearn")
                   for a in session.actions)


def test_project_shadow_module_cannot_borrow_installed_provider(tmp_path):
    (tmp_path / "pydantic.py").write_text(
        "def __getattr__(name):\n"
        "    if name == '__path__':\n        raise AttributeError(name)\n"
        "    raise ImportError('`BaseSettings` has been moved to the `pydantic-settings` package.')\n")
    session, issue = run_failure(tmp_path, "def fail():\n    from pydantic import BaseSettings\n")
    assert issue.diagnosis_rule != "D02"
    assert not any(f.predicate == "removal_owner" for f in session.facts)


def test_replaced_getter_has_no_library_code_origin(tmp_path):
    session, issue = run_failure(tmp_path,
        "import pydantic\ndef replacement(name):\n"
        "    raise ImportError('`BaseSettings` has been moved to the `pydantic-settings` package.')\n"
        "pydantic.__getattr__ = replacement\ndef fail():\n    from pydantic import BaseSettings\n")
    assert issue.diagnosis_rule != "D02"
    assert not any(f.predicate == "removal_owner" for f in session.facts)


def test_saved_library_import_error_cannot_lend_its_old_operation_to_a_later_raise(tmp_path):
    session, issue = run_failure(tmp_path,
        "try:\n    from pydantic import BaseSettings\n"
        "except ImportError as error:\n    saved = error\n"
        "def fail():\n    raise saved\n")
    assert issue.diagnosis_rule != "D02"
    assert not any(f.predicate == "removal_owner" for f in session.facts)
    assert not any(a.action_id.startswith("update-pydantic") for a in session.actions)


def test_changed_builtin_import_hook_does_not_prove_a_direct_library_import(tmp_path):
    session, issue = run_failure(tmp_path,
        "import builtins\nimport pydantic\noriginal = builtins.__import__\n"
        "def hooked(*args, **kwargs):\n    return original(*args, **kwargs)\n"
        "def fail():\n    builtins.__import__ = hooked\n"
        "    try:\n        from pydantic import BaseSettings\n"
        "    finally:\n        builtins.__import__ = original\n")
    assert issue.diagnosis_rule != "D02"
    assert not any(f.predicate == "removal_owner" for f in session.facts)


def test_observer_does_not_call_the_module_getter_again(monkeypatch):
    name, origin = "fixfirst_migration_observation", "/external/migration_observation.py"
    module = types.ModuleType(name)
    module.__file__ = origin
    module.__path__ = []
    exec(compile("calls = []\ndef __getattr__(name):\n    calls.append(name)\n"
                 "    if name == '__path__':\n        raise AttributeError(name)\n"
                 "    raise ImportError('custom migration')\n", origin, "exec"), vars(module))
    monkeypatch.setitem(sys.modules, name, module)
    with pytest.raises(ImportError) as caught:
        exec(compile(f"from {name} import Gone", "/project/test_import.py", "exec"))
    calls = list(vars(module)["calls"])
    row = exception_metadata(caught.value, caught.value.__traceback__)["symbol_observation"]
    assert valid_record(row) and row["module"] == name and row["name"] == "Gone"
    assert vars(module)["calls"] == calls


@pytest.mark.parametrize("names", ["Gone", "Good, Gone"])
def test_getter_local_reassignment_is_not_evidence_of_the_original_argument(monkeypatch, names):
    name, origin = "fixfirst_mutated_getter", "/external/mutated_getter.py"
    module = types.ModuleType(name)
    module.__file__ = origin
    module.__path__ = []
    exec(compile("def __getattr__(name):\n    name = 'Gone'\n"
                 "    raise ImportError('custom migration')\n", origin, "exec"), vars(module))
    monkeypatch.setitem(sys.modules, name, module)
    with pytest.raises(ImportError) as caught:
        exec(compile(f"from {name} import {names}", "/project/test_import.py", "exec"))
    assert exception_metadata(caught.value, caught.value.__traceback__)["symbol_observation"] == {}


def test_exception_hierarchy_checks_do_not_call_a_user_metaclass_comparator():
    seen = []
    class Meta(type):
        def __eq__(cls, other):
            seen.append("compared")
            return False
    class CustomError(ImportError, metaclass=Meta):
        pass
    with pytest.raises(CustomError) as caught:
        raise CustomError("a user error, not an imported library API")
    seen.clear()  # Pytest's own exception matching is outside the observer.
    assert exception_metadata(caught.value, caught.value.__traceback__)["symbol_observation"] == {}
    assert seen == []


def test_collect_wrapper_does_not_read_a_custom_exception_traceback_property():
    from _pytest.nodes import Collector

    seen = []
    class Meta(type):
        def __eq__(cls, other):
            seen.append("compared")
            return False
    class CustomError(ImportError, metaclass=Meta):
        @property
        def __traceback__(self):
            seen.append("traceback")
            return None
    wrapped = Collector.CollectError("wrapped failure")
    wrapped.__cause__ = CustomError("custom import error")
    exception_metadata(wrapped, None)
    assert seen == []


@pytest.mark.parametrize("change", ["imported", "wrong_statement", "wrong_origin", "conflicting_provider",
                                   "missing_proof", "other_argument", "malformed_fromlist", "incomplete_run"])
def test_import_owner_proof_rejects_stale_or_unverifiable_record(tmp_path, change):
    session, issue = run_failure(tmp_path, "def fail():\n    from pydantic import BaseSettings\n")
    assert issue.diagnosis_rule == "D02"
    run = next(r for r in session.runs if r.tool == "pytest_run")
    record = next(r["symbol_observation"] for r in run.records if r.get("symbol_observation"))
    if change == "imported":
        run.source = "imported"
    elif change == "wrong_statement":
        for row in run.records:
            if row.get("type") == "failure":
                row["message"] = row["message"].replace("from pydantic import BaseSettings", "from pydantic import Other")
    elif change == "wrong_origin":
        record["import_getattr"].update(module_file=str(tmp_path / "pydantic.py"), getter_file=str(tmp_path / "pydantic.py"))
    elif change == "conflicting_provider":
        session.environment["import_distributions"]["pydantic"] = ["pydantic", "another-package"]
    elif change == "missing_proof":
        record.pop("import_getattr")
    elif change == "other_argument":
        record["import_getattr"]["argument"] = "Other"
    elif change == "malformed_fromlist":
        record["import_getattr"]["fromlist"] = ["BaseSettings", "BaseSettings"]
    else:
        run.status = "timeout"
    infer_and_plan(session)
    assert issue.diagnosis_rule != "D02"
    assert not any(f.predicate == "removal_owner" for f in session.facts)


@pytest.mark.parametrize("template", ["flat-shop", "src-billing", "pkg-inventory", "unittest-grades", "fixture-orders"])
def test_original_public_unittest_alias_snapshot_requests_new_evidence(template):
    dataset = Path(__file__).resolve().parents[1] / "examples/diagnosis-dataset"
    case_id = template + "--vi_unittest_alias"
    case = next(row for row in map(json.loads, (dataset / "cases.jsonl").read_text().splitlines())
                if row["case_id"] == case_id)
    session = load_session(dataset, case["session"])
    infer_and_plan(session)
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    assert issue.diagnosis is None and issue.diagnosis_rule is None
    assert "Re-run the failing check" in issue.prediction_note
    assert session.actions[0].action_id.startswith("record-removal-ownership-")
    assert not any(f.predicate == "removal_owner" for f in session.facts)


@pytest.mark.parametrize("member", ["assertEquals", "assertNotEquals"])
def test_fresh_local_namesake_without_unittest_base_remains_project_defect(tmp_path, member):
    session, issue = run_failure(tmp_path,
        f"class Local: pass\ndef fail():\n    item = Local()\n    item.{member}(1, 1)\n")
    assert issue.diagnosis_rule == "D43"
    assert not any(f.predicate == "removal_owner_unobserved" for f in session.facts)


@pytest.mark.parametrize("empty", [False, True])
def test_missing_or_empty_ancestry_cannot_turn_a_known_alias_into_a_local_defect(tmp_path, empty):
    session, issue = run_failure(tmp_path,
        "import unittest\nclass Local(unittest.TestCase): pass\n"
        "def fail():\n    item = Local()\n    item.assertEquals(1, 1)\n")
    assert issue.diagnosis_rule == "D03"
    run = next(r for r in session.runs if r.tool == "pytest_run")
    record = next(r["symbol_observation"] for r in run.records if r.get("symbol_observation"))
    if empty:
        record["receiver_owners"] = []  # Includes a bounded observer declining overflow.
    else:
        record.pop("receiver_owners")
    infer_and_plan(session)
    assert issue.diagnosis is None
    assert "Re-run the failing check" in issue.prediction_note
    assert session.actions[0].action_id.startswith("record-removal-ownership-")
