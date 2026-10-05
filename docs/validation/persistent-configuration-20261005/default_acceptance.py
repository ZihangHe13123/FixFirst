"""Rerun fixed product fixtures through default scan, without a language model."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from frozen_cases import build
from fixfirst.runner import DEFAULT_CHECKS
from fixfirst.service import create_session, scan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--django-python", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    for key in ("PYTHONPATH", "PYTEST_ADDOPTS", "DJANGO_SETTINGS_MODULE"):
        os.environ.pop(key, None)
    results = []
    with tempfile.TemporaryDirectory(prefix="ff-default-recipes-") as folder:
        for kind in ("local", "django"):
            python = sys.executable if kind == "local" else args.django_python
            for fmt in ("ini", "hidden_ini", "tox", "cfg", "toml_ini", "toml_native", "pytest_toml", "none"):
                # These Django fixtures access settings only inside test functions.
                # Collection does not execute that fault; it is a healthy control.
                for goal in (("pass_tests", "collect_tests") if kind == "local" else ("pass_tests",)):
                    root = Path(folder) / f"{kind}-{fmt}-{goal}"
                    filename, _ = build(root, kind, fmt)
                    tests = {p.name: p.read_bytes() for p in root.glob("test*.py")}
                    session = create_session(root, python, goal=goal)
                    session.use_classifier = False
                    scan(session)
                    rule = "P12" if kind == "local" else "P86"
                    actions = [a for a in session.actions if rule in a.rule_ids]
                    assert actions, (kind, fmt, goal, [(a.title, a.rule_ids) for a in session.actions])
                    action = actions[0]
                    assert action.title.startswith("Save "), (kind, fmt, goal, action.explanation)
                    fence = chr(96) * 3
                    assignment = re.search(fence + r"(?:ini|toml)\n(.+?)" + fence, action.explanation, re.S)
                    assert assignment, action.explanation
                    original = (root / filename).read_text() if (root / filename).exists() else ""
                    text = assignment[1]
                    if original:
                        lines = text.splitlines()
                        section = lines[0]
                        assert section in original and section.startswith("[")
                        configured = original.replace(section, section + "\n" + "\n".join(lines[1:]), 1)
                    else:
                        configured = text
                    (root / filename).write_text(configured)
                    env = dict(os.environ)
                    for key in ("PYTHONPATH", "PYTEST_ADDOPTS", "DJANGO_SETTINGS_MODULE"):
                        env.pop(key, None)
                    run = subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                         cwd=root, env=env, capture_output=True, text=True, timeout=60)
                    assert run.returncode == 0, (kind, fmt, goal, run.stdout, run.stderr)
                    assert tests == {p.name: p.read_bytes() for p in root.glob("test*.py")}
                    results.append({"kind": kind, "format": fmt, "goal": goal,
                                    "config_file": filename, "rule": rule,
                                    "default_checks": [r.tool for r in session.runs],
                                    "recipe": text, "fresh_process_exit_code": run.returncode,
                                    "test_files_unchanged": True})
    args.out.write_text(json.dumps({"default_checks": list(DEFAULT_CHECKS), "cases": results,
                                    "language_models_called": False}, indent=2) + "\n")
    print(f"{len(results)}/{len(results)} default recipes passed in a fresh process")


if __name__ == "__main__":
    main()
