"""Bounded, static dependency declarations checked against the target interpreter snapshot."""

import configparser
import hashlib
from itertools import islice
import json
from pathlib import Path
import re
import time

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from packaging.markers import InvalidMarker
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion

from .models import Run

MAX_FILES = 30
MAX_BYTES = 128_000
MAX_DECLARATIONS = 2000


def read_project(root: Path) -> dict:
    root = root.resolve()
    result = {"files": [], "declarations": [], "notes": [], "requires_python": []}
    visited, cache, contexts = set(), {}, set()

    def note(message):
        if message not in result["notes"]:
            result["notes"].append(message)

    def read(path):
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            note("A dependency reference points outside the project and was not read")
            return None
        if resolved in visited:
            return cache.get(resolved)
        if len(visited) >= MAX_FILES:
            note(f"More than {MAX_FILES} declaration files; stopped reading")
            return None
        visited.add(resolved)
        relative = str(path.relative_to(root))
        try:
            if not path.is_file():
                raise OSError("not a regular file")
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                note(f"{relative} exceeds the size limit and was not parsed")
                return None
            text = raw.decode("utf-8-sig")
        except (OSError, UnicodeError):
            note(f"{relative} could not be read as a UTF-8 declaration file")
            return None
        result["files"].append(
            {"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        )
        cache[resolved] = text
        return text

    def add(value, source, group="required", constraint=False):
        if len(result["declarations"]) >= MAX_DECLARATIONS:
            note("Too many declarations; stopped parsing")
            return
        if not isinstance(value, str):
            note(f"{source} contains a non-string declaration that was not parsed")
            return
        try:
            req = Requirement(value)
        except InvalidRequirement:
            note(f"{source} uses unsupported requirement syntax; its install state was not judged")
            return
        result["declarations"].append(
            {
                "name": canonicalize_name(req.name),
                "requirement": str(req),
                "source": source,
                "group": group,
                "constraint": constraint,
            }
        )

    def declaration_list(items, source):
        if not isinstance(items, list):
            note(f"{source} should be an array of declarations; not parsed")
            return []
        return items

    def requirements(path, group="required", constraint=False):
        context = (path.resolve(), group, constraint)
        if context in contexts:
            return
        contexts.add(context)
        text = read(path)
        if text is None:
            return
        logical, start = "", 1
        for line, raw in enumerate(text.splitlines(), 1):
            value = raw.strip()
            if not logical:
                start = line
            logical += value[:-1] + " " if value.endswith("\\") else value
            if value.endswith("\\"):
                continue
            value, logical = logical, ""
            if not value or value.startswith("#"):
                continue
            source = f"{path.relative_to(root)}:{start}"
            include = re.fullmatch(r"(-r|-c|--requirement|--constraint)(?:\s*=?\s*)(.+)", value)
            if include:
                ref = re.split(r"\s+#", include[2], maxsplit=1)[0].strip().strip("\"'")
                if "$" in ref or "://" in ref:
                    note(f"{source}: dynamic or remote reference not read")
                else:
                    requirements(
                        path.parent / ref,
                        group,
                        constraint or include[1] in ("-c", "--constraint"),
                    )
                continue
            if value.startswith("-") or "${" in value:
                note(f"{source}: pip options, editable paths and variable substitution are not parsed")
                continue
            value = re.split(r"\s+#", value, maxsplit=1)[0]
            value = re.sub(r"\s+--hash=\S+", "", value)
            add(value, source, group, constraint)
        if logical:
            note(f"{path.relative_to(root)} ends with an unfinished line continuation")

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = read(pyproject)
        if text is not None:
            try:
                data = tomllib.loads(text)
                project = data.get("project", {})
                for item in declaration_list(
                    project.get("dependencies", []), "project.dependencies"
                ):
                    add(item, "pyproject.toml [project.dependencies]")
                for group, values in project.get("optional-dependencies", {}).items():
                    for item in declaration_list(values, "project.optional-dependencies"):
                        add(item, f"pyproject.toml [project.optional-dependencies.{group}]", group)
                for group, values in data.get("dependency-groups", {}).items():
                    for item in declaration_list(values, "dependency-groups"):
                        add(item, f"pyproject.toml [dependency-groups.{group}]", group)
                python = project.get("requires-python")
                if python:
                    result["requires_python"].append(
                        {
                            "specifier": str(python),
                            "source": "pyproject.toml [project.requires-python]",
                        }
                    )
                if "dependencies" in project.get("dynamic", []):
                    note("pyproject.toml declares dynamic dependencies, which are not executed or parsed")
                if data.get("tool", {}).get("poetry"):
                    note("Poetry-specific declarations are not parsed; standard [project] declarations are read separately")
            except (ValueError, TypeError, AttributeError):
                note("pyproject.toml could not be fully parsed")
    # The base file first: included files inherit its required status. Standalone dev/test files
    # are informative because FixFirst does not know which optional environment the user enabled.
    paths = [
        root / "requirements.txt",
        *sorted(islice(root.glob("requirements*.txt"), MAX_FILES + 1)),
    ]
    for path in paths:
        if path.exists():
            requirements(path, "required" if path.name == "requirements.txt" else path.stem)
    setup = root / "setup.cfg"
    if setup.exists():
        text = read(setup)
        if text is not None:
            try:
                cfg = configparser.ConfigParser(interpolation=None)
                cfg.read_string(text)
                for item in cfg.get("options", "install_requires", fallback="").splitlines():
                    if item.strip():
                        add(item.strip(), "setup.cfg [options.install_requires]")
                if cfg.has_section("options.extras_require"):
                    for group, values in cfg.items("options.extras_require"):
                        for item in values.splitlines():
                            if item.strip():
                                add(
                                    item.strip(),
                                    f"setup.cfg [options.extras_require.{group}]",
                                    group,
                                )
                python = cfg.get("options", "python_requires", fallback="")
                if python:
                    result["requires_python"].append(
                        {"specifier": python, "source": "setup.cfg [options.python_requires]"}
                    )
            except configparser.Error:
                note("setup.cfg could not be parsed")
    if (root / "setup.py").exists():
        note("setup.py is not executed; only static declarations are read")
    if not result["files"]:
        note("No supported static declaration file was found")
    return result


def assess_project(data: dict, environment: dict) -> dict:
    data = json.loads(json.dumps(data))
    installed = {}
    for package in environment.get("packages", []):
        installed.setdefault(canonicalize_name(package.get("name", "")), []).append(
            package.get("version", "")
        )
    markers = environment.get("markers", {})
    for row in data["declarations"]:
        req = Requirement(row["requirement"])
        versions = sorted(set(installed.get(row["name"], [])))
        row["installed"] = ", ".join(versions) or "not in snapshot"
        row["status"] = "unknown"
        if not environment:
            continue
        try:
            if req.marker:
                # Marker.evaluate fills missing keys from the host. Prevent cross-host inference.
                required_keys = {
                    "implementation_name",
                    "implementation_version",
                    "os_name",
                    "platform_machine",
                    "platform_release",
                    "platform_system",
                    "platform_version",
                    "python_full_version",
                    "platform_python_implementation",
                    "python_version",
                    "sys_platform",
                }
                if not required_keys.issubset(markers):
                    continue
                if not req.marker.evaluate({**markers, "extra": ""}):
                    row["status"] = "inactive_marker"
                    continue
            if row["constraint"]:
                row["status"] = "constraint_only"
            elif row["group"] != "required":
                row["status"] = "optional"
            elif req.url:
                row["status"] = "direct_reference"
            elif not versions:
                row["status"] = "missing"
            elif len(versions) > 1:
                row["status"] = "ambiguous_install"
            else:
                row["status"] = (
                    "satisfied" if req.specifier.contains(versions[0]) else "version_mismatch"
                )
        except (InvalidVersion, InvalidMarker, KeyError, ValueError):
            row["status"] = "unknown"
    for row in data["requires_python"]:
        row["installed"] = environment.get("python_version", "unknown")
        row["status"] = "unknown"
        try:
            if environment.get("python_version"):
                row["status"] = (
                    "satisfied"
                    if SpecifierSet(row["specifier"]).contains(row["installed"])
                    else "python_mismatch"
                )
        except (InvalidSpecifier, InvalidVersion):
            data["notes"].append(f"{row['source']}: Python constraint could not be parsed")
    return data


def collect_project(session, env_id: str) -> Run:
    from .runner import redact_data

    start = time.monotonic()
    run = Run(
        tool="project",
        cwd=session.project_root,
        scope="declarations:project",
        environment_id=env_id,
    )
    environment = session.environment
    if environment.get("_environment_id") != env_id:
        environment = {}
    data = assess_project(read_project(Path(session.project_root)), environment)
    data["environment_run_id"] = environment.get("_run_id")
    # Paths checked are only root/src; presence does not prove that importing them succeeds.
    data["local_modules"] = []
    for base in (Path(session.project_root), Path(session.project_root) / "src"):
        if not base.is_dir() or not base.resolve().is_relative_to(
            Path(session.project_root).resolve()
        ):
            continue
        for path in islice(base.iterdir(), 500):
            component = path.stem if path.suffix == ".py" else path.name if path.is_dir() else ""
            if re.fullmatch(r"[A-Za-z_]\w*", component) and path.resolve().is_relative_to(
                Path(session.project_root).resolve()
            ):
                data["local_modules"].append(
                    {"name": component, "path": str(path.relative_to(session.project_root))}
                )
    data["python_files"], data["defined_names"] = index_sources(Path(session.project_root))
    run.stdout = json.dumps(redact_data(data), ensure_ascii=False, indent=2)
    run.exit_code = 0
    run.duration_s = round(time.monotonic() - start, 3)
    run.notes = [
        "Read-only snapshot: optional groups are not assumed to be enabled; direct references "
        "and lock files are not verified from it."
    ]
    return run


SKIP_DIRS = {".git", ".hg", ".venv", "venv", "env", "node_modules", "__pycache__", "build", "dist",
             ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages"}
MAX_INDEXED_FILES = 2000
DEFINITION = re.compile(r"^(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.M)


def index_sources(root: Path) -> tuple[list[str], list[str]]:
    """Bounded static index: project .py files and the top-level names they define.

    Used to tell project modules and project classes from libraries; nothing is imported.
    """
    root = root.resolve()
    files, names = [], set()
    stack = [root]
    while stack and len(files) < MAX_INDEXED_FILES:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            if path.is_symlink():
                continue
            if path.is_dir():
                if path.name not in SKIP_DIRS and not path.name.startswith(".") and (
                    len(path.relative_to(root).parts) < 6
                ):
                    stack.append(path)
            elif path.suffix == ".py" and len(files) < MAX_INDEXED_FILES:
                files.append(str(path.relative_to(root)))
                try:
                    if path.stat().st_size <= MAX_BYTES:
                        names.update(DEFINITION.findall(path.read_text("utf-8", errors="replace")))
                except OSError:
                    continue
    return sorted(files), sorted(names)


def declaration_verified(issue, old_runs, new_runs) -> bool:
    """Verify each original declaration independently; deleting/weakening it is not a repair."""
    previous = {r.run_id: r for r in old_runs if r.tool == "project"}
    expected = []

    def key(row):
        return row["source"], row.get("requirement", row.get("specifier", ""))

    for ref in issue.evidence_refs:
        parts = ref.split(":")
        if len(parts) != 3 or parts[1] != "declaration" or parts[0] not in previous:
            continue
        try:
            data = json.loads(previous[parts[0]].stdout)
            rows = data["declarations"] + data["requires_python"]
            expected.append(key(rows[int(parts[2])]))
        except (ValueError, KeyError, IndexError):
            return False
    if not expected:
        return False
    valid_envs = {
        r.run_id
        for r in [*old_runs, *new_runs]
        if r.tool == "environment"
        and r.verified_pass
        and r.source == "executed"
        and r.environment_id == issue.environment_id
    }
    for run in new_runs:
        if (
            run.tool != "project"
            or run.source != "executed"
            or run.environment_id != issue.environment_id
        ):
            continue
        try:
            data = json.loads(run.stdout)
            if data.get("environment_run_id") not in valid_envs:
                continue
            satisfied = {
                key(row)
                for row in data["declarations"] + data["requires_python"]
                if row["status"] == "satisfied"
            }
            if set(expected).issubset(satisfied):
                return True
        except (ValueError, KeyError, TypeError):
            continue
    return False
