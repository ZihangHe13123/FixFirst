"""Log one field-trial project: commands run, FixFirst scans and the operator's grading.

Every entry goes to RUNS/ID/log.jsonl with a timestamp, so the record is written as the trial
happens, not reconstructed afterwards. FixFirst is used through its own command line.

  python trial.py RUNS ID run -- COMMAND...     run in the work copy with the project's venv first on PATH
  python trial.py RUNS ID scan                  fixfirst scan, then log status, issues and the steps
  python trial.py RUNS ID note GRADE TEXT       grading or decision: complete|partial|generic|wrong|harmful|
                                                manual|assisted|deviation|blocked|done|info
  python trial.py RUNS ID diff                  log the work copy's changes against the original commit
"""

import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

FIXFIRST = os.environ.get("FIXFIRST_CLI", "fixfirst")


def log(folder: Path, entry: dict) -> None:
    entry = {"at": datetime.datetime.now().isoformat(timespec="seconds"), **entry}
    with (folder / "log.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def env_for(folder: Path) -> dict:
    env = dict(os.environ)
    venv = folder / "venv"
    env["VIRTUAL_ENV"] = str(venv)
    env["PATH"] = f"{venv / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    return env


def main(argv) -> int:
    runs, pid, command, rest = Path(argv[0]).resolve(), argv[1], argv[2], argv[3:]
    folder = runs / pid
    work = folder / "work"
    if command == "run":
        rest = rest[1:] if rest[:1] == ["--"] else rest
        done = subprocess.run(rest, cwd=work, env=env_for(folder), capture_output=True, text=True, timeout=3600)
        output = done.stdout + done.stderr
        log(folder, {"kind": "command", "argv": rest, "exit": done.returncode, "tail": output[-3000:]})
        print(output[-3000:])
        print(f"[exit {done.returncode}]")
        return 0
    if command == "scan":
        session = (folder / "session").read_text().strip()
        store = str(folder / "store")
        scan = subprocess.run([FIXFIRST, "--store", store, "scan", session], capture_output=True, text=True)
        view = subprocess.run([sys.executable, "-c", VIEW, store, session], capture_output=True, text=True)
        try:
            data = json.loads(view.stdout)
        except json.JSONDecodeError:
            data = {"error": view.stdout[-2000:] + view.stderr[-2000:]}
        log(folder, {"kind": "scan", "scan_exit": scan.returncode, "scan_tail": (scan.stdout + scan.stderr)[-1500:],
                     **data})
        print(json.dumps(data, indent=1, ensure_ascii=False)[:6000])
        return 0
    if command == "note":
        log(folder, {"kind": "note", "grade": rest[0], "text": " ".join(rest[1:])})
        return 0
    if command == "diff":
        diff = subprocess.run(["git", "diff", "--no-color"], cwd=work, capture_output=True, text=True).stdout
        untracked = subprocess.run(["git", "status", "--porcelain"], cwd=work, capture_output=True, text=True).stdout
        log(folder, {"kind": "diff", "diff": diff[-20000:], "status": untracked[-3000:]})
        print(diff[-6000:])
        print(untracked)
        return 0
    raise SystemExit(__doc__)


# Read the session through FixFirst's own view, as the web page and the CLI show it.
VIEW = """
import json, sys
from fixfirst.storage import Store
from fixfirst.workspace import build_view
from fixfirst.evidence import issue_evidence
store, sid = Store(sys.argv[1]), sys.argv[2]
session = store.load(sid)
view = build_view(session)
issues = [i for i in session.issues if i.status in ("open", "awaiting_verification")]
print(json.dumps({
    "status": view["status"].get("kind"), "headline": view["status"].get("headline"),
    "issues": [{"tool": i.tool, "title": i.title[:300], "diagnosis": i.diagnosis, "rule": i.diagnosis_rule,
                "source": i.diagnosis_source,
                "where": issue_evidence(session, i).get("where") if i.tool not in ("ruff", "pip_check") else ""}
               for i in issues][:12],
    "steps": [{k: s.get(k) for k in ("title", "explanation", "command", "cause", "possible", "where", "rules",
                                    "gather", "search")} for s in view["steps"][:3]],
    "optional": [s["title"] for s in view["optional"]][:6],
}, ensure_ascii=False))
"""

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
