import re
import sys

from fixfirst.cli import parser
from fixfirst.models import Session
from fixfirst.reasoning import infer_and_plan
from fixfirst.service import create_session, scan
from fixfirst.storage import Store


def test_factorial_uses_same_records_and_actions_do_not_require_model_or_projection(tmp_path):
    body = "def value(a,b):\n    return ','.join(a,b)\n"
    tests = "from app import value\ndef test_value():\n    assert value('x','y') == 'x,y'\n"
    (tmp_path / "app.py").write_text(body)
    (tmp_path / "test_app.py").write_text(tests)
    original = create_session(tmp_path, sys.executable, goal="pass_tests")
    original.use_classifier = False
    scan(original, ["environment", "project", "pytest_run"])
    arms = {}
    for label, b, c in (("A", False, False), ("B", True, False), ("C", False, True), ("D", True, True)):
        s = original.model_copy(deep=True)
        s.structured_evidence, s.bounded_actions = b, c
        infer_and_plan(s)
        arms[label] = s
        assert not any(f.predicate == "model_suggests" for f in s.facts)
        assert s.inference_trace["issues"][0]["bounded_action"]["generated"] == c
        assert bool([f for f in s.facts if f.predicate == "operation"]) == b
        assert all(ref in {f.fact_id for f in s.facts} for action in s.actions for ref in action.reason_refs)
    assert arms["A"].actions == arms["B"].actions
    assert arms["C"].actions == arms["D"].actions
    assert arms["A"].actions != arms["C"].actions
    assert [i.diagnosis for i in arms["A"].issues] == [i.diagnosis for i in arms["C"].issues]
    advice = arms["C"].actions[0]
    edit = re.search(r"replace `([^`]+)` with `([^`]+)`", advice.explanation)
    assert edit and body.count(edit[1]) == 1
    (tmp_path / "app.py").write_text(body.replace(edit[1], edit[2]))
    scan(arms["C"], ["pytest_run"])
    assert arms["C"].goal_status == "achieved"
    assert (tmp_path / "test_app.py").read_text() == tests
    assert not arms["C"].inference_trace["issues"]  # Fresh trace, no stale eligibility after success.


def test_experimental_flags_persist_and_old_session_defaults_are_off(tmp_path):
    s = create_session(tmp_path, sys.executable, structured_evidence=True, bounded_actions=True)
    store = Store(tmp_path / "store")
    store.save(s)
    restored = store.load(s.session_id)
    assert restored.structured_evidence and restored.bounded_actions
    old = s.model_dump(exclude={"structured_evidence", "bounded_actions", "inference_trace"})
    legacy = Session.model_validate(old)
    assert not legacy.structured_evidence and not legacy.bounded_actions
    args = parser().parse_args(["init", str(tmp_path), "--structured-evidence", "--bounded-actions"])
    assert args.structured_evidence and args.bounded_actions


def test_near_name_does_not_become_a_new_recipe_under_bounded_actions(tmp_path):
    (tmp_path / "app.py").write_text("import random\ndef value():\n    rng = random.Random(0)\n    return rng.randInt(1, 6)\n")
    (tmp_path / "test_app.py").write_text("from app import value\ndef test_value():\n    value()\n")
    s = create_session(tmp_path, sys.executable, goal="pass_tests", structured_evidence=True, bounded_actions=True)
    s.use_classifier = False
    scan(s, ["environment", "project", "pytest_run"])
    row = s.inference_trace["issues"][0]
    assert row["bounded_action"]["eligibility"] == "name_similarity_only"
    assert not row["bounded_action"]["generated"]
    assert not any("replace `" in a.explanation for a in s.actions)
