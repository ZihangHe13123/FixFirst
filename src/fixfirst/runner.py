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
DEFAULT_CHECKS = ("environment", "pip_check", "pytest", "ruff")
TOOLS = (*DEFAULT_CHECKS, "pytest_run")


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


def validate_targets(session: Session, targets: list[str]):
    if not targets or len(targets) > 200 or len(targets) != len(set(targets)):
        raise ValueError("一次请选择 1–200 个不同的已观察测试节点")
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
            raise ValueError("测试节点格式无效；请从已有执行记录复制完整 node ID")
        path = Path(node.split("::", 1)[0])
        if (
            path.is_absolute()
            or not (root / path).resolve().is_relative_to(root)
            or node not in known
        ):
            raise ValueError("只允许重跑当前项目、当前解释器已观察到的测试节点")


def collect(session: Session, tool: str, timeout: float = 30, targets=None) -> Run:
    if tool not in TOOLS:
        raise ValueError("不支持的检查工具")
    targets = list(targets or [])
    if targets:
        if tool != "pytest_run":
            raise ValueError("只有 pytest_run 支持指定测试节点")
        validate_targets(session, targets)
    python, cwd = session.target_python, session.project_root
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
        with tempfile.TemporaryDirectory(prefix="fixfirst-probe-") as directory:
            probe = Path(directory) / "_fixfirst_probe.py"
            probe.write_text(Path(__file__).with_name("probe.py").read_text())
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
    run.targets = targets
    if tool == "pytest_run":
        run.notes.append("本次执行测试体与 fixture；目标范围以项目配置及记录的测试节点为准。")
    if tool == "environment" and run.status == "completed" and run.exit_code == 0:
        try:
            payload = json.loads(run.stdout)
            if not isinstance(payload, dict) or "packages" not in payload:
                raise ValueError()
            session.environment = payload
            run.tool_version = payload["python_version"]
        except (ValueError, KeyError):
            run.notes.append("环境快照格式无法识别")
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
