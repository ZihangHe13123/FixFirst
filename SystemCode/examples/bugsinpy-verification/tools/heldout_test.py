#!/usr/bin/env python3
"""The held-out test of the next version: every selected bug with three uses of the product. No model.

    heldout_test.py OLD_TREE NEW_TREE SELECTION.json TARGET --phase prepare|run [--build-isolation] [--offline]
                    [--case-script FILE] [--mid TREE] [--only CASE ...] [--arms ARM ...]

Written on 2026-10-09 (registry addendum 96 c). SELECTION.json is the file of the preparation (heldout_prepare.py):
per bug the project, the number, the interpreter and the packages that were installed when it reproduced. The arms:
  old-default   the frozen version (OLD_TREE) as a user starts it: goal pass_tests, nothing else;
  new-scoped    the new version (NEW_TREE) with the tests of BugsInPy's run_test.sh named;
  new-default   the new version in the default use (reported besides the two above).
  mid-scoped    only with --mid TREE: a version between the two (TREE), with the tests named, to see what the
                newest version changes against the one before it.
--offline: the runs get no way to the outside network (the proxy variables point to a closed local port, with
localhost exempt, and uv is told to work offline). A project's whole test suite, which the default use runs, may
otherwise contact many outside hosts. Checkouts and environments have to exist already (a prepare without
--offline first); a prepare with --offline then shows that every bug still reproduces under this condition.
--case-script names the script that runs one bug (in this folder; default heldout_case.py; heldout2_case.py for the
second set, whose bug.info files the tree's own reader does not read).
Every arm has its own folder TARGET/<arm>/<project> with its own checkout, environment and store per bug, so that
nothing is shared. The environment of a bug is built from the versions SELECTION.json lists (all of them pinned),
the project itself installed without build isolation as in the preparation.
Every run also gets a home directory of its own, new and empty (TARGET/homes/<phase>/<arm>/<case>): a project's
tests may write to the home directory, which would let one run change another and leave files with the user
(seen on 2026-10-10 with another project, registry addendum 104). uv's cache and interpreter folders are pointed
to the real ones.
  --phase prepare   builds the checkouts and environments of every arm and reproduces the bug in each; the
                    product is not run. Can be repeated until every environment stands.
  --phase run       runs the product in every arm. This is the test; it is run once.
After either phase: per arm and bug, whether the bug reproduced there and whether the installed packages are the
ones of SELECTION.json. Console lines of every run go to TARGET/logs. A run in which the product raised an exception
keeps its record with the traceback; it is not repeated here. --only and --arms (both after the other arguments,
--arms last) limit a call to some bugs and arms, for a second attempt in another TARGET that is reported apart.
"""
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

argv = sys.argv[1:]
arms_wanted = []
if "--arms" in argv:
    at = argv.index("--arms")
    arms_wanted = argv[at + 1:]
    del argv[at:]
only = []
if "--only" in argv:
    at = argv.index("--only")
    only = argv[at + 1:]
    del argv[at:]
isolation = "--build-isolation" in argv
offline = "--offline" in argv
argv = [a for a in argv if a not in ("--build-isolation", "--offline")]
case_script, mid = "heldout_case.py", None
for option in ("--case-script", "--mid"):
    if option in argv:
        at = argv.index(option)
        if option == "--mid":
            mid = Path(argv[at + 1]).resolve()
        else:
            case_script = argv[at + 1]
        del argv[at:at + 2]
phase = argv[argv.index("--phase") + 1]
old, new, selection_path, target = (Path(p).resolve() for p in argv[:4])
assert phase in ("prepare", "run")
HERE = Path(__file__).resolve().parent
ARMS = [a for a in [("old-default", old, "default"), *([("mid-scoped", mid, "scoped")] if mid else []), ("new-scoped", new, "scoped"), ("new-default", new, "default")]
        if not arms_wanted or a[0] in arms_wanted]
selection = json.loads(selection_path.read_text(encoding="utf-8"))["selected"]
print(f"selection sha256 {hashlib.sha256(selection_path.read_bytes()).hexdigest()}: {len(selection)} bugs; phase {phase}{' (offline)' if offline else ''}; case script {case_script}; arms {[a[0] for a in ARMS]}")
for name in ("scripts/bugsinpy_case.py", "scripts/collect_public_data.py"):
    same = len({(t / name).read_bytes() for t in {old, new, *([mid] if mid else [])}}) == 1
    print(f"{name}: {'the same file in both trees' if same else 'DIFFERENT in the two trees'}")
    if not same:
        raise SystemExit("the helpers of the two trees differ; the arms would not be prepared in the same way")
env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "DJANGO_SETTINGS_MODULE", "PYTEST_ADDOPTS", "FIXFIRST_STORE")}
env["PYTHONDONTWRITEBYTECODE"] = "1"
env["UV_CACHE_DIR"] = os.environ.get("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv"))
env["UV_PYTHON_INSTALL_DIR"] = os.environ.get("UV_PYTHON_INSTALL_DIR", str(Path.home() / ".local" / "share" / "uv" / "python"))
if offline:
    for name in ("http_proxy", "https_proxy", "all_proxy", "ftp_proxy"):
        env[name] = env[name.upper()] = "http://127.0.0.1:9"
    env["no_proxy"] = env["NO_PROXY"] = "localhost,127.0.0.1,::1"
    env["UV_OFFLINE"] = "1"
(target / "logs").mkdir(parents=True, exist_ok=True)
if phase == "run" and not only:
    done_before = [p for arm, _, _ in ARMS for p in (target / arm).glob("*/results/*.json") if "fixfirst_before" in p.read_text(encoding="utf-8")]
    if done_before:
        raise SystemExit(f"the product has already been run here ({len(done_before)} records); the test is run once")


def one(entry, arm, tree, mode):
    case, project = entry["case"], entry["project"]
    where = target / arm / project
    record_path = where / "results" / f"{case}.json"
    if record_path.exists():
        record_path.unlink()
    home = target / "homes" / phase / arm / case
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    started = time.monotonic()
    done = subprocess.run([str(tree / ".venv/bin/python"), str(HERE / case_script), str(tree), project, str(entry["bug"]), "--target", str(where),
                           "--mode", "none" if phase == "prepare" else mode, "--python", entry["python"], "--deps", *entry["installed"],
                           *([] if isolation else ["--no-build-isolation"])], cwd=tree, env=dict(env, HOME=str(home)), capture_output=True, text=True, timeout=3600)
    (target / "logs" / f"{phase}{'-offline' if offline and phase == 'prepare' else ''}-{arm}-{case}.txt").write_text(done.stdout + "\n--- stderr\n" + done.stderr[-6000:], encoding="utf-8")
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    same_packages = sorted(record.get("installed", [])) == sorted(entry["installed"])
    return {"case": case, "arm": arm, "exit": done.returncode, "reproduced": bool(record.get("reproduced")), "same_packages": same_packages,
            "left_in_home": sorted(p.name for p in home.iterdir())[:12],
            "checked": "fixfirst_before" in record and "fixfirst_after" in record, "seconds": round(time.monotonic() - started),
            "product_error": [k for k in ("product_error_before", "product_error_after") if k in record],
            "package_difference": sorted(set(record.get("installed", [])) ^ set(entry["installed"]))[:8] if not same_packages else []}


def stream(project):
    rows = []
    for entry in selection:
        if entry["project"] != project or (only and entry["case"] not in only):
            continue
        for arm, tree, mode in ARMS:
            row = one(entry, arm, tree, mode)
            rows.append(row)
            print(f"{row['case']:18}{arm:13}exit {row['exit']}  reproduced {row['reproduced']}  packages as selected {row['same_packages']}"
                  + (f"  checked by the product {row['checked']}" if phase == "run" else "") + f"  {row['seconds']} s"
                  + (f"  differing: {row['package_difference']}" if row["package_difference"] else "")
                  + (f"  PRODUCT EXCEPTION {row['product_error']}" if row["product_error"] else ""), flush=True)
    return rows


projects = list(dict.fromkeys(e["project"] for e in selection))
with concurrent.futures.ThreadPoolExecutor(len(projects)) as pool:
    rows = [r for part in pool.map(stream, projects) for r in part]
ready = [r for r in rows if r["reproduced"] and r["same_packages"]]
print(f"{len(rows)} runs; reproduced with the selected packages: {len(ready)}"
      + (f"; checked by the product: {sum(r['checked'] for r in rows)}" if phase == "run" else ""))
for r in rows:
    if r not in ready:
        print(f"   NOT READY {r['case']} {r['arm']}: exit {r['exit']}, reproduced {r['reproduced']}, packages as selected {r['same_packages']} {r['package_difference']}")
(target / f"{phase}{'-offline' if offline and phase == 'prepare' else ''}-summary.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
