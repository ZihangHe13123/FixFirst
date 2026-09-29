"""Reproduce one BugsInPy bug and record how FixFirst handles it (docs/tasks/B12).

Usage: python scripts/bugsinpy_case.py PROJECT BUG [--target DIR] [--python VERSION]
       [--deps PACKAGE ...] [--node NODE ...] [--no-build-isolation] [--no-fixfirst]

A bug is prepared the way BugsInPy defines it: the fixed commit with the bug's patch
(bug_patch.txt, source files only) reversed, so the tests are the fixed commit's and the source
has the bug. It is installed into a fresh environment (uv, --python). Then:

1. the bug's test (run_test.sh) runs and must fail;
2. FixFirst checks the project (goal: make the tests pass) and its first steps are recorded;
3. the patch is applied again (the fix, as a developer would make it; tests unchanged);
4. the bug's test runs again and must pass;
5. FixFirst checks again and records whether the bug's issue is now fixed and verified.

The bug counts as reproduced only when 1 fails and 4 passes. Everything is written to
DIR/results/<project>-<bug>.json (with the test outputs beside it); the FixFirst sessions open
with `fixfirst --store DIR/.fixfirst serve`. Running it again starts from a clean checkout.
Needs git, uv and internet access (GitHub, PyPI). It runs the project's own tests.
"""

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from collect_public_data import BUGSINPY_COMMIT, BUGSINPY_REPO, fetch, parse_info, raw_url  # noqa: E402
from fixfirst.service import create_session, scan  # noqa: E402
from fixfirst.storage import Store  # noqa: E402
from fixfirst.workspace import build_view  # noqa: E402

BUGS = ROOT / "examples" / "public-data" / "bugsinpy" / "bugs.csv"
CACHE = ROOT / "workbench" / "public-data-cache"


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True, text=True).stdout


def venv_python(folder: Path) -> Path:
    return folder / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def activated(folder: Path) -> dict:
    scripts = venv_python(folder).parent
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    env["PATH"] = str(scripts) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(scripts.parent)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def dotted_to_node(name: str, folder: Path) -> str:
    """unittest's test.test_utils.TestUtil.test_x -> test/test_utils.py::TestUtil::test_x"""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        path = Path(*parts[:end]).with_suffix(".py")
        if (folder / path).is_file():
            return "::".join([path.as_posix(), *parts[end:]])
    raise ValueError(f"No test file found for {name}; pass the test with --node")


def test_nodes(run_test: str, folder: Path) -> list[str]:
    """The tests named in BugsInPy's run_test.sh (pytest, tox or unittest command lines)."""
    nodes = []
    for line in run_test.splitlines():
        words = shlex.split(line, comments=True)
        if "unittest" in words:
            nodes += [dotted_to_node(w, folder) for w in words[words.index("unittest") + 1:]
                      if not w.startswith("-")]
        else:
            nodes += [w for w in words if "::" in w or w.endswith(".py")]
    return list(dict.fromkeys(nodes))


def run_tests(folder: Path, nodes: list[str], output: Path) -> int:
    done = subprocess.run([str(venv_python(folder)), "-m", "pytest", "-q", "-p", "no:cacheprovider", *nodes],
                          cwd=folder, env=activated(folder), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=1800)
    home = Path.home()
    text = done.stdout.decode("utf-8", "replace").replace(str(home), "<home>")
    output.write_text(text, encoding="utf-8")
    return done.returncode


def step_summary(step: dict) -> dict:
    return {"title": step["title"], "cause": step["cause"] or step["possible"],
            "hedged": bool(step["possible"] or step["suspected"]), "rules": step["rules"],
            "command": step["command"], "where": step["where"][:3]}


def check(session, store: Store, nodes: list[str]) -> dict:
    scan(session)
    store.save(session)
    view = build_view(session)
    run = next((r for r in reversed(session.runs) if r.tool == "pytest_run"), None)
    outcomes = {}
    for record in (run.records if run else []):
        if record.get("type") == "outcome" and record.get("nodeid") in nodes and record.get("stage") == "call":
            outcomes[record["nodeid"]] = record["outcome"]
    bug_issues = [i for i in session.issues if set(i.targets) & set(nodes)]
    return {
        "headline": view["status"]["headline"],
        "status": view["status"]["kind"],
        "tests": run.test_summary if run else {},
        "bug_test_outcomes": outcomes,
        "steps": [step_summary(s) for s in view["steps"]],
        "optional": [step_summary(s) for s in view["optional"]],
        # Install, upgrade or pin commands: environment advice for what is a code defect.
        "environment_advice": [s["title"] for s in view["steps"] if s["command"]],
        "bug_issues": [{"title": i.title[:160], "status": i.status, "diagnosis": i.diagnosis,
                        "source": i.diagnosis_source, "rule": i.diagnosis_rule} for i in bug_issues],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("project", help="BugsInPy project name, e.g. PySnooper, tqdm")
    parser.add_argument("bug", type=int)
    parser.add_argument("--target", default="../bugsinpy-cases")
    parser.add_argument("--python", default="3.9", help="Python version for uv (default 3.9)")
    parser.add_argument("--deps", nargs="*", default=["pytest"], help="test packages (default: pytest)")
    parser.add_argument("--node", nargs="*", default=[], help="tests to run, instead of run_test.sh's")
    parser.add_argument("--no-build-isolation", action="store_true",
                        help="install the project with the setuptools from --deps (old setup.py files)")
    parser.add_argument("--no-fixfirst", action="store_true", help="only check that the bug reproduces")
    args = parser.parse_args()
    if not shutil.which("uv"):
        raise SystemExit("uv is needed: https://docs.astral.sh/uv/getting-started/installation/")
    rows = list(csv.DictReader(BUGS.open(newline="", encoding="utf-8")))
    row = next((r for r in rows if r["project"].lower() == args.project.lower() and int(r["bug"]) == args.bug), None)
    if row is None:
        raise SystemExit(f"{args.project} {args.bug} is not in {BUGS.relative_to(ROOT)}")
    case = f"{row['project']}-{args.bug}"
    target = Path(args.target).resolve()
    results = target / "results"
    results.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    base = f"projects/{row['project']}/bugs/{args.bug}"
    files = {}
    for name in ("bug.info", "run_test.sh", "bug_patch.txt"):
        data = fetch(raw_url(BUGSINPY_REPO, BUGSINPY_COMMIT, f"{base}/{name}"), CACHE)
        if data is None:
            raise SystemExit(f"BugsInPy has no {name} for {case}")
        files[name] = data.decode("utf-8", "replace")
    info, run_test = parse_info(files["bug.info"]), files["run_test.sh"]
    buggy, fixed = info["buggy_commit_id"], info["fixed_commit_id"]
    folder = target / case
    patch = target / "results" / f"{case}-bug_patch.txt"
    patch.write_text(files["bug_patch.txt"], encoding="utf-8")
    print(f"== {case}: {row['project_repository']} fixed commit {fixed[:10]}", flush=True)
    if not folder.exists():
        # BugsInPy's patches use LF line endings; Git for Windows would check files out with CRLF.
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "-c", "core.autocrlf=false",
                        row["project_repository"], str(folder)], check=True)
    try:
        git(folder, "checkout", "-q", "-f", fixed)
    except subprocess.CalledProcessError:
        raise SystemExit(f"The fixed commit {fixed} is no longer in {row['project_repository']}; pick another bug")
    git(folder, "clean", "-q", "-f", "-d", "-x", "-e", ".venv")
    try:
        git(folder, "apply", "-R", str(patch))
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"BugsInPy's patch does not reverse cleanly: {error.stderr.strip()}")
    source = [line.split("\t")[-1] for line in git(folder, "apply", "--numstat", str(patch)).splitlines()]
    nodes = args.node or test_nodes(run_test, folder)
    if not nodes:
        raise SystemExit("run_test.sh names no test; pass the tests with --node")
    record = {"case": case, "repository": row["project_repository"], "buggy_commit": buggy,
              "fixed_commit": fixed, "bugsinpy_python": info.get("python_version"),
              "patched_files": source, "tests": nodes, "run_test_sh": run_test.strip(),
              "date": datetime.now().astimezone().isoformat(timespec="seconds")}
    python = venv_python(folder)
    if not python.exists():
        subprocess.run(["uv", "venv", "-q", "-p", args.python, str(folder / ".venv")], check=True)
    install = [["uv", "pip", "install", "-q", "--python", str(python), *args.deps],
               ["uv", "pip", "install", "-q", "--python", str(python), "-e", ".",
                *(["--no-build-isolation"] if args.no_build_isolation else [])]]
    for argv in install:
        if subprocess.run(argv, cwd=folder).returncode != 0:
            record["result"] = "install failed: " + " ".join(argv[5:])
            (results / f"{case}.json").write_text(json.dumps(record, indent=2) + "\n", "utf-8")
            print(f"   {record['result']}; try other --deps, --no-build-isolation or --python")
            return 1
    record["python"] = subprocess.run([str(python), "-c", "import sys; print(sys.version.split()[0])"],
                                      capture_output=True, text=True).stdout.strip()
    freeze = subprocess.run(["uv", "pip", "freeze", "--python", str(python)], capture_output=True, text=True)
    record["installed"] = [line for line in freeze.stdout.splitlines() if not line.startswith("-e ")]

    record["buggy_test_exit_code"] = run_tests(folder, nodes, results / f"{case}-buggy-test.txt")
    print(f"   buggy source: tests exit with {record['buggy_test_exit_code']} (1 = failed, as expected)")
    store = Store(target / ".fixfirst")
    session = None
    if not args.no_fixfirst and record["buggy_test_exit_code"] == 1:
        session = create_session(folder, str(python), goal="pass_tests")
        session.name = case
        record["fixfirst_session"] = session.session_id
        record["fixfirst_before"] = check(session, store, nodes)

    git(folder, "apply", str(patch))
    record["fixed_test_exit_code"] = run_tests(folder, nodes, results / f"{case}-fixed-test.txt")
    print(f"   fixed source: tests exit with {record['fixed_test_exit_code']} (0 = passed, as expected)")
    record["reproduced"] = record["buggy_test_exit_code"] == 1 and record["fixed_test_exit_code"] == 0
    if session is not None:
        record["fixfirst_after"] = check(session, store, nodes)
        before, after = record["fixfirst_before"], record["fixfirst_after"]
        first = before["steps"][0]["title"] if before["steps"] else "(no must-fix step)"
        print(f"   FixFirst before: {before['headline']} | first step: {first}")
        print(f"   environment advice: {before['environment_advice'] or 'none'}")
        print(f"   FixFirst after: {after['headline']} | bug issues: "
              + (", ".join(i["status"] for i in after["bug_issues"]) or "none found"))
    record["result"] = "reproduced" if record["reproduced"] else "not reproduced"
    (results / f"{case}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"   {record['result']} → {results / (case + '.json')}")
    if session is not None:
        print(f"   open the session: fixfirst --store {store.root} serve")
    return 0 if record["reproduced"] else 2


if __name__ == "__main__":
    sys.exit(main())
