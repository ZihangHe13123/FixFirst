"""Bound process trees to a CLI invocation or a web server lifetime."""

import atexit
from contextlib import contextmanager
from contextvars import ContextVar
import os
import signal
import subprocess
import threading


class ProcessCancelled(OSError):
    pass


class ProcessScope:
    def __init__(self):
        self.lock = threading.RLock()
        self.cancelled = False
        self.children = set()

    @contextmanager
    def activate(self):
        token = _scope.set(self)
        try:
            yield
        finally:
            _scope.reset(token)

    def cancel(self):
        # Serialize with creation so shutdown cannot miss a newly launched check.
        with self.lock:
            self.cancelled = True
            error = None
            for child in tuple(self.children):
                try:
                    child.kill_tree()
                except OSError as exc:
                    # A failed signal must not leave the remaining checks running.
                    # Keep the failure visible after attempting every child.
                    if error is None:
                        error = exc
            if error is not None:
                raise error


_default = ProcessScope()
_scope = ContextVar("fixfirst_process_scope", default=_default)
atexit.register(_default.cancel)


class ManagedProcess:
    def __init__(self, argv, **kwargs):
        self.scope = _scope.get()
        self.job = None
        self.closed = False
        with self.scope.lock:
            if self.scope.cancelled:
                raise ProcessCancelled("FixFirst is stopping; no further checks will start")
            if os.name == "nt":
                from ._winprocess import Job

                self.job = Job()
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 4  # suspended
            else:
                kwargs["start_new_session"] = True
            try:
                self.proc = subprocess.Popen(argv, **kwargs)
                if self.job:
                    self.job.start(self.proc)
            except BaseException:
                if "proc" in self.__dict__:
                    self.proc.kill()
                    self.proc.wait()
                    for pipe in (self.proc.stdout, self.proc.stderr, self.proc.stdin):
                        if pipe:
                            pipe.close()
                if self.job:
                    self.job.close()
                raise
            self.scope.children.add(self)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "proc"), name)

    def kill_tree(self):
        with self.scope.lock:
            if self.closed:
                return
            if self.job:
                self.job.kill()
            else:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    # On macOS, a group containing only an unreaped exited leader
                    # can report EPERM. poll() reaps it; still signal the group
                    # again because a finished leader may have live descendants.
                    # A live leader or a second EPERM is a real cleanup failure.
                    if self.proc.poll() is None:
                        raise
                    try:
                        os.killpg(self.proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def close(self):
        with self.scope.lock:
            if self.closed:
                return
            self.kill_tree()
            if self.job:
                self.job.close()
            self.closed = True
            self.scope.children.discard(self)
        self.proc.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.close()
        finally:
            for pipe in (self.proc.stdout, self.proc.stderr, self.proc.stdin):
                if pipe:
                    pipe.close()
