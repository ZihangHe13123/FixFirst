"""Execute FixFirst's actual first action on public development project copies.

The supplied specifications identify the failure layer, never the repair. Commands
come from the generated Action. An explicitly offered editable-install alternative
is recorded as a manual interpretation; inspections and their next action are separate.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import time

from verify_real import ROOT, digest, iso, rc, runtimes, scrub


CHECK = '''import json, sys
from pathlib import Path
from fixfirst.service import create_session, scan
from fixfirst.models import Session
from fixfirst.reasoning import diagnose
from fixfirst.workspace import build_view
mode, root, python, output, saved = sys.argv[1:]
if mode == "inspect":
    s = Session.model_validate_json(Path(saved).read_text())
    step = build_view(s)["steps"][0]
    action = next(a for a in s.actions if a.action_id == step["id"])
    scan(s, [action.check], targets=action.targets)
else:
    s = create_session(Path(root), python, goal="collect_tests" if mode == "collect" else "pass_tests")
    scan(s, ["environment", "project", "pytest" if mode == "collect" else "pytest_run"], timeout=120)
details = diagnose(s)
Path(output).write_text(json.dumps({"session": s.model_dump(), "view": build_view(s),
    "evidence": {key:{k:v["evidence"].get(k) for k in ("exception", "message", "where")}
                 for key,v in details.items() if "features" in v["evidence"]}}, ensure_ascii=False))
'''


def verify(spec, project, source, root):
    root.mkdir(parents=True, exist_ok=False)
    folder, state, tmp = root / "project", root / "state", root / "tmp"
    state.mkdir()
    tmp.mkdir()
    record = {"id": project["id"], "steps": [], "label": spec["label"], "source_commit": rc.source_commit(source)}
    rc.export_source(source, record["source_commit"], folder)
    snapshot = ROOT / "examples/real-world/environments" / (project["id"] + ".txt")
    record["snapshot_sha256"] = digest(snapshot)
    python = rc.create_environment(folder, project, snapshot, record["steps"])
    owner = iso.new_mark()
    interpreters = (*runtimes(python.parent.parent), *runtimes(Path(sys.executable).parent.parent))
    denied = (Path.home(), ROOT, root.parent, *iso.SYSTEM_TEMP)
    uv = Path(shutil.which("uv")).resolve()
    readable = (*interpreters, ROOT / "src")
    offline = iso.write_profile(iso.Policy((folder, state, tmp), readable, owner=owner), root / "offline.sb", denied)
    online = iso.write_profile(iso.Policy((folder, state, tmp), readable, True, (uv,), owner), root / "online.sb", denied)
    env = rc.clean_env(python, state, tmp)
    env["UV_CACHE_DIR"] = str(state / "uv-cache")
    script = state / "check.py"
    script.write_text(CHECK)

    def execute(argv, profile, name, timeout=180):
        start = time.monotonic()
        code, output, stopped = iso.execute(argv, folder, env, profile, timeout, owner)
        record["steps"].append({"step": name, "argv": list(map(str, argv)), "exit_code": code,
                                "seconds": round(time.monotonic() - start, 2), "stopped": stopped,
                                "output": output[-12000:]})
        return code

    def check(name, mode):
        destination = state / (name + ".json")
        code = execute([sys.executable, script, mode, folder, python, destination, state / "saved.json"],
                       online if mode == "inspect" else offline, name, 600 if mode == "inspect" else 150)
        if code or not destination.exists():
            raise RuntimeError(f"{name} did not produce a session")
        return json.loads(destination.read_text())

    def action(data):
        steps = data["view"]["steps"]
        return next((a for a in data["session"]["actions"] if steps and a["action_id"] == steps[0]["id"]), None)

    try:
        for argv in rc.install_commands(project, python, state / "uv-cache"):
            execute(argv, online, "install-project")
        before = check("before", "run")
        record["before"] = before
        selected = [key for key, e in before["evidence"].items() if re.search(spec["pattern"], e["message"] or "")]
        first = action(before)
        record["first_action"] = first
        if spec["label"] == "healthy":
            record.update(outcome="healthy" if not first and before["session"]["goal_status"] == "achieved" else "unexpected_finding")
            return record
        if not selected or not first:
            record["outcome"] = "expected_failure_or_action_missing"
            return record
        record["selected_issues"] = selected
        integrity = rc.integrity(folder)
        if first["kind"] == "inspect":
            if first["check"] != "version_search":
                record["outcome"] = "inspection_not_implemented"
                return record
            (state / "saved.json").write_text(json.dumps(before["session"]))
            inspected = check("inspection", "inspect")
            record["inspection"] = inspected
            first = action(inspected)
            record["action_after_inspection"] = first
            if not first or first["check"] == "version_search" or first["action_id"].startswith("review-search-"):
                record["outcome"] = "inspection_inconclusive"
                return record
        if not first:
            record["outcome"] = "no_action_after_inspection"
            return record
        argv = first["command"]
        if argv:
            if argv[:4] != [str(python), "-m", "pip", "install"]:
                raise ValueError("Unexpected generated command; inspect it before extending this audit")
            record["execution_source"] = "generated_action_command"
        elif "pip install -e ." in first["explanation"]:
            argv = [str(python), "-m", "pip", "install", "-e", "."]
            record["execution_source"] = "explicit_editable_install_alternative_in_action_text"
        else:
            record["outcome"] = "manual_action_requires_interpretation"
            return record
        if execute(argv, online, "generated-repair"):
            record["outcome"] = "generated_command_failed"
            return record
        mode = "collect" if spec.get("verify_collection_only") else "run"
        after = check("after", mode)
        record["after"] = after
        record["test_changes"] = rc.changed(integrity, rc.integrity(folder))
        remaining = [key for key, e in after["evidence"].items() if re.search(spec["pattern"], e["message"] or "")]
        run = next(r for r in reversed(after["session"]["runs"]) if r["tool"] == ("pytest" if mode == "collect" else "pytest_run"))
        # A new collection blocker is not successful verification of a runtime repair.
        reached = run["verified_pass"] if mode == "collect" else (
            run["status"] == "completed" and run["exit_code"] in (0, 1)
            and bool(run.get("test_summary", {}).get("passed", 0) + run.get("test_summary", {}).get("failed", 0)))
        resolved = not remaining and reached and not record["test_changes"]
        record.update(outcome="first_failure_resolved" if resolved else "first_step_not_verified",
                      verification_scope="test_collection" if mode == "collect" else "test_execution",
                      target_error_remaining=bool(remaining), reached_tests=bool(reached),
                      after_fully_passed=mode == "run" and after["session"]["goal_status"] == "achieved")
        return record
    finally:
        record["cleanup"] = iso.stop(owner)
        if record["cleanup"]["error"]:
            record["outcome"] = "cleanup_failed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    specs = json.loads(Path(__file__).with_name("real_cases.json").read_text())["cases"]
    projects = rc.load_manifest(ROOT / "examples/real-world/projects.toml")
    for spec in specs:
        name = spec["id"]
        if args.only and name not in args.only:
            continue
        print(name + ": verifying generated first action", flush=True)
        try:
            record = verify(spec, projects[name], args.sources.resolve() / name, output / name)
        except Exception as exc:
            record = {"id": name, "outcome": "audit_error", "error": f"{type(exc).__name__}: {exc}"}
        public = scrub(record, output)
        (output / (name + ".json")).write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n")
        print({k: public.get(k) for k in ("id", "outcome", "verification_scope", "error")}, flush=True)


if __name__ == "__main__":
    main()
