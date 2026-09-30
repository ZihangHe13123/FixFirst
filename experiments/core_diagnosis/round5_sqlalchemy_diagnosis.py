"""Real SQLite diagnosis and unchanged-test repair using an existing SQLAlchemy Python.

Only unittest is needed in the target environment. No packages are installed and
the target environment is not modified. A fresh temporary project is used per case.
"""

import argparse
import json
from pathlib import Path
import tempfile

from fixfirst.evidence import current_environment
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-head", required=True)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="fixfirst-r5-sqlalchemy-"))
    report = {"code_head": args.code_head, "cases": []}
    for name, query, operation in (
        ("lazy_generator", "create table t (n integer)", "rows = (tuple(row) for row in result)"),
        ("generator_consumed_later", "create table t (n integer)",
         "rows = (tuple(row) for row in result)\n        rows = list(rows)"),
        ("consume_list", "create table t (n integer)", "rows = list(result)"),
        ("fetchall", "create table t (n integer)", "rows = result.fetchall()"),
        ("explicit_close", "select 1", "result.close(); rows = list(result)"),
    ):
        project = root / name
        project.mkdir()
        source = ('from sqlalchemy import create_engine, text\n'
                  'def convert():\n    engine = create_engine("sqlite://")\n'
                  '    with engine.connect() as connection:\n'
                  f'        result = connection.execute(text({query!r}))\n'
                  f'        {operation}\n        return True\n')
        (project / "app.py").write_text(source)
        (project / "requirements.txt").write_text("sqlalchemy>=1.3\n")
        (project / "test_app.py").write_text('import unittest\nfrom app import convert\n'
                                            'class Check(unittest.TestCase):\n'
                                            '    def test_value(self):\n        assert convert() is True\n')
        session = create_session(project, args.python, goal="pass_unittest",
                                 execution={"kind": "unittest", "entry": "."})
        scan(session, ["environment", "project", "unittest_run"], timeout=30)
        report["environment"] = {"python": current_environment(session).get("python_version"),
                                 "packages": [p for p in current_environment(session).get("packages", [])
                                              if p.get("name", "").lower() == "sqlalchemy"]}
        issue = next((i for i in session.issues if i.tool == "unittest_run"), None)
        row = {"name": name, "original_goal": session.goal_status,
               "diagnosis": issue and issue.diagnosis, "rule": issue and issue.diagnosis_rule,
               "steps": [{k: s[k] for k in ("title", "explanation", "where")}
                         for s in build_view(session)["steps"]]}
        if name == "lazy_generator":
            test = (project / "test_app.py").read_bytes()
            (project / "app.py").write_text(source.replace(operation,
                "rows = (tuple(row) for row in result) if result.returns_rows else iter(())"))
            scan(session, ["unittest_run"], timeout=30)
            row.update(repair_goal=session.goal_status, tests_unchanged=test == (project / "test_app.py").read_bytes())
        report["cases"].append(row)
        print(name, row["diagnosis"], row["rule"], row.get("repair_goal"), flush=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
