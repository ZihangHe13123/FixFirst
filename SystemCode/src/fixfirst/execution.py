"""Static entry discovery and native execution without requiring pytest in the project."""

import ast
import configparser
import fnmatch
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from .models import Execution, Run, check_scope

EXCLUDED = {".git", ".venv", "venv", "env", ".env", ".tox", ".nox", "node_modules",
            ".fixfirst", "__pycache__", ".ipynb_checkpoints", "site-packages",
            "build", "dist", "workbench"}
MAX_FILES = 3000


def pytest_settings(root):
    files, functions, configured = ["test_*.py", "*_test.py"], ["test*"], False
    for name, section in (("pytest.ini", "pytest"), ("tox.ini", "pytest"), ("setup.cfg", "tool:pytest")):
        try:
            path = root / name
            if not path.is_file() or path.stat().st_size > 250_000:
                continue
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(path.read_text(encoding="utf-8-sig"))
            if config.has_section(section):
                configured = True
                files = config.get(section, "python_files", fallback=" ".join(files)).split()
                functions = config.get(section, "python_functions", fallback=" ".join(functions)).split()
        except (OSError, UnicodeError, configparser.Error):
            pass
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    try:
        path = root / "pyproject.toml"
        data = (tomllib.loads(path.read_text(encoding="utf-8"))
                if path.is_file() and path.stat().st_size <= 250_000 else {})
        values = data.get("tool", {}).get("pytest", {}).get("ini_options")
        if isinstance(values, dict):
            configured = True
            for key, destination in (("python_files", files), ("python_functions", functions)):
                value = values.get(key)
                if isinstance(value, str):
                    destination[:] = value.split()
                elif isinstance(value, list) and all(isinstance(v, str) for v in value):
                    destination[:] = value
    except (OSError, UnicodeError, ValueError, AttributeError):
        pass
    return files, functions, configured


def discover(root: Path) -> dict:
    """Suggestions only. Never import project code or treat a config as a test."""
    entries, tests, unit_tests, all_python, preferred = [], [], [], [], []
    count, limited = 0, False
    patterns, function_patterns, pytest_configured = pytest_settings(root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not d.startswith(".")
                         and not (Path(directory) / d).is_symlink())
        if len(Path(directory).relative_to(root).parts) >= 6:
            dirs[:] = []
        for name in sorted(files):
            count += 1
            if count > MAX_FILES:
                limited = True
                break
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if path.suffix == ".ipynb":
                entries.append({"kind": "notebook", "entry": relative})
                continue
            if path.suffix != ".py":
                continue
            if name == "conftest.py":
                pytest_configured = True
                continue
            if name in ("setup.py", "__init__.py"):
                continue
            tree = None
            try:
                if path.stat().st_size <= 250_000:
                    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, SyntaxError):
                pass
            nodes = list(ast.walk(tree)) if tree else []
            imported = {alias.name.split(".")[0] for n in nodes if isinstance(n, ast.Import)
                        for alias in n.names}
            imported |= {n.module.split(".")[0] for n in nodes
                         if isinstance(n, ast.ImportFrom) and n.module}
            has_case = any(isinstance(n, ast.ClassDef) and any(
                (isinstance(b, ast.Attribute) and b.attr == "TestCase")
                or (isinstance(b, ast.Name) and b.id == "TestCase") for b in n.bases)
                for n in nodes)
            is_unit = "unittest" in imported and "pytest" not in imported and has_case
            test_name = (any(fnmatch.fnmatch(name, p) for p in patterns)
                         or (is_unit and fnmatch.fnmatch(name, "test*.py")))
            has_tests = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and any(fnmatch.fnmatch(n.name, p) for p in function_patterns) for n in nodes)
            # Broken test files must still be checked; empty placeholder files are not tests.
            if test_name and (has_tests or tree is None):
                tests.append(relative)
                if is_unit:
                    unit_tests.append(relative)
                continue
            if test_name:
                continue
            all_python.append(relative)
            main_guard = any(
                isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                and isinstance(n.test.left, ast.Name) and n.test.left.id == "__name__"
                and any(isinstance(v, ast.Constant) and v.value == "__main__"
                        for v in n.test.comparators) for n in nodes
            )
            if name == "__main__.py" and path.parent != root:
                parts = path.parent.relative_to(root).parts
                if parts and parts[0] == "src":
                    parts = parts[1:]
                if all(p.isidentifier() for p in parts):
                    entries.append({"kind": "module", "entry": ".".join(parts)})
            elif main_guard or (path.parent == root and name in ("main.py", "app.py", "run.py")):
                entry = {"kind": "script", "entry": relative}
                entries.append(entry)
                if path.parent == root and name == "main.py":
                    preferred.append(entry)
        if limited:
            break
    if not entries and len(all_python) == 1:
        entries = [{"kind": "script", "entry": all_python[0]}]
    default = preferred[0] if len(preferred) == 1 else entries[0] if len(entries) == 1 else None
    unit = bool(tests) and len(tests) == len(unit_tests) and not pytest_configured
    # A custom suite remains selectable manually; discovery is intentionally conservative.
    unit_entry = "tests" if tests and all(p.startswith("tests/") for p in tests) else "."
    goal = "pass_unittest" if unit else "pass_tests" if tests else "run_project"
    return {"entries": entries[:100], "tests": tests[:100], "test_count": len(tests),
            "suggested_goal": goal, "default_entry": default, "limited": limited,
            "unittest_entry": unit_entry}


def validate_execution(root: Path, execution: Execution | dict, goal: str) -> Execution:
    value = Execution.model_validate(execution).model_copy(deep=True)
    if any("\x00" in arg or len(arg) > 16_000 for arg in value.args):
        raise ValueError("Program arguments contain a NUL character or are too long")
    if "\x00" in value.entry or "\x00" in value.pattern:
        raise ValueError("The entry or test pattern contains a NUL character")
    if goal == "pass_unittest" and value.kind != "unittest":
        raise ValueError("Choose a unittest discovery directory for this goal")
    if goal == "run_project" and value.kind == "unittest":
        raise ValueError("Choose a script, module or notebook for this goal")
    if value.kind == "module":
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", value.entry):
            raise ValueError("Use a Python module name, for example package.main")
    else:
        path = (root / value.entry).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("The entry must be inside the project folder")
        if value.kind == "unittest":
            if not path.is_dir():
                raise ValueError("The unittest discovery directory does not exist")
        elif not path.is_file() or path.suffix != {"script": ".py", "notebook": ".ipynb"}[value.kind]:
            raise ValueError(f"The {value.kind} entry does not exist or has the wrong extension")
        value.entry = path.relative_to(root.resolve()).as_posix()
    if value.kind in ("notebook", "unittest") and (value.args or value.stdin):
        raise ValueError("Arguments and standard input apply to scripts and modules only")
    return value


def choose_execution(root: Path, goal: str, execution=None):
    found = discover(root)
    if goal == "auto":
        if execution:
            kind = execution.kind if isinstance(execution, Execution) else execution.get("kind")
            goal = "pass_unittest" if kind == "unittest" else "run_project"
        else:
            goal = found["suggested_goal"]
    if goal in ("run_project", "pass_unittest"):
        if execution is None:
            execution = ({"kind": "unittest", "entry": found["unittest_entry"]}
                         if goal == "pass_unittest" else found["default_entry"])
        if execution is None:
            raise ValueError("No single program entry was found. Choose a .py file, module or notebook.")
        execution = validate_execution(root, execution, goal)
    elif execution is not None:
        raise ValueError("Execution settings require the run_project or pass_unittest goal")
    return goal, execution


def collect_execution(session, tool, timeout):
    from .runner import environment_id, execute, MAX_OUTPUT, redact_data

    scope = check_scope(session, tool)
    try:
        if session.execution is None:
            raise ValueError("Choose a program entry or unittest directory before running")
        config = validate_execution(Path(session.project_root), session.execution,
                                    "pass_unittest" if tool == "unittest_run" else "run_project")
    except ValueError as exc:
        return Run(tool=tool, scope=scope, environment_id=environment_id(session.target_python),
                   cwd=session.project_root, status="launch_failed", stderr=str(exc))
    python, cwd = session.target_python, session.project_root
    with tempfile.TemporaryDirectory(prefix="fixfirst-execution-", ignore_cleanup_errors=True) as directory:
        records = Path(directory) / "records.jsonl"
        helper = Path(__file__).with_name(
            "_native_runner.py" if config.kind in ("script", "module") else
            "_unittest_runner.py" if config.kind == "unittest" else "_notebook_runner.py")
        native = config.kind in ("script", "module")
        if native:
            entry = config.entry if config.kind == "module" else str(Path(cwd) / config.entry)
            path0 = cwd if config.kind == "module" else str(Path(entry).parent)
            argv = [python, str(helper), config.kind, entry, path0, str(records), *config.args]
        elif config.kind == "unittest":
            argv = [python, str(helper), config.entry, config.pattern]
        else:
            argv = [sys.executable, str(helper), python, str(Path(cwd) / config.entry), str(timeout)]
        run = execute(argv, cwd, tool, scope, python, timeout,
                      input_text=config.stdin if native else None,
                      extra_env={**({} if native else {"FIXFIRST_EXECUTION_RECORDS": str(records)}),
                                 "PYTHONDONTWRITEBYTECODE": "1"})
        run.execution_kind = config.kind
        if records.exists():
            with records.open("rb") as stream:
                raw = stream.read(MAX_OUTPUT + 1)
            if len(raw) > MAX_OUTPUT:
                run.truncated = True
            for line in raw[:MAX_OUTPUT].decode("utf-8", errors="replace").splitlines():
                try:
                    record = json.loads(line)
                    if isinstance(record, dict):
                        run.records.append(redact_data(record))
                except ValueError:
                    run.notes.append("Execution records were incomplete")
        return run
