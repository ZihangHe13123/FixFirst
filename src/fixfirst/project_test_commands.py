"""Quote bounded project test-command declarations without interpreting or running them."""

import configparser
import os
from pathlib import Path
import re
import stat

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def _read(root, name):
    path = root / name
    try:
        if path.is_symlink():
            return None
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 64_000:
                return None
            data = stream.read(64_001)
        return data.decode("utf-8") if len(data) <= 64_000 else None
    except (OSError, UnicodeError):
        return None


def declared_commands(root: Path):
    from .runner import redact

    found = []

    def add(source, command):
        if isinstance(command, str) and command.strip() and len(command) <= 2000 and len(found) < 8:
            found.append((source, redact(command.strip())))

    for name in ("tox.ini", "setup.cfg"):
        text = _read(root, name)
        if text is None:
            continue
        parser = configparser.RawConfigParser(interpolation=None, strict=False)
        try:
            parser.read_string(text)
            for section in parser.sections():
                if section == "testenv" or section.startswith("testenv:"):
                    for command in parser.get(section, "commands", fallback="").splitlines():
                        add(f"{name} [{section}] commands", command)
                elif section in ("aliases", "alias"):
                    for key, command in parser.items(section):
                        if re.search(r"test|check", key, re.I):
                            add(f"{name} [{section}] {key}", command)
        except configparser.Error:
            continue
    text = _read(root, "Makefile")
    if text is not None:
        target = None
        for number, line in enumerate(text.splitlines(), 1):
            match = re.match(r"^([\w .-]+):(?:[^=].*)?$", line)
            if match:
                target = match[1] if re.search(r"test|check", match[1], re.I) else None
            elif line.startswith("\t") and target:
                add(f"Makefile:{number} ({target})", line[1:])
            elif line and not line.startswith((" ", "#")):
                target = None
    text = _read(root, "pyproject.toml")
    if text is not None:
        try:
            data = tomllib.loads(text)
            tools = data.get("tool", {})
            for group in (tools.get("hatch", {}).get("envs", {}),
                          tools.get("pdm", {}).get("scripts", {}),
                          tools.get("poe", {}).get("tasks", {})):
                if not isinstance(group, dict):
                    continue
                for key, value in group.items():
                    if isinstance(value, dict) and "scripts" in value:
                        entries = value["scripts"]
                    else:
                        entries = {key: value}
                    if not isinstance(entries, dict):
                        continue
                    for task, command in entries.items():
                        if re.search(r"test|check", task, re.I):
                            if isinstance(command, dict):
                                command = command.get("cmd")
                            for item in command if isinstance(command, list) else [command]:
                                add(f"pyproject.toml ({key}/{task})", item)
            tox = tools.get("tox", {})
            if isinstance(tox, dict):
                for key in ("env_run_base", "env"):
                    group = tox.get(key, {})
                    if isinstance(group, dict):
                        for value in [group, *group.values()]:
                            if isinstance(value, dict):
                                for command in value.get("commands", []):
                                    if isinstance(command, list) and all(isinstance(v, str) for v in command):
                                        add(f"pyproject.toml (tool.tox.{key})", repr(command))
        except (ValueError, AttributeError, TypeError):
            pass
    return found
