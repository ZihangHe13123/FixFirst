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

Processes start in their own process group, with stdin closed, and the whole group is killed at the
deadline. A command ends when its own process ends: background processes it leaves (which may hold its
output pipe) do not keep the harness waiting; they end with the run (sweep). Only the end of the
output is kept.
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
import threading
import time

HOME = Path.home()
SENSITIVE = (".ssh", ".omlx", ".claude", "Library/Keychains")
SYSTEM_TEMP = tuple(sorted({Path(os.path.realpath(tempfile.gettempdir())), Path("/private/tmp"),
                            Path("/private/var/folders")}))
STOPPED = 124
KEEP = 1 << 20  # bytes of a command's output that are kept (the end)


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


class Tail:
    """The last `keep` bytes of a stream, read in a thread until the stream ends."""

    def __init__(self, keep: int):
        self.keep, self.data, self.dropped, self.lock = keep, bytearray(), 0, threading.Lock()

    def drain(self, stream):
        with stream:
            for piece in iter(lambda: stream.read1(1 << 16), b""):
                with self.lock:
                    self.data += piece
                    extra = len(self.data) - self.keep
                    if extra > 0:
                        del self.data[:extra]
                        self.dropped += extra

    def text(self) -> str:
        with self.lock:
            data, dropped = bytes(self.data), self.dropped
        text = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
        return f"...({dropped} bytes of earlier output not kept)...\n{text}" if dropped else text


def execute(argv, cwd, env, profile: Path, timeout: float, keep: int = KEEP) -> tuple[int, str, bool]:
    """Run under the profile; at the timeout kill the whole process group. (exit code, output, stopped).
    The result comes when the command's own process ends, even if a process it left in the background
    still holds the output pipe; only the last `keep` bytes of output are kept."""
    if timeout <= 0:
        return STOPPED, "(not started: no time left)", True
    proc = subprocess.Popen(["sandbox-exec", "-f", str(profile), *[str(a) for a in argv]], cwd=cwd, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    tail = Tail(keep)
    reader = threading.Thread(target=tail.drain, args=(proc.stdout,), daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
        stopped = False
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass
        stopped = True
    reader.join(1)  # the rest of the output; a background process may hold the pipe much longer
    if stopped:
        return STOPPED, tail.text() + f"\n(stopped after {timeout:.1f} s)", True
    return proc.returncode, tail.text(), False


MARK = "FIXFIRST_RUN"


def new_mark() -> str:
    return secrets.token_hex(12)


def _listing(argv) -> str:
    """A system listing (ps, lsof); other processes' environments need not be UTF-8."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def marked_processes(mark: str, folder: Path) -> set[int]:
    """This run's processes, found without their parents: every process the harness starts for the run
    carries the mark in its environment, and those that dropped it are found by their working folder
    inside the run's folder (any process of the user working there counts, so keep shells out of a
    running run's folder). A process that clears its environment and leaves the folder is not found."""
    uid, found = str(os.getuid()), set()
    for line in _listing(["ps", "-axwwE", "-o", "pid=,uid=,command="]).splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1] == uid and f"{MARK}={mark}" in parts[2]:
            found.add(int(parts[0]))
    root = os.path.realpath(folder)
    pid = None
    for line in _listing(["lsof", "-a", "-d", "cwd", "-F", "pn", "-u", uid]).splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            path = os.path.realpath(line[1:])
            if path == root or path.startswith(root + os.sep):
                found.add(pid)
    found.discard(os.getpid())
    return found


def sweep(mark: str, folder: Path) -> int:
    """Kill every process of the run that is still alive, with everything below it. Used when a run
    or a grader check ends, so nothing it started can change the case afterwards."""
    stopped = set()
    for _ in range(3):  # a process may start another while its parent is being killed
        pids = marked_processes(mark, folder) - stopped
        if not pids:
            break
        children = child_table()
        for pid in pids:
            for victim in [*reversed(descendants(pid, children)), pid]:
                if victim in stopped:
                    continue
                try:
                    os.kill(victim, signal.SIGKILL)
                    stopped.add(victim)
                except (ProcessLookupError, PermissionError):
                    pass
        time.sleep(0.05)
    return len(stopped)


def child_table() -> dict[int, list[int]]:
    children = {}
    for line in _listing(["ps", "-A", "-o", "pid=,ppid="]).splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    return children


def descendants(pid: int, children: dict | None = None) -> list[int]:
    """Every process below pid, including those that started their own session (FixFirst's checks do)."""
    children = child_table() if children is None else children
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
