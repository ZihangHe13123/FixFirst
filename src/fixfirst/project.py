"""Bounded, static dependency declarations checked against the target interpreter snapshot."""

import ast
import codecs
import configparser
import hashlib
from itertools import islice
import json
import locale
import os
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
    result = {"files": [], "declarations": [], "notes": [], "requires_python": [], "own_names": []}
    visited, cache, contexts = set(), {}, set()

    def note(message):
        if message not in result["notes"]:
            result["notes"].append(message)

    def own(name):
        # The distribution this project builds: installed (often editable) it is the project itself.
        if isinstance(name, str) and name.strip():
            canonical = canonicalize_name(name.strip())
            if canonical not in result["own_names"]:
                result["own_names"].append(canonical)

    def read(path, pip_file=False):
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
        # An absolute include can name a project file via a junction, symlink, 8.3 name or '..'.
        relative = (path if path.is_relative_to(root) else resolved).relative_to(root).as_posix()
        try:
            if not path.is_file():
                raise OSError("not a regular file")
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                note(f"{relative} exceeds the size limit and was not parsed")
                return None
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                if not pip_file:
                    raise
                utf16 = raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
                text = raw.decode("utf-16" if utf16 else locale.getpreferredencoding(False))
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
        text = read(path, pip_file=True)
        if text is None:
            return
        shown = (path if path.is_relative_to(root) else path.resolve()).relative_to(root).as_posix()
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
            source = f"{shown}:{start}"
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
            note(f"{shown} ends with an unfinished line continuation")

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = read(pyproject)
        if text is not None:
            try:
                data = tomllib.loads(text)
                project = data.get("project", {})
                own(project.get("name"))
                own((data.get("tool", {}).get("poetry") or {}).get("name"))
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
                # flit before PEP 621 kept its metadata in [tool.flit.metadata].
                flit = data.get("tool", {}).get("flit", {}).get("metadata", {})
                if isinstance(flit, dict):
                    own(flit.get("dist-name") or flit.get("module"))
                    for item in declaration_list(flit.get("requires", []), "tool.flit.metadata.requires"):
                        add(item, "pyproject.toml [tool.flit.metadata.requires]")
                    for group, values in (flit.get("requires-extra") or {}).items():
                        for item in declaration_list(values, "tool.flit.metadata.requires-extra"):
                            add(item, f"pyproject.toml [tool.flit.metadata.requires-extra.{group}]", group)
                    if flit.get("requires-python"):
                        result["requires_python"].append(
                            {
                                "specifier": str(flit["requires-python"]),
                                "source": "pyproject.toml [tool.flit.metadata.requires-python]",
                            }
                        )
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
            requirements(path, "required" if os.path.normcase(path.name) == "requirements.txt" else path.stem)
    setup = root / "setup.cfg"
    if setup.exists():
        text = read(setup)
        if text is not None:
            try:
                cfg = configparser.ConfigParser(interpolation=None)
                cfg.read_string(text)
                own(cfg.get("metadata", "name", fallback=""))
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
        text = read(root / "setup.py")
        found = setup_py_declarations(text) if text is not None else None
        if found is None:
            note("setup.py could not be read statically")
        else:
            for value, source, group in found:
                add(value, source, group)
            own(setup_py_name(text))
        note("setup.py is not executed; only literal declarations in its setup() call are read")
    for filename in ("environment.yml", "environment.yaml"):
        path = root / filename
        if not path.exists():
            continue
        text = read(path)
        if text is None:
            continue
        from .conda_declarations import read as read_conda

        conda = read_conda(text, filename, MAX_DECLARATIONS)
        for requirement, source in conda["pip"]:
            add(requirement, source)
        result["requires_python"].extend(conda["python"])
        result.setdefault("conda_declarations", []).extend(conda["conda"])
        result.setdefault("conda_mappings", []).extend(conda["mappings"])
        for message in conda["notes"]:
            note(message)
    if not result["files"]:
        note("No supported static declaration file was found")
    # Documentation is a hint, not an enforceable requirement or proof of support.
    result["python_hints"] = []
    for name in (".python-version", "runtime.txt", "README.md", "README.rst", "README.txt"):
        path = root / name
        if not path.exists():
            continue
        text = read(path)
        if text is None:
            continue
        for line, value in enumerate(text.splitlines(), 1):
            if name in (".python-version", "runtime.txt"):
                match = re.fullmatch(r"\s*(?:python-)?(\d+\.\d+(?:\.\d+)?)\s*", value)
            else:
                match = re.search(r"\bPython\s*[`:*]*\s*(\d+\.\d+(?:\.\d+)?)\b", value, re.I)
            if match and len(result["python_hints"]) < 20:
                result["python_hints"].append({"version": match[1], "source": f"{name}:{line}"})
    return result


def setup_calls(text: str) -> tuple[dict, list[ast.Call]] | None:
    """The setup() calls in a setup.py and its top-level assignments, from the syntax tree."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    names = {
        node.targets[0].id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
    }
    calls = [
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and (call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")) == "setup"
    ]
    return names, calls


def setup_py_name(text: str) -> str | None:
    """The literal name passed to setup(), directly or through a top-level variable."""
    parsed = setup_calls(text)
    for call in parsed[1] if parsed else ():
        for keyword in call.keywords:
            if keyword.arg == "name":
                value = keyword.value
                value = parsed[0].get(value.id, value) if isinstance(value, ast.Name) else value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
    return None


def setup_py_declarations(text: str) -> list[tuple[str, str, str]] | None:
    """Literal requirement lists passed to setup(), read from the syntax tree, never executed.

    Handles lists written in the call and lists first assigned to a top-level name
    (``install_requires=INSTALL_REQUIRES``). Anything computed is skipped.
    """
    parsed = setup_calls(text)
    if parsed is None:
        return None
    names, calls = parsed

    def strings(node):
        node = names.get(node.id, node) if isinstance(node, ast.Name) else node
        if isinstance(node, (ast.List, ast.Tuple)):
            return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return []

    found = []
    for call in calls:
        for keyword in call.keywords:
            if keyword.arg == "install_requires":
                found += [(v, "setup.py install_requires", "required") for v in strings(keyword.value)]
            elif keyword.arg == "tests_require":
                found += [(v, "setup.py tests_require", "tests_require") for v in strings(keyword.value)]
            elif keyword.arg == "extras_require":
                value = keyword.value
                value = names.get(value.id, value) if isinstance(value, ast.Name) else value
                if not isinstance(value, ast.Dict):
                    continue
                for key, values in zip(value.keys, value.values):
                    group = key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else ""
                    if group and not group.startswith(":"):
                        found += [(v, f"setup.py extras_require[{group}]", group) for v in strings(values)]
    return found


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
                    {"name": component, "path": path.relative_to(session.project_root).as_posix()}
                )
    data["python_files"], data["defined_names"] = index_sources(Path(session.project_root))
    data["imported_names"] = index_imports(Path(session.project_root), data["python_files"])
    from .source_context import index_source_context

    data["source_context"] = index_source_context(
        Path(session.project_root), data["python_files"], MAX_BYTES,
    )
    from .behavior import index_behavior_context

    data.update(index_behavior_context(
        Path(session.project_root), data["python_files"], data["imported_names"], MAX_BYTES, MAX_INDEXED_FILES,
    ))
    data["lint_config"] = lint_settings(Path(session.project_root))
    data["tested_versions"] = tested_versions(Path(session.project_root))
    run.stdout = json.dumps(redact_data(data), ensure_ascii=False, indent=2)
    run.exit_code = 0
    run.duration_s = round(time.monotonic() - start, 3)
    run.notes = [
        "Read-only snapshot: optional groups are not assumed to be enabled; direct references "
        "and lock files are not verified from it."
    ]
    return run


def tested_versions(root: Path) -> list[dict]:
    """Versions the project was last locked to (Pipfile.lock, poetry.lock, uv.lock).

    A lock records chosen versions, not proof that this input or test suite passed.
    The historical tested_versions field name is retained for session compatibility.
    """
    found = []

    def text(name):
        path = root / name
        try:
            return path.read_text("utf-8", errors="replace") if path.is_file() and path.stat().st_size < 4_000_000 else None
        except OSError:
            return None

    pipfile = text("Pipfile.lock")
    if pipfile:
        try:
            data = json.loads(pipfile)
            for section in ("default", "develop"):
                for name, row in (data.get(section) or {}).items():
                    version = str((row or {}).get("version", "")).lstrip("=")
                    if version:
                        found.append({"name": canonicalize_name(name), "version": version, "source": "Pipfile.lock"})
        except (ValueError, AttributeError):
            pass
    for name in ("poetry.lock", "uv.lock"):
        content = text(name)
        if not content:
            continue
        try:
            for row in tomllib.loads(content).get("package", []):
                if row.get("name") and row.get("version"):
                    found.append({"name": canonicalize_name(row["name"]), "version": str(row["version"]), "source": name})
        except (tomllib.TOMLDecodeError, AttributeError):
            continue
    return found[:5000]


def lint_settings(root: Path) -> dict:
    """Where the project configures Ruff, and which other linter it configures instead.

    Without Ruff settings, Ruff applies its own default rules, which a project that lints
    with flake8 or pylint never adopted.
    """

    def text(name):
        path = root / name
        try:
            return path.read_text("utf-8", errors="replace")[:MAX_BYTES] if path.is_file() else None
        except OSError:
            return None

    ruff = next((name for name in ("ruff.toml", ".ruff.toml") if (root / name).is_file()), None)
    pyproject = text("pyproject.toml")
    tools = {}
    if pyproject:
        try:
            tools = tomllib.loads(pyproject).get("tool", {})
        except tomllib.TOMLDecodeError:
            tools = {}
    if not ruff and isinstance(tools, dict) and "ruff" in tools:
        ruff = "pyproject.toml [tool.ruff]"
    other = next((name for name in (".flake8", ".pylintrc", "pylintrc") if (root / name).is_file()), None)
    for name in ("setup.cfg", "tox.ini"):
        content = text(name)
        if other or not content:
            continue
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read_string(content)
        except configparser.Error:
            continue
        found = next((s for s in ("flake8", "pylint", "pylint.main") if parser.has_section(s)), None)
        if found:
            other = f"{name} [{found}]"
    if not other and isinstance(tools, dict) and "pylint" in tools:
        other = "pyproject.toml [tool.pylint]"
    return {"ruff": ruff, "other": other}


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
                files.append(path.relative_to(root).as_posix())
                try:
                    if path.stat().st_size <= MAX_BYTES:
                        names.update(DEFINITION.findall(path.read_text("utf-8", errors="replace")))
                except OSError:
                    continue
    return sorted(files), sorted(names)


def index_imports(root: Path, files: list[str], limit: int = 2000) -> dict[str, str]:
    """What each imported name is: ``{"np": "numpy", "CliRunner": "click.testing.CliRunner"}``.

    Read with the syntax tree, never executed. Relative imports are the project's own code and
    names imported from different modules in different files are ambiguous; both are left out.
    """
    found: dict[str, set[str]] = {}
    for relative in files:
        path = root / relative
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            tree = ast.parse(path.read_text("utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    found.setdefault(name, set()).add(alias.name if alias.asname else name)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    if alias.name != "*":
                        found.setdefault(alias.asname or alias.name, set()).add(f"{node.module}.{alias.name}")
        if len(found) >= limit:
            break
    return {name: next(iter(modules)) for name, modules in sorted(found.items()) if len(modules) == 1}


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
