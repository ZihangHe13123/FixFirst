"""Run real library failures: bad input is not evidence for a dependency downgrade."""

import hashlib
import sys

import pytest

from fixfirst.evidence import issue_evidence
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def inspect_project(root, source, test, requirement, *, unit=False):
    (root / "app.py").write_text(source)
    (root / "requirements.txt").write_text(requirement + "\n")
    (root / "pytest.ini").write_text("[pytest]\n")
    if unit:
        test_source = "import unittest\nfrom app import convert\nclass Test(unittest.TestCase):\n    def test_convert(self):\n        "
        goal, execution, check = "pass_unittest", {"kind": "unittest", "entry": "."}, "unittest_run"
    else:
        test_source = "from app import convert\ndef test_convert():\n    "
        goal, execution, check = "pass_tests", None, "pytest_run"
    (root / "test_app.py").write_text(test_source + test + "\n")
    session = create_session(root, sys.executable, goal=goal, execution=execution)
    scan(session, ["environment", "project", check], timeout=30)
    issue = next(i for i in session.issues if i.tool == check)
    return session, issue, check


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("requirement,source,test,before,after,title", [
    ("numpy>=1.21", 'import numpy as np\ndef convert():\n    return np.reshape([1,2,3], (2,2))\n',
     "assert convert().shape == (3,1)", "(2,2)", "(3,1)", "Correct the reshape dimensions"),
    ("numpy>=1.21", 'import numpy as np\ndef convert():\n    return np.sum([[1,2],[3,4]], axis=3).tolist()\n',
     "assert convert() == [3,7]", "axis=3", "axis=1", "Choose an axis"),
    ("PyYAML>=5", 'import yaml\ndef convert():\n    return yaml.safe_load("key: [1, 2")\n',
     'assert convert() == {"key": [1,2]}', 'key: [1, 2"', 'key: [1, 2]"', "Correct the YAML syntax"),
    ("click>=7", 'import click\ndef convert():\n    return click.IntRange(0,5).convert("9",None,None)\n',
     "assert convert() == 3", 'convert("9"', 'convert("3"', "Correct the value rejected by the Click parameter"),
])
def test_input_repair_preserves_the_test_and_does_not_downgrade(
        tmp_path, requirement, source, test, before, after, title, locked):
    if locked:
        package = requirement.split(">=")[0].lower()
        version = {"numpy": "1.26.4", "pyyaml": "5.4.1", "click": "7.1.2"}[package]
        (tmp_path / "uv.lock").write_text(f'[[package]]\nname = "{package}"\nversion = "{version}"\n')
    session, issue, check = inspect_project(tmp_path, source, test, requirement)
    assert issue.diagnosis == "code_defect" and issue.diagnosis_rule == "H12"
    assert build_view(session)["steps"][0]["title"].startswith(title)
    assert not any(a.command for a in session.actions)
    expected = hashlib.sha256((tmp_path / "test_app.py").read_bytes()).hexdigest()
    (tmp_path / "app.py").write_text(source.replace(before, after))
    scan(session, [check], timeout=30)
    assert session.goal_status == "achieved"
    assert next(i for i in session.issues if i.issue_id == issue.issue_id).status == "resolved"
    assert hashlib.sha256((tmp_path / "test_app.py").read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("unit", [False, True])
@pytest.mark.parametrize("method,call,repair,test,explanation", [
    ("ptp", "data.ptp()", "np.ptp(data)", "assert convert() == 3", "numpy.ptp(array"),
    ("newbyteorder", "data.newbyteorder('>').dtype.byteorder",
     "data.view(data.dtype.newbyteorder('>')).dtype.byteorder", "assert convert() == '>'", "array.view("),
])
def test_removed_array_method_uses_runtime_owner_and_its_real_replacement(
        tmp_path, unit, method, call, repair, test, explanation):
    import numpy as np
    if int(np.__version__.split(".")[0]) < 2:
        pytest.skip("these ndarray methods were removed in NumPy 2")
    source = f'import numpy as np\ndef convert():\n    data = np.array([1,4])\n    return {call}\n'
    session, issue, check = inspect_project(tmp_path, source, test, "numpy>=1.21", unit=unit)
    assert issue.diagnosis == "version_incompatibility" and issue.diagnosis_rule == "D03"
    evidence = issue_evidence(session, issue)
    assert f"numpy.ndarray.{method}" in evidence["attributes"]
    assert explanation in session.actions[0].explanation
    expected = (tmp_path / "test_app.py").read_bytes()
    (tmp_path / "app.py").write_text(source.replace(call, repair))
    scan(session, [check], timeout=30)
    assert session.goal_status == "achieved"
    assert (tmp_path / "test_app.py").read_bytes() == expected


@pytest.mark.parametrize("source", [
    'class ndarray:\n    pass\ndef convert():\n    return ndarray().ptp()\n',
    'def convert():\n    raise AttributeError("\'numpy.ndarray\' object has no attribute \'ptp\'")\n',
    'ndarray = type("ndarray", (), {"__module__": "numpy"})\ndef convert():\n    return ndarray().ptp()\n',
])
def test_local_or_textual_lookalike_does_not_borrow_numpy_history(tmp_path, source):
    session, issue, _ = inspect_project(tmp_path, source, "convert()", "numpy>=1.21")
    assert issue.diagnosis_rule != "D03"
    assert "numpy.ndarray.ptp" not in issue_evidence(session, issue)["attributes"]
    assert not any("removed in numpy" in a.title for a in session.actions)


@pytest.mark.parametrize("caller,expected", [("parse", "version_incompatibility"), ("Version", "code_defect")])
def test_legacy_parse_history_does_not_apply_to_the_always_strict_constructor(tmp_path, caller, expected):
    source = (f'from packaging.version import {caller}\ndef convert():\n    return {caller}("nightly")\n')
    session, issue, _ = inspect_project(tmp_path, source, "convert()", "packaging>=20")
    assert issue.diagnosis == expected
    assert issue.diagnosis_rule == ("H10" if caller == "parse" else "H12")
    assert not any(a.command for a in session.actions)


def test_a_new_declared_minimum_is_not_an_old_api_migration(tmp_path):
    source = 'from packaging.version import parse\ndef convert():\n    return parse("nightly")\n'
    session, issue, _ = inspect_project(tmp_path, source, "convert()", "packaging>=22")
    assert issue.diagnosis == "code_defect" and issue.diagnosis_rule == "H12"


def test_project_exceptions_do_not_become_library_input_contracts(tmp_path):
    source = 'class ParserError(Exception):\n    pass\ndef convert():\n    raise ParserError("bad YAML")\n'
    session, issue, _ = inspect_project(tmp_path, source, "convert()", "PyYAML>=5")
    assert issue.diagnosis_rule != "H12"
    assert not any(a.action_id.startswith("input-") for a in session.actions)


def test_numpy_copy_error_keeps_the_c_call_site_and_executes_the_migration(tmp_path):
    import numpy as np
    if int(np.__version__.split(".")[0]) < 2:
        pytest.skip("copy=False became strict in NumPy 2")
    source = ('import numpy as np\ndef convert():\n'
              '    return np.array([1,2], dtype=float, copy=False).tolist()\n')
    session, issue, check = inspect_project(tmp_path, source, "assert convert() == [1.,2.]", "numpy>=1.21")
    assert issue.diagnosis_rule == "H10"
    assert issue_evidence(session, issue)["raised_in"] == "project"  # do not invent a library Python frame
    assert "numpy.asarray" in session.actions[0].explanation
    expected = (tmp_path / "test_app.py").read_bytes()
    (tmp_path / "app.py").write_text(source.replace("np.array([1,2], dtype=float, copy=False)",
                                                   "np.asarray([1,2], dtype=float)"))
    scan(session, [check], timeout=30)
    assert session.goal_status == "achieved" and (tmp_path / "test_app.py").read_bytes() == expected


SOLVE = ('import numpy as np\ndef convert():\n'
         '    a = np.asarray([[[2,0],[0,2]],[[4,0],[0,4]],[[1,0],[0,1]]])\n'
         '    b = np.asarray(VECTORS)\n'
         '    return np.linalg.solve(a, b).tolist()\n')


@pytest.mark.parametrize("vectors,requirement,migration", [
    ('[[2,4],[8,4],[3,5]]', "numpy>=1.21", True),
    ('[[2,4,1],[8,4,1],[3,5,1]]', "numpy>=1.21", False),
    ('[[2,4],[8,4],[3,5]]', "numpy>=2", False),
])
def test_solve_history_requires_observed_shapes_that_worked_as_batched_vectors(tmp_path, vectors, requirement, migration):
    import numpy as np
    if int(np.__version__.split(".")[0]) < 2:
        pytest.skip("the solve b interpretation changed in NumPy 2")
    source = SOLVE.replace("VECTORS", vectors)
    session, issue, check = inspect_project(tmp_path, source, "assert convert() == [[1.,2.],[2.,1.],[3.,5.]]", requirement)
    assert (issue.diagnosis_rule == "H10") == migration
    assert not any(a.command for a in session.actions)
    if migration:
        assert "b[..., None]" in session.actions[0].explanation
        before = (tmp_path / "test_app.py").read_bytes()
        (tmp_path / "app.py").write_text(source.replace("np.linalg.solve(a, b)",
                                                       "np.linalg.solve(a, b[..., None])[..., 0]"))
        scan(session, [check], timeout=30)
        assert session.goal_status == "achieved" and (tmp_path / "test_app.py").read_bytes() == before


@pytest.mark.parametrize("unit", [False, True])
def test_optional_field_migration_with_dynamic_inputs_preserves_required_fields(tmp_path, unit):
    source = ('from typing import Optional\nfrom pydantic import BaseModel\n'
              'class Contact(BaseModel):\n    name: str\n    email: Optional[str]\n'
              'def make(record):\n    return Contact(**record)\n'
              'def convert():\n    return make({"name": "Ada"})\n')
    session, issue, check = inspect_project(tmp_path, source, "assert convert().email is None", "pydantic>=1.8", unit=unit)
    assert issue.diagnosis_rule == "H10"
    assert "explicit None default" in session.actions[0].title
    before = (tmp_path / "test_app.py").read_bytes()
    (tmp_path / "app.py").write_text(source.replace("email: Optional[str]", "email: Optional[str] = None"))
    scan(session, [check], timeout=30)
    assert session.goal_status == "achieved" and (tmp_path / "test_app.py").read_bytes() == before


@pytest.mark.parametrize("field,supplied,requirement", [
    ("email: str", '{"name":"Ada"}', "pydantic>=1.8"),
    ("email: Optional[str]", '{"name":"Ada", "emali":"value"}', "pydantic>=1.8"),
    ("email: Optional[str]", '{"name":"Ada"}', "pydantic>=2"),
])
def test_missing_fields_are_not_automatically_optional_migrations(tmp_path, field, supplied, requirement):
    source = ('from typing import Optional\nfrom pydantic import BaseModel\n'
              f'class Contact(BaseModel):\n    name: str\n    {field}\n'
              f'def convert():\n    return Contact(**{supplied})\n')
    session, issue, _ = inspect_project(tmp_path, source, "convert()", requirement)
    assert issue.diagnosis_rule != "H10"
    assert not any("None default" in a.title for a in session.actions)


@pytest.mark.skipif(sys.version_info < (3, 12), reason="SafeConfigParser was removed in Python 3.12")
def test_removed_configparser_name_gets_a_concrete_replacement(tmp_path):
    source = 'from configparser import SafeConfigParser\ndef convert():\n    return SafeConfigParser().sections()\n'
    session, issue, check = inspect_project(tmp_path, source, "assert convert() == []", "")
    assert issue.diagnosis_rule == "D02"
    assert "configparser.ConfigParser" in session.actions[0].explanation
    before = (tmp_path / "test_app.py").read_bytes()
    (tmp_path / "app.py").write_text(source.replace("SafeConfigParser", "ConfigParser"))
    scan(session, [check], timeout=30)
    assert session.goal_status == "achieved" and (tmp_path / "test_app.py").read_bytes() == before
