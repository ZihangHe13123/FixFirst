import contextlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

from .models import Session


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        retry(os.replace, name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def retry(function, *args, **kwargs):
    """Bound retries for transient Windows sharing conflicts, including virus scanners."""
    for attempt in range(20):
        try:
            return function(*args, **kwargs)
        except PermissionError:
            if os.name != "nt" or attempt == 19:
                raise
            time.sleep(0.05)


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def directory(self, session_id: str) -> Path:
        if not re.fullmatch(r"session-[a-f0-9]{12}", session_id):
            raise ValueError("Invalid session id")
        return self.root / session_id

    def load(self, session_id: str) -> Session:
        path = self.directory(session_id) / "session.json"
        return Session.model_validate_json(retry(path.read_text, encoding="utf-8"))

    def save(self, session: Session) -> None:
        atomic_write(
            self.directory(session.session_id) / "session.json", session.model_dump_json(indent=2)
        )

    def list(self) -> list[dict]:
        rows = []
        for path in sorted(self.root.glob("session-*/session.json")):
            try:
                data = json.loads(retry(path.read_text, encoding="utf-8"))
                rows.append(
                    {k: data.get(k) for k in ("session_id", "name", "goal", "goal_status", "created_at")}
                )
            except (ValueError, KeyError, OSError):
                continue
        return rows

    @contextlib.contextmanager
    def lock(self, session_id: str):
        directory = self.directory(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        # Advisory lock file remains harmless after a crash; the OS releases the lock.
        with (directory / ".lock").open("a+") as file:
            try:
                acquire(file)
            except OSError:
                raise ValueError(
                    "This session is already running; wait for the current command to finish"
                ) from None
            try:
                yield
            finally:
                release(file)


def acquire(file):
    if os.name == "nt":
        import msvcrt

        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


def release(file):
    if os.name == "nt":
        import msvcrt

        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file, fcntl.LOCK_UN)
