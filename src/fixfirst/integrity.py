"""What a verification is measured against: the project's tests and the settings that select or
judge them, recorded before a session first runs anything (its baseline).

Three things are kept apart. Whether the latest run passed is a fact about that run. Whether the
tests or those settings changed since the baseline is `Session.baseline_check` (state "unchanged",
"changed", or "unverifiable" when FixFirst cannot tell). Whether the original problem is verified
is decided only when the state is "unchanged": otherwise service.ingest leaves it awaiting
verification (`Issue.verification = "not_comparable"` or "unverifiable") and the goal is not called
reached. Writing or changing tests is often right: a person can accept the current tests as the
new baseline (`fixfirst accept-baseline`, or the web page). FixFirst's MCP tools cannot, so an
agent never resets it.

- The baseline is taken before the first check of its scope runs any project code, and every
  check compares before and after it runs, so a test that rewrites itself is seen.
- Which files are tests is decided when comparing, from both snapshots: conftest.py, files that
  match the project's own `python_files` patterns (pytest's default otherwise) or lie in a tests
  folder, and every file a run actually collected a test from. Every Python file is therefore
  hashed; source files that are not tests are never compared, since changing them is the fix.
- Baselines are kept per scope (pytest's two goals share one; unittest per start folder and
  pattern; Ruff), so changing the goal and back never replaces one.
- Anything FixFirst could not read completely (a limit reached, an unreadable or special file, a
  file over the size limit, a collected test file it does not track) makes the state
  "unverifiable", never "unchanged".

Not counted: pytest's `pythonpath` (putting src on the path repairs the project, not its tests)
and pyproject metadata unrelated to tests. A program (run_project) has no test baseline: its entry,
arguments, input and interpreter are fixed by its check scope, and editing it is the fix.
"""

import configparser
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from .models import now

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox",
             "node_modules", "build", "dist", ".fixfirst", ".ipynb_checkpoints", "site-packages"}
TEST_DIRS = {"tests", "test", "testing"}
DEFAULT_PYTHON_FILES = ("test_*.py", "*_test.py")
# pytest settings that change which tests run or how their outcome is judged.
PYTEST_KEYS = {"addopts", "testpaths", "python_files", "python_classes", "python_functions", "norecursedirs",
               "filterwarnings", "xfail_strict", "usefixtures", "required_plugins", "markers", "minversion",
               "confcutdir", "collect_ignore", "collect_ignore_glob", "doctest_optionflags"}
MAX_ENTRIES = 200_000  # files and folders walked
MAX_FILES = 20_000  # Python files hashed
MAX_BYTES = 16 << 20  # per file
MAX_TOTAL = 512 << 20  # bytes hashed in one snapshot
SCOPE_TOOLS = {"pytest": ("pytest", "pytest_run"), "unittest": ("unittest_run",), "ruff": ("ruff",)}
UNREADABLE = "!"  # prefix of a value that stands for content FixFirst could not read


def scope_of(session) -> str | None:
    if session.goal in ("collect_tests", "pass_tests"):
        return "pytest"
    if session.goal == "pass_unittest" and session.execution:
        return f"unittest:{session.execution.entry}:{session.execution.pattern or 'test*.py'}"
    if session.goal == "check_style":
        return "ruff"
    return None


def tools_of(scope: str | None) -> tuple:
    return SCOPE_TOOLS.get(scope.split(":", 1)[0], ()) if scope else ()


def _hash(path: Path) -> tuple[str | None, int, str | None]:
    """(sha256, size, problem) of a regular file, read with a size limit; opening never waits."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as error:
        return None, 0, f"cannot be read ({error.strerror or error})"
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        return None, 0, "is not a regular file"
    if info.st_size > MAX_BYTES:
        os.close(fd)
        return None, info.st_size, f"is larger than {MAX_BYTES} bytes"
    digest, size = hashlib.sha256(), 0
    with os.fdopen(fd, "rb") as stream:
        for piece in iter(lambda: stream.read(1 << 20), b""):
            size += len(piece)
            if size > MAX_BYTES:
                return None, size, f"grew beyond {MAX_BYTES} bytes while it was read"
            digest.update(piece)
    return digest.hexdigest(), size, None


def _environment(folder: Path) -> bool:
    """A virtual or conda environment inside the project, whatever its name."""
    return (folder / "pyvenv.cfg").is_file() or (folder / "conda-meta").is_dir()


def _python_files(root: Path, problems: list) -> dict:
    files, walked, total = {}, 0, 0
    for folder, dirs, names in os.walk(root):
        here = Path(folder)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")
                         and not _environment(here / d))
        walked += len(dirs) + len(names)
        if walked > MAX_ENTRIES:
            problems.append(f"more than {MAX_ENTRIES} files and folders, so not every test could be recorded")
            return files
        for name in sorted(n for n in names if n.endswith(".py")):
            if len(files) >= MAX_FILES:
                problems.append(f"more than {MAX_FILES} Python files, so not every test could be recorded")
                return files
            path = here / name
            digest, size, problem = _hash(path)
            files[path.relative_to(root).as_posix()] = digest if digest else UNREADABLE + problem
            total += size
            if total > MAX_TOTAL:
                problems.append(f"more than {MAX_TOTAL} bytes of Python files, so not every test could be recorded")
                return files
    return files


def _read(path: Path) -> tuple[str | None, str | None]:
    """(text, problem): None and no problem when the file does not exist."""
    if not path.exists():
        return None, None
    digest, _, problem = _hash(path)
    if problem:
        return None, f"{path.name} {problem}"
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as error:
        return None, f"{path.name} cannot be read ({error})"


def pytest_settings(root: Path) -> dict:
    found = {}
    text, problem = _read(root / "pyproject.toml")
    if problem:
        found["pytest:pyproject.toml"] = UNREADABLE + problem
    elif text is not None:
        try:
            options = tomllib.loads(text).get("tool", {}).get("pytest", {})
            options = options.get("ini_options", options) if isinstance(options, dict) else {}
            found.update({f"pytest:pyproject.toml:{k}": json.dumps(v, sort_keys=True) for k, v in options.items()
                          if k in PYTEST_KEYS})
        except (tomllib.TOMLDecodeError, AttributeError) as error:
            found["pytest:pyproject.toml"] = UNREADABLE + f"pyproject.toml cannot be parsed ({error})"
    for name, section in (("pytest.ini", "pytest"), ("setup.cfg", "tool:pytest"), ("tox.ini", "pytest")):
        text, problem = _read(root / name)
        if problem:
            found[f"pytest:{name}"] = UNREADABLE + problem
            continue
        if text is None:
            continue
        parser = configparser.RawConfigParser(strict=False)
        try:
            parser.read_string(text)
        except configparser.Error as error:
            found[f"pytest:{name}"] = UNREADABLE + f"{name} cannot be parsed ({error})"
            continue
        if parser.has_section(section):
            found.update({f"pytest:{name}:{k}": " ".join(v.split()) for k, v in parser.items(section)
                          if k in PYTEST_KEYS})
    return found


def ruff_settings(root: Path) -> dict:
    found = {}
    text, problem = _read(root / "pyproject.toml")
    if problem:
        found["ruff:pyproject.toml"] = UNREADABLE + problem
    elif text is not None:
        try:
            ruff = tomllib.loads(text).get("tool", {}).get("ruff")
            if ruff is not None:
                found["ruff:pyproject.toml"] = json.dumps(ruff, sort_keys=True)
        except tomllib.TOMLDecodeError as error:
            found["ruff:pyproject.toml"] = UNREADABLE + f"pyproject.toml cannot be parsed ({error})"
    for name in ("ruff.toml", ".ruff.toml"):
        if (root / name).exists():
            digest, _, problem = _hash(root / name)
            found[f"ruff:{name}"] = digest if digest else UNREADABLE + f"{name} {problem}"
    return found


def snapshot(session, scope: str) -> dict:
    root = Path(session.project_root)
    problems: list[str] = []
    if not root.is_dir():
        return {"files": {}, "settings": {}, "problems": [f"the project folder {root} does not exist"]}
    if scope == "ruff":
        return {"files": {}, "settings": ruff_settings(root), "problems": problems}
    files = _python_files(root, problems)
    settings = pytest_settings(root) if scope == "pytest" else {}
    return {"files": files, "settings": settings, "problems": problems}


def _patterns(settings: dict) -> set:
    found = set()
    for key, value in settings.items():
        if key.endswith(":python_files") and not value.startswith(UNREADABLE):
            try:
                parsed = json.loads(value)
            except ValueError:
                parsed = value
            found.update(parsed if isinstance(parsed, list) else str(parsed).split())
    return found


def _collected(session, scope: str, candidates: set) -> set:
    """Files that runs of this scope actually collected tests from (by node id)."""
    tools = tools_of(scope)
    ids = set()
    for run in session.runs:
        if run.tool in tools and run.source == "executed":
            ids.update(run.passed_nodes)
            ids.update(r["nodeid"] for r in run.records if isinstance(r, dict) and r.get("nodeid"))
    for issue in session.issues:
        if issue.tool in tools:
            ids.update(issue.targets)
    found = set()
    start = scope.split(":")[1].strip("./") if scope.startswith("unittest:") else ""
    for node in ids:
        if "::" in node or node.endswith(".py"):
            found.add(node.split("::", 1)[0])
        else:  # unittest: package.module.Class.test, relative to the start folder
            parts = node.split(".")
            for size in range(len(parts) - 1, 0, -1):
                path = "/".join(filter(None, [start, *parts[:size]])) + ".py"
                if path in candidates:
                    found.add(path)
                    break
    return found


def test_files(session, scope: str, base: dict, current: dict) -> set:
    candidates = set(base["files"]) | set(current["files"])
    if scope.startswith("unittest:"):
        _, start, pattern = scope.split(":", 2)
        start = start.strip("./")
        chosen = {p for p in candidates if (not start or p == start or p.startswith(start + "/"))
                  and fnmatch.fnmatch(PurePosixPath(p).name, pattern)}
    else:
        patterns = _patterns(base["settings"]) | _patterns(current["settings"]) or set(DEFAULT_PYTHON_FILES)
        chosen = {p for p in candidates
                  if PurePosixPath(p).name == "conftest.py"
                  or any(fnmatch.fnmatch(PurePosixPath(p).name, pattern) for pattern in patterns)
                  or TEST_DIRS & set(PurePosixPath(p).parts[:-1])}
    return chosen | _collected(session, scope, candidates)


def compare(session, scope: str, base: dict) -> dict:
    current = snapshot(session, scope)
    changed, unverifiable = [], [*base["problems"], *current["problems"]]
    for path in sorted(test_files(session, scope, base, current)):
        before, after = base["files"].get(path), current["files"].get(path)
        if before is None and after is None:
            unverifiable.append(f"{path} was collected as a test, but its content is not recorded")
        elif (before or "").startswith(UNREADABLE) or (after or "").startswith(UNREADABLE):
            marker = before if (before or "").startswith(UNREADABLE) else after
            unverifiable.append(f"{path} {marker.removeprefix(UNREADABLE)}")
        elif before != after:
            changed.append(f"tests:{path}")
    for key in sorted(set(base["settings"]) | set(current["settings"])):
        before, after = base["settings"].get(key), current["settings"].get(key)
        if (before or "").startswith(UNREADABLE) or (after or "").startswith(UNREADABLE):
            unverifiable.append((before if (before or "").startswith(UNREADABLE) else after).removeprefix(UNREADABLE))
        elif before != after:
            changed.append(key)
    return {"changed": changed, "unverifiable": list(dict.fromkeys(unverifiable))}


def _state(result: dict) -> str:
    return "unverifiable" if result["unverifiable"] else "changed" if result["changed"] else "unchanged"


def _record(session, scope: str, reason: str) -> dict:
    base = {**snapshot(session, scope), "recorded_at": now(), "reason": reason}
    session.verification_baseline.setdefault("scopes", {})[scope] = base
    return base


def before_checks(session) -> dict | None:
    """Before a check runs project code: record the scope's baseline if it has none, and compare."""
    scope = scope_of(session)
    if scope is None:
        session.baseline_check = {"scope": None, "state": "not_applicable", "changed": [], "unverifiable": []}
        return None
    base = session.verification_baseline.get("scopes", {}).get(scope) or _record(session, scope, "first check")
    return compare(session, scope, base)


def after_checks(session, before: dict | None) -> dict:
    """After the check: compare again (a run can change its own tests) and keep both results."""
    scope = scope_of(session)
    if scope is None or before is None:
        return session.baseline_check
    after = compare(session, scope, session.verification_baseline["scopes"][scope])
    result = {"changed": sorted(set(before["changed"]) | set(after["changed"])),
              "unverifiable": list(dict.fromkeys(before["unverifiable"] + after["unverifiable"]))}
    session.baseline_check = {"scope": scope, "checked_at": now(), "state": _state(result), **result}
    return session.baseline_check


def check(session) -> dict:
    """Compare now, without running anything (records a missing baseline first)."""
    return after_checks(session, before_checks(session))


def affects(session, tool: str) -> bool:
    """Whether the latest comparison stands in the way of verifying a result of this check."""
    check_ = session.baseline_check
    return check_.get("state") in ("changed", "unverifiable") and tool in tools_of(check_.get("scope"))


def accept(session) -> dict:
    """A person accepts the current tests and settings as the scope's new baseline."""
    scope = scope_of(session)
    if scope is None:
        raise ValueError("This goal has no test baseline: a program is verified by running it the same way")
    previous = session.verification_baseline.get("scopes", {}).get(scope)
    result = compare(session, scope, previous) if previous else {"changed": [], "unverifiable": []}
    base = _record(session, scope, "accepted by the user")
    session.history.append({"time": now(), "kind": "baseline_accepted", "scope": scope,
                            "changed": result["changed"], "unverifiable": result["unverifiable"],
                            "previous_baseline": previous.get("recorded_at") if previous else None})
    fresh = {"changed": [], "unverifiable": list(base["problems"])}
    session.baseline_check = {"scope": scope, "checked_at": now(), "state": _state(fresh), **fresh}
    return result


def current_baseline(session) -> dict:
    return session.verification_baseline.get("scopes", {}).get(scope_of(session) or "", {})


def describe(items: list[str], limit: int = 4) -> str:
    names = [item.split(":", 1)[1] if item.startswith(("tests:", "pytest:", "ruff:")) else item
             for item in items[:limit]]
    return ", ".join(names) + (f" and {len(items) - limit} more" if len(items) > limit else "")
