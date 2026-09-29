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
- it has the network only when the policy says so;
- it belongs to an owner (a run, or one grader check): the profile denies a Mach name made from the
  owner's random token, which nothing else denies. A sandbox is inherited by every process started
  under it and can be neither dropped nor replaced (macOS refuses a second sandbox), so this, and
  not a process's environment, folder, name or command line, tells the harness which processes are
  the owner's, including those that cleared their environment, changed folder or left their session;
- it cannot have processes started outside the sandbox on its behalf: launchd jobs, LaunchServices
  (`open`) and Apple Events are refused;
- it may signal only itself and the processes started under the same sandbox (its own children, also
  detached ones): not the harness, the user's processes, another run, or what an earlier command of
  the same run left (each command gets its own sandbox; those processes end with the run).

Processes start in their own process group, with stdin closed, and the whole group is killed at the
deadline. A command ends when its own process ends: background processes it leaves (which may hold
its output pipe) do not keep the harness waiting. When a run or a grader check ends, stop() kills
every process of its owner and proves that none is left. Only the end of a command's output is kept.
"""

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import functools
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
    owner: str = ""  # the token of the run or grader check that every process under the policy belongs to

    def extended(self, readable=(), readable_files=()) -> "Policy":
        return Policy(self.writable, self.readable + tuple(readable), self.network,
                      self.readable_files + tuple(readable_files), self.owner)


def _quoted(path) -> str:
    """The real path, quoted: sandbox rules match resolved paths (on macOS /var is /private/var)."""
    return '"' + os.path.realpath(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def owner_name(owner: str) -> str:
    """A Mach service name that exists nowhere; only the owner's profiles deny it."""
    return f"org.fixfirst.run.{owner}"


def profile_text(policy: Policy, denied: tuple) -> str:
    """Later rules win: deny the private areas, allow the policy's paths, deny secrets again. Then the
    owner's name, the requests that would start a process outside the sandbox, and the signal targets."""
    if not re.fullmatch(r"[0-9a-f]{24}", policy.owner):
        raise ValueError("a sandbox profile needs its owner's token (new_mark())")
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
    lines.append(f'(deny mach-lookup (global-name "{owner_name(policy.owner)}"))')
    lines.append("(deny job-creation lsopen appleevent-send)")
    lines.append("(deny signal)")
    lines.append("(allow signal (target self) (target same-sandbox))")
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


def execute(argv, cwd, env, profile: Path, timeout: float, owner: str, keep: int = KEEP) -> tuple[int, str, bool]:
    """Run under the profile (whose owner is `owner`); at the timeout kill the command's process tree.
    (exit code, output, stopped). The result comes when the command's own process ends, even if a
    process it left in the background still holds the output pipe; only the last `keep` bytes of
    output are kept."""
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
        kill_tree(proc, owner)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass
        stopped = True
    reader.join(1)  # the rest of the output; a background process may hold the pipe much longer
    if stopped:
        return STOPPED, tail.text() + f"\n(stopped after {timeout:.1f} s)", True
    return proc.returncode, tail.text(), False


def new_mark() -> str:
    """A run's (or grader check's) owner token: 24 random hex digits."""
    return secrets.token_hex(12)


class CleanupError(OSError):
    """The processes of a run or grader check could not be shown to have stopped."""


class _ProcInfo(ctypes.Structure):  # struct proc_bsdinfo, <sys/proc_info.h>
    _fields_ = [("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("xstatus", ctypes.c_uint32),
                ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
                ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32), ("rgid", ctypes.c_uint32),
                ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32), ("rfu", ctypes.c_uint32),
                ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32), ("nfiles", ctypes.c_uint32),
                ("pgid", ctypes.c_uint32), ("pjobc", ctypes.c_uint32), ("tdev", ctypes.c_uint32),
                ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32), ("start_sec", ctypes.c_uint64),
                ("start_usec", ctypes.c_uint64)]


_PIDTBSDINFO, _GLOBAL_NAME, _NO_REPORT = 3, 2, 0x40000000


@functools.cache
def _system():
    """libSystem's process list, process information and sandbox_check (macOS only)."""
    lib = ctypes.CDLL(None, use_errno=True)
    lib.proc_listallpids.restype = ctypes.c_int
    lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    lib.sandbox_check.restype = ctypes.c_int
    lib.sandbox_check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]  # the name follows as a variadic
    return lib


def _pids() -> list[int]:
    """Every pid on the system. The list must be whole: a failed or empty answer, one that may have been
    cut short, or one without this process and launchd raises OSError."""
    lib = _system()
    ctypes.set_errno(0)
    room = lib.proc_listallpids(None, 0)
    if room <= 0:
        raise OSError(ctypes.get_errno() or errno.EIO, "the process list cannot be read")
    for _ in range(4):
        room += 256
        buffer = (ctypes.c_int * room)()
        ctypes.set_errno(0)
        count = lib.proc_listallpids(buffer, ctypes.sizeof(buffer))
        if count <= 0:
            raise OSError(ctypes.get_errno() or errno.EIO, "the process list cannot be read")
        if count < room:  # it fitted, so nothing was cut off
            pids = [pid for pid in buffer[:count] if pid > 0]
            if os.getpid() not in pids or 1 not in pids:
                raise OSError(errno.EIO, "the process list is incomplete")
            return pids
        room *= 2
    raise OSError(errno.EAGAIN, "the process list kept growing while it was read")


def _identity(pid: int) -> tuple | None:
    """(start time, parent, name) of a live process; None only when the kernel says there is no such
    process (it exited, or is a zombie that can no longer run). PermissionError when it exists but
    cannot be read (another user's); OSError for any other failure, which is never taken as "gone"."""
    info = _ProcInfo()
    ctypes.set_errno(0)
    size = _system().proc_pidinfo(pid, _PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    if size == ctypes.sizeof(info):
        return (info.start_sec, info.start_usec), info.ppid, info.comm.decode("utf-8", "replace")
    error = ctypes.get_errno()
    if size == 0 and error == errno.ESRCH:
        return None
    raise (PermissionError if error == errno.EPERM else OSError)(error or errno.EIO, f"process {pid} cannot be read")


def _denies(pid: int, name: bytes) -> bool:
    ctypes.set_errno(0)
    result = _system().sandbox_check(pid, b"mach-lookup", _GLOBAL_NAME | _NO_REPORT, name)
    if result not in (0, 1):
        raise OSError(ctypes.get_errno() or errno.EIO, f"the sandbox of process {pid} cannot be checked")
    return result == 1


def _under(pid: int, owner: str) -> bool:
    """Whether the process runs under one of the owner's profiles: the owner's name is denied and a
    sibling name is allowed. An unsandboxed process allows both; another run's sandbox allows the
    owner's name; a deny-by-default sandbox, and a pid that no longer exists, deny both. A failed
    check raises OSError; it is never taken as "not the owner's"."""
    name = owner_name(owner).encode()
    return _denies(pid, name) and not _denies(pid, name + b".unrelated")


def _examine(pid: int, owner: str):
    """The identity of the owner's process, "other" (the kernel says it is not the owner's), "gone"
    (the kernel says it no longer exists) or "changed" (the pid changed hands during the check)."""
    try:
        before = _identity(pid)
    except PermissionError:
        before = "unreadable"
    if before is None:
        return "gone"
    if not _under(pid, owner):
        return "other"
    if before == "unreadable":
        raise PermissionError(errno.EPERM, f"process {pid} runs under the owner's sandbox but cannot be read")
    after = _identity(pid)
    if after is None:
        return "gone"
    return before if after[0] == before[0] else "changed"


def owned(owner: str) -> dict[int, tuple]:
    """The owner's live processes, pid -> (start time, parent, name). OSError when that cannot be shown:
    the process list failed or looks incomplete, a query failed, or a process under the owner's sandbox
    cannot be read (it became another user). A pid that changed hands during its check is checked again."""
    found = {}
    for pid in _pids():
        for _ in range(3):
            state = _examine(pid, owner)
            if state != "changed":
                break
        else:
            raise OSError(errno.EAGAIN, f"process {pid} kept changing while it was checked")
        if isinstance(state, tuple):
            found[pid] = state
    return found


def _kill(pid: int, sig: int):
    os.kill(pid, sig)


def _kill_if_owned(pid: int, started: tuple, owner: str) -> bool:
    """SIGKILL the process only if it is still the same one (same start time) under the owner's
    sandbox, checked just before: a pid that now belongs to another process is left alone. A failed
    query or kill raises (the caller cannot then show that the process stopped)."""
    now = _identity(pid)
    if not now or now[0] != started or not _under(pid, owner):
        return False
    try:
        _kill(pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return False


def stop(owner: str, settle: float = 3.0) -> dict:
    """Kill every process of the owner and prove that none is left: rounds of finding and killing
    until the owner has no live process, for at most `settle` seconds. {"stopped": [names], "error":
    None, or why the harness cannot say that the owner's processes are gone}."""
    stopped, deadline = {}, time.monotonic() + settle
    try:
        while True:
            found = owned(owner)
            if not found:
                return {"stopped": sorted(stopped.values()), "error": None}
            if time.monotonic() > deadline:
                left = [f"{name} ({pid})" for pid, (_, _, name) in sorted(found.items())]
                return {"stopped": sorted(stopped.values()),
                        "error": f"{len(left)} processes still alive after being killed: {', '.join(left[:5])}"}
            for pid, (started, _, name) in found.items():
                if _kill_if_owned(pid, started, owner):
                    stopped[(pid, started)] = name
            time.sleep(0.02)
    except (OSError, AttributeError) as error:  # without these system calls nothing can be shown
        return {"stopped": sorted(stopped.values()), "error": f"the processes cannot be checked: {error}"}


def descendants(pid: int) -> list[tuple[int, tuple]]:
    """(pid, start time) of every process below pid, by parent links (FixFirst's checks start their
    own sessions, so the process group alone would miss them)."""
    children = {}
    for other in _pids():
        try:
            found = _identity(other)
        except PermissionError:
            continue  # another user's process: the harness could not stop it anyway
        if found:
            children.setdefault(found[1], []).append((other, found[0]))
    result, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            result.append(child)
            todo.append(child[0])
    return result


def kill_tree(proc: subprocess.Popen, owner: str):
    """At a deadline: kill the command's process, its group, and every process below it that is still
    the owner's (a pid is killed only after it is checked again)."""
    try:
        for pid, started in reversed(descendants(proc.pid)):
            _kill_if_owned(pid, started, owner)
    except (OSError, AttributeError):
        pass  # the group is still killed; stop() at the end of the run proves the rest
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
