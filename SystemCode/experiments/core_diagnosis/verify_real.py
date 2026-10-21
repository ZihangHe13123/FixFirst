"""Reproduce public development faults and verify repairs in disposable copies.

Only projects listed in the existing public real-world manifest are eligible. Each
copy has its own environment rebuilt from the recorded pins. Project installation,
checks and repair run with the existing macOS sandbox policy. Source checkouts and
their environments are never executed or written. Labels come from the supplied
review specification, not FixFirst's predictions; human rereview remains explicit.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/agent_baseline"))
import isolation as iso  # noqa: E402
import real_cases as rc  # noqa: E402


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtimes(venv):
    return (venv, *map(Path, rc.venv_record(venv)["interpreters"]))


def scrub(value, folder):
    text = json.dumps(value, ensure_ascii=False)
    for old, new in ((str(folder), "/run"), (str(ROOT), "/fixfirst"),
                     (str(Path.home()), "/home/user")):
        text = text.replace(old, new)
    return json.loads(text)


def check_script():
    return '''import json, sys
from pathlib import Path
from fixfirst.service import create_session, scan
from fixfirst.diagnosis_cases import portable
from fixfirst.reasoning import diagnose
from fixfirst.workspace import build_view
collect = sys.argv[4] == "collect"
s = create_session(Path(sys.argv[1]), sys.argv[2], goal="collect_tests" if collect else "pass_tests")
scan(s, ["environment", "project", "pytest" if collect else "pytest_run"])
details = diagnose(s)
data, env = portable(s, Path(sys.argv[1]))
data["environment"] = {**env, **{k:v for k,v in data["environment"].items() if k.startswith("_")}}
record = {"session": data, "evidence": {key: {"exception":v["evidence"].get("exception"),
    "message":v["evidence"].get("message", ""), "where":v["evidence"].get("where", "")}
    for key,v in details.items() if "features" in v["evidence"]},
    "first_step": (build_view(s)["steps"] or [{}])[0].get("title"),
    "goal_status":s.goal_status}
Path(sys.argv[3]).write_text(json.dumps(record, ensure_ascii=False))
'''


def verify(spec, project, source, root):
    root.mkdir(parents=True, exist_ok=False)
    folder, state, tmp = root / "project", root / "state", root / "tmp"
    state.mkdir()
    tmp.mkdir()
    owner = iso.new_mark()
    record = {"id": project["id"], "label": spec["label"], "pattern": spec["pattern"],
              "repair": spec["repair"], "explanation": spec["explanation"], "steps": []}
    commit = rc.source_commit(source)
    record["source_commit"] = commit
    rc.export_source(source, commit, folder)
    snapshot = ROOT / "examples/real-world/environments" / (project["id"] + ".txt")
    record["snapshot_sha256"] = digest(snapshot)
    python = rc.create_environment(folder, project, snapshot, record["steps"])
    interpreters = (*runtimes(python.parent.parent), *runtimes(Path(sys.executable).parent.parent))
    readable = (*interpreters, ROOT / "src")
    denied = (Path.home(), ROOT, root.parent, *iso.SYSTEM_TEMP)
    uv = Path(shutil.which("uv")).resolve()
    offline = iso.write_profile(iso.Policy((folder, state, tmp), readable, owner=owner), root / "offline.sb", denied)
    online = iso.write_profile(iso.Policy((folder, state, tmp), readable, True, (uv,), owner), root / "online.sb", denied)
    env = rc.clean_env(python, state, tmp)
    env["UV_CACHE_DIR"] = str(state / "uv-cache")
    script = state / "check.py"
    script.write_text(check_script())

    def execute(argv, profile, step, timeout=300):
        started = time.monotonic()
        code, output, stopped = iso.execute(argv, folder, env, profile, timeout, owner)
        record["steps"].append({"step": step, "argv": [str(a) for a in argv], "exit_code": code,
                                "seconds": round(time.monotonic() - started, 2), "stopped": stopped,
                                "output": output[-12000:]})
        return code

    def check(name, collection=False):
        path = state / (name + ".json")
        code = execute([sys.executable, script, folder, python, path, "collect" if collection else "run"], offline, name)
        if code or not path.exists():
            raise RuntimeError(f"{name} checks failed to produce a session")
        return json.loads(path.read_text())

    try:
        for argv in rc.install_commands(project, python, state / "uv-cache"):
            execute(argv, online, "install-project")  # some documented scenarios expect installation failure
        before = check("before")
        record["before"] = before
        matches = [key for key, e in before["evidence"].items() if re.search(spec["pattern"], e["message"])]
        if spec["label"] == "healthy":
            record["accepted"] = before["goal_status"] == "achieved" and not before["evidence"]
            record["verification"] = "healthy_control"
            return record
        if not matches:
            record.update(accepted=False, verification="expected_failure_not_observed")
            return record
        hashes = {str(p.relative_to(folder)): digest(p) for p in folder.rglob("*.py")
                  if ".venv" not in p.parts and (p.name.startswith("test") or "tests" in p.parts or p.name == "conftest.py")}
        if spec.get("source_repair"):
            repair = spec["source_repair"]
            path = folder / repair["path"]
            if not path.resolve().is_relative_to(folder) or repair["path"] in hashes:
                raise ValueError("Source repair must stay in application code")
            original = path.read_text()
            if original.count(repair["old"]) != 1:
                raise ValueError("Source repair did not find exactly one occurrence")
            path.write_text(original.replace(repair["old"], repair["new"]))
            record["source_repair"] = repair
        elif spec["repair"]:
            argv = [str(uv), "pip", "install", "--no-config", "--python", str(python), *spec["repair"]]
            if execute(argv, online, "repair"):
                record.update(accepted=False, verification="repair_failed")
                return record
        collection = bool(spec.get("verify_collection_only"))
        after = check("after", collection)
        record["after"] = after
        remaining = [key for key, e in after["evidence"].items() if re.search(spec["pattern"], e["message"])]
        unchanged = all((folder / name).is_file() and digest(folder / name) == value for name, value in hashes.items())
        tool = "pytest" if collection else "pytest_run"
        run = next((r for r in reversed(after["session"]["runs"]) if r["tool"] == tool), {})
        meaningful = (run.get("verified_pass") if collection else
                      run.get("exit_code") in (0, 1, 2) and (after["evidence"] or after["goal_status"] == "achieved"))
        accepted = bool(not remaining and unchanged and meaningful)
        record.update(accepted=accepted,
                      verification="first_failure_resolved" if accepted else "verification_incomplete",
                      verification_scope="test_collection" if collection else "test_execution",
                      tests_unchanged=unchanged, labelled_issue_ids=matches[:1],
                      after_fully_passed=not collection and after["goal_status"] == "achieved")
        return record
    finally:
        cleanup = iso.stop(owner)
        record["cleanup"] = cleanup
        if cleanup["error"]:
            record["accepted"] = False
            record["verification"] = "cleanup_failed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    specs = json.loads((Path(__file__).with_name("real_cases.json")).read_text())
    projects = rc.load_manifest(ROOT / "examples/real-world/projects.toml")
    records = []
    for spec in specs["cases"]:
        name = spec["id"]
        if args.only and name not in args.only:
            continue
        print(f"{name}: preparing isolated development copy", flush=True)
        try:
            row = verify(spec, projects[name], args.sources.resolve() / name, output / name)
        except Exception as exc:
            row = {"id": name, "accepted": False, "verification": "setup_or_check_error", "error": f"{type(exc).__name__}: {exc}"}
        public = scrub(row, output)
        (output / (name + ".json")).write_text(json.dumps(public, ensure_ascii=False, indent=2))
        records.append({k: public.get(k) for k in ("id", "accepted", "verification", "after_fully_passed", "error")})
        print(records[-1], flush=True)
        (output / "summary.json").write_text(json.dumps({"review_status": specs["review_status"], "cases": records}, indent=2))


if __name__ == "__main__":
    main()
