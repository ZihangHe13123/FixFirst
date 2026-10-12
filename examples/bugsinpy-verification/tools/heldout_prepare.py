#!/usr/bin/env python3
"""Prepare the held-out bugs for the next version: reproduction only, the product is never run.

    heldout_prepare.py TREE WORK SEALED

Written on 2026-10-09 (registry addendum 88, where the rule is fixed before this is run). For the three BugsInPy
projects not used so far (fastapi, httpie, thefuck) the bugs are tried in ascending number with the frozen tree's
own scripts/bugsinpy_case.py and --no-fixfirst, on Python 3.9.6, until eight of a project reproduce (the bug's test
fails on the buggy source and passes with the patch applied again) or the project's bugs are used up.
Per bug at most two sets of test packages, as amended in registry addendum 89 after the sets of addendum 88 could
not install any of the three projects (old setup.py and flit metadata, an old test-server plugin):
  1  thefuck: pytest mock pytest-mock, with setuptools below 70 and wheel;
     fastapi: pytest requests, with flit and flit_core below 4;
     httpie:  the versions BugsInPy pins for the bug's test stack (pytest, pytest-httpbin, httpbin, Flask, Werkzeug,
              Jinja2, MarkupSafe, itsdangerous), mock, with setuptools below 70 and wheel;
     the project itself is installed without build isolation, so that these build tools are the ones used;
  2  only if 1 did not reproduce and something can be added: set 1 with BugsInPy's pytest pin where set 1 left
     pytest open, one package for every module the test output of attempt 1 reports as missing, and for fastapi
     the pydantic version BugsInPy pins for that bug.
The console output of every attempt is kept in WORK/logs.
Every attempt is written to SEALED/attempts.csv; for a reproduced bug the script's record, the two test outputs
and the patch are copied to SEALED/results, and SEALED/SELECTION.json lists the selected bugs with the packages
used and the versions that were installed. WORK holds the checkouts and environments and can be thrown away.
"""
import concurrent.futures
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

tree, work, sealed = (Path(p).resolve() for p in sys.argv[1:4])
sys.path.insert(0, str(tree / "scripts"))
from collect_public_data import BUGSINPY_COMMIT, BUGSINPY_REPO, fetch, raw_url  # noqa: E402

PROJECTS = {"fastapi": (16, ["pytest", "requests", "flit<4", "flit_core<4"]), "httpie": (5, None), "thefuck": (32, ["pytest", "mock", "pytest-mock", "setuptools<70", "wheel"])}
HTTPIE_STACK = ("pytest", "pytest-httpbin", "httpbin", "Flask", "Werkzeug", "Jinja2", "MarkupSafe", "itsdangerous")
WANTED = 8
PACKAGE_OF = {"yaml": "pyyaml", "multipart": "python-multipart", "email_validator": "email-validator", "jwt": "pyjwt", "async_generator": "async-generator",
              "async_exit_stack": "async-exit-stack", "pytest_httpbin": "pytest-httpbin", "pytest_mock": "pytest-mock", "pytest_benchmark": "pytest-benchmark",
              "databases": "databases[sqlite]", "dateutil": "python-dateutil", "bs4": "beautifulsoup4", "OpenSSL": "pyopenssl"}
CACHE = tree / "workbench" / "public-data-cache"
env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "DJANGO_SETTINGS_MODULE", "PYTEST_ADDOPTS", "FIXFIRST_STORE")}
env["PYTHONDONTWRITEBYTECODE"] = "1"
(sealed / "results").mkdir(parents=True, exist_ok=True)
work.mkdir(parents=True, exist_ok=True)


def pinned(project, bug, name):
    data = fetch(raw_url(BUGSINPY_REPO, BUGSINPY_COMMIT, f"projects/{project}/bugs/{bug}/requirements.txt"), CACHE)
    if not data:
        return None
    text = data.decode("utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else data.decode("utf-8", "replace")
    for line in text.splitlines():
        if line.strip().lower().startswith(name.lower() + "=="):
            return line.strip().split("==", 1)[1]
    return None


def first_set(project, bug):
    if project != "httpie":
        return list(PROJECTS[project][1])
    return [f"{name}=={version}" for name in HTTPIE_STACK if (version := pinned(project, bug, name))] + ["mock", "setuptools<70", "wheel"]


def attempt(project, bug, deps, number=1):
    target = work / project
    case = f"{project}-{bug}"
    record_path = target / "results" / f"{case}.json"
    if record_path.exists():
        record_path.unlink()
    started = time.monotonic()
    done = subprocess.run([str(tree / ".venv/bin/python"), str(tree / "scripts/bugsinpy_case.py"), project, str(bug), "--target", str(target), "--python", "3.9.6",
                           "--deps", *deps, "--no-build-isolation", "--no-fixfirst"], cwd=tree, env=env, capture_output=True, text=True, timeout=2400)
    (work / "logs").mkdir(exist_ok=True)
    (work / "logs" / f"{case}-attempt-{number}.txt").write_text(" ".join(deps) + "\n" + done.stdout[-6000:] + "\n--- stderr\n" + done.stderr[-6000:], encoding="utf-8")
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    if "fixfirst_before" in record or "fixfirst_session" in record:
        raise SystemExit(f"{case}: the product was run; this must not happen in the preparation")
    codes = (record.get("buggy_test_exit_code"), record.get("fixed_test_exit_code"))
    if record.get("reproduced"):
        result, note = "reproduced", ""
    elif str(record.get("result", "")).startswith("install failed"):
        result, note = "error", record["result"]
    elif record:
        result, note = ("error" if codes[0] in (2, 3, 4, 5) else "not reproduced"), f"exit codes {codes[0]} and {codes[1]}"
    else:
        last = [line for line in (done.stdout + done.stderr).strip().splitlines() if line.strip()][-1:] or ["no output"]
        result, note = "unavailable", last[0][:200]
    outputs = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (target / "results").glob(f"{case}-*-test.txt"))
    missing = sorted({m.split(".")[0] for m in re.findall(r"No module named '?([\w\.]+)'?", outputs)})
    return {"case": case, "deps": deps, "result": result, "note": note, "record": record, "missing": missing, "seconds": round(time.monotonic() - started), "target": target}


def project_stream(project):
    count = PROJECTS[project][0]
    attempts, selected = [], []
    for bug in range(1, count + 1):
        if len(selected) >= WANTED:
            break
        default = first_set(project, bug)
        first = attempt(project, bug, default)
        attempts.append(first)
        final = first
        if first["result"] != "reproduced" and first["result"] != "unavailable":
            pytest_pin = pinned(project, bug, "pytest")
            second_deps = [f"pytest=={pytest_pin}" if d == "pytest" and pytest_pin else d for d in default] + [PACKAGE_OF.get(m, m) for m in first["missing"] if m != project]
            if project == "fastapi" and (version := pinned(project, bug, "pydantic")):
                second_deps.append(f"pydantic=={version}")
            second_deps = list(dict.fromkeys(second_deps))
            if second_deps != default:
                final = attempt(project, bug, second_deps, number=2)
                attempts.append(final)
        print(f"{final['case']}: {final['result']} after {1 if final is first else 2} attempt(s) {final['note']}", flush=True)
        if final["result"] == "reproduced":
            case, target = final["case"], final["target"]
            for path in (target / "results").glob(f"{case}*"):
                shutil.copyfile(path, sealed / "results" / path.name)
            r = final["record"]
            selected.append({"case": case, "project": project, "bug": bug, "deps": final["deps"], "python": r.get("python"), "tests": r.get("tests"), "fixed_commit": r.get("fixed_commit"),
                             "patched_files": r.get("patched_files"), "installed": r.get("installed")})
    return attempts, selected


with concurrent.futures.ThreadPoolExecutor(3) as pool:
    outcome = dict(zip(PROJECTS, pool.map(project_stream, PROJECTS)))
with (sealed / "attempts.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.writer(stream)
    writer.writerow(["bug", "python", "deps", "result", "note"])
    for project in PROJECTS:
        for a in outcome[project][0]:
            writer.writerow([a["case"], a["record"].get("python", "3.9.6"), " ".join(a["deps"]), a["result"], a["note"]])
selection = {"rule": "registry addenda 88 and 89", "bugsinpy_commit": BUGSINPY_COMMIT, "selected": [s for project in PROJECTS for s in outcome[project][1]]}
(sealed / "SELECTION.json").write_text(json.dumps(selection, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print("tried per project: " + ", ".join(f"{p} {len({a['case'] for a in outcome[p][0]})} bugs in {len(outcome[p][0])} attempts" for p in PROJECTS))
print("selected per project: " + ", ".join(f"{p} {len(outcome[p][1])}" for p in PROJECTS) + f"; in all {len(selection['selected'])}")
print("SELECTION.json sha256 " + hashlib.sha256((sealed / "SELECTION.json").read_bytes()).hexdigest())
