"""Synthetic/redacted excerpts from the frozen v0.8 T1–T4 and N1–N5 record shapes.

The original captures are read-only development evidence, not test dependencies.
Paths here are invented; these tests parse text and never execute a sample project.
"""

import pytest

from fixfirst.models import Run
from fixfirst.parsers import parse


WARNING = "DeprecationWarning: ast.Str is deprecated; use ast.Constant instead"
CONTEXT = "________________ ERROR collecting tests/test_demo.py ________________"


def recorded(text, *, tool="pytest_run", stream="stdout", **kwargs):
    return Run(tool=tool, exit_code=2, argv=["python", "-m", "pytest"], **{stream: text}, **kwargs)


@pytest.mark.parametrize("tool", ["pytest", "pytest_run"])
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("path", ["/python/lib/warnings.py", r"C:\Python\Lib\warnings.py"])
def test_failed_collection_warning_keeps_terminal_type_and_exact_refs(tool, stream, path):
    text = f"{CONTEXT}\n{path}:532: in _deprecated\n    warn(msg)\nE   {WARNING}\n"
    text += "================ short test summary info ================\n"
    text += f"ERROR tests/test_demo.py - {WARNING}\n"
    run = recorded(text, tool=tool, stream=stream)
    events = parse(run)
    assert len(events) == 1
    item = events[0]
    assert (item.code, item.kind, item.tool, item.stage) == (
        "DeprecationWarning", "other_unknown", tool, "collect")
    assert item.message == WARNING and item.location == "tests/test_demo.py"
    assert (item.source_file, item.source_line) == (path, 532)
    assert item.line == 4 and item.evidence_refs == [f"{run.run_id}:{stream}:4"]
    assert not run.verified_pass and not run.coverage_complete


@pytest.mark.parametrize("path", ["/project/conftest.py", r"C:\Demo Project\conftest.py"])
def test_conftest_terminal_warning_overrides_pluggy_wrapper(path):
    wrapper = (
        "/environment/_pytest/config.py:318: PluggyTeardownRaisedWarning: hookwrapper teardown\n"
        "Plugin: helpconfig, Hook: pytest_cmdline_parse\n"
        f"ConftestImportFailure: {WARNING} (from {path})\n"
    )
    text = wrapper + f"ImportError while loading conftest '{path}'.\n"
    text += f"{path}:3: in <module>\n    assert value\nE   {WARNING}\n"
    run = recorded(text, stream="stderr")
    events = parse(run)
    assert len(events) == 1 and events[0].code == "DeprecationWarning"
    assert events[0].location == path
    assert events[0].evidence_refs == [f"{run.run_id}:stderr:7"]


@pytest.mark.parametrize("exception", [None, "CollectError"])
def test_failure_probe_longrepr_recovers_warning_without_losing_probe_reference(exception):
    records = [{"type": "finish", "exit_code": 2, "collected": 0},
               {"type": "failure", "nodeid": "tests/test_demo.py", "stage": "collect",
                "message": f"/python/lib/ast.py:1808: in __getattr__\nE   {WARNING}"}]
    if exception:
        records.append({"type": "exception", "nodeid": "tests/test_demo.py", "stage": "collect",
                        "exception_type": exception, "exception_message": "collection failed"})
    run = recorded("", records=records)
    item, = parse(run)
    assert item.code == "DeprecationWarning" and item.message == WARNING
    assert item.evidence_refs == [f"{run.run_id}:probe:1"]
    assert (item.source_file, item.source_line) == ("/python/lib/ast.py", 1808)
    assert item.stage == "collect" and item.location == "tests/test_demo.py"


def test_structured_exception_remains_authoritative_over_warning_words():
    run = recorded("", records=[
        {"type": "failure", "nodeid": "test_demo.py", "stage": "collect",
         "message": f"E   {WARNING}"},
        {"type": "exception", "nodeid": "test_demo.py", "stage": "collect",
         "exception_type": "ImportError", "exception_message": "cannot import demo",
         "source_file": "test_demo.py", "source_line": 1},
    ])
    item, = parse(run)
    assert item.code == "ImportError" and item.kind == "import_failure"
    assert item.evidence_refs == [f"{run.run_id}:probe:0", f"{run.run_id}:probe:1"]


@pytest.mark.parametrize("source,stage", [("executed", "collect"), ("imported", "unknown")])
def test_plain_traceback_warning_preserves_original_fallback_stage(source, stage):
    text = 'Traceback (most recent call last):\n  File "/python/lib/ast.py", line 1808, in __getattr__\n'
    text += f"    warnings.warn(message)\n{WARNING}\n"
    run = recorded(text, stream="stderr", source=source)
    item, = parse(run)
    assert item.code == "DeprecationWarning" and item.stage == stage
    assert item.source_file == "/python/lib/ast.py" and item.source_line == 1808
    assert item.evidence_refs == [f"{run.run_id}:stderr:4"]


@pytest.mark.parametrize("separator", [
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
])
@pytest.mark.parametrize("first,last", [
    ("KeyError: '__spec__'", "AttributeError: __spec__"),
    ("ValueError: earlier cause", WARNING),
    (WARNING, "RuntimeError: unrelated final failure"),
    (WARNING, "ImportError: cannot import demo"),
])
def test_complete_standard_chain_reports_terminal_exception(first, last, separator):
    text = ('Traceback (most recent call last):\n  File "/project/earlier.py", line 2, in old\n'
            f"{first}\n\n{separator}\n\n"
            'Traceback (most recent call last):\n  File "/project/final.py", line 7, in final\n'
            f"{last}\n")
    run = recorded(text, stream="stderr")
    item, = parse(run)
    assert item.code == last.split(":", 1)[0]
    assert item.message == last
    assert item.source_file == "/project/final.py" and item.source_line == 7
    assert item.evidence_refs == [f"{run.run_id}:stderr:9"]


def test_two_independent_tracebacks_are_not_collapsed():
    text = ('Traceback (most recent call last):\n  File "/project/first.py", line 2, in first\n'
            'ValueError: first failure\n\n'
            'Traceback (most recent call last):\n  File "/project/second.py", line 3, in second\n'
            f"{WARNING}\n")
    events = parse(recorded(text, stream="stderr"))
    assert [item.code for item in events] == ["ValueError", "DeprecationWarning"]


def test_multiple_collection_blocks_keep_separate_warning_failures():
    text = f"{CONTEXT}\nE   {WARNING}\n"
    text += "________________ ERROR collecting tests/test_other.py ________________\n"
    text += "E   UserWarning: project warning promoted to error\n"
    events = parse(recorded(text))
    assert [(item.location, item.code) for item in events] == [
        ("tests/test_demo.py", "DeprecationWarning"), ("tests/test_other.py", "UserWarning")]


def test_project_own_promoted_warning_is_parsed_without_a_compatibility_diagnosis():
    text = f"{CONTEXT}\nmod.py:3: in <module>\nE   DeprecationWarning: add() is deprecated\n"
    item, = parse(recorded(text))
    assert item.code == "DeprecationWarning" and item.kind == "other_unknown"
    assert item.component == "" and item.source_file == "mod.py"


def test_warning_message_containing_other_exception_or_config_text_keeps_warning_type():
    warning = "DeprecationWarning: ValueError: Missing configuration: DEMO_CONFIG"
    item, = parse(recorded(f"{CONTEXT}\nE   {warning}"))
    assert item.code == "DeprecationWarning" and item.kind == "other_unknown"
    assert item.message == warning and item.component == ""


@pytest.mark.parametrize("exit_code", [0, 1, 2, 4])
def test_ordinary_warning_summary_and_bare_warning_never_become_warning_failures(exit_code):
    text = ("DeprecationWarning: an ordinary log line\n"
            "================ warnings summary ================\n"
            "/python/_pytest/rewrite.py:958: DeprecationWarning: ast.Str is deprecated\n"
            "    inlocs = ast.Str(name)\n1 passed, 1 warning\n")
    run = Run(tool="pytest_run", exit_code=exit_code, stdout=text)
    assert all(not item.code.endswith("Warning") for item in parse(run))


def test_successful_structured_run_ignores_warning_summary():
    text = f"================ warnings summary ================\n/python/lib/ast.py:1808: {WARNING}\n"
    run = Run(tool="pytest_run", exit_code=0, stdout=text, records=[
        {"type": "outcome", "nodeid": "test_demo.py::test_ok", "stage": stage,
         "outcome": "passed", "wasxfail": False} for stage in ("setup", "call", "teardown")
    ] + [{"type": "finish", "exit_code": 0, "collected": 1, "collect_only": False,
          "nodes": ["test_demo.py::test_ok"], "records_dropped": False}])
    assert parse(run) == []
    assert run.verified_pass


def test_unrelated_test_failure_is_not_replaced_by_its_warning_summary():
    text = ("________________ test_failure ________________\nE   AssertionError: expected 2\n"
            "================ warnings summary ================\n"
            f"/python/lib/ast.py:1808: {WARNING}\n")
    events = parse(recorded(text))
    assert [item.code for item in events] == ["AssertionError"]


@pytest.mark.parametrize("section", ["warnings summary", "Captured stdout call", "Captured log call"])
def test_traceback_printed_inside_a_nonfailure_section_is_not_a_warning_failure(section):
    text = ('Traceback (most recent call last):\n  File "/project/test_demo.py", line 3, in test\n'
            'AssertionError: expected 2\n'
            f"================ {section} ================\n"
            'Traceback (most recent call last):\n  File "/python/lib/ast.py", line 1808, in warned\n'
            f"{WARNING}\n")
    events = parse(recorded(text))
    assert [item.code for item in events] == ["AssertionError"]


def test_failure_probe_ignores_captured_warning_traceback_after_its_actual_failure():
    run = recorded("", records=[{
        "type": "failure", "nodeid": "test_demo.py", "stage": "collect",
        "message": f"E   {WARNING}\n---------------- Captured stdout call ----------------\n"
                   "Traceback (most recent call last):\nUserWarning: printed diagnostic example\n",
    }])
    item, = parse(run)
    assert item.code == "DeprecationWarning" and item.message == WARNING
    assert item.evidence_refs == [f"{run.run_id}:probe:0"]


@pytest.mark.parametrize("text,kind,component", [
    ("ERROR: usage: pytest [options]\npytest: error: unrecognized arguments: --cov=demo\n",
     "tool_failure", ""),
    ("ImportError while loading conftest '/project/conftest.py'.\nconftest.py:1: in <module>\n"
     "E   ModuleNotFoundError: No module named 'yaml'\n", "import_failure", "yaml"),
    ('Traceback (most recent call last):\n  File "/project/pluggy.py", line 1, in <module>\n'
     "ImportError: cannot import name 'HookimplMarker' from 'pluggy' (/project/pluggy.py)\n",
     "import_failure", ""),
])
def test_missing_plugin_dependency_and_shadowing_keep_legacy_classification(text, kind, component):
    item, = parse(recorded(text, stream="stderr"))
    assert item.kind == kind and item.component == component
    assert not item.code.endswith("Warning")


def test_interrupted_run_does_not_promote_partial_warning_text():
    run = recorded(f"{CONTEXT}\nE   {WARNING}", status="timeout")
    item, = parse(run)
    assert item.kind == "tool_failure" and item.code == ""
