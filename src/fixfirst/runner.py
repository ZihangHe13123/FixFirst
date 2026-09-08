"""Allowlisted checks with bounded output, deadlines and process-group cleanup."""

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import tempfile
import time

from .models import Run, Session

MAX_OUTPUT = 1_000_000
TOOLS = ("environment", "pip_check", "pytest", "ruff")


def redact(text: str) -> str:
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


def environment_id(python: str) -> str:
    # Do not resolve symlinks: distinct venv interpreters may point at the same binary.
    return hashlib.sha256(os.path.abspath(python).encode()).hexdigest()[:16]


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
        raise ValueError("超时与输出上限必须大于零")
    run = Run(tool=tool, argv=argv, cwd=cwd, scope=scope, environment_id=environment_id(python))
    start = time.monotonic()
    env = os.environ.copy()
    env.update({"NO_COLOR": "1", "PYTHONUNBUFFERED": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    env.pop("RUFF_OUTPUT_FILE", None)
    env.pop("PYTEST_ADDOPTS", None)
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        run.status = "launch_failed"
        run.stderr = redact(str(exc))
        return run
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    total = 0

    def kill():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        with selectors.DefaultSelector() as selector:
            for name in buffers:
                pipe = getattr(proc, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while selector.get_map():
                if time.monotonic() - start > timeout:
                    run.status = "timeout"
                    kill()
                    break
                for key, _ in selector.select(timeout=0.05):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    remaining = max_output - total
                    buffers[key.data].extend(chunk[:remaining])
                    total += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        run.status, run.truncated = "output_limit", True
                        kill()
                        break
                if run.truncated:
                    break
            if proc.poll() is None:
                try:
                    proc.wait(timeout=max(0.01, timeout - (time.monotonic() - start)))
                except subprocess.TimeoutExpired:
                    run.status = "timeout"
                    kill()
    except KeyboardInterrupt:
        run.status = "cancelled"
        kill()
    finally:
        if proc.poll() is None:
            kill()
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()
    run.exit_code = proc.returncode
    run.duration_s = round(time.monotonic() - start, 3)
    run.stdout = redact(buffers["stdout"].decode("utf-8", errors="replace"))
    run.stderr = redact(buffers["stderr"].decode("utf-8", errors="replace"))
    return run


SNAPSHOT = """
import sys, json, importlib.metadata as m
packages = []
for d in m.distributions():
    packages.append({'name': d.metadata.get('Name', ''), 'version': d.version,
                     'requires': d.requires or []})
print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix,
 'python_version': sys.version.split()[0], 'packages': packages,
 'import_distributions': m.packages_distributions()}))
"""


def collect(session: Session, tool: str, timeout: float = 30) -> Run:
    if tool not in TOOLS:
        raise ValueError("仅允许 environment、pip_check、pytest、ruff 检查")
    python, cwd = session.target_python, session.project_root
    argv = {
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
    }[tool]
    scope = {
        "pytest": "collect:project",
        "ruff": "lint:project",
        "pip_check": "dependencies:environment",
        "environment": "environment",
    }[tool]
    if tool == "pytest":
        with tempfile.TemporaryDirectory(prefix="fixfirst-probe-") as directory:
            probe = Path(directory) / "_fixfirst_probe.py"
            probe.write_text(Path(__file__).with_name("probe.py").read_text())
            records_file = Path(directory) / "events.jsonl"
            extra = {
                "PYTHONPATH": directory + os.pathsep + os.environ.get("PYTHONPATH", ""),
                "FIXFIRST_PROBE": str(records_file),
            }
            run = execute(argv, cwd, tool, scope, python, timeout, extra_env=extra)
            if records_file.exists():
                raw = records_file.read_bytes()[:MAX_OUTPUT]
                for line in raw.decode("utf-8", "replace").splitlines():
                    try:
                        record = json.loads(redact(line))
                        if isinstance(record, dict):
                            run.records.append(record)
                    except ValueError:
                        run.notes.append("结构化测试事件不完整")
            run.notes.append(
                "测试收集会执行项目导入和 conftest；与目标项目正常运行一样需信任源码。"
            )
    else:
        run = execute(argv, cwd, tool, scope, python, timeout)
    if tool == "environment" and run.status == "completed" and run.exit_code == 0:
        try:
            payload = json.loads(run.stdout)
            if not isinstance(payload, dict) or "packages" not in payload:
                raise ValueError()
            session.environment = payload
            run.tool_version = payload["python_version"]
        except (ValueError, KeyError):
            run.notes.append("环境快照格式无法识别")
    package = {"pytest": "pytest", "ruff": "ruff", "pip_check": "pip"}.get(tool)
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
