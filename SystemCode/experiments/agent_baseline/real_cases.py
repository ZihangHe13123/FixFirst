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
test-selecting pytest setting was changed at any check during the run, pytest exits 0, the same
tests are collected as in the reference, nothing fails, and every test that passes in the
reference passes. A reference that does not itself meet this bar is invalid and grades nothing.

The above is the default legacy protocol. Opt-in h5-v1 uses pytest_policy.py to allow
only persistent import/settings options, protect the configuration-carrier set, and
observe actual explicit settings and exact collected nodes with a grader-only probe.

Where code runs: creating the environment and installing the snapshot's pinned packages happens
outside the sandbox, before the agent starts (uv then runs the new environment's interpreter, which
holds only the snapshot's packages). After that the case's interpreter is never started outside the
sandbox: its home and version come from pyvenv.cfg as written at creation (venv_record), installed
packages from their metadata files (freeze). Everything that runs the project's code (installing the
project itself, the agent's commands, the tests of the grader and of the reference) is started by
the harness under the sandbox (isolation.py); this module only builds the commands.
"""

import configparser
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ElementTree

import pytest_policy as pp

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


@contextmanager
def open_regular(path: Path):
    """A binary stream of a regular file, or None for anything else (a folder, a named pipe, a device,
    a link to one of them, a missing file). The harness reads the agent's files outside the sandbox,
    so opening must never wait: a plain open of a named pipe waits until something writes to it."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        fd = None
    if fd is not None and not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        fd = None
    if fd is None:
        yield None
        return
    with os.fdopen(fd, "rb") as stream:
        yield stream


def read_regular(path: Path, limit: int = 16 << 20) -> bytes | None:
    """A regular file's bytes; None for anything else or for a file over `limit` bytes."""
    with open_regular(path) as stream:
        data = stream.read(limit + 1) if stream else None
    return data if data is not None and len(data) <= limit else None


def write_regular(path: Path, text: str):
    """Write text into a regular file (created if missing) for the agent's write_file tool: the final
    name is not followed if it is a link, and a named pipe is refused instead of waited on."""
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags | getattr(os, "O_NONBLOCK", 0), 0o666)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError(f"{path.name} is not a regular file")
    with os.fdopen(fd, "wb") as stream:
        stream.truncate(0)
        stream.write(text.encode("utf-8"))


def file_hash(path: Path) -> str:
    """sha256 of a regular file, read in pieces; a fixed value for anything else, so that a test file
    replaced by a named pipe still counts as changed."""
    with open_regular(path) as stream:
        if stream is None:
            return "not a regular file"
        h = hashlib.sha256()
        for piece in iter(lambda: stream.read(1 << 20), b""):
            h.update(piece)
        return h.hexdigest()


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


def create_environment(project_dir: Path, project: dict, snapshot: Path, log: list) -> Path:
    """Create project_dir/.venv and install the snapshot's pinned packages (no project code runs)."""
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is needed to rebuild the environments")
    version, pins, _ = read_snapshot(snapshot)
    env_dir = project_dir / ".venv"
    seed = ["--seed"] if project.get("pip", True) else []
    python = venv_python(project_dir)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as stream:
        stream.write("\n".join(pins) + "\n")
        pinned = stream.name
    try:
        for argv in ([uv, "venv", "-q", *seed, "-p", interpreter(project, version), env_dir],
                     [uv, "pip", "install", "-q", "--python", python, "-r", pinned]):
            started = time.monotonic()
            result = run(argv, cwd=project_dir)
            log.append({"step": " ".join(str(a) for a in argv[1:5]), "exit_code": result.returncode,
                        "seconds": round(time.monotonic() - started, 1), "stderr": result.stderr[-2000:]})
            if result.returncode:
                raise RuntimeError(f"environment step failed: {result.stderr.strip()[-500:]}")
    finally:
        os.unlink(pinned)
    return python


# pip install options whose next word is their value (a requirements file, a folder of links, an index...),
# never something the line installs.
VALUE_OPTIONS = {"-r", "--requirement", "-c", "--constraint", "-f", "--find-links", "-i", "--index-url",
                 "--extra-index-url", "-t", "--target", "--prefix", "--root", "--src", "--platform",
                 "--python-version", "--implementation", "--abi", "--upgrade-strategy", "--trusted-host", "--cert",
                 "--client-cert", "--cache-dir", "--log", "--proxy", "--retries", "--timeout", "--exists-action",
                 "--global-option", "--config-settings", "-C", "--no-binary", "--only-binary", "--report",
                 "--progress-bar", "--keyring-provider", "--use-feature", "--use-deprecated", "--python", "--group"}
PROJECT_TARGET = re.compile(r"\.(\[[A-Za-z0-9][A-Za-z0-9._-]*(,[A-Za-z0-9][A-Za-z0-9._-]*)*\])?")


def install_targets(line: str) -> list[str]:
    """What a manifest install line installs: its positional words and the values of -e/--editable. The
    values of the other options are skipped, so `-r ./requirements.txt` or `--find-links . pytest` never
    look like the project."""
    words, targets, i = shlex.split(line), [], 0
    while i < len(words):
        word = words[i]
        if word in ("-e", "--editable") and i + 1 < len(words):
            targets.append(words[i + 1])
            i += 2
            continue
        if word.startswith("--editable="):
            targets.append(word.removeprefix("--editable="))
        elif word in VALUE_OPTIONS:
            i += 1  # its value
        elif not word.startswith("-"):
            targets.append(word)
        i += 1
    return targets


def installs_project(line: str) -> bool:
    """Whether a manifest install line installs the project itself (third-party packages come from the
    snapshot instead)."""
    return any(t == "." or t.startswith((".[", "./")) for t in install_targets(line))


def registrable_install(line: str) -> bool:
    """Whether `install_fails` may name this line: a plain install of the project itself and nothing else
    (`.`, `.[extras]`, `-e .`, `-e .[extras]`, `--editable=.`). Anything more complex is refused."""
    try:
        words = shlex.split(line)
    except ValueError:
        return False
    if len(words) == 2 and words[0] in ("-e", "--editable"):
        words = words[1:]
    elif len(words) == 1 and words[0].startswith("--editable="):
        words = [words[0].removeprefix("--editable=")]
    return len(words) == 1 and PROJECT_TARGET.fullmatch(words[0]) is not None


def install_steps(project: dict, python: Path, uv_cache: Path) -> list[dict]:
    """The commands that install the project itself from its folder, without new dependencies, each
    with its manifest line and whether the manifest registers it as failing at the start
    (`install_fails`). They run the project's build code, so the harness runs them in the sandbox
    (with the network for build requirements)."""
    fails = set(project.get("install_fails", []))
    steps = []
    for line in project["install"]:
        if not installs_project(line):
            continue  # third-party packages: already in the snapshot
        words = shlex.split(line)
        if project.get("pip", True):
            argv = [str(python), "-m", "pip", "install", "-q", "--no-deps", *words]
        else:
            argv = [shutil.which("uv") or "uv", "pip", "install", "-q", "--no-deps", "--no-config",
                    "--cache-dir", str(uv_cache), "--python", str(python), *words]
        steps.append({"line": line, "argv": argv, "expected_failure": line in fails})
    return steps


def install_commands(project: dict, python: Path, uv_cache: Path) -> list[list[str]]:
    """The same commands without their marks (as before `install_fails`), for the core-diagnosis checks."""
    return [step["argv"] for step in install_steps(project, python, uv_cache)]


def install_fails_problems(project: dict) -> list[str]:
    """`install_fails` registers, before any run, the install lines of the project itself that fail at
    the start (the starting state of the case). It may name nothing else."""
    fails = project.get("install_fails", [])
    if not isinstance(fails, list) or not all(isinstance(line, str) for line in fails):
        return ["install_fails must be a list of the project's install lines"]
    problems = [f"install_fails names {line!r} more than once" for line in sorted(set(fails)) if fails.count(line) > 1]
    for line in dict.fromkeys(fails):
        if line not in project.get("install", []):
            problems.append(f"install_fails names {line!r}, which is not one of its install lines")
        elif not registrable_install(line):
            problems.append(f"install_fails names {line!r}, which is not a plain install of the project itself "
                            "(only ., .[extras], -e . or -e .[extras] can be registered)")
    return problems


def install_fails_registered(project: dict) -> int:
    """How many of the project's install steps are registered as failing at the start."""
    fails = set(project.get("install_fails", []))
    return sum(1 for line in project.get("install", []) if line in fails and installs_project(line))


def registered_failure_problem(code, stopped) -> str | None:
    """Why one execution of a registered failing install step does not reach the registered start (None
    when it does). The start is the state after the step ran to completion and exited with an error of its
    own; a step stopped at its time limit, ended by a signal, or with no record that it ran to completion
    never reached it. Runs and references both judge by this."""
    if stopped is True:
        return "was stopped at its time limit"
    if stopped is not False:
        return "has no record that it ran to completion"
    if type(code) is not int:
        return "did not finish"
    if code == 0:
        return "succeeded"
    if code < 0:
        return f"was ended by signal {-code}"
    return None


def venv_record(venv: Path) -> dict:
    """What the environment's pyvenv.cfg says, read (never run) right after it is created: the folder
    of the base interpreter, the version, and the folders the interpreter needs to read."""
    values = {}
    for line in (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip().lower()] = value.strip()
    home = Path(values["home"])
    return {"home": str(home), "version": values.get("version_info") or values.get("version") or "unknown",
            "interpreters": sorted({os.path.realpath(home), os.path.realpath(home.parent)})}


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _headers(path: Path) -> dict:
    found = {}
    with open_regular(path) as stream:
        for _ in range(5000 if stream else 0):
            line = stream.readline(1 << 16).decode("utf-8", "replace")
            if not line.strip():
                break  # the metadata headers end at the first blank line
            key, sep, value = line.partition(":")
            if sep and key in ("Name", "Version") and key not in found:
                found[key] = value.strip()
            if len(found) == 2:
                break
    return found


def freeze(python: Path) -> list[str]:
    """The installed distributions like `pip freeze`, read from their metadata files; nothing is run,
    so no startup hook (.pth, sitecustomize) of the environment executes. Only regular files are read."""
    venv, lines = python.parent.parent, set()
    for site in sorted(venv.glob("lib/python*/site-packages")) + sorted(venv.glob("Lib/site-packages")):
        for info in sorted(site.glob("*.dist-info")) + sorted(site.glob("*.egg-info")):
            headers = _headers(info / ("METADATA" if info.suffix == ".dist-info" else "PKG-INFO"))
            if not headers.get("Name"):
                continue
            try:
                url = json.loads(read_regular(info / "direct_url.json", 1 << 20) or b"{}")
            except ValueError:
                url = {}
            if isinstance(url, dict) and url.get("url"):
                editable = isinstance(url.get("dir_info"), dict) and url["dir_info"].get("editable")
                lines.add(f"-e {url['url']}" if editable else f"{canonical(headers['Name'])} @ {url['url']}")
            else:
                lines.add(f"{canonical(headers['Name'])}=={headers.get('Version', '')}")
    return sorted(lines)


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

    def key(line):
        name, sep, version = line.partition("==")
        return f"{canonical(name)}=={version}" if sep else line.lower()
    have = {key(line) for line in installed}
    return [pin for pin in pins if key(pin) not in have]


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

    def text(path):
        data = read_regular(path)
        if data is None:
            raise ValueError("not a regular file of a sensible size")
        return data.decode("utf-8")
    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(text(pyproject))
            options = data.get("tool", {}).get("pytest", {})
            options = options.get("ini_options", options) if isinstance(options, dict) else {}
            found.update({f"pyproject.toml:{k}": json.dumps(v, sort_keys=True) for k, v in options.items()
                          if k in SELECTING_KEYS})
        except ValueError:  # also TOMLDecodeError and UnicodeDecodeError
            found["pyproject.toml"] = "unreadable"
    for name, section in (("setup.cfg", "tool:pytest"), ("tox.ini", "pytest")):
        path = project_dir / name
        if not path.exists():
            continue
        parser = configparser.RawConfigParser(strict=False)
        try:
            parser.read_string(text(path))
        except (configparser.Error, ValueError):
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
            state[relative.as_posix()] = file_hash(path)
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
        h.update(file_hash(path).encode())
    venv = project_dir / ".venv"
    if python and venv.exists():
        for info in sorted(venv.rglob("*.dist-info")):
            h.update(info.name.encode())
    return h.hexdigest()


def clean_env(python: Path, home: Path, tmp: Path | None = None) -> dict:
    """The case interpreter first on PATH, its own HOME and temporary folder, nothing inherited."""
    env = {k: os.environ[k] for k in CLEAN_ENV_KEYS if k in os.environ}
    env.update({"PATH": f"{python.parent}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(home),
                "LANG": "en_US.UTF-8", "VIRTUAL_ENV": str(python.parent.parent), "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    if tmp:
        env["TMPDIR"] = str(tmp)
    return env


def junit_outcomes(path: Path) -> dict:
    """Node outcome by test id from pytest's JUnit XML."""
    outcomes = {}
    if not path.exists():
        return outcomes
    data = read_regular(path, 256 << 20)
    if data is None:
        raise ElementTree.ParseError(f"{path.name} is not a regular file of a sensible size")
    for case in ElementTree.fromstring(data).iter("testcase"):
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


def _grader_ignore(folder, names) -> set:
    """Left out of the grader's copy: the environment, caches, and special files (named pipes,
    sockets), which hold no content and cannot be copied."""
    left_out = {".venv", ".pytest_cache", "__pycache__"} & set(names)
    for name in names:
        try:
            mode = os.lstat(os.path.join(folder, name)).st_mode
        except OSError:
            continue
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
            left_out.add(name)
    return left_out


def run_suite(project_dir: Path, python: Path, grader_dir: Path, execute, timeout=1200,
              grading_policy=pp.LEGACY) -> dict:
    """The full test suite on a copy of the project in grader_dir (so the tests cannot change the
    workspace), with the case interpreter and a clean environment. `execute(argv, cwd, env, timeout)`
    runs it in the sandbox and returns (exit code, output, stopped)."""
    copy, home, tmp = grader_dir / "project", grader_dir / "home", grader_dir / "tmp"
    shutil.copytree(project_dir, copy, symlinks=True, ignore=_grader_ignore)
    home.mkdir()
    tmp.mkdir()
    report = grader_dir / "junit.xml"
    argv = [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"]
    env = clean_env(python, home, tmp)
    if grading_policy == pp.H5:
        shutil.copyfile(pp.PROBE, grader_dir / pp.PROBE.name)
        # Import the trusted probe ahead of cwd, then restore normal project import paths.
        # A project-local module with the same name cannot replace it, and the grader directory
        # does not become an extra application import root.
        launcher = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
                    "import _h5_grading_probe as probe; sys.path.pop(0); "
                    "import pytest; raise SystemExit(pytest.main(sys.argv[1:], plugins=[probe]))")
        argv = [str(python), "-c", launcher, str(grader_dir), *argv[3:]]
        env.update(FIXFIRST_H5_REPORT=str(grader_dir / "h5-observation.json"))
        state = pp.snapshot(copy)
    started = time.monotonic()
    code, output, stopped = execute(argv, copy, env, timeout)
    junit_error = None
    try:
        outcomes = junit_outcomes(report)
    except (OSError, ElementTree.ParseError) as error:
        if grading_policy != pp.H5:
            raise  # unchanged legacy behavior
        outcomes, junit_error = {}, f"{type(error).__name__}: {error}"[:500]
    counts = {}
    for outcome in outcomes.values():
        counts[outcome] = counts.get(outcome, 0) + 1
    result = {"exit_code": code, "stopped": stopped, "counts": counts, "outcomes": outcomes,
              "seconds": round(time.monotonic() - started, 1),
              "summary": output.strip().splitlines()[-1] if output.strip() else ""}
    if grading_policy == pp.H5:
        try:
            observation = json.loads(pp.read_file(grader_dir / "h5-observation.json", 64 << 20))
        except (OSError, ValueError):
            observation = None
        result.update(grading_policy=pp.H5, grading_policy_sha256=pp.identity(),
                      h5_observation=observation, h5_state=state, h5_process_stopped=stopped,
                      h5_junit_error=junit_error)
    return result


EXIT_CODES = {1: "tests failed", 2: "interrupted", 3: "internal error", 4: "usage error", 5: "no tests collected",
              124: "stopped at the time limit"}


def validate_reference(reference: dict) -> list[str]:
    """A reference can grade only if its repair worked and its own suite passed cleanly."""
    problems = []
    for step in reference.get("repair", []):
        code = step.get("exit_code")
        if step.get("expected_failure"):
            # The registered starting state: this step must fail, as it did before any run.
            problem = registered_failure_problem(code, step.get("stopped"))
            if problem:
                problems.append(f"the registered failing step {step['command']!r} {problem}: "
                                "the start is not the registered one")
        elif code != 0:
            problems.append(f"repair step {step['command']!r} exited with {code}")
    if reference.get("exit_code") != 0:
        code = reference.get("exit_code")
        problems.append(f"the reference suite exited with {code} ({EXIT_CODES.get(code, 'unexpected')})")
    outcomes = reference.get("outcomes") or {}
    if not any(o == "passed" for o in outcomes.values()):
        problems.append("no test passed in the reference")
    bad = sorted(n for n, o in outcomes.items() if o in ("failed", "error"))
    if bad:
        problems.append(f"{len(bad)} tests failed or errored in the reference, e.g. {bad[0]}")
    if reference.get("grading_policy", pp.LEGACY) == pp.H5:
        problems += h5_problems(reference)
        baseline = reference.get("h5_baseline")
        invalid_baseline = pp.state_problems(baseline)
        if invalid_baseline:
            problems += invalid_baseline
        elif baseline.get("errors"):
            problems.append("H5 reference baseline cannot be inspected")
        else:
            violations = reference.get("h5_violations")
            if not isinstance(violations, dict):
                problems.append("H5 reference lacks repair integrity checks")
            elif violations or (not pp.state_problems(reference.get("h5_state"))
                                and pp.violations(baseline, reference["h5_state"])):
                problems.append("H5 reference repair violated the protection rule")
        observed = reference.get("h5_observation")
        if not pp.observation_problems(observed, reference.get("exit_code")) and not any(
                o == "passed" for o in observed["outcomes"].values()):
            problems.append("H5 no collected node passed in the reference observation")
    return problems


def h5_problems(suite: dict) -> list[str]:
    if suite.get("grading_policy") != pp.H5 or suite.get("grading_policy_sha256") != pp.identity():
        return ["H5 suite is missing or bound to another grading implementation"]
    if suite.get("h5_process_stopped") is not False:
        return ["H5 suite was stopped or lacks process completion metadata"]
    if suite.get("h5_junit_error"):
        return ["H5 JUnit report could not be read: " + suite["h5_junit_error"]]
    problems = pp.observation_problems(suite.get("h5_observation"), suite.get("exit_code"))
    state = suite.get("h5_state")
    state_errors = pp.state_problems(state)
    if state_errors:
        return problems + state_errors
    if state["errors"]:
        return problems + ["H5 suite configuration or tests cannot be inspected"]
    return problems or pp.configuration_problems(suite["h5_observation"], state)


def judge(result: dict, reference: dict, violations: list[str]) -> dict:
    """Compare a suite run with a valid reference outcome (see validate_reference)."""
    reasons = []
    h5 = reference.get("grading_policy", pp.LEGACY) == pp.H5
    if h5:
        result_errors = h5_problems(result)
        conclusive_failure = pp.failed_check(result)
        invalid = validate_reference(reference) + ([] if violations or conclusive_failure else result_errors)
        if invalid:
            raise ValueError("; ".join(invalid))
        if not result_errors:
            reasons += pp.compare(result, reference)
        elif conclusive_failure:
            reasons.append("H5 pytest failed after the grader probe started; complete success observations are unavailable")
    elif result.get("grading_policy", pp.LEGACY) != pp.LEGACY:
        raise ValueError("candidate and reference use different grading policies")
    if violations:
        reasons.append(("H5 protected tests or configuration changed during the run: " if h5 else
                        "tests, conftest.py or test-selecting pytest settings changed during the run: ")
                       + ", ".join(violations[:8]))
    code = result["exit_code"]
    if code != 0:
        reasons.append(f"pytest exited with {code} ({EXIT_CODES.get(code, 'unexpected')}): {result['summary']}")
    expected, found = set(reference["outcomes"]), set(result["outcomes"])
    if expected - found:
        missing = sorted(expected - found)
        reasons.append(f"{len(missing)} tests of the reference were not run, e.g. {missing[0]}")
    if found - expected:
        extra = sorted(found - expected)
        reasons.append(f"{len(extra)} tests that the reference does not have, e.g. {extra[0]}")
    bad = sorted(n for n, o in result["outcomes"].items() if o in ("failed", "error"))
    if bad:
        reasons.append(f"{len(bad)} tests failed or errored, e.g. {bad[0]}")
    lost = sorted(n for n, o in reference["outcomes"].items()
                  if o == "passed" and result["outcomes"].get(n) not in (None, "passed", "failed", "error"))
    if lost:
        reasons.append(f"{len(lost)} tests that pass in the reference were skipped, e.g. {lost[0]}")
    return {"fixed": not reasons, "reasons": reasons, "counts": result["counts"],
            "reference_counts": reference["counts"], "tests_changed": sorted(violations)}


REFERENCE_KEYS = ("key", "commit", "repair", "exit_code", "counts", "outcomes", "problems")


def read_reference_cache(path: Path, key: str, attempt: str, grading_policy=pp.LEGACY) -> tuple[dict | None, str | None]:
    """A cached reference only if it is complete, for this key and still valid. Anything else is set
    aside (renamed, never deleted) and reported, so that the reference is built again."""
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in REFERENCE_KEYS if not isinstance(data, dict) or k not in data]
        problem = (f"missing {', '.join(missing)}" if missing else "another key" if data["key"] != key
                   else "another grading policy" if data.get("grading_policy", pp.LEGACY) != grading_policy
                   else "; ".join(data["problems"] or validate_reference(data)) or None)
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
        problem = f"unreadable ({type(error).__name__})"
    if not problem:
        return data, None
    aside = path.with_name(f"{path.name}.unusable-{attempt}")
    path.rename(aside)
    return None, f"the cached reference was not usable ({problem}); kept as {aside.name} and built again"


def write_json(path: Path, data) -> None:
    """Write through a temporary file and rename, so that a reader never sees half a file."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)
