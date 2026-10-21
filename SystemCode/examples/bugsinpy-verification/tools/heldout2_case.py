#!/usr/bin/env python3
"""One BugsInPy bug with the product of a tree, in the default use or with the bug's tests named. No model.

    heldout2_case.py TREE PROJECT BUG --target DIR --mode default|scoped|none [--python VERSION] [--deps PACKAGE ...]
                     [--no-build-isolation]

The case script of the second held-out set (2026-10-10, registry addendum 111): heldout_case.py with one change.
BugsInPy's bug.info of some projects writes a key with a blank before the equals sign and with CRLF line ends
(fixed_commit_id ="..."), which the tree's parse_info does not read; here the file is read tolerantly (blanks
around the equals sign, either line end). Nothing else differs. What follows is the text of heldout_case.py.

Written on 2026-10-09 (registry addendum 96 c) for the held-out test of the next version; one script for every arm,
so that all arms are recorded and matched in the same way. The flow and the helpers are those of the tree's own
scripts/bugsinpy_case.py (take the fixed commit, apply BugsInPy's patch in reverse, run the bug's tests, check
with the product, apply the patch again, run the tests, check again). The modes:
  default   the session is created as that script creates it (goal pass_tests, nothing else);
  scoped    the session is created with tests=<the tests of BugsInPy's run_test.sh> (the tree must support it);
  none      the product is not run (preparation: the environment is built and the bug reproduced).
Recorded as in b12_scoped_case.py: the issues of the bug's tests by exact equality of a test's name with an issue's
target (bug_issues_exact, the way of the tree's script) and also counting the parametrized instances of a named
test and the tests inside a named file or class (bug_issues, which is what is judged).
If the product raises an exception during a check, the traceback is recorded (product_error_before or
product_error_after), that check has no record, and the flow goes on, so that the reproduction is still recorded.
"""
import argparse
import csv
import json
import re
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
sys.argv = [sys.argv[0], *sys.argv[2:]]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import bugsinpy_case as base  # noqa: E402  (the tree's own script: its helpers are used unchanged)
from collect_public_data import BUGSINPY_COMMIT, BUGSINPY_REPO, fetch, parse_info, raw_url  # noqa: E402
from fixfirst.service import create_session  # noqa: E402
from fixfirst.storage import Store  # noqa: E402
from fixfirst.workspace import build_view  # noqa: E402


def covers(selector, node):
    return node == selector or node.startswith(selector + "::") or node.startswith(selector + "[")


def check(session, store, nodes):
    record = base.check(session, store, nodes)
    record["bug_issues_exact"] = record["bug_issues"]
    wide = [i for i in session.issues if i.tool == "pytest_run" and any(covers(n, t) for n in nodes for t in i.targets)]
    record["bug_issues"] = [{"title": i.title[:160], "status": i.status, "diagnosis": i.diagnosis, "source": i.diagnosis_source, "rule": i.diagnosis_rule,
                             "note": (getattr(i, "note", "") or "")[:300], "scope": getattr(i, "scope", None)} for i in wide]
    run = next((r for r in reversed(session.runs) if r.tool == "pytest_run"), None)
    view = build_view(session)
    record.update(saved_selection=list(getattr(session, "test_targets", []) or []), run_scope=getattr(run, "scope", None) if run else None,
                  run_status=run.status if run else None, run_exit_code=run.exit_code if run else None,
                  status_detail=view["status"]["detail"][:400], open_issue_titles=[(i.tool, i.title[:100], i.status) for i in session.issues][:12])
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("bug", type=int)
    parser.add_argument("--target", required=True)
    parser.add_argument("--mode", required=True, choices=["default", "scoped", "none"])
    parser.add_argument("--python", default="3.9")
    parser.add_argument("--deps", nargs="*", default=["pytest"])
    parser.add_argument("--no-build-isolation", action="store_true")
    args = parser.parse_args()
    rows = list(csv.DictReader(base.BUGS.open(newline="", encoding="utf-8")))
    row = next(r for r in rows if r["project"].lower() == args.project.lower() and int(r["bug"]) == args.bug)
    case = f"{row['project']}-{args.bug}"
    target = Path(args.target).resolve()
    results = target / "results"
    results.mkdir(parents=True, exist_ok=True)
    base.CACHE.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in ("bug.info", "run_test.sh", "bug_patch.txt"):
        files[name] = fetch(raw_url(BUGSINPY_REPO, BUGSINPY_COMMIT, f"projects/{row['project']}/bugs/{args.bug}/{name}"), base.CACHE).decode("utf-8", "replace")
    info = dict(re.findall(r'^(\w+)[ \t]*=[ \t]*"?([^"\r\n]*)"?[ \t]*\r?$', files["bug.info"], flags=re.M))
    assert info == {**parse_info(files["bug.info"]), **info}, "the tolerant reading must agree with the tree's wherever the tree's reads a key"
    run_test = files["run_test.sh"].replace("\r\n", "\n")
    fixed = info["fixed_commit_id"]
    folder = target / case
    patch = results / f"{case}-bug_patch.txt"
    patch.write_text(files["bug_patch.txt"], encoding="utf-8")
    print(f"== {case} ({args.mode}): {row['project_repository']} fixed commit {fixed[:10]}", flush=True)
    if not folder.exists():
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "-c", "core.autocrlf=false", row["project_repository"], str(folder)], check=True)
    base.git(folder, "checkout", "-q", "-f", fixed)
    base.git(folder, "clean", "-q", "-f", "-d", "-x", "-e", ".venv")
    base.git(folder, "apply", "-R", str(patch))
    nodes = base.test_nodes(run_test, folder)
    record = {"case": case, "mode": args.mode, "repository": row["project_repository"], "fixed_commit": fixed, "tests": nodes, "deps": args.deps,
              "patched_files": [line.split("\t")[-1] for line in base.git(folder, "apply", "--numstat", str(patch)).splitlines()],
              "product_tree": str(ROOT), "date": datetime.now().astimezone().isoformat(timespec="seconds")}
    python = base.venv_python(folder)
    if not python.exists():
        subprocess.run(["uv", "venv", "-q", "-p", args.python, str(folder / ".venv")], check=True)
    for argv in (["uv", "pip", "install", "-q", "--python", str(python), *args.deps],
                 ["uv", "pip", "install", "-q", "--python", str(python), "-e", ".", *(["--no-build-isolation"] if args.no_build_isolation else [])]):
        if subprocess.run(argv, cwd=folder).returncode != 0:
            record["result"] = "install failed"
            (results / f"{case}.json").write_text(json.dumps(record, indent=2) + "\n", "utf-8")
            print("   install failed")
            return 1
    record["python"] = subprocess.run([str(python), "-c", "import sys; print(sys.version.split()[0])"], capture_output=True, text=True).stdout.strip()
    freeze = subprocess.run(["uv", "pip", "freeze", "--python", str(python)], capture_output=True, text=True)
    record["installed"] = [line for line in freeze.stdout.splitlines() if not line.startswith("-e ")]
    record["buggy_test_exit_code"] = base.run_tests(folder, nodes, results / f"{case}-buggy-test.txt")
    store = Store(target / ".fixfirst")
    session = None
    if args.mode != "none" and record["buggy_test_exit_code"] == 1:
        try:
            session = create_session(folder, str(python), goal="pass_tests", **({"tests": nodes} if args.mode == "scoped" else {}))
        except ValueError as error:
            record["selection_refused"] = str(error)
        if session is not None:
            session.name = case
            record["fixfirst_session"] = session.session_id
            try:
                record["fixfirst_before"] = check(session, store, nodes)
            except Exception:
                record["product_error_before"] = traceback.format_exc()[-3000:]
    base.git(folder, "apply", str(patch))
    record["fixed_test_exit_code"] = base.run_tests(folder, nodes, results / f"{case}-fixed-test.txt")
    record["reproduced"] = record["buggy_test_exit_code"] == 1 and record["fixed_test_exit_code"] == 0
    if session is not None:
        try:
            record["fixfirst_after"] = check(session, store, nodes)
        except Exception:
            record["product_error_after"] = traceback.format_exc()[-3000:]
        before, after = record.get("fixfirst_before"), record.get("fixfirst_after")
        if before:
            print(f"   before: {before['headline']} | first step: {before['steps'][0]['title'] if before['steps'] else '(none)'} | bug issues {[i['status'] for i in before['bug_issues']]}")
        if after:
            print(f"   after: {after['headline']} | bug issues {[i['status'] for i in after['bug_issues']]}")
        for key in ("product_error_before", "product_error_after"):
            if key in record:
                print(f"   THE PRODUCT RAISED AN EXCEPTION ({key}): " + record[key].strip().splitlines()[-1])
    elif "selection_refused" in record:
        print("   the selection was refused: " + record["selection_refused"])
    record["result"] = "reproduced" if record["reproduced"] else "not reproduced"
    (results / f"{case}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"   {record['result']}: exit codes {record['buggy_test_exit_code']} and {record['fixed_test_exit_code']}")
    return 0 if record["reproduced"] else 2


if __name__ == "__main__":
    sys.exit(main())
