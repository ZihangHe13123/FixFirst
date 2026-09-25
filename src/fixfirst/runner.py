"""Allowlisted checks with bounded output, deadlines and process-group cleanup."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time

from .models import Run, Session
from .processes import ManagedProcess, ProcessCancelled

MAX_OUTPUT = 1_000_000
# Real test suites can take minutes; a check that runs longer is stopped and reported.
DEFAULT_TIMEOUT = 600
DEFAULT_CHECKS = ("environment", "pip_check", "pytest", "ruff", "project")
TOOLS = (*DEFAULT_CHECKS, "pytest_run", "version_search")
SEARCH_TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def redact(text: str) -> str:
    # pytest prints os.environ in tracebacks of environment lookups; never keep its contents.
    text = re.sub(r"environ\(\{[^\n]*", "environ({<redacted>})", text)
    text = re.sub(
        r"""(?i)(['"][\w.-]*(?:key|token|secret|passw(?:or)?d|credential)[\w.-]*['"]\s*:\s*)(['"])[^'"\n]*\2""",
        r"\1\2[credential]\2",
        text,
    )
    text = re.sub(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[credential]@", text)
    text = re.sub(r"(?i)\b(authorization\s*:\s*(?:bearer|basic)\s+)\S+", r"\1[credential]", text)
    text = re.sub(
        r"(?i)(\b(?:api[_-]?key|access[_-]?token|password|secret|token)"
        r"\s*[:=]\s*)[^\s,;]+",
        r"\1[credential]",
        text,
    )
    text = re.sub(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,})\b", "[credential]", text
    )
    return text


def venv_python(root: Path) -> Path:
    """Interpreter inside a virtual environment created with the venv module."""
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def activation_env(python: str) -> dict:
    """What activating the interpreter's environment would set.

    Tests often start console scripts by name (mypy, flask, a project's own command); they
    only find them when the environment's bin/Scripts folder is on PATH, as it is for a user
    who activated the environment.
    """
    folder = Path(python).parent
    root = folder.parent
    if os.name == "nt" and (folder / "conda-meta").is_dir():
        folders = [folder, folder / "Library/mingw-w64/bin", folder / "Library/usr/bin",
                   folder / "Library/bin", folder / "Scripts", folder / "bin"]
        return {"CONDA_PREFIX": str(folder),
                "PATH": os.pathsep.join(map(str, folders)) + os.pathsep + os.environ.get("PATH", "")}
    if not ((root / "pyvenv.cfg").is_file() or (root / "conda-meta").is_dir()):
        return {}
    return {"VIRTUAL_ENV": str(root), "PATH": str(folder) + os.pathsep + os.environ.get("PATH", "")}


def venv_site_packages(root: Path) -> Path:
    if os.name == "nt":
        return root / "Lib" / "site-packages"
    return next((root / "lib").glob("python*/site-packages"))


def environment_id(python: str) -> str:
    # Do not resolve symlinks: distinct venv interpreters may point at the same binary.
    # normcase makes C:\\Venv and c:\\venv the same interpreter on Windows (no-op elsewhere).
    return hashlib.sha256(os.path.normcase(os.path.abspath(python)).encode()).hexdigest()[:16]


def redact_data(value):
    """Redact string values without damaging the enclosing JSON syntax."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    return value


def kill_tree(proc: ManagedProcess) -> None:
    """Stop a check and everything it started."""
    proc.kill_tree()


def execute(
    argv: list[str],
    cwd: str,
    tool: str,
    scope: str,
    python: str,
    timeout: float = 30,
    max_output: int = MAX_OUTPUT,
    extra_env: dict | None = None,
) -> Run:
    if timeout <= 0 or max_output <= 0:
        raise ValueError("Timeout and output limit must be greater than zero")
    run = Run(tool=tool, argv=argv, cwd=cwd, scope=scope, environment_id=environment_id(python))
    start = time.monotonic()
    env = os.environ.copy()
    env.update(
        {
            "NO_COLOR": "1",
            "PYTHONUNBUFFERED": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            # Decode child output the same way on every platform (Windows defaults to the
            # console code page otherwise).
            "PYTHONIOENCODING": "utf-8",
        }
    )
    env.pop("RUFF_OUTPUT_FILE", None)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTHONHOME", None)
    env.update(activation_env(python))
    if extra_env:
        env.update(extra_env)
    # A new process group/session lets a timeout stop the whole tree, and keeps a Ctrl+C in
    # the terminal from reaching the check directly.
    try:
        proc = ManagedProcess(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        run.status = "cancelled" if isinstance(exc, ProcessCancelled) else "launch_failed"
        run.stderr = redact(str(exc))
        return run
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    total = [0]
    lock = threading.Lock()
    overflow = threading.Event()

    def pump(name, pipe):
        # Pipes cannot be polled with select() on Windows, so each stream gets a reader.
        try:
            while True:
                chunk = pipe.read1(8192)
                if not chunk:
                    return
                with lock:
                    remaining = max_output - total[0]
                    buffers[name].extend(chunk[:remaining])
                    total[0] += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        overflow.set()
                        return
        except (OSError, ValueError):
            return

    readers = [
        threading.Thread(target=pump, args=(name, getattr(proc, name)), daemon=True)
        for name in buffers
    ]
    for reader in readers:
        reader.start()
    try:
        # Finished only when the process exited and both streams reached end of file.
        while proc.poll() is None or any(r.is_alive() for r in readers):
            if proc.scope.cancelled:
                run.status = "cancelled"
                break
            if proc.poll() is not None:
                # A completed parent must not leave descendants holding our pipes open.
                kill_tree(proc)
            if overflow.is_set():
                run.status, run.truncated = "output_limit", True
                break
            if time.monotonic() - start > timeout:
                run.status = "timeout"
                break
            time.sleep(0.01)
    except KeyboardInterrupt:
        run.status = "cancelled"
    finally:
        proc.close()
        for reader in readers:
            reader.join(timeout=2)
        proc.stdout.close()
        proc.stderr.close()
    run.exit_code = proc.returncode
    run.duration_s = round(time.monotonic() - start, 3)
    stdout = buffers["stdout"].decode("utf-8", errors="replace")
    run.stdout = redact(stdout)
    if tool == "environment":
        try:
            run.stdout = json.dumps(redact_data(json.loads(stdout)), ensure_ascii=False)
        except ValueError:
            pass
    run.stderr = redact(buffers["stderr"].decode("utf-8", errors="replace"))
    return run


SNAPSHOT = """
import sys, json, os, platform, importlib.metadata as m
v = sys.implementation.version
implementation_version = f'{v.major}.{v.minor}.{v.micro}'
if v.releaselevel != 'final':
    implementation_version += {'alpha': 'a', 'beta': 'b', 'candidate': 'rc'}.get(v.releaselevel, v.releaselevel) + str(v.serial)
packages = []
for d in m.distributions():
    packages.append({'name': d.metadata.get('Name', ''), 'version': d.version,
                     'requires': d.requires or []})
import sysconfig
paths = sysconfig.get_paths()
# Python 3.8/3.9 have neither packages_distributions() nor sys.stdlib_module_names.
try:
    imports = m.packages_distributions()
except AttributeError:
    imports = {}
    for d in m.distributions():
        tops = (d.read_text('top_level.txt') or '').split()
        if not tops:
            for f in d.files or ():
                top = f.parts[0] if f.parts else ''
                top = top[:-3] if top.endswith('.py') else top
                if top.isidentifier() and top not in tops:
                    tops.append(top)
        for top in tops:
            imports.setdefault(top, []).append(d.metadata.get('Name', ''))
stdlib = getattr(sys, 'stdlib_module_names', None)
if stdlib is None:
    stdlib = set(sys.builtin_module_names)
    for folder in (paths['stdlib'], os.path.join(paths['stdlib'], 'lib-dynload')):
        for entry in (os.listdir(folder) if os.path.isdir(folder) else ()):
            base = entry.split('.')[0]
            if base.isidentifier() and entry != 'site-packages':
                stdlib.add(base)
print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix,
 'python_version': sys.version.split()[0], 'packages': packages,
 'import_distributions': imports,
 'stdlib_modules': sorted(stdlib),
 'paths': {k: paths.get(k, '') for k in ('stdlib', 'platstdlib', 'purelib', 'platlib')},
 'markers': {'implementation_name': sys.implementation.name,
 'implementation_version': implementation_version, 'os_name': os.name,
 'platform_machine': platform.machine(), 'platform_release': platform.release(),
 'platform_system': platform.system(), 'platform_version': platform.version(),
 'python_full_version': platform.python_version(),
 'platform_python_implementation': platform.python_implementation(),
 'python_version': '.'.join(platform.python_version_tuple()[:2]), 'sys_platform': sys.platform}}))
"""


def search_releases(session: Session, targets: list[str]) -> Run:
    """Try older releases of a library in a throwaway environment (versions.py)."""
    from packaging.utils import canonicalize_name

    from .versions import search

    if len(targets) != 2 or not all(isinstance(t, str) and SEARCH_TARGET.match(t) for t in targets):
        raise ValueError("A release search needs a distribution name and a dotted name")
    dist, api = targets
    python = session.target_python
    run = Run(tool="version_search", argv=["version-search", dist, api], cwd=session.project_root,
              scope=f"versions:{canonicalize_name(dist)}:{api}", environment_id=environment_id(python))
    run.targets = targets
    environment = session.environment if session.environment.get("_environment_id") == run.environment_id else {}
    installed = next(
        (p.get("version") for p in environment.get("packages", [])
         if canonicalize_name(p.get("name", "")) == canonicalize_name(dist)),
        None,
    )
    start = time.monotonic()
    if not installed or not environment.get("python_version"):
        run.status, run.stderr = "launch_failed", "Take an environment snapshot first (press Check again)."
        return run
    result = search(python, environment["python_version"], environment.get("markers", {}), dist, installed, api)
    run.stdout = json.dumps(result)
    run.exit_code = 0
    run.duration_s = round(time.monotonic() - start, 3)
    return run


def validate_targets(session: Session, targets: list[str]):
    if not targets or len(targets) > 200 or len(targets) != len(set(targets)):
        raise ValueError("Choose 1-200 distinct, previously observed test nodes")
    known = {
        r.get("nodeid")
        for run in session.runs
        if run.tool == "pytest_run"
        and run.source == "executed"
        and run.environment_id == environment_id(session.target_python)
        for r in run.records
        if r.get("type") in ("outcome", "failure")
    }
    root = Path(session.project_root).resolve()
    for node in targets:
        if (
            not isinstance(node, str)
            or len(node) > 2000
            or any(c in node for c in ("\n", "\r", "\0"))
            or node.startswith("-")
            or "::" not in node
        ):
            raise ValueError("Invalid test node; copy the full node id from an earlier run")
        path = Path(node.split("::", 1)[0])
        if (
            path.is_absolute()
            or not (root / path).resolve().is_relative_to(root)
            or node not in known
        ):
            raise ValueError("Only nodes observed in this project with the current interpreter can be re-run")


def collect(session: Session, tool: str, timeout: float = DEFAULT_TIMEOUT, targets=None) -> Run:
    if tool not in TOOLS:
        raise ValueError("Unsupported check")
    targets = list(targets or [])
    if tool == "version_search":
        return search_releases(session, targets)
    if targets:
        if tool != "pytest_run":
            raise ValueError("Only pytest_run accepts test nodes")
        validate_targets(session, targets)
    python, cwd = session.target_python, session.project_root
    if tool == "project":
        from .project import collect_project

        return collect_project(session, environment_id(python))
    if tool == "environment":
        session.environment = {}  # A failed refresh must not leave the previous snapshot active.
    commands = {
        "environment": [python, "-c", SNAPSHOT],
        "pip_check": [python, "-m", "pip", "check"],
        "ruff": [
            python,
            "-m",
            "ruff",
            "check",
            "--no-fix",
            "--no-fix-only",
            "--no-unsafe-fixes",
            "--no-cache",
            "--output-format",
            "json",
            ".",
        ],
        "pytest": [
            python,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--color=no",
            "-o",
            "addopts=",
            "-p",
            "_fixfirst_probe",
        ],
    }
    commands["pytest_run"] = [arg for arg in commands["pytest"] if arg != "--collect-only"]
    commands["pytest_run"] += ["--rootdir", cwd]
    if targets:
        commands["pytest_run"] += ["--", *targets]
    argv = commands[tool]
    scope = {
        "pytest": "collect:project",
        "ruff": "lint:project",
        "pip_check": "dependencies:environment",
        "environment": "environment",
        "pytest_run": "tests:selected" if targets else "tests:project",
    }[tool]
    if tool in ("pytest", "pytest_run"):
        with tempfile.TemporaryDirectory(prefix="fixfirst-probe-", ignore_cleanup_errors=True) as directory:
            probe = Path(directory) / "_fixfirst_probe.py"
            probe.write_text(Path(__file__).with_name("probe.py").read_text(encoding="utf-8"), encoding="utf-8")
            records_file = Path(directory) / "events.jsonl"
            extra = {
                "PYTHONPATH": os.pathsep.join([directory, *[
                    part or cwd for part in os.environ.get("PYTHONPATH", "").split(os.pathsep)
                ]]),
                "FIXFIRST_PROBE": str(records_file),
                "PYTHONDONTWRITEBYTECODE": "1",
                "FIXFIRST_USER_IOENCODING": os.environ.get("PYTHONIOENCODING", ""),
            }
            run = execute(argv, cwd, tool, scope, python, timeout, extra_env=extra)
            if records_file.exists():
                raw = records_file.read_bytes()[:MAX_OUTPUT]
                for line in raw.decode("utf-8", "replace").splitlines():
                    try:
                        record = redact_data(json.loads(line))
                        if isinstance(record, dict):
                            run.records.append(record)
                    except ValueError:
                        run.notes.append("Structured test events were incomplete")
            run.notes.append(
                "Test collection imports project modules and conftest; only run it on code you trust."
            )
    elif tool in ("environment", "pip_check"):
        # Neither needs the project directory; running there would let a project file such
        # as random.py shadow the standard library and break the check itself.
        with tempfile.TemporaryDirectory(prefix="fixfirst-env-", ignore_cleanup_errors=True) as directory:
            run = execute(argv, directory, tool, scope, python, timeout)
        run.cwd = cwd
    else:
        run = execute(argv, cwd, tool, scope, python, timeout)
    run.targets = targets
    if tool == "pytest_run":
        run.notes.append("This run executed test bodies and fixtures; scope follows the project configuration and the recorded nodes.")
    if tool == "environment" and run.status == "completed" and run.exit_code == 0:
        try:
            payload = json.loads(run.stdout)
            if not isinstance(payload, dict) or "packages" not in payload:
                raise ValueError()
            session.environment = payload
            session.environment["_run_id"] = run.run_id
            session.environment["_environment_id"] = run.environment_id
            run.tool_version = payload["python_version"]
        except (ValueError, KeyError):
            run.notes.append("Environment snapshot format not recognised")
    package = {"pytest": "pytest", "pytest_run": "pytest", "ruff": "ruff", "pip_check": "pip"}.get(
        tool
    )
    if package:
        run.tool_version = next(
            (
                p["version"]
                for p in session.environment.get("packages", [])
                if p.get("name", "").lower() == package
            ),
            "unknown",
        )
    return run
