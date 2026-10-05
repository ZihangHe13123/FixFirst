"""Bounded UTF-8 file tools for the explicit lines mode; no project code is imported."""

from contextlib import contextmanager
import os
from pathlib import Path, PureWindowsPath
import stat
import uuid

MAX_BYTES = 16 << 20
PATH_HELP = ("Paths may be relative to the project directory or absolute paths inside it. "
             "The project directory is already the base; project/ is not an automatically stripped prefix.")
PATH_ERROR = "Use a project-relative file path (such as src/module.py) or an absolute path inside the project; parent traversal and outside paths are not allowed."


def head_tail(text, limit=6000):
    if len(text) <= limit:
        return text, 0
    if limit < 64:
        raise ValueError("output limit must be at least 64")
    omitted = len(text) - limit
    while True:
        marker = f"\n... [{omitted} characters omitted] ...\n"
        kept = limit - len(marker)
        updated = len(text) - kept
        if updated == omitted:
            break
        omitted = updated
    first = (kept + 1) // 2
    return text[:first] + marker + text[-(kept - first):], omitted


@contextmanager
def parent(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError("path must be a nonempty string. " + PATH_ERROR)
    path = Path(relative)
    if PureWindowsPath(relative).drive or not path.parts or ".." in path.parts:
        raise ValueError(PATH_ERROR)
    if path.is_absolute():
        project = Path(root).absolute()
        # Canonicalize only the trusted root: requested links inside it must still be
        # visited with O_NOFOLLOW. macOS may spell the same root under /var or /private/var.
        for base in (project, project.resolve()):
            try:
                path = path.relative_to(base)
                break
            except ValueError:
                continue
        else:
            raise ValueError(PATH_ERROR)
        if not path.parts:
            raise ValueError("path must name a file inside the project. " + PATH_ERROR)
    if os.open not in os.supports_dir_fd:
        raise ValueError("lines-mode file tools require directory-relative file APIs")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, path.name
    finally:
        os.close(fd)


def read_at(fd, name):
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(opened, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError("not a regular UTF-8 file of at most 16 MB")
        data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("file exceeds 16 MB")
    return data, info


def read_page(root, args, limit=6000):
    with parent(root, args["path"]) as (fd, name):
        data, _ = read_at(fd, name)
    text = data.decode("utf-8")
    if {"offset", "limit"} & args.keys():
        if {"start_line", "line_count"} & args.keys():
            raise ValueError("do not mix line and character page parameters")
        offset, size = args.get("offset", 0), args.get("limit", limit)
        if type(offset) is not int or not 0 <= offset <= len(text):
            raise ValueError(f"offset must be an integer from 0 to {len(text)}")
        if type(size) is not int or not 1 <= size <= limit:
            raise ValueError(f"limit must be an integer from 1 to {limit}")
        end = min(offset + size, len(text))
        return {"text": text[offset:end], "offset": offset, "next_offset": end,
                "total_chars": len(text), "eof": end == len(text), "omitted_chars": 0}
    lines = text.splitlines(keepends=True)
    start, count = args.get("start_line", 1), args.get("line_count", 100)
    if type(start) is not int or not 1 <= start <= len(lines) + 1:
        raise ValueError(f"start_line must be an integer from 1 to {len(lines) + 1}")
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError("line_count must be an integer from 1 to 1000")
    end = min(start - 1 + count, len(lines))
    page, omitted = head_tail("".join(lines[start - 1:end]), limit)
    return {"text": page, "start_line": start, "line_count": end - start + 1,
            "next_line": end + 1, "total_lines": len(lines), "eof": end == len(lines),
            "omitted_chars": omitted}


def exact_edit(root, args):
    old, new, expected = args["old"], args["new"], args.get("expected_count", 1)
    if not isinstance(old, str) or not old or not isinstance(new, str):
        raise ValueError("old must be nonempty text and new must be text")
    if type(expected) is not int or not 1 <= expected <= 1000:
        raise ValueError("expected_count must be an integer from 1 to 1000")
    with parent(root, args["path"]) as (fd, name):
        data, info = read_at(fd, name)
        text = data.decode("utf-8")
        found = text.count(old)
        if found != expected:
            raise ValueError(f"expected {expected} exact matches, found {found}; file unchanged")
        if len(data) + found * (len(new.encode()) - len(old.encode())) > MAX_BYTES:
            raise ValueError("edited file would exceed 16 MB")
        edited = text.replace(old, new).encode("utf-8")
        temporary = ".fixfirst-edit-" + uuid.uuid4().hex
        try:
            opened = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             stat.S_IMODE(info.st_mode), dir_fd=fd)
            with os.fdopen(opened, "wb") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
                stream.write(edited)
                stream.flush()
                os.fsync(stream.fileno())
            current = os.stat(name, dir_fd=fd, follow_symlinks=False)
            def identity(s):
                return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

            if identity(current) != identity(info):
                raise ValueError("file changed during the edit; replacement not applied")
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
    return {"path": args["path"], "replacements": found, "bytes_before": len(data), "bytes_after": len(edited)}
