"""Start a participant terminal in one prepared task and its own .venv.

Usage: python experiments/user_study/open_task.py TARGET TASK

Run before the timer starts, for both study conditions. The child shell does not
load user profiles; type exit to return to the experimenter's terminal. Grading
uses the same clean starting environment, independently of later shell changes.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from prepare import TASKS, task_environment, venv_python


def interactive_shell() -> list[str]:
    if os.name == "nt":
        shell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if shell:
            return [shell, "-NoLogo", "-NoProfile"]
    else:
        shell = shutil.which("bash")
        if shell:
            return [shell, "--noprofile", "--norc", "-i"]
    raise SystemExit("No supported shell found (PowerShell on Windows; bash on macOS/Linux)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("target", help="the folder given to prepare.py")
    parser.add_argument("task", choices=list(TASKS))
    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    manifest = target / ".study" / "manifest.json"
    if not manifest.exists():
        raise SystemExit(f"Nothing prepared in {target}; run prepare.py first")
    task = json.loads(manifest.read_text(encoding="utf-8"))["tasks"].get(args.task)
    if task is None:
        raise SystemExit(f"{args.task} was not prepared in {target}")
    folder = target / task["folder"]
    python = venv_python(folder)
    if not python.is_file():
        raise SystemExit(f"The task's Python is missing: {python}; run prepare.py again")
    print(f"Task: {args.task}\nProject: {folder}\nPython: {python}", flush=True)
    print("Use python -m pytest and python -m pip in this terminal. Type exit when finished.", flush=True)
    env = task_environment(folder)
    env["BASH_SILENCE_DEPRECATION_WARNING"] = "1"
    return subprocess.run(interactive_shell(), cwd=folder, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
