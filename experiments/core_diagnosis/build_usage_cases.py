"""Construct and execute ordinary API misuse for development training.

Each program passes first, receives a known bad argument, then passes again after
restoring that argument. Test files stay byte-identical. These are generated
training fixtures, not naturally occurring failures or human-reviewed examples.
The reserved controls use other callables and are never imported here.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

from fixfirst.diagnosis_cases import CHECKS, portable
from fixfirst.service import create_session, scan


USAGES = [
    ("urlencode", "keyword", "from urllib.parse import urlencode", 'urlencode({"a": 1})', 'urlencode({"a": 1}, unknown_option=True)', "a=1"),
    ("base64", "keyword", "from base64 import b64encode", 'b64encode(b"hi").decode()', 'b64encode(b"hi", unknown_option=True).decode()', "aGk="),
    ("normpath", "keyword", "from os.path import normpath", 'normpath("a/./b")', 'normpath("a/./b", unknown_option=True)', "a/b"),
    ("html_escape", "keyword", "from html import escape", 'escape("<a>")', 'escape("<a>", unknown_option=True)', "&lt;a&gt;"),
    ("mean", "keyword", "from statistics import mean", 'mean([1, 3])', 'mean([1, 3], unknown_option=True)', 2),
    ("quote", "positional", "from urllib.parse import quote", 'quote("a b", safe="")', 'quote(safe="")', "a%20b"),
    ("textwrap", "positional", "from textwrap import fill", 'fill("red blue", width=8)', 'fill(width=8)', "red blue"),
    ("csv_reader", "positional", "from csv import DictReader", 'list(DictReader(["a\\n", "1\\n"]))', 'list(DictReader())', [{"a": "1"}]),
    ("ip_address", "positional", "from ipaddress import ip_address", 'ip_address("127.0.0.1").is_loopback', 'ip_address().is_loopback', True),
    ("calendar", "positional", "from calendar import isleap", 'isleap(2024)', 'isleap()', True),
]

VALIDATION = [
    ("url", "AnyUrl", '"https://example.org/"', "17", "str", "https://example.org/"),
    ("date", "date", '"2020-02-03"', '"never-a-date"', "str", "2020-02-03"),
    ("uuid", "UUID", '"00000000-0000-0000-0000-000000000001"', '"invalid-uuid"', "str", "00000000-0000-0000-0000-000000000001"),
    ("range", "Annotated[int, Field(ge=1)]", "3", "0", "int", 3),
    ("list", "list[int]", "[1, 2]", "0", "list", [1, 2]),
]


def definitions():
    for name, group, imports, good, bad, expected in USAGES:
        yield name, group, f"{imports}\n\ndef convert():\n    return {good}\n", good, bad, expected
    for name, annotation, good, bad, cast, expected in VALIDATION:
        source = ("from datetime import date\nfrom uuid import UUID\nfrom typing import Annotated\n"
                  "from pydantic import BaseModel, AnyUrl, Field\n\n"
                  f"class Payload(BaseModel):\n    value: {annotation}\n\n"
                  f"def convert():\n    return {cast}(Payload(value={good}).value)\n")
        yield "validation_" + name, "validation", source, f"value={good}", f"value={bad}", expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows, proofs = [], []
    for name, group, source, old, bad, expected in definitions():
        root = output / "projects" / name
        root.mkdir(parents=True)
        app, test = root / "app.py", root / "test_app.py"
        app.write_text(source)
        test.write_text(f"from app import convert\ndef test_convert():\n    assert convert() == {expected!r}\n")
        original_test = hashlib.sha256(test.read_bytes()).hexdigest()

        def run():
            session = create_session(root, sys.executable, goal="pass_tests")
            scan(session, CHECKS)
            return session

        healthy = run()
        if healthy.goal_status != "achieved" or source.count(old) != 1:
            raise ValueError(f"Invalid healthy fixture: {name}")
        app.write_text(source.replace(old, bad))
        failure = run()
        issues = [i for i in failure.issues if i.tool == "pytest_run" and i.status == "open" and i.kind != "tool_failure"]
        if not issues:
            raise ValueError(f"No actual failure: {name}")
        data, environment = portable(failure, root)
        data["environment"] = {**environment, **{k: v for k, v in data["environment"].items() if k.startswith("_")}}
        app.write_text(source)
        repaired = run()
        if repaired.goal_status != "achieved" or hashlib.sha256(test.read_bytes()).hexdigest() != original_test:
            raise ValueError(f"Repair did not pass unchanged tests: {name}")
        rows.append({"case_id": name, "template": "api-usage-training", "scenario": "usage-" + group,
                     "label": "code_defect", "knowledge_covered": False, "session": data,
                     "label_origin": "controlled bad-argument injection, execution-verified", "human_rereview": "pending"})
        proofs.append({"id": name, "group": group, "good": old, "bad": bad,
                       "healthy_passed": True, "failure_observed": True, "repair_passed": True,
                       "unchanged_test_sha256": original_test})
        print(name + ": pass -> fail -> pass, tests unchanged", flush=True)
    (output / "cases.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    (output / "environment.json").write_text(json.dumps({"layout": "inline per observation"}) + "\n")
    (output / "manifest.json").write_text(json.dumps({
        "origin": "controlled_usage_training", "license": "CC0-1.0 fixture source",
        "cases": proofs, "groups": ["keyword", "positional", "validation"],
        "limitations": "15 generated examples in three related fault families, not 15 independent real projects. Reserved controls are separate callables/types and remain development validation.",
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
