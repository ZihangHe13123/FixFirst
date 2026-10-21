"""Real failures, actionable migrations and counterexamples for behavior evidence."""

import hashlib
import json
from pathlib import Path
import sys

import pytest

from fixfirst import diagnosis_cases as cases
from fixfirst.behavior import promotion_in_json_call, scalar_representation_only
from fixfirst.evidence import issue_evidence
from fixfirst.reasoning import infer_and_plan
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def project(root, source, requirement, expected):
    root.mkdir()
    (root / "requirements.txt").write_text(requirement + "\n")
    (root / "app.py").write_text(source)
    (root / "test_app.py").write_text(
        f"from app import convert\n\ndef test_convert():\n    assert convert() == {expected!r}\n"
    )
    session = create_session(root, sys.executable, goal="pass_tests")
    scan(session, cases.CHECKS)
    return session


POSITIVE = [
    (
        "numpy_repr", "numpy>=1.21",
        'import numpy as numeric\n\ndef convert():\n    value = numeric.float64(3.25)\n    return f"total={value!r}"\n',
        'return f"total={value!r}"', 'return "total=" + str(value)', "total=3.25",
        "Format the NumPy scalar explicitly",
    ),
    (
        "numpy_promotion", "numpy>=1.21",
        'from numpy import float32 as scalar\nimport json\n\ndef convert():\n    return json.dumps({"amount": scalar(2.5) + 0.25})\n',
        'scalar(2.5) + 0.25', 'float(scalar(2.5) + 0.25)', '{"amount": 2.75}',
        "Convert the computed NumPy scalar",
    ),
    (
        "pydantic_coercion", "pydantic>=1.8",
        'from pydantic import BaseModel\n\nclass Record(BaseModel):\n    code: str\n\ndef convert():\n    return Record(code=17).code\n',
        'Record(code=17)', 'Record(code=str(17))', "17",
        "Convert the numeric input to text",
    ),
]


@pytest.mark.parametrize("name,requirement,source,old,new,expected,title", POSITIVE)
def test_the_first_step_fixes_the_real_failure_without_changing_tests(
    tmp_path, name, requirement, source, old, new, expected, title,
):
    if name.startswith("numpy"):
        np = pytest.importorskip("numpy")
        if int(np.__version__.split(".")[0]) < 2:
            pytest.skip("behavior changed in NumPy 2")
    root = tmp_path / name
    session = project(root, source, requirement, expected)
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    assert issue.diagnosis == "version_incompatibility"
    assert issue.diagnosis_source == "heuristic" and issue.diagnosis_rule == "H10"
    first = build_view(session)["steps"][0]
    assert first["title"].startswith(title)
    assert "unchanged tests" in first["explanation"] or "tests unchanged" in first["explanation"]
    assert any(f.status == "knowledge" and f.predicate == "change_summary" for f in session.facts)
    test_file = root / "test_app.py"
    before = hashlib.sha256(test_file.read_bytes()).hexdigest()
    # Apply the action's conversion to application code, never to the expected answer.
    (root / "app.py").write_text(source.replace(old, new))
    scan(session, cases.CHECKS)
    assert hashlib.sha256(test_file.read_bytes()).hexdigest() == before
    assert not [i for i in session.issues if i.tool == "pytest_run" and i.status == "open"]
    assert any(r.tool == "pytest_run" and r.verified_pass for r in session.runs)


NEGATIVE = [
    (
        "literal_looks_like_numpy", "numpy>=1.21",
        'import numpy as np\n\ndef unrelated():\n    return f"total={np.float64(3.25)!r}"\n\ndef convert():\n    return "total=np.float64(3.25)"\n',
        "total=3.25",
    ),
    (
        "different_value", "numpy>=1.21",
        'import numpy as np\n\ndef convert():\n    return f"total={np.float64(3.25)!r}"\n',
        "total=9.5",
    ),
    (
        "direct_scalar_json", "numpy>=1.21",
        'import numpy as np\nimport json\n\ndef convert():\n    return json.dumps({"amount": np.float32(2.75)})\n',
        '{"amount": 2.75}',
    ),
    (
        "new_numpy_contract", "numpy>=2.0",
        'import numpy as np\n\ndef convert():\n    return f"total={np.float64(3.25)!r}"\n',
        "total=3.25",
    ),
    (
        "invalid_integer", "pydantic>=1.8",
        'from pydantic import BaseModel\n\nclass Record(BaseModel):\n    code: int\n\ndef convert():\n    return Record(code="not-a-number").code\n',
        17,
    ),
    (
        "invalid_dict", "pydantic>=1.8",
        'from pydantic import BaseModel\n\nclass Record(BaseModel):\n    code: str\n\ndef convert():\n    return Record(code={"x": 17}).code\n',
        "17",
    ),
    (
        "strict_alias", "pydantic>=1.8",
        'from pydantic import BaseModel, StrictStr as Text\n\nclass Record(BaseModel):\n    code: Text\n\ndef convert():\n    return Record(code=17).code\n',
        "17",
    ),
    (
        "strict_config", "pydantic>=1.8",
        'from pydantic import BaseModel, ConfigDict\n\nclass Record(BaseModel):\n    model_config = ConfigDict(strict=True)\n    code: str\n\ndef convert():\n    return Record(code=17).code\n',
        "17",
    ),
    (
        "strict_dict_config", "pydantic>=1.8",
        'from pydantic import BaseModel\n\nclass Record(BaseModel):\n    model_config = {"strict": True}\n    code: str\n\ndef convert():\n    return Record(code=17).code\n',
        "17",
    ),
    (
        "new_pydantic_contract", "pydantic>=2.0",
        'from pydantic import BaseModel\n\nclass Record(BaseModel):\n    code: str\n\ndef convert():\n    return Record(code=17).code\n',
        "17",
    ),
]


@pytest.mark.parametrize("name,requirement,source,expected", NEGATIVE)
def test_unrelated_or_intentional_behavior_is_not_an_upgrade_diagnosis(
    tmp_path, name, requirement, source, expected,
):
    session = project(tmp_path / name, source, requirement, expected)
    issues = [i for i in session.issues if i.tool == "pytest_run" and i.status == "open"]
    assert issues, "the counterexample must actually fail"
    assert all(i.diagnosis != "version_incompatibility" for i in issues)
    assert not any(a.rule_ids == ["P64"] or a.action_id.startswith("declared-") for a in session.actions)


def saved_hard(scenario):
    root = Path(__file__).resolve().parents[1] / "examples" / "hard-dataset"
    row = next(json.loads(line) for line in (root / "cases.jsonl").open()
               if json.loads(line)["scenario"] == scenario)
    return cases.load_session(root, row["session"]).model_copy(deep=True)


def test_hidden_library_frame_comes_from_the_probe_and_a_user_callback_stays_local():
    session = saved_hard("vb_pydantic_coercion")
    issue = next(i for i in session.issues if i.tool == "pytest_run")
    evidence = issue_evidence(session, issue)
    assert evidence["raised_in"] == "third_party" and evidence["library"] == "pydantic"
    assert evidence["project_calls_library"]
    record = next(r for run in session.runs for r in run.records if r.get("type") == "exception")
    # An outer library calling a user validator is not the library raising the error.
    record["source_file"] = session.project_root + "/app.py"
    evidence = issue_evidence(session, issue)
    assert evidence["raised_in"] == "project" and not evidence["library"]


def test_old_snapshot_cannot_assert_that_pydantic_default_validation_was_used():
    session = saved_hard("vb_pydantic_coercion")
    infer_and_plan(session)
    assert not any(a.rule_ids == ["P64"] for a in session.actions)


def test_relative_and_absolute_spellings_of_the_same_frame_are_not_counted_twice():
    session = saved_hard("vb_pydantic_coercion")
    records = [r for run in session.runs for r in run.records]
    failure = next(r for r in records if r.get("type") == "failure")
    exception = next(r for r in records if r.get("type") == "exception")
    failure["message"] = (
        "test_app.py:1: in test_value\n    call(callback)\n"
        "/venv/lib/python3.12/site-packages/provider/core.py:2: in call\n    callback()\n"
        "app.py:3: in callback\n    raise ValueError('invalid input')\n"
    )
    exception.update(exception_type="ValueError", exception_message="invalid input",
                     source_file=session.project_root + "/app.py", source_line=3)
    issue = next(i for i in session.issues if i.tool == "pytest_run")
    evidence = issue_evidence(session, issue)
    assert evidence["third_party_frame_ratio"] == 0.333
    assert evidence["where"] == "app.py:3" and not evidence["library"]


@pytest.mark.parametrize("change", ["old_version", "no_installed_version", "no_project_context"])
def test_matching_output_without_version_evidence_is_not_enough(change):
    session = saved_hard("vb_numpy_promotion")
    infer_and_plan(session)
    assert any(a.rule_ids == ["P64"] for a in session.actions), "positive control must match"
    if change == "old_version":
        for package in session.environment["packages"]:
            if package["name"].lower() == "numpy":
                package["version"] = "1.26.4"
    elif change == "no_installed_version":
        session.environment["packages"] = [p for p in session.environment["packages"] if p["name"].lower() != "numpy"]
    else:
        session.runs = [r for r in session.runs if r.tool != "project"]
    infer_and_plan(session)
    assert not any(a.rule_ids == ["P64"] for a in session.actions)


def test_string_matcher_requires_equivalent_values_and_does_not_execute_text():
    assert scalar_representation_only("assert 'sum=np.float64(3.25)' == 'sum=3.25'")
    assert not scalar_representation_only("assert 'sum=np.float64(3.25)' == 'sum=4.25'")
    assert not scalar_representation_only("assert 'np.float32(3.25)' == 'np.float64(3.25)'")
    assert not scalar_representation_only("assert __import__('os').system('anything') == '3.25'")


def test_promotion_requires_the_mixed_expression_inside_the_json_value():
    imports = {"np": "numpy", "json": "json"}
    assert promotion_in_json_call(['return json.dumps({"n": np.float32(2.5) + 0.25})'], imports)
    assert not promotion_in_json_call(['return json.dumps({"n": np.float32(2.75)})'], imports)
    assert not promotion_in_json_call(['x = np.float32(2.5) + 0.25; return json.dumps({"n": value})'], imports)
    assert not promotion_in_json_call(['return json.dumps({"n": "np.float32(2.5) + 0.25"})'], imports)
