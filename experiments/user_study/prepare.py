"""Build fresh copies of the four user-study tasks, each with its own environment (task B8).

Usage: python experiments/user_study/prepare.py TARGET [--only T1 ...] [--self-test]

Run it before every participant: it rebuilds TARGET/T1-report ... TARGET/T4-booking from
experiments/user_study/tasks, installs each task's pinned packages into its own .venv (the
first run downloads them; pip caches them afterwards) and records in TARGET/.study what
grade.py checks. It never deletes a folder it did not create.

--self-test then checks that grade.py fails every fresh task, applies the reference solutions
(solutions.py) and checks that grade.py passes them. The copies are left fixed, so run
prepare.py again before a participant.

Needs Python 3.12 or newer: task T3 relies on a module that Python 3.12 removed.
"""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PYTEST = "pytest==9.1.1"
TASKS = {
    "T1": {"folder": "T1-report", "set": "A", "packages": ["Jinja2==3.1.6", PYTEST], "tests": 4},
    "T2": {"folder": "T2-inventory", "set": "A", "packages": [PYTEST], "tests": 5},
    "T3": {"folder": "T3-versions", "set": "B", "packages": [PYTEST], "tests": 4},
    "T4": {"folder": "T4-booking", "set": "B", "packages": [PYTEST], "tests": 4},
}
MARKER = ".study-task"

# Keep OS, locale, terminal and network settings, not a participant's Python/pytest
# overrides or application variables. Used by both the participant shell and grader.
SYSTEM_ENV = set("""
PATH HOME USER LOGNAME SHELL TMPDIR TMP TEMP
SYSTEMROOT WINDIR SYSTEMDRIVE COMSPEC PATHEXT USERPROFILE HOMEDRIVE HOMEPATH
APPDATA LOCALAPPDATA PROGRAMDATA PROGRAMFILES PROGRAMFILES(X86)
COMMONPROGRAMFILES COMMONPROGRAMFILES(X86) PROCESSOR_ARCHITECTURE NUMBER_OF_PROCESSORS
TERM COLORTERM TERM_PROGRAM COLUMNS LINES LANG LANGUAGE
HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY SSL_CERT_FILE SSL_CERT_DIR
REQUESTS_CA_BUNDLE CURL_CA_BUNDLE
""".split())


def venv_python(folder: Path) -> Path:
    return folder / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def task_environment(folder: Path, environ=None) -> dict[str, str]:
    """A fresh task terminal: preserve system settings, bind Python/pip to this task."""
    source = os.environ if environ is None else environ
    env = {key: value for key, value in source.items()
           if (key.upper() in SYSTEM_ENV or key.upper().startswith("LC_"))
           and key.upper() != "PATH"}
    inherited_path = next((value for key, value in source.items() if key.upper() == "PATH"), os.defpath)
    python = venv_python(folder)
    env["PATH"] = str(python.parent) + os.pathsep + inherited_path
    env["VIRTUAL_ENV"] = str(python.parent.parent)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def fingerprint(folder: Path) -> dict:
    """SHA-256 of every file under tests/, by relative path."""
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((folder / "tests").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def build(target: Path, task_id: str) -> dict:
    task = TASKS[task_id]
    folder = target / task["folder"]
    if folder.exists():
        if not (folder / MARKER).exists():
            raise SystemExit(f"{folder} exists and was not made by prepare.py; move it away first")
        shutil.rmtree(folder)
    shutil.copytree(HERE / "tasks" / task["folder"], folder,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    (folder / MARKER).write_text(f"User study task {task_id}: prepare.py deletes and rebuilds this folder.\n",
                                 encoding="utf-8")
    print(f"== {task_id} {task['folder']}: creating .venv and installing {' '.join(task['packages'])}", flush=True)
    subprocess.run([sys.executable, "-m", "venv", str(folder / ".venv")], check=True)
    subprocess.run([str(venv_python(folder)), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                    *task["packages"]], check=True)
    return {"folder": task["folder"], "set": task["set"], "expected_tests": task["tests"],
            "tests": fingerprint(folder)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("target", help="folder for the task copies, e.g. C:\\study or ~/study")
    parser.add_argument("--only", nargs="*", choices=list(TASKS), default=[])
    parser.add_argument("--self-test", action="store_true", help="check that every task fails, then passes when fixed")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise SystemExit("Use Python 3.12 or newer (task T3 relies on a module that Python 3.12 removed)")
    target = Path(args.target).expanduser().resolve()
    (target / ".study").mkdir(parents=True, exist_ok=True)
    manifest_file = target / ".study" / "manifest.json"
    manifest = json.loads(manifest_file.read_text("utf-8")) if manifest_file.exists() else {"tasks": {}}
    for task_id in args.only or list(TASKS):
        manifest["tasks"][task_id] = build(target, task_id)
    manifest["python"] = sys.version.split()[0]
    manifest["prepared"] = datetime.now().astimezone().isoformat(timespec="seconds")
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nReady in {target}.")
    if not args.self_test:
        print(f"Each task should now fail: python {Path(__file__).with_name('grade.py')} {target} T1")
        return 0

    from grade import grade
    from solutions import FIXES

    ok = True
    for task_id in args.only or list(TASKS):
        before, why = grade(target, task_id)
        FIXES[task_id](target / TASKS[task_id]["folder"])
        after, summary = grade(target, task_id)
        good = not before and after
        ok &= good
        print(f"{task_id}: fresh copy {'PASS' if before else 'FAIL'} ({why}); "
              f"with the reference fix {'PASS' if after else 'FAIL'} ({summary}) -> {'as expected' if good else 'PROBLEM'}")
    print("\nSelf-test passed. Run prepare.py again before a participant." if ok else "\nSelf-test found a problem.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
