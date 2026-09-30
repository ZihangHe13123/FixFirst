"""Probe NumPy 2's descriptor removals using a chosen, already installed target Python.

Run with PYTHONPATH pointing to the code under review, and --python pointing to
the chosen NumPy environment. Both pytest and unittest are checked. Only fresh
temporary project copies are modified; the target environment is not installed into.
"""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from fixfirst.evidence import current_environment, issue_evidence
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--code-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="fixfirst-r5-methods-"))
    results, environment = [], {}
    for method, call, repair, expected in [
        ("ptp", "data.ptp()", "np.ptp(data)", "3"),
        ("newbyteorder", "data.newbyteorder('>').dtype.byteorder",
         "data.view(data.dtype.newbyteorder('>')).dtype.byteorder", "'>'"),
    ]:
        for mode in ("pytest", "unittest"):
            folder = root / f"{method}-{mode}"
            folder.mkdir()
            original = f"import numpy as np\ndef convert():\n    data = np.array([1,4])\n    return {call}\n"
            (folder / "app.py").write_text(original)
            (folder / "requirements.txt").write_text("numpy>=1.21\n")
            (folder / "pytest.ini").write_text("[pytest]\n")
            unit = mode == "unittest"
            test = ("import unittest\nfrom app import convert\nclass Check(unittest.TestCase):\n    def test_value(self):\n        "
                    if unit else "from app import convert\ndef test_value():\n    ")
            (folder / "test_app.py").write_text(test + f"assert convert() == {expected}\n")
            before = hashlib.sha256((folder / "test_app.py").read_bytes()).hexdigest()
            tool = "unittest_run" if unit else "pytest_run"
            session = create_session(folder, args.python, goal="pass_unittest" if unit else "pass_tests",
                                     execution={"kind": "unittest", "entry": "."} if unit else None)
            scan(session, ["environment", "project", tool], timeout=30)
            captured = current_environment(session)
            environment = {"python_version": captured.get("python_version"),
                           "packages": [p for p in captured.get("packages", [])
                                        if p.get("name", "").lower() in ("numpy", "pytest")]}
            issue = next(i for i in session.issues if i.tool == tool)
            evidence = issue_evidence(session, issue)
            row = {"method": method, "mode": mode, "diagnosis": issue.diagnosis, "rule": issue.diagnosis_rule,
                   "message": evidence["message"], "runtime_attribute": evidence["runtime_attribute"],
                   "step": build_view(session)["steps"][0]["title"], "before_exit": session.runs[-1].exit_code}
            (folder / "app.py").write_text(original.replace(call, repair))
            scan(session, [tool], timeout=30)
            row.update(after_goal=session.goal_status, after_exit=session.runs[-1].exit_code,
                       tests_unchanged=before == hashlib.sha256((folder / "test_app.py").read_bytes()).hexdigest())
            results.append(row)
            print(method, mode, row["diagnosis"], row["rule"], row["after_goal"], flush=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"code_head": args.code_head, "environment": environment, "cases": results,
                   "limits": "Known replacements applied in copies. Before-code misses are not counted as advice successes."},
                  stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
