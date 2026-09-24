"""Allowlisted checks with bounded output, deadlines and process-group cleanup."""

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
import time

from .models import Run, Session

MAX_OUTPUT = 1_000_000
DEFAULT_CHECKS = ("environment", "pip_check", "pytest", "ruff", "project")
TOOLS = (*DEFAULT_CHECKS, "pytest_run")


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


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop a check and everything it started."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if proc.poll() is None:
            proc.kill()
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


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
    if extra_env:
        env.update(extra_env)
    # A new process group/session lets a timeout stop the whole tree, and keeps a Ctrl+C in
    # the terminal from reaching the check directly.
    group = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            **group,
        )
    except OSError as exc:
        run.status = "launch_failed"
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
        if run.status != "completed" or proc.poll() is None:
            kill_tree(proc)
        proc.wait()
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
print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix,
 'python_version': sys.version.split()[0], 'packages': packages,
 'import_distributions': m.packages_distributions(),
 'stdlib_modules': sorted(getattr(sys, 'stdlib_module_names', ())),
 'paths': {k: paths.get(k, '') for k in ('stdlib', 'platstdlib', 'purelib', 'platlib')},
 'markers': {'implementation_name': sys.implementation.name,
 'implementation_version': implementation_version, 'os_name': os.name,
 'platform_machine': platform.machine(), 'platform_release': platform.release(),
 'platform_system': platform.system(), 'platform_version': platform.version(),
 'python_full_version': platform.python_version(),
 'platform_python_implementation': platform.python_implementation(),
 'python_version': '.'.join(platform.python_version_tuple()[:2]), 'sys_platform': sys.platform}}))
"""


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


def collect(session: Session, tool: str, timeout: float = 30, targets=None) -> Run:
    if tool not in TOOLS:
        raise ValueError("Unsupported check")
    targets = list(targets or [])
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
            probe.write_text(Path(__file__).with_name("probe.py").read_text(encoding="utf-8"))
            records_file = Path(directory) / "events.jsonl"
            extra = {
                "PYTHONPATH": directory + os.pathsep + os.environ.get("PYTHONPATH", ""),
                "FIXFIRST_PROBE": str(records_file),
                "PYTHONDONTWRITEBYTECODE": "1",
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
