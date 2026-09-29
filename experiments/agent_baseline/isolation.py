"""Restricted execution, time budgets and run identities for the agent harness (task B7).

Every process that runs a case's code (the agent's commands, FixFirst's MCP server and the checks
it starts, the grader, the reference repair and its test run, installing the project itself) runs
under macOS sandbox-exec with a Policy:

- it writes only to the folders the policy names (a run's project, state and temporary folder, or
  the grader's own copy); never the system temporary folder, other runs or the repository;
- under the home folder, the output folder, the repository and the system temporary folders it
  reads only what the policy names (the run's own folders, the interpreters and, for FixFirst's
  server, FixFirst's code), so reference repairs, labels, reference outcomes and other runs stay
  out of reach; ~/.ssh, ~/.omlx, ~/.claude and the keychains are never readable;
- it has the network only when the policy says so.

Processes start in their own process group and the whole group is killed at the deadline.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tempfile
import time

HOME = Path.home()
SENSITIVE = (".ssh", ".omlx", ".claude", "Library/Keychains")
SYSTEM_TEMP = tuple(sorted({Path(os.path.realpath(tempfile.gettempdir())), Path("/private/tmp"),
                            Path("/private/var/folders")}))
STOPPED = 124


@dataclass(frozen=True)
class Policy:
    writable: tuple
    readable: tuple
    network: bool = False
    readable_files: tuple = ()

    def extended(self, readable=(), readable_files=()) -> "Policy":
        return Policy(self.writable, self.readable + tuple(readable), self.network,
                      self.readable_files + tuple(readable_files))


def _quoted(path) -> str:
    """The real path, quoted: sandbox rules match resolved paths (on macOS /var is /private/var)."""
    return '"' + os.path.realpath(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def profile_text(policy: Policy, denied: tuple) -> str:
    """Later rules win: deny the private areas, allow the policy's paths, deny secrets again."""
    lines = ["(version 1)", "(allow default)"]
    if not policy.network:
        lines.append("(deny network*)")
    lines.append("(deny file-read-data " + " ".join(f"(subpath {_quoted(p)})" for p in denied) + ")")
    allowed = [f"(subpath {_quoted(p)})" for p in policy.readable + policy.writable]
    allowed += [f"(literal {_quoted(p)})" for p in policy.readable_files]
    lines.append("(allow file-read-data " + " ".join(allowed) + ")")
    lines.append("(deny file-read* " + " ".join(f"(subpath {_quoted(HOME / p)})" for p in SENSITIVE) + ")")
    lines.append("(deny file-write*)")
    lines.append("(allow file-write* " + " ".join(f"(subpath {_quoted(p)})" for p in policy.writable)
                 + ' (literal "/dev/null") (subpath "/dev/fd"))')
    return "\n".join(lines) + "\n"


def write_profile(policy: Policy, path: Path, denied: tuple) -> Path:
    path.write_text(profile_text(policy, denied), encoding="utf-8")
    return path


def execute(argv, cwd, env, profile: Path, timeout: float) -> tuple[int, str, bool]:
    """Run under the profile; at the timeout kill the whole process group. (exit code, output, stopped)."""
    if timeout <= 0:
        return STOPPED, "(not started: no time left)", True
    proc = subprocess.Popen(["sandbox-exec", "-f", str(profile), *[str(a) for a in argv]], cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                            start_new_session=True)
    try:
        output, _ = proc.communicate(timeout=timeout)
        return proc.returncode, output, False
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        output, _ = proc.communicate()
        return STOPPED, (output or "") + f"\n(stopped after {timeout:.1f} s)", True


def descendants(pid: int) -> list[int]:
    """Every process below pid, including those that started their own session (FixFirst's checks do)."""
    listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True).stdout
    children = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found


def kill_tree(proc: subprocess.Popen):
    """Kill a process, its group and everything below it (found before anything is killed)."""
    below = descendants(proc.pid)
    for pid in reversed(below):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


class Budget:
    """The agent's time: model requests and tool calls count, the harness's own checks do not."""

    def __init__(self, seconds: float):
        self.limit = seconds
        self.started = time.monotonic()
        self.paused = 0.0

    def used(self) -> float:
        return time.monotonic() - self.started - self.paused

    def remaining(self) -> float:
        return self.limit - self.used()

    @contextmanager
    def pause(self):
        started = time.monotonic()
        try:
            yield
        finally:
            self.paused += time.monotonic() - started


def slug(text: str, keep: int = 40) -> str:
    """A folder-safe name that stays unique: readable prefix plus a hash of the full text."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")[:keep] or "x"
    return f"{safe}-{hashlib.sha256(text.encode()).hexdigest()[:8]}"


def new_attempt() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def run_folder(root: Path, case: str, arm: str, run_index: int, model: str, attempt: str) -> Path:
    """A folder for one run that is never reused: an existing one is refused, not replaced."""
    folder = root / "runs" / f"{slug(case, 30)}--{arm}--r{run_index}--{slug(model)}--{attempt}"
    folder.mkdir(parents=True, exist_ok=False)
    return folder
