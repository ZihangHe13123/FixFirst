import json
import re
import sys

import pytest

from fixfirst.classification import SCHEMA_VERSION
from fixfirst.evidence import FEATURE_NAMES
from fixfirst.migration_advice import renamed_keyword
from fixfirst.reasoning import infer_and_plan
from fixfirst.service import create_session, scan
from fixfirst.symbol_advice import join_edit, spelling_edit


def model(path, label):
    path.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "task": "root_cause",
        "feature_names": FEATURE_NAMES, "classes": [label],
        "nodes": [{"left": -1, "right": -1, "feature": -2, "threshold": -2., "values": [1.]}]}))
    return str(path)


@pytest.mark.parametrize("body,test", [
    ("import random\ndef value():\n    rng = random.Random(0)\n    return rng.randInt(1, 6)\n",
     "from app import value\ndef test_value():\n    assert 1 <= value() <= 6\n"),
    ("def value(a, b):\n    return ','.join(a, b)\n",
     "from app import value\ndef test_value():\n    assert value('x', 'y') == 'x,y'\n"),
    ("from collections import Ordereddict\ndef value():\n    return Ordereddict(a=1)['a']\n",
     "from app import value\ndef test_value():\n    assert value() == 1\n"),
])
def test_model_supported_exact_advice_passes_original_test_without_changing_it(tmp_path, body, test):
    (tmp_path / "app.py").write_text(body)
    test_path = tmp_path / "test_app.py"
    test_path.write_text(test)
    s = create_session(tmp_path, sys.executable, goal="pass_tests", model=model(tmp_path / "tree.json", "code_defect"))
    scan(s, ["environment", "project", "pytest_run"])
    advice = s.actions[0]
    assert any(rule.startswith("observed-symbol:") for rule in advice.rule_ids)
    match = re.search(r"app.py:(\d+): replace `([^`]+)` with `([^`]+)`", advice.explanation)
    assert match, advice.explanation
    lines = body.splitlines(keepends=True)
    offset = int(match[1]) - 1
    assert lines[offset].strip() == match[2]
    indent = lines[offset][:-len(lines[offset].lstrip())]
    lines[offset] = indent + match[3] + "\n"
    (tmp_path / "app.py").write_text("".join(lines))
    scan(s, ["pytest_run"])
    assert s.goal_status == "achieved"
    assert test_path.read_text() == test


def test_raw_unsupported_version_prediction_is_preserved_but_not_adopted(tmp_path):
    (tmp_path / "app.py").write_text("import random\ndef value():\n    rng = random.Random(0)\n    return rng.randInt(1, 6)\n")
    (tmp_path / "test_app.py").write_text("from app import value\ndef test_value():\n    value()\n")
    s = create_session(tmp_path, sys.executable, goal="pass_tests", model=model(tmp_path / "tree.json", "version_incompatibility"))
    scan(s, ["environment", "project", "pytest_run"])
    issue = next(i for i in s.issues if i.tool == "pytest_run")
    assert issue.prediction == "version_incompatibility" and issue.prediction_confidence == 1
    assert issue.diagnosis is None and "cause remains unconfirmed" in issue.prediction_note
    assert not any(f.predicate == "model_suggests" for f in s.facts)
    assert not any(a.command or a.check == "version_search" for a in s.actions)
    s.model_path = model(tmp_path / "tree.json", "code_defect")
    infer_and_plan(s)
    assert issue.diagnosis == "code_defect" and not issue.prediction_note


def test_import_edit_preserves_bindings_and_rejects_ambiguous_or_dynamic_names():
    row = {"name": "Ordereddict", "module": "collections", "operation": "IMPORT_FROM",
           "requested_member_present": False, "dynamic": False, "unique": True,
           "candidates": [{"name": "OrderedDict", "relation": "case"}]}
    assert spelling_edit("from collections import Ordereddict, deque", row) == "from collections import OrderedDict as Ordereddict, deque"
    assert spelling_edit("from collections import Ordereddict as Store", row) == "from collections import OrderedDict as Store"
    assert spelling_edit("from another import Ordereddict", row) is None
    assert spelling_edit("from collections import Ordereddict", {**row, "dynamic": True}) is None
    assert spelling_edit("from collections import Ordereddict", {**row, "unique": False}) is None
    assert spelling_edit("from collections import Ordereddict", {**row, "candidates": [{"name": "OrderedDict", "relation": "other"}]}) is None


def test_join_recipe_does_not_guess_values_or_generalize_to_other_builtins():
    row = {"kind": "builtin_call", "module": "builtins", "owner": "str", "name": "join",
           "argument_count_expected": 1, "argument_count_given": 2, "argument_types": ["str", "str"]}
    assert join_edit("return ','.join(a, b)", row) == "return ','.join((a, b))"
    assert join_edit("return ','.join(a(), b)", row) is None
    assert join_edit("return ','.join(a, b)", {**row, "argument_types": ["str", "other"]}) is None
    assert join_edit("return len(a, b)", {**row, "owner": "", "name": "len"}) is None
    assert join_edit("return ','.join(a, *b)", row) is None


@pytest.mark.parametrize("statement,expected", [
    ("with client(proxies='http://localhost') as conn:", "with client(proxy='http://localhost') as conn:"),
    ("result = client(proxies='http://localhost', timeout=2)", "result = client(proxy='http://localhost', timeout=2)"),
    ("文字 = client(proxies='http://localhost')", "文字 = client(proxy='http://localhost')"),
    ("client(proxies={'https://': url})", None),
    ("client(proxies=config)", None),
    ("client(proxies='x', proxy='y')", None),
    ("client(proxies='x', **options)", None),
    ("client(proxies='x', timeout=get_timeout())", None),
])
def test_documented_proxy_rename_requires_one_literal_url_and_keeps_other_code(statement, expected):
    entry = {"name": "proxies", "rename_to": "proxy", "rename_value": "string_literal"}
    assert renamed_keyword(statement, entry) == expected
