#!/usr/bin/env python3
"""B12 phase 2: the frozen product on the BugsInPy bugs that reproduced in phase 1. No model.

    b12_phase2.py TREE TARGET [--only CASE ...]

Written on 2026-10-09 (registry addendum 86). Runs the frozen tree's own scripts/bugsinpy_case.py (written on
2026-09-29, before the product was run on any of these bugs but PySnooper 2) for the 28 bugs that phase 1 lists as
reproduced, with the test packages phase 1 found and the interpreter phase 1 used (Python 3.9.6). The product is the
one of TREE (its src/ is what the script imports); TARGET gets one folder per stream so that their stores do not
meet. Four streams run side by side, each one bug after the other. Every bug's console lines go to TARGET/logs.
"""
import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path

argv = sys.argv[1:]
only = []
if "--only" in argv:
    at = argv.index("--only")
    only = argv[at + 1:]
    del argv[at:]
tree, target = Path(argv[0]).resolve(), Path(argv[1]).resolve()
TQDM, COOKIE_COV, COOKIE, NEW, OLD, SNOOP = (["pytest", "nose"], ["pytest", "pytest-mock", "freezegun", "pytest-cov"], ["pytest", "pytest-mock", "freezegun"],
                                              ["pytest"], ["pytest<8"], ["pytest", "python_toolbox", "six"])
CASES = ([("tqdm", n, TQDM, "a") for n in range(1, 10)]
         + [("cookiecutter", 2, COOKIE_COV, "b"), ("cookiecutter", 3, COOKIE_COV, "b"), ("cookiecutter", 4, COOKIE, "b"), ("PySnooper", 2, SNOOP, "b")]
         + [("tornado", n, NEW if n in (5, 6, 9, 14) else OLD, "c" if n <= 9 else "d") for n in (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)])
(target / "logs").mkdir(parents=True, exist_ok=True)
env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "DJANGO_SETTINGS_MODULE", "PYTEST_ADDOPTS", "FIXFIRST_STORE")}
env["PYTHONDONTWRITEBYTECODE"] = "1"


def stream(name):
    lines = []
    for project, bug, deps, where in CASES:
        case = f"{project}-{bug}"
        if where != name or (only and case not in only):
            continue
        started = time.monotonic()
        done = subprocess.run([str(tree / ".venv/bin/python"), str(tree / "scripts/bugsinpy_case.py"), project, str(bug), "--target", str(target / name),
                               "--python", "3.9.6", "--deps", *deps], cwd=tree, env=env, capture_output=True, text=True, timeout=7200)
        (target / "logs" / f"{case}.txt").write_text(done.stdout + "\n--- stderr\n" + done.stderr[-4000:])
        lines.append(f"{case}: exit {done.returncode}, {time.monotonic() - started:.0f} s")
        print(lines[-1], flush=True)
    return lines


with concurrent.futures.ThreadPoolExecutor(4) as pool:
    results = list(pool.map(stream, "abcd"))
print(f"{sum(len(r) for r in results)} bugs run")
