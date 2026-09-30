"""What a verification is measured against: the project's tests and the settings that select or
judge them, recorded when a session first checks the project (its baseline).

Three things are kept apart. Whether the latest run passed is a fact about that run. Whether the
tests or those settings changed since the baseline is recorded here (`Session.baseline_check`).
Whether the original problem is verified is decided only when nothing it depends on changed: if a
test file, a conftest.py or such a setting changed, a pass no longer shows that the original
problem is fixed, so service.ingest leaves it awaiting verification (`Issue.verification =
"not_comparable"`) and the goal is not called reached. Writing or changing tests is often right:
a person can accept the changed tests as the new baseline (`fixfirst accept-baseline`, or the web
page). FixFirst's MCP tools cannot, so an agent never resets it silently.

Not counted: pytest's `pythonpath` (putting src on the path repairs the project, not its tests) and
pyproject metadata unrelated to tests. For a program (run_project) the baseline is the entry,
arguments, input and interpreter, which the check's scope already fixes; editing the program is
the fix. For unittest it is the files its discovery pattern selects; for the style goal, Ruff's
settings.
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

SKIP_DIRS = {".venv", "venv", ".env", "env", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
             ".tox", ".nox", "node_modules", "build", "dist", ".fixfirst", ".ipynb_checkpoints"}
TEST_DIRS = {"tests", "test", "testing"}
# pytest settings that change which tests run or how their outcome is judged.
PYTEST_KEYS = {"addopts", "testpaths", "python_files", "python_classes", "python_functions", "norecursedirs",
               "filterwarnings", "xfail_strict", "usefixtures", "required_plugins", "markers", "minversion",
               "confcutdir", "collect_ignore", "collect_ignore_glob", "doctest_optionflags"}
MAX_FILES = 20_000
MAX_BYTES = 16 << 20
TEST_TOOLS = ("pytest", "pytest_run", "unittest_run")


def _hash(path: Path) -> str:
    """The content hash of a regular file; opening never waits (a named pipe is not read)."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return "unreadable"
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return "not a regular file"
        digest = hashlib.sha256()
        for piece in iter(lambda: stream.read(1 << 20), b""):
            digest.update(piece)
        return digest.hexdigest()


def _files(root: Path):
    count = 0
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for name in sorted(names):
            count += 1
            if count > MAX_FILES:
                return
            yield Path(folder) / name


def is_test_file(relative: PurePosixPath) -> bool:
    name = relative.name
    return name.endswith(".py") and (
        name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py")
        or bool(TEST_DIRS & set(relative.parts[:-1])))


def _read(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def pytest_settings(root: Path) -> dict:
    found = {}
    text = _read(root / "pyproject.toml")
    if text is not None:
        try:
            options = tomllib.loads(text).get("tool", {}).get("pytest", {})
            options = options.get("ini_options", options) if isinstance(options, dict) else {}
            found.update({f"pytest:pyproject.toml:{k}": json.dumps(v, sort_keys=True) for k, v in options.items()
                          if k in PYTEST_KEYS})
        except (tomllib.TOMLDecodeError, AttributeError):
            found["pytest:pyproject.toml"] = "unreadable"
    for name, section in (("pytest.ini", "pytest"), ("setup.cfg", "tool:pytest"), ("tox.ini", "pytest")):
        text = _read(root / name)
        if text is None:
            continue
        parser = configparser.RawConfigParser(strict=False)
        try:
            parser.read_string(text)
        except configparser.Error:
            found[f"pytest:{name}"] = "unreadable"
            continue
        if parser.has_section(section):
            found.update({f"pytest:{name}:{k}": " ".join(v.split()) for k, v in parser.items(section)
                          if k in PYTEST_KEYS})
    return found


def ruff_settings(root: Path) -> dict:
    found = {}
    text = _read(root / "pyproject.toml")
    if text is not None:
        try:
            ruff = tomllib.loads(text).get("tool", {}).get("ruff")
            if ruff is not None:
                found["ruff:pyproject.toml"] = json.dumps(ruff, sort_keys=True)
        except tomllib.TOMLDecodeError:
            found["ruff:pyproject.toml"] = "unreadable"
    for name in ("ruff.toml", ".ruff.toml"):
        if (root / name).exists():
            found[f"ruff:{name}"] = _hash(root / name)
    return found


def snapshot(session) -> dict:
    """What the session's goal is verified against, as key -> hash or setting."""
    root = Path(session.project_root)
    if not root.is_dir():
        return {}
    goal, found = session.goal, {}
    if goal in ("collect_tests", "pass_tests"):
        for path in _files(root):
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if is_test_file(relative):
                found[f"tests:{relative}"] = _hash(path)
        found.update(pytest_settings(root))
    elif goal == "pass_unittest" and session.execution:
        start = (root / session.execution.entry).resolve()
        pattern = session.execution.pattern or "test*.py"
        if start.is_dir():
            for path in _files(start):
                if fnmatch.fnmatch(path.name, pattern):
                    found[f"tests:{PurePosixPath(path.relative_to(root).as_posix())}"] = _hash(path)
    elif goal == "check_style":
        found.update(ruff_settings(root))
    return found


def record(session, reason: str) -> None:
    session.verification_baseline = {"goal": session.goal, "recorded_at": now(), "reason": reason,
                                     "files": snapshot(session)}
    session.baseline_check = {"checked_at": now(), "changed": []}


def check(session) -> list[str]:
    """Compare the project with the baseline and store what changed. The first check of a session,
    or the first after its goal changed, records the baseline instead."""
    base = session.verification_baseline
    if not base or base.get("goal") != session.goal:
        record(session, "first check" if not base else "goal changed")
        return []
    current = snapshot(session)
    before = base.get("files", {})
    changed = sorted(key for key in set(before) | set(current) if before.get(key) != current.get(key))
    session.baseline_check = {"checked_at": now(), "changed": changed}
    return changed


def affects(changed: list[str], tool: str) -> bool:
    """Whether the changes bear on a check: tests and pytest settings on test runs, Ruff's settings
    on Ruff."""
    prefixes = ("tests:", "pytest:") if tool in TEST_TOOLS else ("ruff:",) if tool == "ruff" else ()
    return any(key.startswith(prefixes) for key in changed) if prefixes else False


def accept(session) -> list[str]:
    """A person accepts the current tests and settings as the new baseline; returns what changed."""
    changed = check(session)
    previous = session.verification_baseline.get("recorded_at", "")
    record(session, "accepted by the user")
    session.history.append({"time": now(), "kind": "baseline_accepted", "changed": changed,
                            "previous_baseline": previous})
    return changed


def describe(changed: list[str], limit: int = 4) -> str:
    names = [key.split(":", 1)[1] for key in changed[:limit]]
    return ", ".join(names) + (f" and {len(changed) - limit} more" if len(changed) > limit else "")
