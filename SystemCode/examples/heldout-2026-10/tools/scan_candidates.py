#!/usr/bin/env python3
"""Screen candidate projects for the FixFirst held-out batch (task A1, step 1).

Walks awesome-python in list order and applies only the skip conditions the A1
card allows, so the sampling stays mechanical and free of "this one looks
easier" choices. Anything that cannot be decided from repository metadata is
marked REVIEW and left for you.

Writes, next to this script's parent folder:
  candidates.csv        one row per candidate, ready for you to review
  projects.stubs.toml   one [[project]] block per suggestion

Nothing is committed or pushed. Only public metadata is read.

Usage:
    python tools/scan_candidates.py --list-categories
    python tools/scan_candidates.py --category "Web Development" --limit 20
    python tools/scan_candidates.py --all --limit 60
    python tools/scan_candidates.py --all --limit 200 --token-file ~/.github_token

GitHub allows 60 requests an hour without a token and 5000 with one; each
candidate costs about 3. Without a token the script stops cleanly when the
budget runs out, and a later run resumes from the cache.

What it cannot decide, and marks REVIEW for you:
  - whether the tests need the network or a paid service
  - whether the project needs a compiled C extension
  - which project gets which root cause, and the `scenario` wording
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent
OUT_CSV = OUT_DIR / "candidates.csv"
OUT_TOML = OUT_DIR / "projects.stubs.toml"
CACHE_FILE = HERE / "scan-cache.json"

AWESOME = "https://raw.githubusercontent.com/vinta/awesome-python/master/README.md"
BUGSINPY = "https://api.github.com/repos/soarsmu/BugsInPy/contents/projects"

TOKEN: str | None = None
CUTOFF = datetime(2022, 1, 1, tzinfo=timezone.utc)
RECENT = datetime.now(timezone.utc) - timedelta(days=730)

# A1 rule 4: the pilot batch, plus everything already used under examples/.
EXCLUDED = {
    "pallets-eco/flask-sqlalchemy",
    "jazzband/django-model-utils",
    "psf/requests",
    "mwaskom/seaborn",
    "scikit-learn-contrib/imbalanced-learn",
    "fastapi/typer",
    "vxgmichel/aiostream",
    "jmespath/jmespath.py",
    "scrapy/parsel",
    "kennethreitz/records",
    "tkem/cachetools",
    "more-itertools/more-itertools",
    "python-attrs/attrs",
    "pallets/flask",       # flask 1.1.4, named in A1 rule 4
    "python-humanize/humanize",  # the humanize write-up
    "soarsmu/bugsinpy",
}

C_EXT_SUFFIXES = {".pyx", ".pxd", ".c", ".cpp", ".cc", ".rs", ".f", ".f90"}
SKIP_DIRS = {".venv", "node_modules", "site-packages", "build", "dist", ".tox"}

CSV_COLUMNS = [
    "id", "repo", "ref", "python", "domain", "found_in",
    "tried_on", "pytest_summary", "root_cause_guess", "kept", "reason",
]

_calls = 0
_cache: dict = {}


def resolve_token(token_file: str | None) -> str | None:
    """The GitHub token, from --token-file or the environment.

    The file form keeps the token out of shell history and out of any
    transcript: write it once with
        printf '%s' ghp_xxx > ~/.github_token
    and the value is never echoed anywhere.
    """
    if token_file:
        path = Path(token_file).expanduser()
        if not path.exists():
            raise SystemExit(f"token file not found: {path}")
        return path.read_text("utf-8").strip() or None
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


# ---------------------------------------------------------------- fetch layer

def load_cache() -> None:
    global _cache
    if CACHE_FILE.exists():
        _cache = json.loads(CACHE_FILE.read_text("utf-8"))


def save_cache() -> None:
    CACHE_FILE.write_text(json.dumps(_cache, indent=1, sort_keys=True), "utf-8")


def get(url: str, api: bool = False) -> object | None:
    """Fetch a URL, return parsed JSON or text. None on 403/404."""
    global _calls
    if url in _cache:
        return _cache[url]
    headers = {"User-Agent": "fixfirst-heldout-scan"}
    if api and TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(url, headers=headers)
    try:
        if api:
            _calls += 1  # only GitHub API calls count against the rate limit
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        if error.code in (403, 404, 429):
            if api and not TOKEN and error.code == 403:
                print("GitHub rate limit reached. Set GITHUB_TOKEN and re-run to resume.",
                      file=sys.stderr)
                raise SystemExit(2)
            _cache[url] = None
            return None
        raise
    except urllib.error.URLError as error:
        print(f"network error on {url}: {error}", file=sys.stderr)
        return None
    if api:
        try:
            _cache[url] = json.loads(body)
        except json.JSONDecodeError:
            _cache[url] = None
    else:
        _cache[url] = body
    return _cache[url]


def github(path: str) -> object | None:
    return get(f"https://api.github.com{path}", api=True)


def get_json(url: str) -> object | None:
    """Fetch a JSON document that is not the GitHub API.

    Kept separate from get(api=True) so the GitHub token is never sent to
    another host.
    """
    body = get(url)
    if not isinstance(body, str):
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


# ------------------------------------------------------------- awesome-python

def load_categories() -> dict[str, list[tuple[str, str]]]:
    """{category: [(owner/repo, description), ...]} in README order.

    The README keeps the real categories as `###` headings inside its
    `## Projects` section; the `##` headings are just Sponsors/Categories/
    Projects/Resources, so they are skipped.
    """
    text = get(AWESOME)
    if not isinstance(text, str):
        raise SystemExit("could not download awesome-python's README")
    categories: dict[str, list[tuple[str, str]]] = {}
    in_projects = False
    current = None
    for line in text.splitlines():
        section = re.match(r"^##\s+(.+?)\s*$", line)
        if section:
            title = section.group(1).strip().strip("*").lower()
            in_projects = title == "projects"
            current = None
            continue
        if not in_projects:
            continue
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip().strip("*")
            categories.setdefault(current, [])
            continue
        if current is None:
            continue
        # Entries are indented bullets; nesting is only used for the companion
        # "awesome-*" lists, which are not projects.
        entry = re.match(
            r"^\s*-\s+\[([^\]]+)\]\(https://github\.com/([^/)\s]+)/([^/)\s#?]+)[^)]*\)"
            r"\s*(?:[-–—]\s*(.*))?$",
            line,
        )
        if entry:
            label, owner, name, description = entry.groups()
            repo = f"{owner}/{name.removesuffix('.git').rstrip('/')}"
            if label.lower().startswith("awesome-") or name.lower().startswith("awesome-"):
                continue
            categories[current].append((repo, (description or "").strip()))
    return categories


def load_bugsinpy_projects() -> set[str]:
    listing = github("/repos/soarsmu/BugsInPy/contents/projects")
    if not isinstance(listing, list):
        return set()
    return {item["name"].lower() for item in listing if item.get("type") == "dir"}


# ------------------------------------------------------------ repo inspection

def inspect(repo: str) -> dict:
    """Public metadata for one repo, or {'error': ...}."""
    meta = github(f"/repos/{repo}")
    if not isinstance(meta, dict):
        return {"error": "repo not found"}
    branch = meta.get("default_branch") or "main"
    tree = github(f"/repos/{repo}/git/trees/{urllib.parse.quote(branch)}?recursive=1")
    paths: list[str] = []
    if isinstance(tree, dict) and isinstance(tree.get("tree"), list):
        paths = [item["path"] for item in tree["tree"] if item.get("type") == "blob"]
    return {
        "language": meta.get("language"),
        "archived": bool(meta.get("archived")),
        "size_kb": meta.get("size") or 0,
        "description": (meta.get("description") or "").strip(),
        "branch": branch,
        "paths": paths,
    }


def test_signals(paths: list[str]) -> tuple[bool, int]:
    parts = [p for p in paths if not any(d in p.split("/") for d in SKIP_DIRS)]
    test_files = [
        p for p in parts
        if re.search(r"(^|/)tests?/", p) and p.endswith(".py")
        or re.search(r"(^|/)test_[^/]*\.py$", p)
        or re.search(r"(^|/)[^/]*_test\.py$", p)
    ]
    return bool(test_files), len(test_files)


def c_extension_signals(paths: list[str]) -> list[str]:
    return sorted({Path(p).suffix for p in paths if Path(p).suffix in C_EXT_SUFFIXES})


# --------------------------------------------------------------------- PyPI

def pypi_releases(package: str) -> dict[str, datetime]:
    """{version: earliest upload time}, yanked and pre-releases removed."""
    data = get_json(f"https://pypi.org/pypi/{urllib.parse.quote(package)}/json")
    if not isinstance(data, dict):
        return {}
    releases: dict[str, datetime] = {}
    for version, files in (data.get("releases") or {}).items():
        if re.search(r"[abc]|rc|dev|post", version, re.I):
            continue
        stamps = [
            f["upload_time_iso_8601"] for f in files
            if f.get("upload_time_iso_8601") and not f.get("yanked")
        ]
        if not stamps:
            continue
        releases[version] = datetime.fromisoformat(min(stamps)).astimezone(timezone.utc)
    return releases


def package_name(repo: str, branch: str) -> str | None:
    """The PyPI distribution name for a repo, or None.

    The repository name and the distribution name often differ, so this tries
    the common spellings first and then falls back to whatever the packaging
    metadata declares. PyPI and raw.githubusercontent.com are not part of the
    GitHub rate limit.
    """
    name = repo.split("/")[-1].lower()
    for candidate in dict.fromkeys((name, name.replace("-", "_"), name.replace("_", "-"))):
        if pypi_releases(candidate):
            return candidate
    for path in ("pyproject.toml", "setup.py", "setup.cfg"):
        text = get(f"https://raw.githubusercontent.com/{repo}/{branch}/{path}")
        if not isinstance(text, str):
            continue
        # pyproject/setup.cfg declare it as a key; setup.py calls setup(name=...).
        for pattern in (r'^\s*name\s*=\s*["\']([^"\']+)["\']',
                        r'\bname\s*=\s*["\']([^"\']+)["\']'):
            declared = re.search(pattern, text, re.M)
            if declared and pypi_releases(declared.group(1).strip()):
                return declared.group(1).strip()
    return None


def choose_versions(package: str) -> dict[str, str]:
    releases = pypi_releases(package)
    if not releases:
        return {}
    ordered = sorted(releases.items(), key=lambda kv: kv[1])
    older = [(v, t) for v, t in ordered if t < CUTOFF]
    recent = [(v, t) for v, t in ordered if t >= RECENT]
    return {
        "before_2022": older[-1][0] if older else "",
        "recent": recent[-1][0] if recent else ordered[-1][0],
    }


# ------------------------------------------------------------------ decision

def screen(repo: str, description: str, bugsinpy: set[str]) -> dict:
    info = inspect(repo)
    if "error" in info:
        return {"verdict": "SKIP", "reason": info["error"]}
    if info["language"] and info["language"] != "Python":
        return {"verdict": "SKIP",
                "reason": f"not pure Python (repo language is {info['language']})"}
    if repo.split("/")[-1].lower() in bugsinpy:
        return {"verdict": "SKIP", "reason": "reserved for B12 (BugsInPy)"}
    has_tests, count = test_signals(info["paths"])
    if not has_tests:
        return {"verdict": "SKIP", "reason": "no pytest-runnable tests found"}
    extensions = c_extension_signals(info["paths"])
    notes = []
    if extensions:
        notes.append(f"ships {'/'.join(extensions)} sources - check for a C extension")
    if info["size_kb"] > 200_000:
        notes.append(f"large repo ({info['size_kb'] // 1000} MB)")
    notes.append("confirm the tests need no network or paid service")
    package = package_name(repo, info["branch"])
    versions = choose_versions(package) if package else {}
    if not versions:
        notes.append("PyPI name unknown - read the tag off the repo's Releases page")
    return {
        "verdict": "REVIEW",
        "reason": "; ".join(notes),
        "test_files": count,
        "versions": versions,
        "description": description or info["description"],
    }


# --------------------------------------------------------------------- output

def load_existing() -> dict[str, dict]:
    if not OUT_CSV.exists():
        return {}
    with open(OUT_CSV, newline="", encoding="utf-8") as handle:
        return {row["repo"]: row for row in csv.DictReader(handle) if row.get("repo")}


def write_csv(rows: dict[str, dict]) -> None:
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows.values():
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})


def write_toml(rows: dict[str, dict], categories: dict[str, list]) -> None:
    domain_of = {repo: name for name, entries in categories.items() for repo, _ in entries}
    blocks = [
        "# Generated by tools/scan_candidates.py. Review every field before copying a",
        "# block into projects.toml - in particular `scenario`, `install` and `ref`.",
        "",
    ]
    for row in rows.values():
        if row.get("kept") != "yes":
            continue
        versions = row.get("_versions") or {}
        blocks += [
            "[[project]]",
            f'id = "{row["id"]}"',
            f'repo = "{row["repo"]}"',
            f'ref = "{versions.get("before_2022") or "<tag - fill in>"}"  '
            f'# before 2022: {versions.get("before_2022") or "?"} | '
            f'recent: {versions.get("recent") or "?"}',
            f'domain = "{domain_of.get(row["repo"], "")}"',
            '# layout = "<src layout|flat package>, <pyproject.toml|setup.py>, <where deps are declared>"',
            f'python = "{row.get("python") or "3.12"}"',
            '# install = ["-e .", "-r requirements-dev.txt"]   # read the README / tox.ini',
            '# scenario = "<how this env was made and what was deliberately left out>"',
            "",
        ]
    OUT_TOML.write_text("\n".join(blocks), "utf-8")


def slug(repo: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", repo.split("/")[-1].lower()).strip("-")


# ----------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list-categories", action="store_true",
                        help="print awesome-python's categories and stop")
    parser.add_argument("--category", action="append", default=[],
                        help="walk only this category (repeatable)")
    parser.add_argument("--all", action="store_true", help="walk every category")
    parser.add_argument("--limit", type=int, default=25,
                        help="stop after this many candidates (default 25)")
    parser.add_argument("--max-budget", type=int, default=55,
                        help="stop before this many GitHub API calls without a token "
                             "(default 55; ignored when a token is set)")
    parser.add_argument("--token-file", default=None,
                        help="read the GitHub token from this file instead of the "
                             "GITHUB_TOKEN / GH_TOKEN environment variables")
    args = parser.parse_args()

    global TOKEN
    TOKEN = resolve_token(args.token_file)
    if TOKEN:
        args.max_budget = 5000
    if not TOKEN:
        print("No GITHUB_TOKEN set: about 55 API calls per hour, then the script stops.",
              file=sys.stderr)

    load_cache()
    try:
        categories = load_categories()
    except SystemExit as error:
        print(error, file=sys.stderr)
        return 2

    if args.list_categories:
        for name, entries in categories.items():
            print(f"{name}  ({len(entries)} entries)")
        save_cache()
        return 0

    wanted = list(categories) if args.all else args.category
    if not wanted:
        print("pick one or more --category, or pass --all "
              "(see --list-categories)", file=sys.stderr)
        return 2
    unknown = [name for name in wanted if name not in categories]
    if unknown:
        print(f"unknown category: {', '.join(unknown)}", file=sys.stderr)
        return 2

    bugsinpy = load_bugsinpy_projects()
    rows = load_existing()
    today = datetime.now().strftime("%Y-%m-%d")
    scanned = skipped = kept = 0
    seen: set[str] = set()

    for name in wanted:
        for repo, description in categories[name]:
            if scanned >= args.limit or _calls >= args.max_budget:
                break
            if repo.lower() in EXCLUDED:
                continue
            if repo in seen:
                continue
            seen.add(repo)
            scanned += 1
            if scanned % 5 == 0:
                print(f"  scanned {scanned}, kept {kept}, skipped {skipped}", flush=True)
            result = screen(repo, description, bugsinpy)
            if result["verdict"] == "SKIP":
                skipped += 1
                rows.setdefault(repo, {}).update({
                    "id": slug(repo), "repo": repo, "domain": name, "found_in": name,
                    "tried_on": today, "kept": "no", "reason": result["reason"],
                })
                continue
            kept += 1
            versions = result["versions"]
            rows[repo] = {
                # `ref` defaults to the last release before 2022, which is what
                # a version_incompatibility candidate needs; the TOML stub also
                # carries the recent tag for the healthy / code_defect cases.
                "id": slug(repo), "repo": repo,
                "ref": versions.get("before_2022", ""),
                "python": "3.12",
                "domain": name, "found_in": f"awesome-python: {name}", "tried_on": today,
                "root_cause_guess": "", "kept": "yes", "reason": result["reason"],
                "_versions": versions,
                "_test_files": result["test_files"],
            }
            write_csv(rows)
            save_cache()
        if scanned >= args.limit or _calls >= args.max_budget:
            break

    write_csv(rows)
    write_toml(rows, categories)
    save_cache()
    print(f"scanned {scanned}, kept {kept}, skipped {skipped}, {_calls} API calls")
    print(f"wrote {OUT_CSV.name} and {OUT_TOML.name} - read them yourself; "
          f"set `kept` per row before trusting anything.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
