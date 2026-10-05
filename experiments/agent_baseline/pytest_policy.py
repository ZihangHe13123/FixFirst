"""Opt-in H5 protection. Legacy integrity and saved grades stay in real_cases.py."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import stat

from iniconfig import IniConfig, ParseError

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

LEGACY = "legacy"
H5 = "h5-v1"
POLICIES = (LEGACY, H5)
ALLOWED = {"pythonpath", "DJANGO_SETTINGS_MODULE"}
INI_FILES = {"pytest.ini": "pytest", ".pytest.ini": "pytest", "tox.ini": "pytest", "setup.cfg": "tool:pytest"}
TOML_FILES = ("pytest.toml", ".pytest.toml", "pyproject.toml")
CONFIG_FILES = (*INI_FILES, *TOML_FILES)
ALWAYS_CARRIERS = {"pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml"}
SKIP_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", ".nox", "node_modules"}
TEST_DIRS = {"tests", "test", "testing"}
# Classification only. Protection does not depend on this list keeping up with pytest.
SELECTION = {"addopts", "testpaths", "python_files", "python_classes", "python_functions", "norecursedirs",
             "filterwarnings", "xfail_strict", "strict_xfail", "strict_markers", "strict_parametrization_ids",
             "strict_config", "usefixtures", "required_plugins", "markers", "minversion", "confcutdir",
             "collect_ignore", "collect_ignore_glob"}
PROBE = Path(__file__).with_name("_h5_grading_probe.py")
PROMPT = (
    " H5 grading rule: do not add, edit or remove test files, conftest.py, or files under tests/, test/ or testing/."
    " In root pytest configuration only pythonpath and DJANGO_SETTINGS_MODULE may be added, changed or removed;"
    " every other pytest option must remain unchanged. If pytest configuration already exists, keep exactly"
    " the same configuration files; otherwise you may add one configuration location with only those options."
    " The grader runs the full suite in a fresh process without your shell's environment variables;"
    " it requires the reference's complete test nodes and every reference-passing test to pass."
)


def identity() -> str:
    """Bind both the rule and the executed probe; changing either starts a new protocol/cache."""
    h = hashlib.sha256()
    for path in (Path(__file__), PROBE, *[Path(__file__).with_name(n) for n in
                                       ("agent_pilot.py", "real_cases.py", "isolation.py", "hard_instances.py")]):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def read_file(path: Path, limit=16 << 20) -> bytes:
    """Bounded nonblocking read, refusing links, directories, sockets and named pipes."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("not a regular file")
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("not a regular file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("file exceeds the read limit")
    return data


def is_test_file(relative: Path) -> bool:
    name = relative.name
    return (name == "conftest.py" or name.startswith("test_") and name.endswith(".py")
            or name.endswith("_test.py") or bool(TEST_DIRS & set(relative.parts[:-1])))


def config_tables(root: Path) -> tuple[dict, list[str]]:
    """Keep native and ini tables separate. Never collapse multiline values or option-name case."""
    tables, errors = {}, []
    for name in CONFIG_FILES:
        path = root / name
        if not os.path.lexists(path):
            continue
        try:
            text = read_file(path, 1 << 20).decode("utf-8")
            if name in INI_FILES:
                section = INI_FILES[name]
                data = IniConfig(str(path), data=text).sections
                if section in data or name in ALWAYS_CARRIERS:
                    values = dict(data.get(section, {}))
                    if "addopts" in values:
                        values["addopts"] = shlex.split(values["addopts"])
                    tables[name] = {section: values}
            else:
                data = tomllib.loads(text)
                if name == "pyproject.toml":
                    tool = data.get("tool", {})
                    if not isinstance(tool, dict):
                        raise ValueError("tool is not a table")
                    if "pytest" not in tool:
                        continue
                    options = tool["pytest"]
                    if not isinstance(options, dict):
                        raise ValueError("tool.pytest is not a table")
                    native = {k: v for k, v in options.items() if k != "ini_options"}
                    sections = {}
                    if native:
                        sections["tool.pytest"] = native
                    if "ini_options" in options:
                        if not isinstance(options["ini_options"], dict):
                            raise ValueError("tool.pytest.ini_options is not a table")
                        sections["tool.pytest.ini_options"] = options["ini_options"]
                    tables[name] = sections  # even an empty declared table is a carrier
                else:
                    options = data.get("pytest", {})
                    if not isinstance(options, dict):
                        raise ValueError("pytest is not a table")
                    tables[name] = {"pytest": options}
        except (OSError, ValueError, ParseError) as error:
            tables[name] = {}
            errors.append(f"{name}: {type(error).__name__}: {error}")
    return tables, errors


def snapshot(root: Path) -> dict:
    tests, errors = {}, []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for name in sorted(files) + [d for d in dirs if (Path(folder) / d).is_symlink()]:
            path = Path(folder) / name
            relative = path.relative_to(root)
            protected = is_test_file(relative) or (name in TEST_DIRS and path.is_symlink())
            if not protected:
                continue
            try:
                tests[relative.as_posix()] = hashlib.sha256(read_file(path)).hexdigest()
            except (ValueError, OSError) as error:
                tests[relative.as_posix()] = "unreadable"
                errors.append(f"test {relative.as_posix()}: {error}")
    tables, config_errors = config_tables(root)
    options = {f"{name}:{section}:{key}": json.dumps(value, sort_keys=True, default=str)
               for name, sections in tables.items() for section, table in sections.items()
               for key, value in table.items() if key not in ALLOWED}
    return {"tests": tests, "options": options, "carriers": sorted(tables), "tables": tables,
            "errors": errors + config_errors}


def violations(before: dict, after: dict) -> dict:
    """Stable keys and categories; callers retain the first occurrence, even after restoration."""
    found = {}
    for field, category in (("tests", "test_content"), ("options", "other_pytest_option")):
        a, b = before[field], after[field]
        for key in sorted(a.keys() | b.keys()):
            if a.get(key) != b.get(key):
                kind = "selection_or_outcome" if field == "options" and key.rsplit(":", 1)[-1] in SELECTION else category
                found[f"{field}:{key}"] = {"category": kind, "before": a.get(key), "after_value": b.get(key)}
    a, b = before["carriers"], after["carriers"]
    if (a and a != b) or (not a and len(b) > 1):
        found["configuration_carriers"] = {"category": "configuration_carriers", "before": a, "after_value": b}
    for error in after["errors"]:
        found[f"unreadable:{error}"] = {"category": "test_content" if error.startswith("test ") else "configuration_carriers"}
    return found


def observation_problems(data, code) -> list[str]:
    """Validate the independent probe before a result may be graded."""
    if (not isinstance(data, dict) or data.get("schema") != 1 or data.get("policy") != H5
            or data.get("started") is not True):
        return ["missing or invalid H5 grader observation"]
    if data.get("complete") is not True or data.get("exit_code") != code or type(code) is not int:
        return ["H5 grader observation did not complete with the process exit code"]
    if data.get("errors") != []:
        return [f"H5 grader observation errors: {data.get('errors')}"]
    nodes, outcomes = data.get("nodes"), data.get("outcomes")
    if not isinstance(nodes, list) or not all(isinstance(n, str) and n for n in nodes) or len(nodes) != len(set(nodes)):
        return ["H5 collected nodes are missing, malformed or duplicated"]
    if not isinstance(outcomes, dict) or any(n not in nodes or o not in {"passed", "failed", "error", "skipped", "xfailed", "xpassed"}
                                             for n, o in outcomes.items()):
        return ["H5 per-node outcomes are malformed"]
    if code == 0 and set(outcomes) != set(nodes):
        return ["H5 successful suite lacks outcomes for collected nodes"]
    config = data.get("config")
    if not isinstance(config, dict) or set(config) != {"file", "raw", "effective"}:
        return ["H5 effective configuration is missing"]
    if not isinstance(config["file"], (str, type(None))) or any(not isinstance(config[k], dict) for k in ("raw", "effective")):
        return ["H5 effective configuration is malformed"]
    if set(config["raw"]) != set(config["effective"]) or set(config["raw"]) & ALLOWED:
        return ["H5 protected effective configuration keys are inconsistent"]
    for value in config["effective"].values():
        if (not isinstance(value, dict) or set(value) != {"registered", "value"}
                or type(value["registered"]) is not bool):
            return ["H5 effective option observation is malformed"]
    return []


def failed_check(suite: dict) -> bool:
    """A trusted probe started, and the pytest process returned failure normally.

    Complete settings/nodes are necessary to prove success, not to turn pytest's
    nonzero exit into a failure. No completion inference from a missing startup record.
    """
    observation = suite.get("h5_observation")
    return (suite.get("grading_policy") == H5 and suite.get("grading_policy_sha256") == identity()
            and suite.get("h5_process_stopped") is False and type(suite.get("exit_code")) is int
            and suite["exit_code"] in {1, 2, 3, 4, 5} and isinstance(observation, dict)
            and observation.get("schema") == 1 and observation.get("policy") == H5
            and observation.get("started") is True)


def state_problems(state) -> list[str]:
    if not isinstance(state, dict) or set(state) != {"tests", "options", "carriers", "tables", "errors"}:
        return ["H5 protection snapshot is missing or malformed"]
    if (any(not isinstance(state[k], dict) for k in ("tests", "options", "tables"))
            or any(not isinstance(state[k], list) for k in ("carriers", "errors"))):
        return ["H5 protection snapshot fields are malformed"]
    if any(not isinstance(k, str) or not isinstance(v, str) for f in ("tests", "options") for k, v in state[f].items()):
        return ["H5 protection snapshot values are malformed"]
    if (any(not isinstance(n, str) or n not in CONFIG_FILES for n in state["carriers"])
            or state["carriers"] != sorted(state["tables"]) or not all(isinstance(e, str) for e in state["errors"])):
        return ["H5 protection snapshot carriers are malformed"]
    if any(not isinstance(sections, dict) or any(not isinstance(v, dict) for v in sections.values())
           for sections in state["tables"].values()):
        return ["H5 protection snapshot tables are malformed"]
    return []


def configuration_problems(observation: dict, state: dict) -> list[str]:
    """The recorded active settings must include the protected settings of the selected file.

    A pytest downgrade must not silently ignore a newer config format/option. Refuse to grade
    an active protected option that the grader's pytest/plugins cannot interpret.
    """
    config = observation["config"]
    priority = ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")
    expected_file = next((name for name in priority if name in state["carriers"]), None)
    # A bare pyproject may be pytest's fallback config while carrying no pytest options.
    if expected_file is not None and config["file"] != expected_file:
        return ["H5 pytest did not load the highest-priority project configuration carrier"]
    if config["file"] not in state["tables"]:
        return [] if not config["raw"] and config["file"] in (None, "pyproject.toml") else ["H5 loaded config has no static counterpart"]
    sections = state["tables"][config["file"]]
    expected = {}
    for section, values in sections.items():
        for key, value in values.items():
            if key not in ALLOWED:
                # pyproject ini mode converts scalars to strings, unlike native TOML mode.
                if section == "tool.pytest.ini_options" and not isinstance(value, list):
                    value = str(value)
                expected[key] = shlex.split(value) if key == "addopts" and isinstance(value, str) else value
    if config["raw"] != expected:
        return ["H5 actual explicit settings do not match the protected file settings"]
    if any(value.get("registered") is not True for value in config["effective"].values()
           if isinstance(value, dict)):
        return ["H5 an active protected option is not recognized by the grader's pytest/plugins"]
    return []


def compare(result: dict, reference: dict) -> list[str]:
    a, b = reference["h5_observation"], result["h5_observation"]
    reasons = []
    if set(a["nodes"]) != set(b["nodes"]):
        reasons.append("H5 full collected test nodes differ from the reference")
    if a["config"]["raw"] != b["config"]["raw"] or a["config"]["effective"] != b["config"]["effective"]:
        reasons.append("H5 actual protected pytest configuration differs from the reference")
    # Different allowed-only configuration files are legal only when the start had none.
    if reference["h5_baseline"]["carriers"] and a["config"]["file"] != b["config"]["file"]:
        reasons.append("H5 the loaded pytest configuration file differs from the reference")
    lost = [n for n, o in a["outcomes"].items() if o == "passed" and b["outcomes"].get(n) != "passed"]
    if lost:
        reasons.append(f"H5 {len(lost)} reference-passing nodes did not pass, e.g. {sorted(lost)[0]}")
    return reasons
