"""Run the fixed public prerequisites using the FixFirst source on PYTHONPATH.

Only exact product edits are applied; no values or replacement names are guessed.
This is a public prerequisite, not independent acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


ROOT = Path(__file__).resolve().parent


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts
            and ".pytest_cache" not in p.parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a fresh output directory")
    args.output.mkdir(parents=True)
    manifest = json.loads((ROOT / "public-manifest.json").read_text())
    rows = []
    for case in manifest["cases"]:
        folder = args.output / case["id"]
        project = folder / "project"
        shutil.copytree(ROOT / "public" / case["id"], project)
        assert hashes(project) == case["file_sha256"]
        started = time.monotonic()
        session = create_session(project, sys.executable, goal="pass_tests")
        first = None
        applied = []
        for round_number in range(1, 11):
            if time.monotonic() - started >= 3600:
                break
            scan(session, ["environment", "project", "pytest_run"] if round_number == 1 else ["pytest_run"])
            (folder / f"{round_number:02d}-session.json").write_text(session.model_dump_json(indent=2))
            view = build_view(session)
            if first is None:
                first = {"goal": session.goal_status, "issues": [i.model_dump() for i in session.issues],
                         "trace": session.inference_trace, "step": view["steps"][0] if view["steps"] else None}
            if session.goal_status == "achieved" or not view["steps"]:
                break
            action = next(a for a in session.actions if a.action_id == view["steps"][0]["id"])
            edits = re.findall(r"([^\s`:]+):(\d+): replace `([^`]+)` with `([^`]+)`", action.explanation)
            if len(edits) != 1 or action.command or action.check or action.blocked_reasons:
                break
            path, line, old, new = edits[0]
            file = (project / path).resolve()
            if project.resolve() not in file.parents or file.name.startswith("test") or file.name == "conftest.py":
                raise AssertionError("Product suggested changing original tests or a path outside the project")
            lines = file.read_text().splitlines(keepends=True)
            offset = int(line) - 1
            if offset >= len(lines) or lines[offset].strip() != old:
                break
            if (path, old, new) in applied:
                break
            indent = lines[offset][:len(lines[offset]) - len(lines[offset].lstrip())]
            lines[offset] = indent + new + "\n"
            file.write_text("".join(lines))
            applied.append((path, old, new))
        untouched = all(hashes(project)[p] == value for p, value in case["file_sha256"].items()
                        if p.startswith("test") or p == "conftest.py")
        assert untouched
        row = {"id": case["id"], "role": case["role"], "first": first, "edits_applied": applied,
               "original_tests_unchanged": untouched, "final_goal": session.goal_status,
               "rounds": round_number, "duration_seconds": round(time.monotonic() - started, 3)}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("id", "role", "final_goal", "rounds", "edits_applied")}), flush=True)
    result = {"scope": "Public prerequisite real executions, not independent performance", "tasks": rows,
              "python": sys.version, "source": __import__("fixfirst").__file__}
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
