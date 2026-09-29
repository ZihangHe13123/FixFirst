"""Judge one user-study task (task B8): PASS only when the unchanged test suite fully passes.

Usage: python experiments/user_study/grade.py TARGET TASK [--show]     e.g. grade.py C:\\study T1

Runs the task's tests with its own .venv, the way a fresh terminal would: variables set in the
participant's terminal do not count. The files under tests/ must be the ones prepare.py
created. PASS needs every expected test to pass; failures, errors, skips and missing tests all
count as FAIL. --show prints pytest's output as well.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepare import fingerprint, venv_python  # noqa: E402


def grade(target: Path, task_id: str, show: bool = False) -> tuple[bool, str]:
    manifest_file = target / ".study" / "manifest.json"
    if not manifest_file.exists():
        return False, f"nothing prepared in {target}; run prepare.py first"
    task = json.loads(manifest_file.read_text("utf-8"))["tasks"].get(task_id)
    if task is None:
        return False, f"{task_id} was not prepared in {target}"
    folder = target / task["folder"]
    if fingerprint(folder) != task["tests"]:
        return False, "files under tests/ were changed, added or deleted"
    python = venv_python(folder)
    if not python.exists():
        return False, "the task's .venv is missing; run prepare.py again"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(python.parent.parent)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        done = subprocess.run([str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=folder, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        return False, "the tests did not finish within 5 minutes"
    if show:
        print(done.stdout + done.stderr)
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    summary = lines[-1].strip("= ") if lines else "(no output)"
    counts = {word: int(number) for number, word in re.findall(r"(\d+) (\w+)", summary)}
    passed = counts.get("passed", 0)
    others = [word for word in counts if word not in ("passed", "warning", "warnings")]
    if done.returncode == 0 and passed == task["expected_tests"] and not others:
        return True, summary
    if passed != task["expected_tests"] and not others:
        summary += f" (expected {task['expected_tests']} passed)"
    return False, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("target", help="the folder given to prepare.py")
    parser.add_argument("task", choices=["T1", "T2", "T3", "T4"])
    parser.add_argument("--show", action="store_true", help="also print pytest's output")
    args = parser.parse_args()
    passed, detail = grade(Path(args.target).expanduser().resolve(), args.task, args.show)
    print(f"{'PASS' if passed else 'FAIL'} {args.task}: {detail}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
