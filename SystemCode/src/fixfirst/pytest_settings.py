"""Bounded static records of project pytest warning filters.

These records show configuration present on disk, not which configuration or
filter was effective in a run. CLI options, environment variables, plugins and
runtime changes are deliberately not inferred. Empty results also cover files
that were missing, unsafe, oversized or unparseable; they do not prove that no
warning filter was active.
"""

import configparser
import os
from pathlib import Path
import stat

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


MAX_BYTES = 128_000
MAX_FILTERS = 100
MAX_FILTER_CHARS = 2000
MAX_TOTAL_FILTER_CHARS = 16_000
CONFIGS = (
    ("pytest.ini", "pytest"),
    (".pytest.ini", "pytest"),
    ("pyproject.toml", "tool.pytest.ini_options"),
    ("tox.ini", "pytest"),
    ("setup.cfg", "tool:pytest"),
)


def _read(root: Path, name: str) -> str | None:
    """Read only a bounded regular file directly inside the resolved root."""
    path = root / name
    descriptor = None
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            return None
        if path.resolve(strict=True).parent != root:
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        opened, current = os.fstat(descriptor), path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(current.st_mode)
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
                or path.resolve(strict=True).parent != root or opened.st_size > MAX_BYTES):
            return None
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(MAX_BYTES + 1)
        return raw.decode("utf-8-sig") if len(raw) <= MAX_BYTES else None
    except (OSError, UnicodeError, RuntimeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _filters(text: str, name: str, section: str) -> list[str]:
    if name == "pyproject.toml":
        value = tomllib.loads(text)
        for part in section.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        value = value.get("filterwarnings") if isinstance(value, dict) else None
    else:
        # Defaults must not be mistaken for a value explicitly recorded in the
        # pytest section; option names remain exact and interpolation is off.
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read_string(text)
        parser.defaults().clear()
        value = parser.get(section, "filterwarnings", fallback=None)
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    filters = [item.strip() for item in value if item.strip()]
    if (len(filters) > MAX_FILTERS or any(len(item) > MAX_FILTER_CHARS for item in filters)
            or sum(map(len, filters)) > MAX_TOTAL_FILTER_CHARS):
        return []
    return filters


def recorded_warning_filters(root: Path) -> list[dict]:
    """Return every safely readable static source, preserving filter order.

    No precedence is assigned across files. Invalid or over-limit files supply
    no record; valid files are still returned. Warning categories and regexes
    remain strings and are never imported, evaluated or compiled.
    """
    root = Path(root)
    try:
        if root.is_symlink() or not root.is_dir():
            return []
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return []
    records = []
    for name, section in CONFIGS:
        text = _read(root, name)
        if text is None:
            continue
        try:
            filters = _filters(text, name, section)
        except (configparser.Error, ValueError, TypeError, RecursionError):
            continue
        if filters:
            records.append({"source": f"{name} [{section}]", "filters": filters})
    return records
