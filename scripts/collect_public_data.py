"""Collect the public data FixFirst can use from PyDFix and BugsInPy.

Usage: python scripts/collect_public_data.py [--output DIR] [--cache DIR]

Both sources are read at fixed commits, so the output is reproducible. Nothing is executed and
no project is installed: the script downloads PyDFix's four analysis tables and BugsInPy's
per-bug metadata, then writes

- pydfix/summary.json   what the 1,927 table rows contain, by error kind
- pydfix/cases.csv      the distinct import errors that fall within FixFirst's scope
- pydfix/labels.csv     a labelling sheet for those cases (created once, never overwritten)
- pydfix/LICENSE        PyDFix's BSD-3-Clause notice, required when redistributing its data
- bugsinpy/bugs.csv     one row per bug: Python version, commits, test file, what must be compiled
- bugsinpy/summary.json counts by project, Python version, runtime and tier

BugsInPy has no licence file, so only facts and links are stored, never its files.
Downloads are cached (default workbench/public-data-cache) and need about 1,100 requests.
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent

PYDFIX_REPO = "ucd-plse/PyDFix"
PYDFIX_COMMIT = "b276d79e7aff1993280e80bad97a8b8a08e6661f"
BUGSINPY_REPO = "soarsmu/BugsInPy"
BUGSINPY_COMMIT = "11c5f1eea954a42132cfd06bf257766a7963e0fd"

# table: (artifacts file, results file, results key column, outcome column, patch column)
PYDFIX_TABLES = {
    "bugsinpy": ("bugsinpy_artifacts_dependency_broken_orig.csv",
                 "bugsinpy_iterative_solve_results_orig.csv",
                 "Artifact Name", "Build Outcome", "Final Patch"),
    "bugswarm": ("bugswarm_artifacts_dependency_broken_orig.csv",
                 "bugswarm_iterative_solve_results_orig.csv",
                 "Image", "Outcome", "Final patch"),
}

# First match wins; an import error anywhere in the row puts it in scope.
ROW_KINDS = [
    ("python_version_requirement", re.compile(r"requires Python|requires a different Python")),
    ("build_or_setup_py_failure", re.compile(r"setup\.py (egg_info|build|install)|build_ext")),
    ("pip_install_command_failed", re.compile(r"pip install")),
    ("type_or_attribute_error", re.compile(r"TypeError|AttributeError")),
]
IMPORT_ERROR = re.compile(r"(No module named|cannot import name) '?([A-Za-z_][\w.]*)'?")

# Packages that have no wheel for their 2019-2020 pinned release on this Mac (Apple Silicon), so
# pip must compile them. Small extensions build with the command-line tools; the large native
# stacks rarely do. A planning aid only: no bug has been installed by this script.
SMALL_EXTENSIONS = {
    "cffi", "psutil", "regex", "aiohttp", "multidict", "yarl", "uvloop", "httptools", "ujson",
    "greenlet", "typed-ast",
}
NATIVE_STACK = {
    "numpy", "scipy", "pandas", "matplotlib", "tensorflow", "tensorflow-gpu", "torch", "cython",
    "scikit-learn", "h5py", "lxml", "pillow", "kiwisolver", "cryptography", "pycurl", "gevent",
    "cymem", "murmurhash", "preshed", "thinc", "blis", "srsly", "pyzmq",
}
# Projects whose own source has C extensions, so the project itself must be compiled.
COMPILED_PROJECTS = {"matplotlib", "pandas", "spacy"}


def raw_url(repo, commit, path):
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"


def fetch(url, cache: Path):
    """Return the body, or None for 404. Both outcomes are cached."""
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    body, missing = cache / key, cache / f"{key}.404"
    if body.exists():
        return body.read_bytes()
    if missing.exists():
        return None
    request = urllib.request.Request(url, headers={"User-Agent": "fixfirst-collect-public-data"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            missing.touch()
            return None
        raise
    body.write_bytes(data)
    return data


def read_csv(data: bytes):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8", "replace"), newline="")))


def write_csv(path: Path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def pydfix_repository(log_name):
    # bugsinpy: black_1_0.log (project, bug, version); bugswarm: owner-repo-JOBID.failed.log
    return re.sub(r"(-\d+\.(passed|failed)|_\d+_\d+)\.log$", "", log_name)


def collect_pydfix(output: Path, cache: Path):
    out = output / "pydfix"
    out.mkdir(parents=True, exist_ok=True)
    source = f"https://github.com/{PYDFIX_REPO}/tree/{PYDFIX_COMMIT}"
    summary = {"source": source, "tables": {}}
    cases = {}
    for table, (artifacts_file, results_file, key_col, outcome_col, patch_col) in PYDFIX_TABLES.items():
        artifacts = read_csv(fetch(raw_url(PYDFIX_REPO, PYDFIX_COMMIT, f"orig_data/{artifacts_file}"), cache))
        results = {row[key_col]: row for row in read_csv(
            fetch(raw_url(PYDFIX_REPO, PYDFIX_COMMIT, f"orig_data/{results_file}"), cache))}
        kinds = Counter()
        kind_repositories = defaultdict(set)
        repositories = Counter()
        for row in artifacts:
            log = row["Reproduced Log File Name"]
            repository = pydfix_repository(log)
            repositories[repository] += 1
            segments = [s.strip() for s in row["Error Line Flagged"].split("<DELIM>") if s.strip()]
            found = {}  # one entry per missing name, even when the row repeats it
            for segment in segments:
                for match in IMPORT_ERROR.finditer(segment):
                    found.setdefault((match.group(1), match.group(2)), segment)
            if found:
                kind = "import_error_in_scope"
            elif not segments:
                kind = "empty_error_line"
            else:
                text = " ".join(segments)
                kind = next((name for name, pattern in ROW_KINDS if pattern.search(text)), "other")
            kinds[kind] += 1
            kind_repositories[kind].add(repository)
            result = results.get(log, {})
            outcome = result.get(outcome_col, "not in results table") or "not in results table"
            candidates = re.findall(r'"_name": "([^"]+)"', row["Possible Candidates"])
            for (message, name), segment in found.items():
                error_kind = "no_module" if message == "No module named" else "cannot_import_name"
                case_id = f"pydfix-{table}-{repository}-{name}"
                case = cases.setdefault(case_id, {
                    "case_id": case_id, "table": table, "repository": repository,
                    "error_kind": error_kind, "missing_name": name, "rows": 0,
                    "example_log": log, "error_excerpt": segment[:200],
                    "candidate_packages": set(), "outcomes": Counter(), "fixed_patch_example": "",
                })
                case["rows"] += 1
                case["candidate_packages"].update(candidates)
                case["outcomes"][outcome] += 1
                if outcome == "Successfully fixed build" and not case["fixed_patch_example"]:
                    case["fixed_patch_example"] = result.get(patch_col, "")[:300]
        top = repositories.most_common(3)
        summary["tables"][table] = {
            "file": artifacts_file,
            "rows": len(artifacts),
            "repositories": len(repositories),
            "largest_repositories": {name: count for name, count in top},
            "rows_by_kind": {k: {"rows": v, "repositories": len(kind_repositories[k])}
                             for k, v in kinds.most_common()},
            "distinct_in_scope_cases": sum(1 for c in cases.values() if c["table"] == table),
        }
    rows = []
    for case in sorted(cases.values(), key=lambda c: (c["table"], c["repository"], c["missing_name"])):
        rows.append({
            **{k: case[k] for k in ("case_id", "table", "repository", "error_kind", "missing_name",
                                    "rows", "example_log", "error_excerpt")},
            "candidate_packages": " ".join(sorted(case["candidate_packages"])),
            "pydfix_outcomes": "; ".join(f"{k}: {v}" for k, v in case["outcomes"].most_common()),
            "pydfix_fixed_patch_example": case["fixed_patch_example"],
            "source": f"{source}/orig_data/{PYDFIX_TABLES[case['table']][0]}",
        })
    write_csv(out / "cases.csv", rows, list(rows[0]))
    labels = out / "labels.csv"
    if not labels.exists():
        write_csv(labels, [{"case_id": r["case_id"], "root_cause": "", "labelled_by": "",
                            "reviewed_by": "", "notes": ""} for r in rows],
                  ["case_id", "root_cause", "labelled_by", "reviewed_by", "notes"])
    summary["total_rows"] = sum(t["rows"] for t in summary["tables"].values())
    summary["distinct_in_scope_cases"] = len(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    (out / "LICENSE").write_bytes(fetch(raw_url(PYDFIX_REPO, PYDFIX_COMMIT, "LICENSE"), cache))
    return summary


def parse_info(text):
    return dict(re.findall(r'^(\w+)="?([^"\n]*)"?\s*$', text, flags=re.M))


def requirement_names(text):
    names = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def collect_bugsinpy(output: Path, cache: Path):
    out = output / "bugsinpy"
    out.mkdir(parents=True, exist_ok=True)
    tree = json.loads(fetch(f"https://api.github.com/repos/{BUGSINPY_REPO}/git/trees/"
                            f"{BUGSINPY_COMMIT}?recursive=1", cache))
    bug_dirs = sorted({p["path"].rsplit("/", 1)[0] for p in tree["tree"]
                       if re.fullmatch(r"projects/[^/]+/bugs/\d+/bug\.info", p["path"])},
                      key=lambda d: (d.split("/")[1].lower(), int(d.split("/")[3])))
    projects = sorted({d.split("/")[1] for d in bug_dirs})

    def get(path):
        data = fetch(raw_url(BUGSINPY_REPO, BUGSINPY_COMMIT, path), cache)
        if data is None:
            return None
        # Some requirements files were saved on Windows as UTF-16 with a byte-order mark.
        encoding = "utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
        return data.decode(encoding, "replace")

    with ThreadPoolExecutor(max_workers=16) as pool:
        project_info = dict(zip(projects, pool.map(lambda p: get(f"projects/{p}/project.info"), projects)))
        infos = list(pool.map(lambda d: get(f"{d}/bug.info"), bug_dirs))
        requirements = list(pool.map(lambda d: get(f"{d}/requirements.txt"), bug_dirs))

    rows = []
    for bug_dir, info_text, requirements_text in zip(bug_dirs, infos, requirements):
        _, project, _, bug = bug_dir.split("/")
        info = parse_info(info_text or "")
        github = parse_info(project_info[project] or "").get("github_url", "").rstrip("/")
        version = info.get("python_version", "")
        minor = ".".join(version.split(".")[:2])
        names = requirement_names(requirements_text or "")
        small, native = sorted(names & SMALL_EXTENSIONS), sorted(names & NATIVE_STACK)
        if project.lower() in COMPILED_PROJECTS:
            native.insert(0, "project-itself")
        if native:
            tier = "3: large native stack to compile"
        elif small:
            tier = "2: small C extensions to compile"
        else:
            tier = "1: nothing to compile"
        runtime = "uv, Python 3.8" if minor == "3.8" else f"Docker, Python {minor}"
        rows.append({
            "project": project, "bug": bug, "python_version": version, "runtime": runtime,
            "tier": tier, "packages_to_compile": " ".join(native + small),
            "requirements_pinned": "yes" if requirements_text else "no",
            "buggy_commit": info.get("buggy_commit_id", ""),
            "fixed_commit": info.get("fixed_commit_id", ""),
            "test_file": info.get("test_file", ""),
            "project_repository": github,
            "bugsinpy_folder": f"https://github.com/{BUGSINPY_REPO}/tree/{BUGSINPY_COMMIT}/{bug_dir}",
        })
    write_csv(out / "bugs.csv", rows, list(rows[0]))
    by_project = defaultdict(Counter)
    for row in rows:
        by_project[row["project"]][f"tier {row['tier'][0]}, {row['runtime']}"] += 1
    summary = {
        "source": f"https://github.com/{BUGSINPY_REPO}/tree/{BUGSINPY_COMMIT}",
        "bugs": len(rows),
        "projects": len(by_project),
        "python_versions": dict(sorted(Counter(".".join(r["python_version"].split(".")[:2])
                                               for r in rows).items())),
        "tiers": dict(sorted(Counter(r["tier"] for r in rows).items())),
        "tier_by_project": {p: dict(sorted(c.items())) for p, c in sorted(by_project.items(),
                                                                         key=lambda i: i[0].lower())},
        "runtimes": dict(sorted(Counter(r["runtime"] for r in rows).items())),
        "note": ("Tiers count the pinned packages without an Apple Silicon wheel. The pinned lists "
                 "are whole environment freezes, so a single test may need fewer. No bug has been "
                 "reproduced by this script."),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "examples" / "public-data"))
    parser.add_argument("--cache", default=str(ROOT / "workbench" / "public-data-cache"))
    args = parser.parse_args()
    output, cache = Path(args.output), Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    pydfix = collect_pydfix(output, cache)
    print(f"PyDFix: {pydfix['total_rows']} rows, {pydfix['distinct_in_scope_cases']} distinct "
          f"in-scope import errors")
    bugsinpy = collect_bugsinpy(output, cache)
    print(f"BugsInPy: {bugsinpy['bugs']} bugs in {bugsinpy['projects']} projects; tiers {bugsinpy['tiers']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
