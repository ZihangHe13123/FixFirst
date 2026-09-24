"""Run FixFirst once on every project from examples/real-world/projects.toml and record what
a user would see: the headline, the steps in order and the cause behind each.

Usage: python scripts/run_real_world.py [target-dir] [--only ID ...] [--output FILE] [--search]

The same checks as the web page's "Check again" run with the goal "Make my tests pass". With
--search, a first step that offers to find a working release is followed, as a user pressing
"Find it" would, and the step shown afterwards is recorded too (it needs internet access).
Sessions are saved in <target-dir>/.fixfirst, so they can be opened with
`fixfirst --store <target-dir>/.fixfirst serve`.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fixfirst.service import create_session, scan  # noqa: E402
from fixfirst.storage import Store  # noqa: E402
from fixfirst.workspace import build_view  # noqa: E402

HERE = Path(__file__).resolve().parent.parent / "examples" / "real-world"


def step_summary(step: dict) -> dict:
    return {
        "title": step["title"],
        "cause": step["cause"],
        "possible": step["possible"],
        "suspected": step["suspected"],
        "optional": step["optional"],
        "where": step["where"][:3],
        "command": step["command"],
        "rules": [r.split(":")[0] for r in step["rules"]],
        "issues": len(step["issue_ids"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", default="../test-projects/generalisation")
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--output", default=str(HERE / "results-latest.json"))
    parser.add_argument("--search", action="store_true", help="follow a first 'Find it' step")
    args = parser.parse_args()
    target = Path(args.target).resolve()
    store = Store(target / ".fixfirst")
    projects = tomllib.loads((HERE / "projects.toml").read_text("utf-8"))["project"]
    results = []
    for project in projects:
        if args.only and project["id"] not in args.only:
            continue
        folder = target / project["id"]
        python = folder / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        print(f"== {project['id']}", flush=True)
        start = time.monotonic()
        session = create_session(folder, str(python), goal="pass_tests")
        session.name = project["id"]
        scan(session)
        store.save(session)
        view = build_view(session)
        searched = None
        if args.search and view["steps"] and view["steps"][0]["search"]:
            before = step_summary(view["steps"][0])
            action = next(a for a in session.actions if a.action_id == view["steps"][0]["id"])
            scan(session, [action.check], targets=action.targets)
            store.save(session)
            view = build_view(session)
            searched = {"offered": before, "result": json.loads(session.runs[-1].stdout)}
        run = next((r for r in reversed(session.runs) if r.tool == "pytest_run"), None)
        results.append(
            {
                "id": project["id"],
                "session_id": session.session_id,
                "python": session.environment.get("python_version"),
                "seconds": round(time.monotonic() - start, 1),
                "headline": view["status"]["headline"],
                "status": view["status"]["kind"],
                "tests": run.test_summary if run else {},
                "steps": [step_summary(s) for s in view["steps"]],
                "optional": [step_summary(s) for s in view["optional"]],
                "other": [s["title"] for s in view["other"]],
                "pending": len(view["pending"]),
                "search": searched,
                "issues": [
                    {
                        "title": i.title[:160],
                        "tool": i.tool,
                        "kind": i.kind,
                        "diagnosis": i.diagnosis,
                        "source": i.diagnosis_source,
                        "rule": i.diagnosis_rule,
                    }
                    for i in session.issues
                    if i.status in ("open", "awaiting_verification")
                ][:40],
            }
        )
        first = view["steps"][0]["title"] if view["steps"] else "(no must-fix step)"
        print(f"   {view['status']['headline']} | first step: {first}", flush=True)
    output = Path(args.output)
    previous = json.loads(output.read_text("utf-8")) if output.exists() and args.only else []
    merged = {r["id"]: r for r in previous} | {r["id"]: r for r in results}
    output.write_text(json.dumps(list(merged.values()), indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"\nSaved {output}. Browse with: fixfirst --store {store.root} serve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
