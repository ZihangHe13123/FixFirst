"""Snapshot-backed local import guidance shared by test and program goals."""

import ast
import configparser
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .pytest_settings import _read

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


_BACKENDS = {"setuptools.build_meta": "setuptools", "setuptools.build_meta:__legacy__": "setuptools",
             "hatchling.build": "hatchling", "flit_core.buildapi": "flit-core",
             "poetry.core.masonry.api": "poetry-core"}


def _named_metadata(value):
    if (not isinstance(value, dict) or not isinstance(value.get("name"), str)
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", value["name"])):
        return False
    dynamic = isinstance(value.get("dynamic"), list) and "version" in value["dynamic"]
    if "version" not in value:
        return dynamic
    if dynamic or not isinstance(value["version"], str):
        return False
    try:
        Version(value["version"])
        return True
    except InvalidVersion:
        return False


def recorded_editable_project(root: Path) -> dict:
    """Record a conservative build entrypoint without importing or running it.

    This establishes an optional installation route, not that the build succeeds
    or that its backend supports every declared option. Configuration-only files
    and dynamic setup functions supply no such route.
    """
    absent = {"schema_version": 1, "supported": False, "sources": []}
    root = Path(root)
    try:
        if root.is_symlink() or not root.is_dir():
            return absent
        root = root.resolve(strict=True)
        texts = {name: _read(root, name) for name in ("pyproject.toml", "setup.py", "setup.cfg")}
        pyproject_present = (root / "pyproject.toml").exists() or (root / "pyproject.toml").is_symlink()
        cfg = {}
        if texts["setup.cfg"] is not None:
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(texts["setup.cfg"])
            parser.defaults().clear()
            cfg = dict(parser.items("metadata")) if parser.has_section("metadata") else {}
        if pyproject_present:
            if texts["pyproject.toml"] is None:
                return absent
            data = tomllib.loads(texts["pyproject.toml"])
            build = data.get("build-system")
            if not isinstance(build, dict) or build.get("build-backend") not in _BACKENDS:
                return absent
            requires = build.get("requires")
            if (not isinstance(requires, list) or not requires or build.get("backend-path")
                    or not all(isinstance(item, str) for item in requires)):
                return absent
            backend = build["build-backend"]
            parsed = [Requirement(item) for item in requires]
            if not any(canonicalize_name(item.name) == _BACKENDS[backend] and item.marker is None for item in parsed):
                return absent
            sources = ["pyproject.toml"]
            metadata = data.get("project")
            if backend == "poetry.core.masonry.api" and not _named_metadata(metadata):
                metadata = data.get("tool", {}).get("poetry")
            if backend.startswith("setuptools.") and not _named_metadata(metadata) and _named_metadata(cfg):
                metadata = cfg
                sources.append("setup.cfg")
            if _named_metadata(metadata):
                return {"schema_version": 1, "supported": True, "sources": sources, "backend": backend}
            return absent
        if texts["setup.py"] is None:
            return absent
        module = ast.parse(texts["setup.py"])
        imports = {}
        for node in module.body:
            if isinstance(node, ast.ImportFrom) and node.module in ("setuptools", "distutils.core"):
                imports.update({n.asname or n.name: node.module + "." + n.name for n in node.names})
            elif isinstance(node, ast.Import):
                imports.update({n.asname or n.name: n.name for n in node.names})
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.ClassDef)):
                names = ({node.name} if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else
                         {part.id for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                          for part in ast.walk(target) if isinstance(part, ast.Name)})
                for name in names:
                    imports.pop(name, None)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                name = (imports.get(call.func.id) if isinstance(call.func, ast.Name) else
                        imports.get(call.func.value.id, "") + "." + call.func.attr
                        if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) else "")
                if name not in ("setuptools.setup", "distutils.core.setup"):
                    continue
                if any(keyword.arg is None for keyword in call.keywords):
                    continue
                values = dict(cfg)
                for keyword in call.keywords:
                    if keyword.arg in ("name", "version"):
                        values[keyword.arg] = ast.literal_eval(keyword.value)
                if _named_metadata(values):
                    sources = ["setup.py"] + (["setup.cfg"] if cfg else [])
                    return {"schema_version": 1, "supported": True, "sources": sources,
                            "backend": name.rsplit(".", 1)[0]}
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError, SyntaxError,
            configparser.Error, InvalidRequirement, RecursionError):
        pass
    return absent


def _current_project(session):
    from .evidence import current_environment, project_index

    run, project = project_index(session)
    environment = current_environment(session)
    latest = next((r for r in reversed(session.runs) if r.tool == "project"), None)
    latest_env = next((r for r in reversed(session.runs) if r.tool == "environment"), None)
    env_run = next((r for r in session.runs if r.run_id == environment.get("_run_id")), None)
    if (not run or run is not latest or not env_run or env_run.tool != "environment"
            or env_run is not latest_env
            or env_run.environment_id != environment.get("_environment_id") or run.cwd != session.project_root
            or any(r.source != "executed" or r.status != "completed" or r.exit_code != 0 or r.truncated
                   for r in (run, env_run)) or not env_run.verified_pass):
        return {}, {}
    return project, environment


def _import_root(module, project, environment):
    from .local_imports import candidate_matches

    candidates = candidate_matches(module, project, environment)
    if len(candidates) == 1:
        return candidates[0]["import_root"]
    # Old snapshots only recorded root and src, without an import_root field.
    paths = {row.get("path") for row in project.get("local_modules", [])
             if isinstance(row, dict) and row.get("name") == module.split(".")[0]}
    roots = set()
    for path in paths:
        if not isinstance(path, str):
            continue
        parts = PurePosixPath(path).parts
        if len(parts) == 1:
            roots.add(".")
        elif len(parts) == 2 and parts[0] == "src":
            roots.add("src")
    return next(iter(roots)) if len(roots) == 1 else None


def _original_command(session):
    if session.goal == "run_project":
        return "original notebook execution" if session.execution and session.execution.kind == "notebook" else "original program command"
    return {"pass_tests": "original test command", "collect_tests": "original test-collection command",
            "pass_unittest": "original unittest command", "check_style": "original style-check command"}[session.goal]


def _editable_route(record):
    if (not isinstance(record, dict) or type(record.get("schema_version")) is not int
            or record["schema_version"] != 1 or record.get("supported") is not True
            or not isinstance(record.get("sources"), list)):
        return False
    sources, backend = record["sources"], record.get("backend")
    if not isinstance(backend, str):
        return False
    if backend in _BACKENDS:
        return sources == ["pyproject.toml"] or (
            str(backend).startswith("setuptools.") and sources == ["pyproject.toml", "setup.cfg"])
    return backend in ("setuptools", "distutils.core") and sources in (["setup.py"], ["setup.py", "setup.cfg"])


def refine(session, actions, by_id):
    """Refine P12 using recorded project evidence; never read live project files."""
    project, environment = _current_project(session)
    original = _original_command(session)
    for action in actions:
        if "P12" not in action.rule_ids:
            continue
        modules = {by_id[i].component for i in action.issue_ids if i in by_id}
        relative = _import_root(next(iter(modules)), project, environment) if len(modules) == 1 and project else None
        location = "the directory containing the top-level module or package"
        if isinstance(relative, str):
            path = PurePosixPath(relative)
            if not path.is_absolute() and ".." not in path.parts and "\\" not in relative:
                cls = PureWindowsPath if re.match(r"^[A-Za-z]:[\\/]", session.project_root) else PurePosixPath
                location = str(cls(session.project_root).joinpath(*path.parts))
        action.explanation = (
            "The module was recorded in this project but the selected Python cannot import it. "
            f"Add the absolute path to {location} to PYTHONPATH in the environment of the same Python interpreter. "
            + ("This is the project's src directory. " if relative == "src" else "")
            + "Preserve any existing PYTHONPATH entries "
            "using your platform's path separator. If setting it in a shell, quote the entire path/value, "
            "including paths containing spaces; do not paste an unquoted path into a shell assignment. "
            f"Then re-run the {original} from the project root, preserving its arguments and input."
        )
        if session.goal == "run_project" and (not session.execution or session.execution.kind != "notebook"):
            action.explanation += (
                " If the entry is a module inside a package, use Python module mode with its package.module "
                "name instead of executing that package file directly, retaining its arguments and input."
            )
        metadata = project.get("editable_project", {})
        if _editable_route(metadata):
            action.explanation += (
                " If the project reads its own installed distribution metadata, PYTHONPATH alone is insufficient. "
                "The current project snapshot records a build entrypoint. Review the project's build instructions, "
                "then optionally install this project from its root using the same selected Python interpreter "
                "with -m pip install -e .; quote the interpreter path when it contains spaces. This also supplies "
                "the project's installed metadata. Re-run the original command after installation."
            )
        action.verification = (
            f"Re-run the {original} with the same interpreter, arguments and input and the updated import path"
        )
        action.command = []
    return actions
