"""Real projects for the agent baseline (task B7).

Every run gets its own copy of the project, exported from a fixed commit, and its own
environment, rebuilt from the recorded snapshot (`pip freeze` of the environment the pilot used,
examples/real-world/environments/<id>.txt). Environments are rebuilt, never copied: a copied
virtual environment keeps absolute paths to the original. Nothing outside the run folder is
changed; the source clone and FixFirst's own environment stay as they are.

Grading is independent of the model and of FixFirst: the full test suite runs with the case's own
interpreter in a clean environment (no inherited Python, pytest or application variables), and
its per-test outcomes (JUnit XML) are compared with a reference outcome, obtained once by applying
a known repair to a separate copy. A run counts as fixed only when no test file, conftest.py or
test-selecting pytest setting was changed, nothing fails, and every test that passes in the
reference passes.
"""

import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ElementTree

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

SKIP_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", ".nox", "node_modules"}
TEST_DIRS = {"tests", "test", "testing"}
# pytest settings that change which tests run or how their outcome is reported. `pythonpath` is
# not among them: putting src on the path is an accepted repair for an uninstalled src layout.
SELECTING_KEYS = {"addopts", "testpaths", "python_files", "python_classes", "python_functions", "norecursedirs",
                  "filterwarnings", "xfail_strict", "usefixtures", "required_plugins", "markers", "minversion",
                  "confcutdir", "collect_ignore", "collect_ignore_glob"}
CLEAN_ENV_KEYS = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")


def run(argv, cwd=None, env=None, timeout=1800) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in argv], cwd=cwd, env=env, capture_output=True, text=True,
                          errors="replace", timeout=timeout)


def load_manifest(path: Path) -> dict:
    return {p["id"]: p for p in tomllib.loads(path.read_text(encoding="utf-8"))["project"]}


def read_snapshot(path: Path) -> tuple[str, list[str], list[str]]:
    """(Python version, pinned requirements, lines naming a local folder: the project itself)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    version = re.match(r"# Python (\S+)", lines[0])[1]
    pins = [line for line in lines[1:] if line.strip() and not line.startswith("#")]
    local = [line for line in pins if " @ file:" in line]
    return version, [line for line in pins if line not in local], local


def source_commit(source: Path) -> str:
    return run(["git", "-C", source, "rev-parse", "HEAD"]).stdout.strip()


def export_source(source: Path, commit: str, dest: Path):
    """The tracked files at `commit`, without history or anything left in the working tree."""
    dest.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "source.tar"
        result = run(["git", "-C", source, "archive", "--format=tar", "-o", archive, commit])
        if result.returncode:
            raise RuntimeError(f"git archive failed: {result.stderr.strip()}")
        with tarfile.open(archive) as tar:
            try:
                tar.extractall(dest, filter="data")
            except TypeError:  # Python releases before the extraction filters
                tar.extractall(dest)  # noqa: S202 (our own git archive)


def interpreter(project: dict, version: str) -> str:
    return "/usr/bin/python3" if project["python"] == "system" else version


def venv_python(project_dir: Path) -> Path:
    return project_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def build_environment(project_dir: Path, project: dict, snapshot: Path, log: list) -> Path:
    """Rebuild the recorded environment in project_dir/.venv with uv, from the snapshot's pins."""
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is needed to rebuild the environments")
    version, pins, _ = read_snapshot(snapshot)
    env_dir = project_dir / ".venv"
    seed = ["--seed"] if project.get("pip", True) else []
    steps = [[uv, "venv", "-q", *seed, "-p", interpreter(project, version), env_dir]]
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as stream:
        stream.write("\n".join(pins) + "\n")
        pinned = stream.name
    python = venv_python(project_dir)
    steps.append([uv, "pip", "install", "-q", "--python", python, "-r", pinned])
    # The project itself, installed from this copy the way the manifest says, without new dependencies.
    for line in project["install"]:
        words = shlex.split(line)
        if any(w == "." or w.startswith((".[", "./")) for w in words):
            steps.append([uv, "pip", "install", "-q", "--no-deps", "--python", python, *words])
    env = {**os.environ, "SETUPTOOLS_SCM_PRETEND_VERSION": project["ref"].lstrip("v")}
    try:
        for argv in steps:
            started = time.monotonic()
            result = run(argv, cwd=project_dir, env=env)
            log.append({"step": " ".join(str(a) for a in argv[1:5]), "exit_code": result.returncode,
                        "seconds": round(time.monotonic() - started, 1), "stderr": result.stderr[-2000:]})
            if result.returncode:
                raise RuntimeError(f"environment step failed: {result.stderr.strip()[-500:]}")
    finally:
        os.unlink(pinned)
    return python


def freeze(python: Path) -> list[str]:
    result = run(["uv", "pip", "freeze", "--python", python])
    return sorted(line for line in result.stdout.splitlines() if line.strip())


def freeze_difference(before: list[str], after: list[str]) -> dict:
    def table(lines):
        out = {}
        for line in lines:
            name = re.split(r"[=@ ]", line, maxsplit=1)[0].lower()
            out[name] = line
        return out
    a, b = table(before), table(after)
    return {"added": sorted(b[k] for k in b.keys() - a.keys()), "removed": sorted(a[k] for k in a.keys() - b.keys()),
            "changed": sorted(f"{a[k]} -> {b[k]}" for k in a.keys() & b.keys() if a[k] != b[k])}


def snapshot_mismatch(snapshot: Path, installed: list[str]) -> list[str]:
    """Pins of the snapshot that the rebuilt environment does not have exactly."""
    _, pins, _ = read_snapshot(snapshot)
    have = {line.lower() for line in installed}
    return [pin for pin in pins if pin.lower() not in have]


def _walk(project_dir: Path):
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for name in sorted(files):
            yield Path(root) / name


def is_test_file(relative: Path) -> bool:
    name = relative.name
    return (name == "conftest.py" or name == "pytest.ini" or name.startswith("test_") and name.endswith(".py")
            or name.endswith("_test.py") or bool(TEST_DIRS & set(relative.parts[:-1])))


def pytest_settings(project_dir: Path) -> dict:
    """The test-selecting pytest settings, by file and key (pytest.ini is hashed as a test file)."""
    found = {}
    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            options = data.get("tool", {}).get("pytest", {})
            options = options.get("ini_options", options) if isinstance(options, dict) else {}
            found.update({f"pyproject.toml:{k}": json.dumps(v, sort_keys=True) for k, v in options.items()
                          if k in SELECTING_KEYS})
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            found["pyproject.toml"] = "unreadable"
    for name, section in (("setup.cfg", "tool:pytest"), ("tox.ini", "pytest")):
        path = project_dir / name
        if not path.exists():
            continue
        parser = configparser.RawConfigParser(strict=False)
        try:
            parser.read_string(path.read_text(encoding="utf-8"))
        except (configparser.Error, UnicodeDecodeError):
            found[name] = "unreadable"
            continue
        if parser.has_section(section):
            found.update({f"{name}:{k}": " ".join(v.split()) for k, v in parser.items(section) if k in SELECTING_KEYS})
    return found


def integrity(project_dir: Path) -> dict:
    """Hashes of the test files, conftest.py files and test-selecting pytest settings."""
    state = {}
    for path in _walk(project_dir):
        relative = path.relative_to(project_dir)
        if is_test_file(relative):
            state[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for key, value in pytest_settings(project_dir).items():
        state[key] = hashlib.sha256(value.encode()).hexdigest()
    return state


def changed(before: dict, after: dict) -> list[str]:
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


def workspace_digest(project_dir: Path, python: Path | None) -> str:
    """Changes to the project files or to the installed distributions."""
    h = hashlib.sha256()
    for path in _walk(project_dir):
        h.update(path.relative_to(project_dir).as_posix().encode())
        h.update(path.read_bytes())
    venv = project_dir / ".venv"
    if python and venv.exists():
        for info in sorted(venv.rglob("*.dist-info")):
            h.update(info.name.encode())
    return h.hexdigest()


def clean_env(python: Path, home: Path) -> dict:
    """What the grader runs with: the case interpreter first on PATH, nothing inherited."""
    env = {k: os.environ[k] for k in CLEAN_ENV_KEYS if k in os.environ}
    env.update({"PATH": f"{python.parent}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(home),
                "LANG": "en_US.UTF-8", "VIRTUAL_ENV": str(python.parent.parent), "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    return env


def junit_outcomes(path: Path) -> dict:
    """Node outcome by test id from pytest's JUnit XML."""
    outcomes = {}
    if not path.exists():
        return outcomes
    for case in ElementTree.parse(path).getroot().iter("testcase"):
        node = f"{case.get('classname', '')}::{case.get('name', '')}"
        kinds = {child.tag for child in case}
        if "failure" in kinds:
            outcome = "failed"
        elif "error" in kinds:
            outcome = "error"
        elif "skipped" in kinds:
            skipped = next(child for child in case if child.tag == "skipped")
            outcome = "xfailed" if (skipped.get("type") or "").endswith("xfail") else "skipped"
        else:
            outcome = "passed"
        outcomes[node] = outcome
    return outcomes


def run_suite(project_dir: Path, python: Path, home: Path, timeout=1200) -> dict:
    """The full test suite, on a copy of the project (tests cannot change the workspace), with the
    case interpreter and a clean environment."""
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / project_dir.name
        shutil.copytree(project_dir, copy, symlinks=True,
                        ignore=shutil.ignore_patterns(".venv", ".pytest_cache", "__pycache__"))
        report = Path(scratch) / "junit.xml"
        started = time.monotonic()
        try:
            result = run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"],
                         cwd=copy, env=clean_env(python, home), timeout=timeout)
            code, output = result.returncode, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            code, output = 124, f"(timed out after {timeout} s)"
        outcomes = junit_outcomes(report)
    counts = {}
    for outcome in outcomes.values():
        counts[outcome] = counts.get(outcome, 0) + 1
    return {"exit_code": code, "counts": counts, "outcomes": outcomes, "seconds": round(time.monotonic() - started, 1),
            "summary": output.strip().splitlines()[-1] if output.strip() else ""}


def judge(result: dict, reference: dict, tests_changed: list[str]) -> dict:
    """Compare a suite run with the reference outcome."""
    reasons = []
    if tests_changed:
        reasons.append("tests, conftest.py or test-selecting pytest settings changed: " + ", ".join(tests_changed[:8]))
    if not result["outcomes"]:
        reasons.append(f"no test outcome was recorded (exit code {result['exit_code']}: {result['summary']})")
    bad = sorted(n for n, o in result["outcomes"].items() if o in ("failed", "error"))
    if bad:
        reasons.append(f"{len(bad)} tests failed or errored, e.g. {bad[0]}")
    expected = sorted(n for n, o in reference["outcomes"].items() if o == "passed")
    missing = [n for n in expected if result["outcomes"].get(n) != "passed"]
    if missing:
        reasons.append(f"{len(missing)} of the {len(expected)} tests that pass in the reference did not pass, "
                       f"e.g. {missing[0]}")
    allowed = {n for n, o in reference["outcomes"].items() if o in ("skipped", "xfailed")}
    extra = sorted(n for n, o in result["outcomes"].items() if o in ("skipped", "xfailed") and n not in allowed)
    if extra:
        reasons.append(f"{len(extra)} tests skipped or xfailed that the reference runs, e.g. {extra[0]}")
    if result["exit_code"] != 0 and reference.get("exit_code") == 0 and not reasons:
        reasons.append(f"pytest exited with {result['exit_code']}")
    return {"fixed": not reasons, "reasons": reasons, "counts": result["counts"],
            "reference_counts": reference["counts"], "tests_changed": tests_changed}
