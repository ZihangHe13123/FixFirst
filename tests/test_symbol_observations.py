"""Real failures establish which namespace/argument evidence is actually observable."""

import math
import sys
import types

import pytest

from fixfirst._runtime_evidence import exception_metadata, namespace_candidates, near_distance
from fixfirst.evidence import FEATURE_NAMES, V6_FEATURE_NAMES, V7_FEATURE_NAMES, observations
from fixfirst.service import create_session, scan
from fixfirst.symbol_context import qualified_attribute_history, valid_record


def observed(function):
    try:
        function()
    except (AttributeError, ImportError, TypeError) as error:
        return exception_metadata(error, error.__traceback__)["symbol_observation"]
    raise AssertionError("The test must raise a real exception")


def test_failed_import_has_a_verified_module_and_case_candidate():
    def fail():
        from collections import Ordereddict
        return Ordereddict
    row = observed(fail)
    assert row["module"] == "collections" and row["operation"] == "IMPORT_FROM"
    assert row["candidates"] == [{"name": "OrderedDict", "relation": "case"}]
    assert row["unique"] and not row["requested_member_present"]


def test_actual_instance_members_are_observed_without_calling_them():
    class Bucket:
        def append(self):
            raise AssertionError("The observer must not invoke a candidate")

    def fail():
        item = Bucket()
        return item.appned()
    row = observed(fail)
    assert row["kind"] == "instance" and row["name"] == "appned"
    assert row["candidates"] == [{"name": "append", "relation": "swap"}]


def test_other_near_name_remains_distinct_from_supported_spelling_patterns():
    row = observed(lambda: math.sqroot(4))
    assert row["candidates"] == [{"name": "sqrt", "relation": "other"}]
    assert namespace_candidates("msort", {"sort"}) == ([{"name": "sort", "relation": "other"}], True)


@pytest.mark.parametrize("error", [
    AttributeError("module 'math' has no attribute 'sqroot'", name="sqroot", obj=math),
    ImportError("cannot import name 'Ordereddict' from 'collections'", name="collections"),
    TypeError("str.join() takes exactly one argument (2 given)"),
])
def test_exception_text_and_public_exception_fields_do_not_prove_an_operation(error):
    def fail():
        raise error
    assert observed(fail) == {}


def test_descriptor_is_not_evaluated_again_and_its_name_is_recorded_present():
    calls = []
    class Item:
        @property
        def ready(self):
            calls.append(1)
            raise AttributeError("unavailable resource")
    def fail():
        item = Item()
        return item.ready
    row = observed(fail)
    assert calls == [1]
    assert row["requested_member_present"] and row["candidates"] == []


def test_custom_metaclass_hooks_are_not_run_by_the_observer():
    calls = []
    class Meta(type):
        @property
        def __module__(cls):
            calls.append(1)
            return "builtins"
    class Item(metaclass=Meta):
        pass
    def fail():
        item = Item()
        return item.missing
    assert observed(fail) == {}
    assert calls == []


def test_ambiguous_case_names_are_not_made_unique_by_truncation(monkeypatch):
    module = types.ModuleType("fixfirst_symbol_test")
    module.Foo, module.FOO = 1, 2
    monkeypatch.setitem(sys.modules, module.__name__, module)
    row = observed(lambda: module.foo)
    assert not row["unique"] and len(row["candidates"]) == 2


def test_oversized_namespace_is_unknown(monkeypatch):
    module = types.ModuleType("fixfirst_large_symbol_test")
    vars(module).update({f"member_{n}": None for n in range(5001)})
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert observed(lambda: module.missing) == {}


@pytest.mark.parametrize("callee", ["join", "len"])
def test_actual_builtin_arity_records_counts_and_types_but_no_values(callee):
    def join():
        a, b = "private-first", "private-second"
        return ",".join(a, b)
    def length():
        a, b = "private-first", "private-second"
        return len(a, b)
    row = observed(join if callee == "join" else length)
    assert row["kind"] == "builtin_call" and row["name"] == callee
    assert (row["argument_count_expected"], row["argument_count_given"]) == (1, 2)
    assert row["argument_types"] == ["str", "str"]
    assert "private-first" not in str(row) and "private-second" not in str(row)


def test_distance_cap_handles_insert_delete_replace_and_empty_inputs():
    assert near_distance("sqroot", "sqrt") == 2
    assert near_distance("Index", "Indxe") == 2
    assert near_distance("", "ab") == 2 and near_distance("", "abc") == 3
    assert near_distance("different", "unrelated") == 3


def test_real_probe_serializes_symbol_features_and_keeps_old_feature_prefix(tmp_path):
    (tmp_path / "app.py").write_text("import random\ndef roll():\n    rng = random.Random(0)\n    return rng.randInt(1, 6)\n")
    (tmp_path / "test_app.py").write_text("from app import roll\ndef test_roll():\n    assert 1 <= roll() <= 6\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    _, details = observations(session, session.issues)
    row = next(value for value in details.values() if value.get("symbol_observation"))
    values = dict(zip(FEATURE_NAMES, row["features"]))
    assert row["symbol_location"] == "app.py:4"
    assert row["symbol_statement"] == "return rng.randInt(1, 6)"
    assert values["symbol_candidate_case"] == 1 and values["symbol_use_project"] == 1
    assert values["symbol_namespace_observed"] == 1
    assert FEATURE_NAMES[:65] == V6_FEATURE_NAMES and FEATURE_NAMES[:80] == V7_FEATURE_NAMES
    run = next(r for r in session.runs if r.tool == "pytest_run")
    run.source = "imported"
    _, imported = observations(session, session.issues)
    item = next(value for value in imported.values() if "features" in value)
    assert item["symbol_observation"] == {}


def test_pytest_collection_wrapper_keeps_the_actual_import_observation(tmp_path):
    (tmp_path / "app.py").write_text("from collections import Ordereddict\n")
    (tmp_path / "test_app.py").write_text("import app\ndef test_ok():\n    assert app\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    _, details = observations(session, session.issues)
    item = next(iter(details.values()))
    assert item["exception"] == "ImportError"
    assert item["symbol_observation"]["operation"] == "IMPORT_FROM"
    assert item["symbol_observation"]["candidates"] == [{"name": "OrderedDict", "relation": "case"}]
    assert item["symbol_location"] == "app.py:1"
    assert item["symbol_statement"] == "from collections import Ordereddict"


@pytest.mark.parametrize("version,providers,local,kind,expected", [
    ("2.1.1", ["SQLAlchemy"], False, "instance", True),
    ("1.4.54", ["SQLAlchemy"], False, "instance", False),
    ("2.1.1", ["SQLAlchemy", "another-provider"], False, "instance", False),
    ("2.1.1", ["SQLAlchemy"], True, "instance", False),
    ("2.1.1", ["SQLAlchemy"], False, "class", True),
])
def test_qualified_history_needs_observed_type_version_and_unique_nonlocal_provider(version, providers, local, kind, expected):
    record = {"source": "failed_instruction_namespace", "kind": kind, "module": "sqlalchemy.engine.base",
              "owner": "Engine", "name": "execute", "static_namespace_checked": True,
              "requested_member_present": False, "dynamic": False, "candidates": [], "unique": False,
              "operation": "LOAD_ATTR", "file": "/project/app.py", "line": 2}
    environment = {"packages": [{"name": "SQLAlchemy", "version": version}],
                   "import_distributions": {"sqlalchemy": providers}}
    project = {"local_modules": [{"name": "sqlalchemy"}] if local else []}
    assert qualified_attribute_history({"symbol_observation": record}, project, environment) is expected
    # A printed class name / old exception-object payload alone is insufficient.
    assert not qualified_attribute_history({"runtime_attribute": record}, project, environment)
    assert valid_record({**record, "file": None}) == {}
