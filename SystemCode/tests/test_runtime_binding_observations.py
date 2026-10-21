"""Actual failures, not error strings, establish limited binding observations."""

import builtins
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import types

import pytest

from fixfirst._runtime_evidence import exception_metadata


def failure(function):
    try:
        function()
    except (AttributeError, TypeError, ValueError) as error:
        return exception_metadata(error, error.__traceback__)
    raise AssertionError("Expected an actual failure")


def test_alias_keeps_call_spelling_and_actual_python_function_contract():
    def normalise(value, /):
        raise AssertionError("The function body must not run")

    adapt, value = normalise, 7
    result = failure(lambda: adapt(value=value))
    row = result["symbol_observation"]
    assert result["symbol_observation_status"] == "observed_operation"
    assert (row["kind"], row["name"], row["callee_name"]) == ("python_binding", "adapt", "normalise")
    assert row["parameters"] == [{"name": "value", "kind": "positional_only", "required": True}]
    assert row["positional_count"] == 0 and row["keyword_names"] == ["value"]
    assert row["argument_types"] == ["int"]
    assert row["binding_errors"] == {"positional_only_as_keyword": ["value"], "missing": ["value"],
                                     "unexpected": [], "duplicate": [], "too_many_positional": False}
    assert row["definition_line"] == normalise.__code__.co_firstlineno


def test_loaded_stdlib_python_function_records_missing_parameter_without_guessing_its_value():
    row = failure(lambda: re.fullmatch("[A-Z]+"))["symbol_observation"]
    assert row["kind"] == "python_binding" and row["module"] == "re"
    assert row["name"] == row["callee_name"] == "fullmatch"
    assert row["binding_errors"]["missing"] == ["string"]
    assert row["positional_count"] == 1 and row["argument_types"] == ["str"]
    assert "[A-Z]+" not in json.dumps(row)


@pytest.mark.parametrize("case,expected", [
    ("missing", {"missing": ["first", "required"]}),
    ("unexpected", {"unexpected": ["extra"], "missing": ["first", "required"]}),
    ("duplicate", {"duplicate": ["first"], "missing": ["required"]}),
    ("excess", {"too_many_positional": True, "missing": ["required"]}),
])
def test_python_binding_categories_follow_the_actual_argument_layout(case, expected):
    def target(first, optional=9, *, required, other=10):
        raise AssertionError("Must not enter the body")

    calls = {"missing": lambda: target(), "unexpected": lambda: target(extra=1),
             "duplicate": lambda: target(1, first=2), "excess": lambda: target(1, 2, 3)}
    row = failure(calls[case])["symbol_observation"]
    assert row["kind"] == "python_binding"
    assert row["parameters"] == [
        {"name": "first", "kind": "positional_or_keyword", "required": True},
        {"name": "optional", "kind": "positional_or_keyword", "required": False},
        {"name": "required", "kind": "keyword_only", "required": True},
        {"name": "other", "kind": "keyword_only", "required": False}]
    for key, value in expected.items():
        assert row["binding_errors"][key] == value


def test_signature_hooks_wrapped_target_and_default_object_are_never_inspected():
    calls = []

    class Trap:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError("No default or signature hook should be inspected")

        def __repr__(self):
            calls.append("repr")
            raise AssertionError("No repr")

    default = Trap()

    def target(value, /, optional=default, *, other=default):
        return value

    target.__signature__ = default
    target.__wrapped__ = default
    row = failure(lambda: target(value=1))["symbol_observation"]
    assert row["kind"] == "python_binding" and calls == []
    assert [p["required"] for p in row["parameters"]] == [True, False, False]


@pytest.mark.parametrize("which", ["direct", "module", "alias"])
def test_builtin_keyword_binding_uses_static_signature_and_preserves_alias(which):
    data, adapt = [1], len
    calls = {"direct": lambda: len(obj=data), "module": lambda: builtins.len(obj=data),
             "alias": lambda: adapt(obj=data)}
    row = failure(calls[which])["symbol_observation"]
    assert row["kind"] == "builtin_binding" and row["callee_name"] == "len"
    assert row["name"] == ("adapt" if which == "alias" else "len")
    assert row["parameters"] == [{"name": "obj", "kind": "positional_only", "required": True}]
    assert row["argument_types"] == ["list"]
    assert row["binding_errors"]["positional_only_as_keyword"] == ["obj"]


def test_builtin_valid_binding_but_invalid_value_is_not_called_a_binding_failure():
    value = 3
    result = failure(lambda: len(value))
    assert result["symbol_observation"] == {}
    assert result["symbol_observation_status"] == "valid_binding_body_error"


def test_builtin_implicit_module_slash_is_not_a_user_parameter():
    row = failure(lambda: pow(extra=1))["symbol_observation"]
    assert row["kind"] == "builtin_binding"
    assert [p["name"] for p in row["parameters"]] == ["base", "exp", "mod"]
    assert row["binding_errors"]["unexpected"] == ["extra"]
    assert row["binding_errors"]["missing"] == ["base", "exp"]


@pytest.mark.parametrize("style", ["args", "kwargs"])
def test_expansion_is_rejected_even_if_its_values_could_be_inspected(style):
    def target(value, /):
        return value

    args, kwargs = (1, 2), {"value": 1}
    result = failure((lambda: target(*args)) if style == "args" else (lambda: target(**kwargs)))
    assert result["symbol_observation"] == {}
    assert result["symbol_observation_status"] == "unsupported_call_shape"


def test_variadic_python_signature_stays_unsupported():
    def target(value, /, *args):
        return value

    result = failure(lambda: target(value=1))
    assert result["symbol_observation"] == {}
    assert result["symbol_observation_status"] == "variadic_signature"


@pytest.mark.parametrize("same_message", [False, True])
def test_body_or_manually_raised_typeerror_does_not_establish_a_binding_failure(same_message):
    def target(value, /):
        message = "target() got some positional-only arguments passed as keyword arguments: 'value'"
        raise TypeError(message if same_message else "business validation")

    result = failure(lambda: target(1))
    assert result["symbol_observation"] == {}
    assert result["symbol_observation_status"] == "unsupported_call_shape"


def test_unknown_callable_object_and_bound_method_are_not_introspected():
    class Callable:
        def __call__(self, value):
            return value

        def method(self, value):
            return value

    target = Callable()
    for call in (lambda: target(), lambda: target.method()):
        row = failure(call)
        assert row["symbol_observation"] == {}
        assert row["symbol_observation_status"] in {"unsupported_callable", "unsupported_call_shape"}


def test_a_rebound_module_function_uses_the_actual_function_not_the_imported_spelling(monkeypatch):
    module = types.ModuleType("binding_test_module")

    def replacement(other, /):
        return other

    module.adapt = replacement
    monkeypatch.setitem(sys.modules, module.__name__, module)
    row = failure(lambda: module.adapt(value=1))["symbol_observation"]
    assert row["name"] == "adapt" and row["callee_name"] == "replacement"
    assert row["binding_errors"]["unexpected"] == ["value"]
    assert row["binding_errors"]["missing"] == ["other"]


def test_constructed_receiver_uses_native_exception_object_without_repeating_constructor():
    calls = []

    class Store:
        def __init__(self):
            calls.append("constructed")

        def read(self):
            raise AssertionError("Candidates must not run")

    result = failure(lambda: Store().fetch())
    row = result["symbol_observation"]
    assert result["symbol_observation_status"] == "observed_operation"
    assert row["name"] == "fetch" and row["kind"] == "instance"
    assert not row["requested_member_present"] and not row["dynamic"]
    assert calls == ["constructed"]


def test_native_error_fields_cannot_bypass_an_innermost_manual_raise():
    class Store:
        pass

    obj = Store()

    def fail():
        raise AttributeError("missing", name="fetch", obj=obj)

    result = failure(fail)
    assert result["symbol_observation"] == {}


def test_constructed_receiver_with_dynamic_hooks_remains_unknown():
    calls = []

    class Store:
        def __getattr__(self, name):
            calls.append(name)
            raise AttributeError("missing", name=name, obj=self)

    assert failure(lambda: Store().fetch())["symbol_observation"] == {}
    assert calls == ["fetch"]


def test_receiver_module_metadata_never_hashes_user_objects():
    calls = []

    class ModuleTrap:
        def __hash__(self):
            calls.append("hashed")
            raise AssertionError("Module metadata is not a trusted lookup key")

    class Store:
        pass

    Store.__module__ = ModuleTrap()
    row = failure(lambda: Store().fetch())["symbol_observation"]
    assert row["kind"] == "instance" and row["module"] == row["owner"] == ""
    assert calls == []


def test_too_many_arguments_are_not_serialized():
    def target(value, /):
        return value

    result = failure(lambda: target(1, 2, 3, 4, 5, 6, 7, 8, 9))
    assert result["symbol_observation"] == {}
    assert result["symbol_observation_status"] == "unsupported_call_shape"


def test_oversized_python_parameter_layout_is_rejected():
    namespace = {"__name__": __name__}
    exec("def target(" + ",".join(f"p{i}" for i in range(33)) + "):\n pass", namespace)
    target = namespace["target"]
    result = failure(lambda: target())
    assert result["symbol_observation"] == {}
    assert result["symbol_observation_status"] == "signature_limit"


def test_other_exception_type_has_an_explicit_rejection_reason():
    def target():
        raise ValueError("business failure")

    result = failure(target)
    assert result["symbol_observation"] == {}
    assert result["symbol_observation_status"] == "unsupported_exception"


@pytest.mark.parametrize("key,kind", [("positional-only", "python_binding"),
                                     ("own-store-method", "instance"), ("regex-arity", "python_binding")])
def test_frozen_public_failures_emit_real_probe_records_without_changing_original_tests(tmp_path, key, kind):
    from fixfirst.models import Session
    from fixfirst.runner import collect

    original = Path(__file__).resolve().parents[1] / "experiments/field_trial/round11/public" / key
    project = tmp_path / "project"
    shutil.copytree(original, project)
    before = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in project.rglob("*") if p.is_file()}
    session = Session(name="raw-probe-only", project_root=str(project), target_python=sys.executable, goal="pass_tests")
    run = collect(session, "pytest_run", timeout=30)
    exceptions = [r for r in run.records if r.get("type") == "exception"]
    assert run.exit_code == 1 and len(exceptions) == 1
    assert exceptions[0]["symbol_observation_status"] == "observed_operation"
    assert exceptions[0]["symbol_observation"]["kind"] == kind
    assert all(hashlib.sha256((project / relative).read_bytes()).hexdigest() == expected
               for relative, expected in before.items())


def test_real_collection_binding_failure_propagates_its_direct_exception_status(tmp_path):
    from fixfirst.models import Session
    from fixfirst.runner import collect

    (tmp_path / "app.py").write_text("def target(value, /):\n return value\ntarget(value=1)\n")
    (tmp_path / "test_app.py").write_text("import app\ndef test_app():\n assert app\n")
    session = Session(name="collect-wrapper", project_root=str(tmp_path), target_python=sys.executable)
    run = collect(session, "pytest", timeout=30)
    exceptions = [r for r in run.records if r.get("exception_type") == "TypeError"]
    assert len(exceptions) == 1
    assert exceptions[0]["symbol_observation_status"] == "observed_operation"
    assert exceptions[0]["symbol_observation"]["binding_errors"]["positional_only_as_keyword"] == ["value"]


def test_real_collection_wrapper_reports_the_import_cause_status(tmp_path):
    from fixfirst.models import Session
    from fixfirst.runner import collect

    (tmp_path / "app.py").write_text("from collections import Ordereddict\n")
    (tmp_path / "test_app.py").write_text("import app\ndef test_app():\n assert app\n")
    session = Session(name="collect-wrapper", project_root=str(tmp_path), target_python=sys.executable)
    run = collect(session, "pytest", timeout=30)
    exceptions = [r for r in run.records if r.get("exception_type") == "CollectError"]
    assert len(exceptions) == 1
    assert exceptions[0]["symbol_observation_status"] == "observed_operation"
    assert exceptions[0]["symbol_observation"]["operation"] == "IMPORT_FROM"
