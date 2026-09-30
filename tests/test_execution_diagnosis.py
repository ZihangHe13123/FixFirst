"""Core diagnosis across native execution modes, using actual failing programs."""

import hashlib
import sys

import pytest

from fixfirst.evidence import issue_evidence
from fixfirst.execution_parsers import native_failure
from fixfirst.models import Run
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


@pytest.mark.parametrize("header,message,module,name", [
    ("ValueError", "bad input\nOtherError: this is message text\nfield", "", "ValueError"),
    ("library.errors.Invalid", "wrong value\ncode\n  expected text", "library.errors", "Invalid"),
    ("KeyboardInterrupt", "", "", "KeyboardInterrupt"),
])
def test_native_exception_header_precedes_multiline_message(header, message, module, name):
    text = 'Traceback (most recent call last):\n  File "/project/app.py", line 2, in run\n    fail()\n'
    text += header + (": " + message if message else "") + "\n"
    run = Run(tool="python_run", exit_code=1, stderr=text)
    native_failure(run)
    record = next(r for r in run.records if r["type"] == "exception")
    assert record["exception_type"] == name
    assert record["exception_module"] == module
    assert record["exception_message"] == message


def test_native_chained_exception_uses_the_last_traceback():
    run = Run(tool="python_run", exit_code=1, stderr=(
        'Traceback (most recent call last):\n  File "/project/first.py", line 2, in run\n'
        '    fail()\nKeyError: bad\n\nThe above exception was the direct cause of the following exception:\n\n'
        'Traceback (most recent call last):\n  File "/project/last.py", line 4, in run\n'
        '    raise ValueError("invalid")\nValueError: invalid\nfield\n'))
    native_failure(run)
    record = next(r for r in run.records if r["type"] == "exception")
    assert record["exception_type"] == "ValueError"
    assert record["exception_message"] == "invalid\nfield"
    assert record["source_file"] == "/project/last.py" and record["source_line"] == 4


def execution_case(root, mode, source, requirement):
    (root / "app.py").write_text(source, encoding="utf-8")
    (root / "requirements.txt").write_text(requirement + "\n", encoding="utf-8")
    call = "from app import convert\nconvert()\n"
    goal, tool = "run_project", "python_run"
    if mode == "unittest":
        goal, tool = "pass_unittest", "unittest_run"
        entry = root / "test_app.py"
        entry.write_text("import unittest\nfrom app import convert\nclass Work(unittest.TestCase):\n"
                         "    def test_convert(self):\n        convert()\n")
        execution = {"kind": mode, "entry": "."}
    elif mode == "notebook":
        nbformat = pytest.importorskip("nbformat")
        pytest.importorskip("nbclient")
        pytest.importorskip("ipykernel")
        entry = root / "work.ipynb"
        nbformat.write(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(call)]), entry)
        execution = {"kind": mode, "entry": entry.name}
    else:
        entry = root / "main.py"
        entry.write_text(call)
        execution = {"kind": mode, "entry": "main" if mode == "module" else entry.name}
    session = create_session(root, sys.executable, goal=goal, execution=execution)
    scan(session, ["environment", "project", tool], timeout=40)
    issue = next(i for i in session.issues if i.tool == tool)
    assert issue.prediction is None, "the pytest-trained tree is not validated for native modes"
    return session, issue, tool, entry


@pytest.mark.parametrize("mode", ["script", "module", "unittest"])
@pytest.mark.parametrize("value,changed", [("17", True), ('{"x": 17}', False)])
def test_multiline_validation_keeps_type_module_and_distinguishes_invalid_input(
    tmp_path, mode, value, changed,
):
    source = ("from pydantic import BaseModel\nclass Record(BaseModel):\n    code: str\n"
              f"def convert():\n    return Record(code={value}).code\n")
    session, issue, tool, entry = execution_case(tmp_path, mode, source, "pydantic>=1.8")
    evidence = issue_evidence(session, issue)
    assert evidence["exception"] == "ValidationError"
    assert evidence["exception_module"].startswith("pydantic")
    assert evidence["message"].startswith("1 validation error for Record\ncode\n")
    assert evidence["library"] == "pydantic" and evidence["where"] == "app.py:5"
    if not changed:
        assert issue.diagnosis != "version_incompatibility"
        assert not any(a.action_id.startswith("declared-") for a in session.actions)
        return
    assert issue.diagnosis_rule == "H10"
    assert build_view(session)["steps"][0]["title"].startswith("Convert the numeric input to text")
    before = hashlib.sha256(entry.read_bytes()).hexdigest()
    (tmp_path / "app.py").write_text(source.replace("Record(code=17)", "Record(code=str(17))"))
    scan(session, [tool], timeout=40)
    assert session.goal_status == "achieved"
    assert next(i for i in session.issues if i.issue_id == issue.issue_id).status == "resolved"
    assert hashlib.sha256(entry.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("mode", ["script", "module", "unittest", "notebook"])
def test_call_specific_yaml_remedy_works_with_the_entry_unchanged(tmp_path, mode):
    pytest.importorskip("yaml")
    source = 'from yaml import load as parse\ndef convert():\n    return parse("value: 3")\n'
    session, issue, tool, entry = execution_case(tmp_path, mode, source, "PyYAML>=5")
    evidence = issue_evidence(session, issue)
    assert issue.diagnosis_rule == "H10"
    assert evidence["source_location"] == "app.py:3"
    if mode == "notebook":
        assert evidence["where"] == "work.ipynb · cell 1"
    assert build_view(session)["steps"][0]["title"].startswith("Choose an explicit safe YAML loader")
    before = hashlib.sha256(entry.read_bytes()).hexdigest()
    (tmp_path / "app.py").write_text(source.replace("import load as", "import safe_load as"))
    scan(session, [tool], timeout=40)
    assert session.goal_status == "achieved"
    assert next(i for i in session.issues if i.issue_id == issue.issue_id).status == "resolved"
    assert hashlib.sha256(entry.read_bytes()).hexdigest() == before


def test_notebook_local_lookalike_does_not_inherit_yaml_history(tmp_path):
    source = ('def load(text, Loader):\n    return text\n'
              'def convert():\n    return load("value: 3")\n')
    session, issue, _, _ = execution_case(tmp_path, "notebook", source, "PyYAML>=5")
    assert issue.diagnosis != "version_incompatibility"
    assert not any(a.rule_ids == ["P64"] for a in session.actions)


@pytest.mark.parametrize("expression,changed", [("scalar(2.5) + 0.25", True), ("scalar(2.75)", False)])
def test_notebook_keeps_stdlib_provenance_for_numpy_serialization(tmp_path, expression, changed):
    numpy = pytest.importorskip("numpy")
    if int(numpy.__version__.split(".")[0]) < 2:
        pytest.skip("behavior changed in NumPy 2")
    source = ('from numpy import float32 as scalar\nimport json\n'
              f'def convert():\n    return json.dumps({{"amount": {expression}}})\n')
    session, issue, tool, entry = execution_case(tmp_path, "notebook", source, "numpy>=1.21")
    evidence = issue_evidence(session, issue)
    assert evidence["raised_in"] == "stdlib"
    assert evidence["source_location"] == "app.py:4"
    if not changed:
        assert issue.diagnosis != "version_incompatibility"
        assert not any(a.rule_ids == ["P64"] for a in session.actions)
        return
    assert issue.diagnosis_rule == "H10"
    assert build_view(session)["steps"][0]["title"].startswith("Convert the computed NumPy scalar")
    before = hashlib.sha256(entry.read_bytes()).hexdigest()
    (tmp_path / "app.py").write_text(source.replace(expression, f"float({expression})"))
    scan(session, [tool], timeout=40)
    assert session.goal_status == "achieved"
    assert next(i for i in session.issues if i.issue_id == issue.issue_id).status == "resolved"
    assert hashlib.sha256(entry.read_bytes()).hexdigest() == before


def test_notebook_does_not_invent_an_unobserved_exception_module(tmp_path):
    source = ('from pydantic import BaseModel\nclass Record(BaseModel):\n    code: str\n'
              'def convert():\n    return Record(code=17).code\n')
    session, issue, _, _ = execution_case(tmp_path, "notebook", source, "pydantic>=1.8")
    evidence = issue_evidence(session, issue)
    assert evidence["exception"] == "ValidationError"
    assert evidence["library"] == "pydantic"
    assert evidence["source_location"] == "app.py:5"
    assert evidence["exception_module"] == "", "the kernel only reports the unqualified type"
    assert issue.diagnosis != "version_incompatibility"
