"""Bounded, static import-path candidates; these never prove module ownership.

The ordinary root/src index is also used to prove shadowing. A separate index
keeps an incidental nested name from granting that permission. A candidate can
only support guidance for the exact missing import after issue-level checks.
"""

import ast
import configparser
from pathlib import Path, PurePosixPath

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from packaging.utils import canonicalize_name

from .domain import provider


MAX_SOURCE_FILES = 2000
MAX_ROOTS = 64
MAX_CANDIDATES = 4000
MAX_METADATA_BYTES = 128_000
SKIP = {"venv", "env", "node_modules", "__pycache__", "build", "dist", "site-packages",
        "vendor", "vendors", "_vendor", "third_party", "third-party"}
INCIDENTAL = {"fixture", "fixtures", "examples", "example", "docs", "doc"}
CONTAINERS = {"src", "lib", "source", "python", "tests"}


def _safe_parts(value):
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"..", ""} for part in value.split("/")):
        return None
    if any(part.startswith(".") or part.casefold() in SKIP for part in path.parts if part != "."):
        return None
    return path


def _in_root(root, relative):
    """Skip symlinks, including in-root aliases, so a path has one identity."""
    path = root
    try:
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                return False
            if path.is_dir() and (path / "pyvenv.cfg").is_file():
                return False
        return path.resolve().is_relative_to(root)
    except OSError:
        return False


def _metadata(root, filename):
    path = root / filename
    try:
        if not _in_root(root, PurePosixPath(filename)) or not path.is_file():
            return None
        with path.open("rb") as stream:
            raw = stream.read(MAX_METADATA_BYTES + 1)
        return raw.decode("utf-8-sig") if len(raw) <= MAX_METADATA_BYTES else None
    except (OSError, UnicodeError):
        return None


def _packaging_roots(root):
    """Recognize literal search roots, never execute a backend or setup.py."""
    roots = []

    def add(value, filename):
        if isinstance(value, str):
            roots.append((value.strip(), "packaging:" + filename))

    text = _metadata(root, "pyproject.toml")
    if text is not None:
        try:
            tool = tomllib.loads(text).get("tool", {})
            setuptools = tool.get("setuptools", {})
            add(setuptools.get("package-dir", {}).get(""), "pyproject.toml")
            packages = setuptools.get("packages", {})
            if isinstance(packages, dict):
                where = packages.get("find", {}).get("where", [])
                for value in where if isinstance(where, list) else []:
                    add(value, "pyproject.toml")
            for package in tool.get("poetry", {}).get("packages", []):
                if isinstance(package, dict) and isinstance(package.get("include"), str):
                    add(package.get("from"), "pyproject.toml")
        except (ValueError, TypeError, AttributeError):
            pass
    text = _metadata(root, "setup.cfg")
    if text is not None:
        try:
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read_string(text)
            for line in cfg.get("options", "package_dir", fallback="").splitlines():
                key, equal, value = line.partition("=")
                if equal and not key.strip():
                    add(value, "setup.cfg")
            for value in cfg.get("options.packages.find", "where", fallback="").splitlines():
                add(value, "setup.cfg")
        except configparser.Error:
            pass
    text = _metadata(root, "setup.py")
    if text is not None:
        try:
            tree = ast.parse(text)
            aliases = {alias.asname or alias.name: alias.name for node in tree.body
                       if isinstance(node, ast.ImportFrom) and node.module == "setuptools"
                       for alias in node.names}
            modules = {alias.asname or alias.name for node in tree.body if isinstance(node, ast.Import)
                       for alias in node.names if alias.name == "setuptools"}

            def called(node, name):
                return (isinstance(node.func, ast.Name) and aliases.get(node.func.id) == name
                        or isinstance(node.func, ast.Attribute) and node.func.attr == name
                        and isinstance(node.func.value, ast.Name) and node.func.value.id in modules)

            for call in ast.walk(tree):
                if not isinstance(call, ast.Call) or not called(call, "setup"):
                    continue
                for keyword in call.keywords:
                    if keyword.arg == "package_dir":
                        try:
                            mapping = ast.literal_eval(keyword.value)
                        except (ValueError, TypeError):
                            continue
                        if isinstance(mapping, dict):
                            add(mapping.get(""), "setup.py")
                    if keyword.arg == "packages" and isinstance(keyword.value, ast.Call) and (
                            called(keyword.value, "find_packages") or called(keyword.value, "find_namespace_packages")):
                        for argument in keyword.value.keywords:
                            if argument.arg == "where" and isinstance(argument.value, ast.Constant):
                                add(argument.value.value, "setup.py")
        except (SyntaxError, ValueError, TypeError, RecursionError):
            pass
    return roots


def index_local_candidates(root: Path, files: list[str]) -> list[dict]:
    """Index exact dotted names under bounded, non-package import containers.

    Hitting a bound suppresses the candidate index rather than treating a
    truncated search as evidence that a name has only one possible location.
    """
    root = root.resolve()
    if len(files) >= MAX_SOURCE_FILES:
        return []
    safe = []
    for value in files:
        path = _safe_parts(value)
        if path is not None and path.suffix == ".py" and _in_root(root, path):
            safe.append(path)
    existing = {path.as_posix() for path in safe}
    roots = {}

    def add(value, source):
        relative = _safe_parts(value)
        if relative is None or relative == PurePosixPath(".") or not _in_root(root, relative):
            return
        if not (root / relative).is_dir():
            return
        if not source.startswith("packaging:"):
            if any(part.casefold() in INCIDENTAL for part in relative.parts):
                return
            if any(ancestor.name in CONTAINERS for ancestor in relative.parents
                   if ancestor != PurePosixPath(".")):
                return
            # Cutting a path inside a Python package would turn a submodule
            # into an unrelated top-level module.
            if (source != "test-helper-layout" and any((ancestor / "__init__.py").as_posix() in existing
                   for ancestor in (relative, *relative.parents) if ancestor != PurePosixPath("."))):
                return
        roots.setdefault(relative, source)

    for path in safe:
        for ancestor in path.parents:
            if (len(ancestor.parts) == 1 and ancestor.name in CONTAINERS
                    or ancestor.name == "src"):
                # A helper imported by a test inside the tests package is a
                # separate case: the consumer must verify that test location.
                source = ("test-helper-layout" if ancestor == PurePosixPath("tests")
                          and "tests/__init__.py" in existing else "conventional-layout")
                add(ancestor.as_posix(), source)
    for value, source in _packaging_roots(root):
        add(value, source)
    if len(roots) > MAX_ROOTS:
        return []
    found = {}
    for relative, source in sorted(roots.items()):
        for path in safe:
            if not path.is_relative_to(relative):
                continue
            parts = path.relative_to(relative).parts
            if any(part.casefold() in INCIDENTAL for part in parts[:-1]) and not source.startswith("packaging:"):
                continue
            components = (*parts[:-1], path.stem)
            if components[-1] == "__init__":
                components = components[:-1]
            if not components or not all(component.isidentifier() for component in components):
                continue
            # Parent directories are namespace packages when __init__.py is
            # absent. Their path, unlike a file stem, remains fully qualified.
            for length in range(1, len(components) + 1):
                name = ".".join(components[:length])
                target = relative.joinpath(*components[:length])
                if length == len(components) and path.stem != "__init__":
                    target = path
                row = {"name": name, "path": target.as_posix(), "import_root": relative.as_posix(),
                       "source": source}
                found[(name, row["path"], row["import_root"])] = row
                if len(found) > MAX_CANDIDATES:
                    return []
    return [found[key] for key in sorted(found)]


def candidate_matches(module: str, project: dict, environment: dict) -> list[dict]:
    """Return one unambiguous path, without promoting it to shadowing evidence.

    Callers must additionally establish a real project/test import failure.
    Snapshots without environment metadata cannot rule out an external owner.
    """
    if (not isinstance(module, str) or not all(part.isidentifier() for part in module.split("."))
            or not isinstance(environment.get("import_distributions"), dict)
            or not isinstance(environment.get("packages"), list)
            or not environment.get("stdlib_modules")):
        return []
    if any(not isinstance(row, dict) or not row.get("name") or not row.get("version")
           for row in environment["packages"]):
        return []
    top = module.split(".")[0]
    own = {canonicalize_name(name) for name in project.get("own_names", [])}
    providers = {canonicalize_name(name) for name in environment["import_distributions"].get(top, [])}
    if top in environment["stdlib_modules"] or providers - own:
        return []
    declared = {canonicalize_name(row.get("name", "")) for row in project.get("declarations", [])}
    import_names = {canonicalize_name(top), canonicalize_name(provider(top) or top)}
    if import_names & (declared - own):
        return []
    matches = {}
    for row in project.get("local_module_candidates", []):
        if (isinstance(row, dict) and row.get("name") == module
                and _safe_parts(row.get("path")) is not None
                and _safe_parts(row.get("import_root")) is not None):
            matches[(row["path"], row["import_root"])] = row
    return list(matches.values()) if len(matches) == 1 else []
