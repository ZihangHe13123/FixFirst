#!/usr/bin/env python3
"""Prepare the third set of held-out bugs: reproduction only, the product is never run.

    heldout3_prepare.py TREE WORK SEALED

Written on 2026-10-10; the rule is fixed in registry addendum 121 before this is run. The projects are ones already
used, the bugs are ones never tried with the product: per project the bugs are tried in ascending number from the
first one after those of the earlier sets (ansible from 8, black from 6, luigi from 6, scrapy from 8, youtube-dl
from 6, thefuck from 9, fastapi from 10), with heldout2_case.py --mode none on Python 3.9.6, until four of a project
reproduce (the bug's tests exit 1 on the buggy source and 0 with the patch applied again), or the project's bugs
are used up, or ten were tried.
Per bug at most two sets of test packages, those that the earlier sets used for the project:
  1  ansible, scrapy, youtube-dl: pytest, setuptools below 70, wheel; black: these and setuptools_scm, aiohttp,
     aiohttp-cors; luigi: these and nose, mock; thefuck: these and mock, pytest-mock; fastapi: these and requests,
     flit and flit_core below 4;
  2  only if 1 did not reproduce and something can be added: set 1 with BugsInPy's pytest pin where set 1 left
     pytest open, one package for every module that the test outputs of attempt 1 report as missing (BugsInPy's
     pin for that package if it has one), and for fastapi BugsInPy's pydantic pin of that bug.
The project itself is installed without build isolation. Every attempt has a home directory of its own.
Every attempt is written to SEALED/attempts.csv; for a reproduced bug the record, the two test outputs and the
patch are copied to SEALED/results, and SEALED/SELECTION.json lists the selected bugs with the packages used and
the versions that were installed. The console output of every attempt is kept in WORK/logs. WORK holds the
checkouts and environments and can be thrown away.
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

HERE = Path(__file__).resolve().parent
BASE = ["pytest", "setuptools<70", "wheel"]
PROJECTS = {"ansible": BASE, "black": BASE + ["setuptools_scm", "aiohttp", "aiohttp-cors"], "luigi": ["pytest", "nose", "mock", "setuptools<70", "wheel"],
            "scrapy": BASE, "youtube-dl": BASE, "thefuck": ["pytest", "mock", "pytest-mock", "setuptools<70", "wheel"],
            "fastapi": ["pytest", "requests", "flit<4", "flit_core<4", "setuptools<70", "wheel"]}
FIRST = {"ansible": 8, "black": 6, "luigi": 6, "scrapy": 8, "youtube-dl": 6, "thefuck": 9, "fastapi": 10}
WANTED, TRIED_AT_MOST = 4, 10
PACKAGE_OF = {"yaml": "pyyaml", "OpenSSL": "pyopenssl", "attr": "attrs", "dateutil": "python-dateutil", "daemon": "python-daemon", "PIL": "pillow",
              "Crypto": "pycryptodome", "bs4": "beautifulsoup4", "typed_ast": "typed-ast", "service_identity": "service-identity", "pydispatch": "PyDispatcher",
              "pytest_asyncio": "pytest-asyncio", "pytest_sanic": "pytest-sanic", "pytest_mock": "pytest-mock", "zope": "zope.interface", "jwt": "pyjwt",
              "psycopg2": "psycopg2-binary", "sklearn": "scikit-learn", "google": "protobuf", "pkg_resources": "setuptools<70"}
OWN = {"ansible": {"ansible", "units"}, "black": {"black", "blib2to3", "_black_version", "blackd"}, "luigi": {"luigi"}, "scrapy": {"scrapy"},
       "youtube-dl": {"youtube_dl"}, "thefuck": {"thefuck"}, "fastapi": {"fastapi"}}
CACHE = tree / "workbench" / "public-data-cache"
rows_csv = list(csv.DictReader((tree / "examples/public-data/bugsinpy/bugs.csv").open(newline="", encoding="utf-8")))
COUNT = {p: sum(r["project"] == p for r in rows_csv) for p in PROJECTS}
env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "DJANGO_SETTINGS_MODULE", "PYTEST_ADDOPTS", "FIXFIRST_STORE")}
env["PYTHONDONTWRITEBYTECODE"] = "1"
env["UV_CACHE_DIR"] = os.environ.get("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv"))
env["UV_PYTHON_INSTALL_DIR"] = os.environ.get("UV_PYTHON_INSTALL_DIR", str(Path.home() / ".local" / "share" / "uv" / "python"))
(sealed / "results").mkdir(parents=True, exist_ok=True)
(work / "logs").mkdir(parents=True, exist_ok=True)


def pins(project, bug):
    data = fetch(raw_url(BUGSINPY_REPO, BUGSINPY_COMMIT, f"projects/{project}/bugs/{bug}/requirements.txt"), CACHE)
    if not data:
        return {}
    text = data.decode("utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else data.decode("utf-8", "replace")
    found = {}
    for line in text.splitlines():
        if "==" in line and not line.strip().startswith("#"):
            name, version = line.strip().split("==", 1)
            found[name.strip().lower().replace("_", "-")] = version.split(";")[0].strip()
    return found


def attempt(project, bug, deps, number):
    target = work / project
    case = f"{project}-{bug}"
    record_path = target / "results" / f"{case}.json"
    if record_path.exists():
        record_path.unlink()
    for old in (target / "results").glob(f"{case}-*-test.txt") if (target / "results").exists() else []:
        old.unlink()
    home = work / "homes" / f"{case}-{number}"
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    started = time.monotonic()
    try:
        done = subprocess.run([str(tree / ".venv/bin/python"), str(HERE / "heldout2_case.py"), str(tree), project, str(bug), "--target", str(target), "--mode", "none",
                               "--python", "3.9.6", "--deps", *deps, "--no-build-isolation"], cwd=tree, env=dict(env, HOME=str(home)), capture_output=True, text=True, timeout=1500)
        console = done.stdout[-6000:] + "\n--- stderr\n" + done.stderr[-6000:]
    except subprocess.TimeoutExpired:
        console = "TIMEOUT after 1500 s"
    (work / "logs" / f"{case}-attempt-{number}.txt").write_text(" ".join(deps) + "\n" + console, encoding="utf-8")
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    if any(k.startswith("fixfirst") or k.startswith("product_error") for k in record):
        raise SystemExit(f"{case}: the product was run; this must not happen in the preparation")
    codes = (record.get("buggy_test_exit_code"), record.get("fixed_test_exit_code"))
    if record.get("reproduced"):
        result, note = "reproduced", ""
    elif record.get("result") == "install failed":
        result, note = "error", "install failed"
    elif record and codes[0] is not None:
        result, note = ("error" if codes[0] in (2, 3, 4, 5) else "not reproduced"), f"exit codes {codes[0]} and {codes[1]}"
    else:
        last = [line for line in console.strip().splitlines() if line.strip()][-1:] or ["no output"]
        result, note = "unavailable", last[0][:200]
    outputs = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (target / "results").glob(f"{case}-*-test.txt"))
    missing = sorted({m.split(".")[0] for m in re.findall(r"No module named '?([\w\.]+)'?", outputs)} - OWN[project])
    return {"case": case, "deps": deps, "result": result, "note": note, "record": record, "missing": missing, "seconds": round(time.monotonic() - started), "target": target}


def project_stream(project):
    attempts, selected, tried = [], [], 0
    for bug in range(FIRST[project], COUNT[project] + 1):
        if len(selected) >= WANTED or tried >= TRIED_AT_MOST:
            break
        tried += 1
        default = list(PROJECTS[project])
        first = attempt(project, bug, default, 1)
        attempts.append(first)
        final = first
        if first["result"] not in ("reproduced", "unavailable"):
            pinned = pins(project, bug)
            second = [f"pytest=={pinned['pytest']}" if d == "pytest" and "pytest" in pinned else d for d in default]
            for module in first["missing"]:
                name = PACKAGE_OF.get(module, module)
                key = name.lower().replace("_", "-")
                second.append(f"{name}=={pinned[key]}" if key in pinned else name)
            if project == "fastapi" and "pydantic" in pinned:
                second.append(f"pydantic=={pinned['pydantic']}")
            second = list(dict.fromkeys(second))
            if second != default:
                final = attempt(project, bug, second, 2)
                attempts.append(final)
        print(f"{final['case']}: {final['result']} after {1 if final is first else 2} attempt(s) {final['note']} ({sum(a['seconds'] for a in attempts if a['case'] == final['case'])} s)", flush=True)
        if final["result"] == "reproduced":
            case, target = final["case"], final["target"]
            for path in (target / "results").glob(f"{case}*"):
                shutil.copyfile(path, sealed / "results" / path.name)
            r = final["record"]
            selected.append({"case": case, "project": project, "bug": bug, "deps": final["deps"], "python": r.get("python"), "tests": r.get("tests"), "fixed_commit": r.get("fixed_commit"),
                             "patched_files": r.get("patched_files"), "installed": r.get("installed")})
    return attempts, selected


with concurrent.futures.ThreadPoolExecutor(len(PROJECTS)) as pool:
    outcome = dict(zip(PROJECTS, pool.map(project_stream, PROJECTS)))
with (sealed / "attempts.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.writer(stream)
    writer.writerow(["bug", "python", "deps", "result", "note"])
    for project in PROJECTS:
        for a in outcome[project][0]:
            writer.writerow([a["case"], a["record"].get("python", "3.9.6"), " ".join(a["deps"]), a["result"], a["note"]])
selection = {"rule": "registry addendum 121", "bugsinpy_commit": BUGSINPY_COMMIT, "selected": [s for project in PROJECTS for s in outcome[project][1]]}
(sealed / "SELECTION.json").write_text(json.dumps(selection, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print("tried per project: " + ", ".join(f"{p} {len({a['case'] for a in outcome[p][0]})} bugs in {len(outcome[p][0])} attempts" for p in PROJECTS))
print("selected per project: " + ", ".join(f"{p} {len(outcome[p][1])}" for p in PROJECTS) + f"; in all {len(selection['selected'])}")
print("SELECTION.json sha256 " + hashlib.sha256((sealed / "SELECTION.json").read_bytes()).hexdigest())
