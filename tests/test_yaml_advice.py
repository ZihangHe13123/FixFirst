"""Executed library binding failures and their project lookalikes."""

import hashlib
import re
import sys

import pytest

from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def diagnose(root, source, expected="None"):
    (root / "app.py").write_text(source, encoding="utf-8")
    (root / "requirements.txt").write_text("PyYAML>=6\n")
    test = root / "test_app.py"
    test.write_text(f"from app import convert\ndef test_convert():\n    assert convert() == {expected}\n")
    session = create_session(root, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"], timeout=40)
    return session, test


@pytest.mark.parametrize("name,expected", [("load", "{'value': 3}"), ("load_all", "[{'value': 3}]")])
@pytest.mark.parametrize("alias", [False, True])
def test_real_loader_omission_has_an_executable_source_recipe(tmp_path, name, expected, alias):
    import_line = f"from yaml import {name} as parse" if alias else "import yaml"
    callee = "parse" if alias else "yaml." + name
    expression = f'{callee}("value: 3")'
    if name == "load_all":
        expression = "[document for document in " + expression + "]"
    source = f"{import_line}\ndef convert():\n    return {expression}\n"
    session, test = diagnose(tmp_path, source, expected)
    issues = [i for i in session.issues if i.tool == "pytest_run" and i.status == "open"]
    assert issues and all(i.diagnosis == "code_defect" for i in issues)
    steps = build_view(session)["steps"]
    assert steps[0]["title"] == "Choose an explicit safe YAML loader"
    assert ("safe_load_all" if name == "load_all" else "safe_load") in steps[0]["instructions"]
    assert steps[0]["instructions"].startswith("For standard YAML data")
    assert "custom tags" in steps[0]["instructions"]
    assert not steps[0]["command"]
    before = hashlib.sha256(test.read_bytes()).hexdigest()
    instructions = steps[0]["instructions"]
    changes = re.findall(r"replace `([^`]+)` with `([^`]+)`", instructions)
    assert len(changes) == 1
    old, new = changes[0]
    assert source.count(old) == 1
    imports = re.findall(r"add `([^`]+)` immediately before", instructions)
    repaired = source.replace(old, (imports[0] + "\n    " if imports else "") + new)
    (tmp_path / "app.py").write_text(repaired)
    scan(session, ["project", "pytest_run"], timeout=40)
    assert session.goal_status == "achieved"
    assert hashlib.sha256(test.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("source", [
    'def load(text, Loader):\n    return text\ndef convert():\n    return load("value: 3")\n',
    'import yaml\ndef load(text, Loader):\n    return text\nload.__module__ = "yaml"\nyaml.load = load\ndef convert():\n    return yaml.load("value: 3")\n',
    'import yaml\ndef convert():\n    raise TypeError("load() missing 1 required positional argument: \'Loader\'")\n',
    'import yaml\ndef convert():\n    try:\n        yaml.load("value: 3")\n    except TypeError:\n        raise TypeError("load() missing 1 required positional argument: \'Loader\'") from None\n',
    'import yaml\ndef convert():\n    yaml.load("value: 3", Loader=yaml.SafeLoader)\n    raise TypeError("unrelated argument error")\n',
    'from yaml import load as parse\ndef parse(text, Loader):\n    return text\ndef convert():\n    return parse("value: 3")\n',
    # The current runtime observer cannot isolate the nested call in list(...).
    # Missing operation provenance must remain a review, not a fabricated recipe.
    'import yaml\ndef convert():\n    return list(yaml.load_all("value: 3"))\n',
])
def test_same_name_shadowing_and_forged_errors_do_not_get_yaml_guidance(tmp_path, source):
    session, _ = diagnose(tmp_path, source)
    assert not any(a.action_id.startswith("yaml-loader-") for a in session.actions)


def test_project_wrapper_named_load_does_not_hide_the_real_library_call(tmp_path):
    source = 'import yaml\ndef load(text):\n    return yaml.load(text)\ndef convert():\n    return load("value: 3")\n'
    session, _ = diagnose(tmp_path, source, "{'value': 3}")
    assert any(a.action_id.startswith("yaml-loader-") for a in session.actions)
