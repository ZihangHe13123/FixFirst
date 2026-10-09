"""Turn recorded check output into structured evidence, observed facts and features.

Everything here is read from runs that FixFirst actually recorded: pytest probe records,
the environment snapshot and the static project index. Nothing is taken from labels or
from the parser's issue category, so the learned classifier cannot simply echo the rules.
"""

import difflib
import json
from pathlib import PurePosixPath
import posixpath
import re

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .behavior import observed_changes, observed_input_errors
from .models import Fact, Issue, Run, Session
from .runner import environment_id
from .source_context import FEATURE_NAMES as SOURCE_FEATURE_NAMES, feature_values, resolved_calls
from .interface_history import FEATURE_NAMES as HISTORY_FEATURE_NAMES, feature_values as history_features
from .symbol_context import FEATURE_NAMES as SYMBOL_FEATURE_NAMES, feature_values as symbol_features
from .symbol_context import HISTORY_FEATURE_NAMES as SYMBOL_HISTORY_FEATURE_NAMES, qualified_attribute_history, valid_record

MODULE_MISSING = re.compile(r"No module named '([\w.]+)'")
CANNOT_IMPORT = re.compile(
    r"cannot import name '(\w+)' from (?:partially initialized module )?'([\w.]+)'"
)
MODULE_ATTR = re.compile(r"module '([\w.]+)' has no attribute '(\w+)'")
OBJECT_ATTR = re.compile(r"'([\w.]+)' object has no attribute '(\w+)'")
KWARG = re.compile(r"(?:([\w.]+)\(\) )?got an unexpected keyword argument '(\w+)'")
POSITIONAL = re.compile(r"([\w.]+)\(\) (?:takes|missing) \d+ (?:positional|required)")
CALL_SIGNATURE = re.compile(
    r"missing \d+ required (?:positional|keyword-only) arguments?"
    r"|takes (?:from \d+ to )?\d+ positional arguments? but \d+ (?:was|were) given"
    r"|got an unexpected keyword argument|got multiple values for argument"
    r"|positional-only arguments? passed as keyword"
)
MISSING_FILE = re.compile(r"(?:No such file or directory|\[WinError [23]\][^\r\n:]*): '([^']+)'")
PIP_CONFLICT = re.compile(
    r"^(?P<who>\S+) (?P<version>\S+) has requirement (?P<requirement>.+), but you have \S+ \S+?\.?$"
)
EXPLICIT_CONFIG = re.compile(
    r"(?:Missing (?:required )?(?:configuration|environment variable|config)|"
    r"(?:configuration|environment variable) (?:missing|not set))[:\s]+['\"]?([A-Z][A-Z0-9_]+)",
    re.I,
)
EXCEPTION_LINE = re.compile(r"^E\s+([A-Za-z_][\w.]*(?:Error|Exception|Exit|Warning)):?\s?(.*)$", re.M)
FRAME = re.compile(r"^(\S.*?\.py|<[^>]+>):(\d+):? (?:in \S+|\w+(?:Error|Exception))?\s*$", re.M)
# Plain Python tracebacks, printed when pytest or a plugin fails before pytest can format them.
PLAIN_FRAME = re.compile(r'^\s*File "([^"]+)", line (\d+)(?:, in \S+)?', re.M)
# IPython supplies file frames and arrow-marked executed lines in notebook errors.
NOTEBOOK_FRAME = re.compile(r"^File (.+?\.py):(\d+)(?:, in .*)?$", re.M)
NOTEBOOK_EXECUTED = re.compile(r"^\s*-+>\s*\d+\s+(.*)$")
IMPORT_STATEMENT = re.compile(r"^(?:from ([\w.]+) import ([\w, ()]+)|import ([\w.]+))")
NUMPY_REMOVED = re.compile(r"`(?:np|numpy)\.(\w+)` was removed")
FIXTURE_MISSING = re.compile(r"fixture '(\w+)' not found")
# pytest reports a missing fixture at the requesting test: "file /p/tests/test_x.py, line 24".
REQUEST_LOCATION = re.compile(r"^file (.+\.py), line (\d+)$", re.M)
DEPRECATED_NAME = re.compile(
    r"^(Attribute )?['\"`]?([A-Za-z_][\w.]*?)(?:\(\))?['\"`]? (?:is|are|has been|was) deprecated"
)
DEPRECATION_CATEGORIES = ("DeprecationWarning", "PendingDeprecationWarning", "FutureWarning")
CALL_WITH_KWARG = r"([A-Za-z_][\w.]*)\([^()]*\b{}\s*="
CONFIG_SUFFIXES = (".json", ".yaml", ".yml", ".ini", ".toml", ".cfg", ".conf", ".env")
CONFIG_WORDS = re.compile(
    r"\b(config\w*|settings?|environment variable|token|secret|api[_ ]?key|dsn|credential\w*)\b",
    re.I,
)
REMOVED_WORDS = re.compile(r"\b(removed|deprecated|no longer|has been moved|was renamed)\b", re.I)

EXCEPTIONS = (
    "ModuleNotFoundError",
    "ImportError",
    "AttributeError",
    "KeyError",
    "FileNotFoundError",
    "TypeError",
    "AssertionError",
    "RuntimeError",
    "ValueError",
    "NameError",
    "SyntaxError",
)
LOCATIONS = ("project", "test", "third_party", "stdlib", "unknown")
SIGNALS = (
    "no_attribute",
    "cannot_import_name",
    "unexpected_kwarg",
    "environ_lookup",
    "getenv",
    "nonetype",
    "config_words",
    "config_file",
    "config_context",
    "file_missing",
    "partially_initialized",
    "relative_import",
    "removed_hint",
)
LEGACY_FEATURE_NAMES = [
    *(f"exception_{name}" for name in EXCEPTIONS),
    "exception_other",
    "stage_collect",
    "stage_setup",
    "stage_call",
    "stage_teardown",
    *(f"raised_in_{name}" for name in LOCATIONS),
    "third_party_frame_ratio",
    "module_mentioned",
    "module_installed",
    "module_stdlib",
    "module_local",
    "module_similar_local",
    "module_declared",
    "missing_module_dotted",
    "api_mentioned",
    "owner_defined_locally",
    *(f"signal_{name}" for name in SIGNALS),
]
# Keep the schema-3 prefix stable so existing exported models remain usable.
# These shared contexts pool observable signals across different fault mechanisms;
# they are not diagnoses, rule matches or identifiers from the knowledge base.
CONTEXT_FEATURE_NAMES = [
    "context_configuration",
    "context_project_names",
    "context_import_operation",
    "context_external_provider",
    "context_data_operation",
]
V4_FEATURE_NAMES = LEGACY_FEATURE_NAMES + CONTEXT_FEATURE_NAMES
V5_FEATURE_NAMES = V4_FEATURE_NAMES + SOURCE_FEATURE_NAMES
V6_FEATURE_NAMES = V5_FEATURE_NAMES + HISTORY_FEATURE_NAMES
V7_FEATURE_NAMES = V6_FEATURE_NAMES + SYMBOL_FEATURE_NAMES
FEATURE_NAMES = V7_FEATURE_NAMES + SYMBOL_HISTORY_FEATURE_NAMES
FEATURE_LAYOUTS = {3: LEGACY_FEATURE_NAMES, 4: V4_FEATURE_NAMES, 5: V5_FEATURE_NAMES,
                   6: V6_FEATURE_NAMES, 7: V7_FEATURE_NAMES, 8: FEATURE_NAMES}


WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:/")


def classify_path(path: str, project_root: str, environment: dict) -> str:
    """Where a traceback frame lives. Accepts POSIX and Windows paths."""
    if not path:
        return "unknown"
    path = path.replace("\\", "/")
    root = (project_root or "").replace("\\", "/").rstrip("/")
    if "site-packages" in path or "dist-packages" in path:
        return "third_party"
    if root and path.startswith("../"):
        resolved = posixpath.normpath(root + "/" + path)
        if resolved.startswith("/") or WINDOWS_ABSOLUTE.match(resolved):
            path = resolved
    windows = bool(WINDOWS_ABSOLUTE.match(path))
    relative = None
    if root and (path.lower() if windows else path).startswith(
        (root.lower() if windows else root) + "/"
    ):
        relative = path[len(root) + 1 :]
    elif path.startswith("<"):
        return "stdlib" if path.startswith("<frozen") else "unknown"
    elif not path.startswith(("/", "../")) and not windows:
        relative = path  # pytest prints project files relative to the rootdir
    if relative is not None:
        name = PurePosixPath(relative).name
        parts = PurePosixPath(relative).parts
        test = (
            name.startswith("test_")
            or name.endswith("_test.py")
            or name == "conftest.py"
            or "tests" in parts
        )
        return "test" if test else "project"
    stdlib = environment.get("paths", {}).get("stdlib", "").replace("\\", "/")
    if (stdlib and path.lower().startswith(stdlib.lower())) or re.search(
        r"/lib/python3\.\d+/", path
    ):
        return "stdlib"
    return "unknown"


def frames_in(traceback: str) -> list[tuple[str, str]]:
    """(path, line) of every traceback frame, in pytest's format or Python's own."""
    found = []
    for line in traceback.splitlines():
        match = FRAME.match(line) or PLAIN_FRAME.match(line) or NOTEBOOK_FRAME.match(line)
        if match:
            found.append((match[1], match[2]))
    return found


def source_lines(traceback: str) -> str:
    """Code shown in a pytest traceback (not the error text or file paths)."""
    return "\n".join(
        line for line in traceback.splitlines()
        if line.startswith(("    ", ">")) and not FRAME.match(line.strip())
    )


def executed_lines(traceback: str) -> list[str]:
    """Source lines that actually ran: pytest's ">" lines, or the line under a frame header."""
    lines = traceback.splitlines()
    executed = []
    for index, line in enumerate(lines):
        notebook_line = NOTEBOOK_EXECUTED.match(line)
        if notebook_line:
            executed.append(notebook_line[1].strip())
        elif line.startswith(">"):
            executed.append(line[1:].strip())
        elif ((FRAME.match(line) and " in " in line) or PLAIN_FRAME.match(line)) and index + 1 < len(lines):
            following = lines[index + 1]
            if following.startswith("    ") and following.strip():
                executed.append(following.strip())
    return executed


def shown_path(path: str, project_root: str) -> str:
    """A path as the user should see it: relative inside the project, package-relative
    inside site-packages."""
    path = path.replace("\\", "/")
    # Checked first: a virtual environment often lives inside the project folder.
    inside = re.split(r"(?:site|dist)-packages/", path, maxsplit=1)
    if len(inside) == 2:
        return inside[1]
    root = project_root.replace("\\", "/").rstrip("/") + "/"
    if path.startswith(root):
        return path[len(root):]
    stdlib = re.search(r"/lib/python3\.\d+/(.+)$", path)
    return stdlib[1] if stdlib else path


def statement_at_location(traceback: str, location: str, project_root: str) -> str:
    """Match pytest's leading frame header or trailing error location.

    A trailing frame must have exactly one highlighted line since the previous
    frame. Multiline/ambiguous excerpts cannot support an exact source edit.
    """
    lines = traceback.splitlines()
    start = 0
    for index, line in enumerate(lines):
        match = FRAME.match(line) or PLAIN_FRAME.match(line)
        if not match:
            continue
        if f"{shown_path(match[1], project_root)}:{match[2]}" == location:
            if " in " in line and index + 1 < len(lines) and lines[index + 1].startswith("    "):
                return lines[index + 1].strip().removeprefix(">").strip()[:2000]
            highlighted = [item[1:].strip() for item in lines[start:index] if item.startswith(">")]
            if len(highlighted) == 1:
                return highlighted[0][:2000]
        start = index + 1
    return ""


def describe_warning(record: dict, project_root: str, environment: dict) -> dict:
    """Where a recorded warning came from and whether the environment, not the test, added it.

    A deprecation warning counts as coming from the environment when it is raised inside an
    installed library or the standard library, or when it names a standard-library or
    Python-version deprecation. Deprecations a project raises for its own API do not count.
    """
    from .domain import deprecation

    category = str(record.get("category", ""))
    message = str(record.get("message", ""))
    filename = str(record.get("filename", ""))
    kind = classify_path(filename, project_root, environment)
    match = DEPRECATED_NAME.match(message)
    if match:
        entity = ("attribute:" if match[1] else "api:") + match[2]
    else:
        entity = "warning:" + category
    top = match[2].split(".")[0] if match and not match[1] else ""
    if kind == "third_party":
        package = re.split(r"[/.]", shown_path(filename, project_root), maxsplit=1)[0]
        names = environment.get("import_distributions", {}).get(package) or [package]
        emitted_by = "dist:" + canonicalize_name(names[0])
    elif kind == "stdlib":
        emitted_by = "dist:python"
    elif kind in ("project", "test"):
        emitted_by = "project"
    else:
        emitted_by = "unknown"
    external = category in DEPRECATION_CATEGORIES and (
        kind in ("third_party", "stdlib")
        or bool(re.search(r"\bPython 3\.\d+", message))
        or top in environment.get("stdlib_modules", [])
        or deprecation(entity) is not None
    )
    line = record.get("lineno")
    return {
        "category": category,
        "message": message[:300],
        "origin": shown_path(filename, project_root) + (f":{line}" if line else ""),
        "origin_kind": kind,
        "emitted_by": emitted_by,
        "entity": entity,
        "external": external,
    }


def domain_usages(message: str) -> list[str]:
    from .domain import usages_in

    return usages_in(message)


def output_context(session: Session, event) -> str:
    """For events parsed from plain output, the lines leading up to the error line."""
    run = next((r for r in session.runs if r.run_id == event.run_id), None)
    for ref in event.evidence_refs:
        _, stream, line = (ref.split(":") + ["", ""])[:3]
        if run and stream in ("stdout", "stderr") and line.isdigit():
            lines = getattr(run, stream).splitlines()
            return "\n".join(lines[max(0, int(line) - 40) : int(line)])
    return event.message


def records_for(session: Session, issue: Issue) -> list[dict]:
    """Probe records cited by the issue's events (failure longrepr and exception details)."""
    runs = {r.run_id: r for r in session.runs}
    found = []
    for event in session.events:
        if event.event_id not in issue.event_ids:
            continue
        for ref in event.evidence_refs:
            run_id, _, index = ref.partition(":probe:")
            run = runs.get(run_id)
            if run and index.isdigit() and int(index) < len(run.records):
                found.append(run.records[int(index)])
    return found


def issue_evidence(session: Session, issue: Issue) -> dict:
    events = [e for e in session.events if e.event_id in issue.event_ids]
    records = records_for(session, issue)
    exception_record = next((r for r in records if r.get("type") == "exception"), {})
    failure_record = next((r for r in records if r.get("type") == "failure"), {})
    probe_runs = {ref.partition(":probe:")[0] for event in events for ref in event.evidence_refs if ":probe:" in ref}
    executed_runs = {r.run_id for r in session.runs if r.source == "executed"}
    executed_metadata = bool(probe_runs) and probe_runs <= executed_runs
    symbol = valid_record(exception_record.get("symbol_observation")) if executed_metadata else {}
    # Collection issues retain the failure-report reference; pytest emits its
    # structured CollectError afterward. Join only one matching executed record,
    # without replacing the legacy exception/frame fields used by old models.
    if (not symbol and executed_metadata and failure_record.get("stage") == "collect"
            and failure_record.get("nodeid")):
        matches = [r for run in session.runs if run.run_id in probe_runs for r in run.records
                   if r.get("type") == "exception" and r.get("exception_type") == "CollectError"
                   and r.get("stage") == "collect" and r.get("nodeid") == failure_record["nodeid"]]
        if len(matches) == 1:
            symbol = valid_record(matches[0].get("symbol_observation"))
    traceback = str(failure_record.get("message") or "")
    if not traceback:
        traceback = "\n".join(output_context(session, e) for e in events)
    exception = str(exception_record.get("exception_type") or "")
    message = str(exception_record.get("exception_message") or "")
    if exception in ("", "CollectError"):
        found = EXCEPTION_LINE.findall(traceback)
        if found:
            exception, message = found[-1][0].split(".")[-1], found[-1][1]
        elif events and events[0].code:
            exception, message = events[0].code, events[0].message
        else:
            match = re.search(r"\b(\w+(?:Error|Exception)):\s*(.*)", events[0].message) if events else None
            exception, message = (match[1], match[2]) if match else ("", events[0].message if events else "")
    if issue.kind == "test_assertion":
        exception = "AssertionError"
    text = message + "\n" + traceback
    environment = current_environment(session)

    located = frames_in(traceback)
    source_file = str(exception_record.get("source_file") or "")
    notebook = bool(exception_record.get("cell") and source_file)

    def frame_key(path):
        value = path.replace("\\", "/")
        if not value.startswith(("/", "<")) and not WINDOWS_ABSOLUTE.match(value):
            value = posixpath.normpath(session.project_root.replace("\\", "/") + "/" + value)
        return value.casefold() if WINDOWS_ABSOLUTE.match(value) else value

    # pytest may hide a library frame in longrepr. The probe still records the
    # innermost frame of the actual exception; preserve it for provenance/call flow.
    if source_file and exception_record.get("stage") != "collect" and not notebook:
        source_line = str(exception_record.get("source_line") or "")
        if located and frame_key(located[-1][0]) == frame_key(source_file):
            located[-1] = (source_file, source_line or located[-1][1])
        else:
            located.append((source_file, source_line))
    frames = [path for path, _ in located]
    last = source_file if source_file and exception_record.get("stage") != "collect" and not notebook else ""
    if not last and frames:
        last = frames[-1]
    if not last and notebook:
        last = source_file
    raised_in = classify_path(last, session.project_root, environment)
    kinds = [classify_path(f, session.project_root, environment) for f in frames]
    # Attribute the raising frame, not an outer library which called user code.
    library = ""
    if raised_in == "third_party":
        inside = re.split(r"(?:site|dist)-packages[\\/]", last.replace("\\", "/"), maxsplit=1)
        if len(inside) == 2:
            library = re.split(r"[/.]", inside[1], maxsplit=1)[0]
    # The last frame in the user's own code is where they should look.
    root = session.project_root.replace("\\", "/").rstrip("/") + "/"
    where = ""
    for (path, line), kind in zip(located, kinds):
        if kind in ("project", "test"):
            shown = path.replace("\\", "/")
            where = f"{shown[len(root):] if shown.startswith(root) else shown}:{line}"

    if not where:
        # Fixture errors cite the requesting test instead of a traceback frame.
        for path, line in REQUEST_LOCATION.findall(traceback):
            if classify_path(path, session.project_root, environment) in ("project", "test"):
                where = f"{shown_path(path, session.project_root)}:{line}"
    source_location = where
    source_statement = ""
    symbol_origin = classify_path(str(symbol.get("file", "")), session.project_root, environment)
    symbol_location = (f"{shown_path(symbol['file'], session.project_root)}:{symbol['line']}"
                       if symbol and type(symbol.get("line")) is int and symbol["line"] > 0 else "")
    symbol_statement = ""
    trace_lines = traceback.splitlines()
    for index, line in enumerate(trace_lines[:-1]):
        match = FRAME.match(line) or PLAIN_FRAME.match(line)
        if match and f"{shown_path(match[1], session.project_root)}:{match[2]}" == source_location:
            source_statement = trace_lines[index + 1].strip().removeprefix(">").strip()[:2000]
    if symbol_location:
        symbol_statement = statement_at_location(traceback, symbol_location, session.project_root)
    if notebook:
        where = f"{shown_path(source_file, session.project_root)} · cell {exception_record['cell']}"
    warnings = [
        describe_warning(w, session.project_root, environment)
        for w in exception_record.get("warnings") or []
        if isinstance(w, dict)
    ]
    recorders = {w.get("recorder") for w in exception_record.get("warnings") or [] if isinstance(w, dict)}
    # The failed assertion is about the recorder (len(recwarn) == 1, not record, ...).
    warning_assertion = exception == "AssertionError" and bool(warnings) and (
        re.search(r"Warnings(?:Recorder|Checker)\(", text) is not None
        or any(
            re.search(rf"\b{re.escape(str(name))}\b", line)
            for name in recorders if name
            for line in executed_lines(traceback)
        )
    )

    evidence = {
        "issue_id": issue.issue_id,
        "exception": exception,
        "exception_module": (str(exception_record.get("exception_module") or "")
                             if exception_record.get("exception_type") == exception else ""),
        "message": message[:2000],
        "executed_lines": executed_lines(traceback)[:80],
        "stage": issue.stage,
        "raised_in": raised_in,
        "where": where,
        # The notebook cell is the user-facing location; static callable matching
        # must use the actual Python file/line when that cell calls a module.
        "source_location": source_location,
        "source_statement": source_statement,
        "library": library,
        "library_location": (f"{shown_path(last, session.project_root)}:{located[-1][1]}"
                             if library and located else ""),
        "third_party_frame_ratio": round(kinds.count("third_party") / len(kinds), 3) if kinds else 0.0,
        "missing_module": None,
        "modules": [],
        "apis": [],
        "attributes": [],
        "kwargs": [],
        "owners": [],
        "config_keys": [],
        "missing_files": [],
        "fixtures": FIXTURE_MISSING.findall(text)[:5],
        "warnings": warnings,
        "warning_assertion": warning_assertion,
        "signals": [],
        "runtime_attribute": exception_record.get("attribute_access") or {},
        "module_attribute": exception_record.get("module_attribute") or {},
        "symbol_observation": symbol,
        "symbol_use_origin": symbol_origin,
        "symbol_location": symbol_location,
        "symbol_statement": symbol_statement,
        "precise_statement": statement_at_location(traceback, source_location, session.project_root),
        "library_calls": [],
        "call_arguments": [],
        "validation_errors": exception_record.get("validation_errors") or [],
    }
    for frame in exception_record.get("traceback_frames", [])[:20]:
        if not isinstance(frame, dict):
            continue
        path, function = str(frame.get("file", "")), str(frame.get("function", ""))
        if classify_path(path, session.project_root, environment) != "third_party":
            continue
        pieces = re.split(r"(?:site|dist)-packages[\\/]", path.replace("\\", "/"), maxsplit=1)
        if len(pieces) == 2 and re.fullmatch(r"\w+", function):
            module = pieces[1].removesuffix(".py").replace("/", ".").removesuffix(".__init__")
            evidence["library_calls"].append(f"{module}.{function}")
            shapes = frame.get("array_shapes")
            if isinstance(shapes, dict) and all(
                isinstance(shapes.get(k), list) and len(shapes[k]) <= 16
                and all(type(v) is int and v >= 0 for v in shapes[k]) for k in ("a", "b")
            ):
                evidence["call_arguments"].append({"callee": f"{module}.{function}", "shapes": shapes})

    def add(key, value):
        if value and value not in evidence[key]:
            evidence[key].append(value)

    match = MODULE_MISSING.search(text)
    if match:
        add("modules", match[1])
        evidence["missing_module"] = match[1]
    for name, module in CANNOT_IMPORT.findall(text):
        add("modules", module)
        add("apis", f"{module}.{name}")
    for module, name in MODULE_ATTR.findall(message or text):
        add("modules", module)
        add("apis", f"{module}.{name}")
    for owner, name in OBJECT_ATTR.findall(message or text):
        add("attributes", name)
        add("owners", owner)
        if owner != "NoneType" and "." not in owner:
            add("apis", f"{owner}.{name}")
    # Qualified object types in text alone are not enough to borrow an API's
    # history. The target-side probe records the actual registered object's type.
    attribute = evidence["runtime_attribute"]
    if exception == "AttributeError" and isinstance(attribute, dict):
        parts = [attribute.get(k, "") for k in ("owner_module", "owner_name", "name")]
        if all(isinstance(p, str) and re.fullmatch(r"[A-Za-z_]\w*(?:\.\w+)*", p) for p in parts):
            add("attributes", ".".join(parts))
            add("modules", parts[0])
    for owner in POSITIONAL.findall(message):
        add("owners", owner.split(".")[0])
    for owner, name in KWARG.findall(message):
        add("kwargs", name)
        owner = owner.split(".")[0] if owner else ""
        if not owner:
            call = re.search(CALL_WITH_KWARG.format(re.escape(name)), traceback)
            owner = call[1].split(".")[-1] if call else ""
        if owner:
            add("owners", owner)
            add("kwargs", f"{owner}.{name}")
    for name in NUMPY_REMOVED.findall(message):
        add("modules", "numpy")
        add("apis", f"numpy.{name}")
    # The import statement that ran names the API even when a library raises a custom message.
    statements = [
        m.groups() for m in map(IMPORT_STATEMENT.match, executed_lines(traceback)) if m
    ]
    if statements and exception.endswith(("ImportError", "ModuleNotFoundError")):
        module, names, plain = statements[-1]
        if module:
            add("modules", module)
            # When the error names the missing name, the rest of the import line is fine.
            if not CANNOT_IMPORT.search(text):
                for name in re.findall(r"\w+", names):
                    add("apis", f"{module}.{name}")
        elif plain and not evidence["modules"]:
            add("modules", plain)
    for key in re.findall(r"environ\[['\"]([A-Za-z_][\w]*)['\"]\]", traceback):
        add("config_keys", key)
    for key in re.findall(r"getenv\(['\"]([A-Za-z_][\w]*)['\"]", traceback):
        add("config_keys", key)
    match = EXPLICIT_CONFIG.search(message)
    if match:
        add("config_keys", match[1])
    if exception == "KeyError" and ("environ" in traceback or "<frozen os>" in last):
        key = message.strip().strip("'\"")
        if re.fullmatch(r"[A-Za-z_]\w*", key):
            add("config_keys", key)
    for path in MISSING_FILE.findall(text):
        add("missing_files", path.replace("\\\\", "\\"))

    signals = {
        "no_attribute": "has no attribute" in message,
        "cannot_import_name": "cannot import name" in text,
        "unexpected_kwarg": "unexpected keyword argument" in message,
        "environ_lookup": "environ" in traceback and exception == "KeyError",
        "getenv": "getenv(" in traceback,
        "nonetype": "'NoneType' object" in message,
        "config_words": bool(CONFIG_WORDS.search(message)),
        "config_file": any(
            p.lower().endswith(CONFIG_SUFFIXES) or re.search(r"config|settings|\.env", p, re.I)
            for p in evidence["missing_files"]
        ),
        "config_context": bool(CONFIG_WORDS.search(source_lines(traceback))),
        "file_missing": bool(evidence["missing_files"]),
        "partially_initialized": "partially initialized module" in text,
        "relative_import": "attempted relative import" in text
        or "no known parent package" in text,
        "removed_hint": bool(REMOVED_WORDS.search(message)),
    }
    evidence["signals"] = [name for name in SIGNALS if signals[name]]
    evidence["modules"] = [m.split(".")[0] for m in evidence["modules"]]
    evidence["modules"] = list(dict.fromkeys(evidence["modules"]))
    # A call rejected for its arguments, and what was called as the code spells it
    # (``yaml.load``, ``CliRunner``). Used for grounded advice, not classifier labels.
    evidence["call_signature"] = exception == "TypeError" and bool(CALL_SIGNATURE.search(message))
    evidence["callees"] = []
    if evidence["call_signature"]:
        lines = executed_lines(traceback)
        for owner in evidence["owners"]:
            call = next(
                (m for m in (re.search(rf"([A-Za-z_][\w.]*\.)?\b{re.escape(owner)}\s*\(", line)
                             for line in reversed(lines)) if m),
                None,
            )
            add("callees", (call[1] or "") + owner if call else owner)
    # Did the project's own code call into the library that raised?
    first = next((i for i, (path, kind) in enumerate(zip(frames, kinds))
                  if kind == "third_party" and library and f"/{library}" in path.replace("\\", "/")), None)
    evidence["project_calls_library"] = first is not None and any(
        kind in ("project", "test") for kind in kinds[:first]
    )
    return evidence


def current_environment(session: Session) -> dict:
    """The environment snapshot, only if it was taken from the selected interpreter."""
    if session.environment.get("_environment_id") != environment_id(session.target_python):
        return {}
    return session.environment


def project_index(session: Session) -> tuple[Run | None, dict]:
    """The latest project snapshot, only if assessed against the current environment snapshot.

    Declaration status depends on installed versions, so a later environment refresh makes
    an older project snapshot stale until the project check runs again.
    """
    current = environment_id(session.target_python)
    run = next(
        (
            r
            for r in reversed(session.runs)
            if r.tool == "project" and r.source == "executed" and r.environment_id == current
        ),
        None,
    )
    environment = current_environment(session)
    if not run or not environment.get("_run_id"):
        return None, {}
    try:
        data = json.loads(run.stdout)
    except ValueError:
        return None, {}
    if not isinstance(data, dict) or data.get("environment_run_id") != environment["_run_id"]:
        return None, {}
    return run, data


def module_context(session: Session, module: str, project: dict) -> dict:
    """What the environment snapshot and project index say about an import name."""
    environment = current_environment(session)
    dotted = "." in module
    leaf = module.rsplit(".", 1)[-1]
    provided = [] if dotted else environment.get("import_distributions", {}).get(module, [])
    files = project.get("python_files", [])
    if dotted:
        relative = module.replace(".", "/")
        local = [
            f for f in files
            if f.removeprefix("src/") in (relative + ".py", relative + "/__init__.py")
        ]
    else:
        local = [r["path"] for r in project.get("local_modules", []) if r["name"] == module]
    stems = {}
    for path in files:
        pure = PurePosixPath(path)
        stems.setdefault(pure.stem if pure.name != "__init__.py" else pure.parent.name, path)
    similar = [
        stems[name]
        for name in difflib.get_close_matches(leaf, list(stems), n=3, cutoff=0.75)
        if name != leaf
    ]
    declared = [
        row["source"]
        for row in project.get("declarations", [])
        if row["name"] == canonicalize_name(module)
        or any(canonicalize_name(d) == row["name"] for d in provided)
    ]
    return {
        "installed": provided,
        "stdlib": not dotted and module in environment.get("stdlib_modules", []),
        "stdlib_known": bool(environment.get("stdlib_modules")),
        "local": local,
        "similar": similar,
        "declared": declared,
    }


def features(evidence: dict, contexts: dict, project: dict, environment=None, *, interface_history=True) -> list[float]:
    """Numeric evidence features for the decision tree, in FEATURE_NAMES order."""
    module = evidence["missing_module"] or (evidence["modules"][0] if evidence["modules"] else None)
    context = contexts.get(module, {}) if module else {}
    top = contexts.get(module.split(".")[0], {}) if module else {}
    defined = set(project.get("defined_names", []))
    values = {f"exception_{name}": evidence["exception"] == name for name in EXCEPTIONS}
    values["exception_other"] = evidence["exception"] not in EXCEPTIONS
    values.update({f"stage_{s}": evidence["stage"] == s for s in ("collect", "setup", "call", "teardown")})
    values.update({f"raised_in_{name}": evidence["raised_in"] == name for name in LOCATIONS})
    values["third_party_frame_ratio"] = evidence["third_party_frame_ratio"]
    values["module_mentioned"] = module is not None
    values["module_installed"] = bool(top.get("installed"))
    values["module_stdlib"] = bool(top.get("stdlib"))
    values["module_local"] = bool(context.get("local") or evidence.get("local_import_candidate"))
    values["module_similar_local"] = bool(context.get("similar"))
    values["module_declared"] = bool(context.get("declared") or top.get("declared"))
    values["missing_module_dotted"] = bool(evidence["missing_module"] and "." in module)
    values["api_mentioned"] = bool(evidence["apis"] or evidence["kwargs"])
    values["owner_defined_locally"] = any(o in defined for o in evidence["owners"])
    values.update({f"signal_{name}": name in evidence["signals"] for name in SIGNALS})
    values["context_configuration"] = any(
        values[f"signal_{name}"]
        for name in ("environ_lookup", "getenv", "config_words", "config_file", "config_context")
    )
    values["context_project_names"] = any(
        values[name] for name in (
            "module_local", "module_similar_local", "owner_defined_locally",
            "signal_relative_import", "signal_partially_initialized",
        )
    )
    values["context_import_operation"] = evidence["exception"] in (
        "ImportError", "ModuleNotFoundError",
    ) or values["signal_cannot_import_name"] or values["signal_relative_import"]
    values["context_external_provider"] = any(
        values[name] for name in ("module_installed", "module_stdlib", "raised_in_third_party")
    )
    values["context_data_operation"] = evidence["exception"] in (
        "KeyError", "ValueError", "NameError", "SyntaxError", "IndexError", "ZeroDivisionError",
    )
    values.update(feature_values(evidence, values, project, environment or {}))
    values.update(history_features(evidence, values, project, environment or {}, use_history=interface_history))
    values.update(symbol_features(evidence))
    values["qualified_attribute_history_match"] = (
        interface_history and qualified_attribute_history(evidence, project, environment or {}))
    return [float(values[name]) for name in FEATURE_NAMES]


def observed(subject, predicate, value, refs) -> Fact:
    return Fact(
        fact_id=f"{subject}:{predicate}:{value}",
        subject=subject,
        predicate=predicate,
        value=value,
        evidence_refs=sorted(set(refs)),
    )


def renamed_module_candidates(session: Session, evidence: dict, candidates: list[str]) -> list[str]:
    """Filter D16's candidates without changing the similarity evidence for the tree."""
    leaf = evidence["missing_module"].rsplit(".", 1)[-1]
    test_names = {f"{prefix}{leaf}" for prefix in ("test_", "tests_")} | {
        f"{leaf}{suffix}" for suffix in ("_test", "_tests")
    }

    def path_key(value):
        value = value.replace("\\", "/")
        if not value.startswith("/") and not WINDOWS_ABSOLUTE.match(value):
            value = posixpath.join(session.project_root.replace("\\", "/"), value)
        value = posixpath.normpath(value)
        return value.casefold() if WINDOWS_ABSOLUTE.match(value) else value

    # An outer project caller is not the importer when the exception is raised in a library.
    location = (evidence.get("source_location") or "") if evidence.get("raised_in") in ("project", "test") else ""
    importer = path_key(location.rsplit(":", 1)[0]) if location else None
    return [path for path in candidates
            if path_key(path) != importer and PurePosixPath(path).stem not in test_names]


def observations(session: Session, issues: list[Issue], *, interface_history=True) -> tuple[list[Fact], dict]:
    """Observed facts for the rule base plus per-issue evidence and feature vectors."""
    facts: list[Fact] = []
    details = {}
    project_run, project = project_index(session)
    project_ref = [f"{project_run.run_id}:stdout:1"] if project_run else []
    environment = current_environment(session)
    env_ref = [f"{environment['_run_id']}:stdout:1"] if environment.get("_run_id") else []
    # Root causes are for failing tests; a check that could not run is a tool problem.
    diagnosable = [
        i for i in issues
        if i.tool in ("pytest", "pytest_run", "python_run", "unittest_run")
        and i.kind != "tool_failure" and i.stage != "verification"
    ]
    modules = set()
    for issue in diagnosable:
        evidence = issue_evidence(session, issue)
        from .observed_operations import projection

        projected, operation_context = projection(
            session, issue, evidence, {**project, "_run_id": project_run.run_id if project_run else None},
            environment, use_history=interface_history)
        evidence["operation_context"] = operation_context
        facts += projected
        if interface_history:
            from .removal_ownership import evidence_facts as removal_owner_facts

            facts += removal_owner_facts(
                session, issue, evidence, {**project, "_run_id": project_run.run_id if project_run else None},
                environment)
        modules.update(f.value.removeprefix("module:") for f in projected if f.predicate == "module")
        from .binding_advice import evidence_facts as binding_facts

        facts += binding_facts(session, issue, evidence, project, environment)
        refs = issue.evidence_refs
        subject = issue.issue_id
        if evidence["exception"]:
            facts.append(observed(subject, "exception", evidence["exception"], refs))
        if evidence["exception_module"]:
            facts.append(observed(subject, "exception_module", evidence["exception_module"], refs))
        facts.append(observed(subject, "raised_in", evidence["raised_in"], refs))
        if evidence["where"]:
            facts.append(observed(subject, "source_location", evidence["where"], refs))
        spelling = evidence["module_attribute"]
        if (isinstance(spelling, dict) and spelling.get("source") == "loaded_module_namespace"
                and spelling.get("unique") is True and len(spelling.get("suggestions", [])) == 1
                and classify_path(str(spelling.get("file", "")), session.project_root, environment) in ("project", "test")
                and type(spelling.get("line")) is int and spelling["line"] > 0):
            module, old, new = spelling.get("module", ""), spelling.get("name", ""), spelling["suggestions"][0]
            if all(isinstance(v, str) and re.fullmatch(r"[A-Za-z_]\w*(?:\.\w+)*", v) for v in (module, old, new)):
                facts += [observed(subject, "spelling_module", "module:" + module, refs),
                          observed(subject, "spelling_from", module + "." + old, refs),
                          observed(subject, "spelling_to", module + "." + new, refs),
                          observed(subject, "spelling_location", f"{shown_path(spelling['file'], session.project_root)}:{spelling['line']}", refs)]
                modules.add(module)
        for module in evidence["modules"]:
            facts.append(observed(subject, "module", "module:" + module, refs))
            modules.add(module)
        if evidence["missing_module"]:
            facts.append(
                observed(subject, "missing_module", "module:" + evidence["missing_module"], refs)
            )
            modules.add(evidence["missing_module"])
            top = evidence["missing_module"].split(".")[0]
            if top != evidence["missing_module"]:
                # Which package the missing submodule belongs to (and whether that is installed).
                facts.append(observed("module:" + evidence["missing_module"], "submodule_of", "module:" + top, refs))
                modules.add(top)
        for api in evidence["apis"]:
            facts.append(observed(subject, "api", "api:" + api, refs))
        for name in evidence["attributes"]:
            facts.append(observed(subject, "attribute", "attribute:" + name, refs))
        for name in evidence["kwargs"]:
            facts.append(observed(subject, "kwarg", "kwarg:" + name, refs))
        for owner in evidence["owners"]:
            facts.append(observed(subject, "owner", "callable:" + owner, refs))
            if owner in project.get("defined_names", []):
                facts.append(observed("callable:" + owner, "defined_locally", "yes", project_ref))
        for key in evidence["config_keys"]:
            facts.append(observed(subject, "config_key", "config:" + key, refs))
        for path in evidence["missing_files"]:
            facts.append(observed(subject, "missing_file", "file:" + path, refs))
        for signal in evidence["signals"]:
            facts.append(observed(subject, "signal", signal, refs))
        for usage in domain_usages(evidence["message"]):
            facts.append(observed(subject, "usage", usage, refs))
        if re.search(r"setup\.py'?,? '?(?:bdist|sdist|build|install|develop|egg_info)", evidence["message"]):
            facts.append(observed(subject, "runs", "setup.py", refs))
            installed = {canonicalize_name(p.get("name", "")) for p in environment.get("packages", [])}
            if environment.get("_run_id") and "setuptools" not in installed:
                facts.append(observed("dist:setuptools", "not_installed", "yes", env_ref))
        for fixture in dict.fromkeys(evidence["fixtures"]):
            facts.append(observed(subject, "missing_fixture", "fixture:" + fixture, refs))
            if fixture in project.get("defined_names", []):
                facts.append(observed("fixture:" + fixture, "defined_locally", "yes", project_ref))
        facts += warning_facts(subject, evidence, refs)
        if evidence["library"]:
            providers = environment.get("import_distributions", {}).get(evidence["library"]) or []
            names = providers or [
                evidence["library"]
            ]
            dist = "dist:" + canonicalize_name(names[0])
            facts.append(observed(subject, "raised_by_library", dist, refs))
            if len({canonicalize_name(name) for name in providers}) == 1:
                facts.append(observed(subject, "library_owner", dist, refs + env_ref))
            if evidence["library_location"]:
                facts.append(observed(subject, "library_location", evidence["library_location"], refs))
            if evidence.get("project_calls_library"):
                facts.append(observed(subject, "project_calls", dist, refs))
            if dist == "dist:pytest" or dist.startswith("dist:pytest-"):
                facts.append(observed(dist, "is_test_runner", "yes", refs))
        for change, distribution in observed_changes(evidence, project):
            facts.append(observed(subject, "behavior_symptom", "behavior:" + change, refs + project_ref))
            facts.append(observed(subject, "behavior_provider", "dist:" + distribution, refs + project_ref))
        for symptom, distribution in observed_input_errors(evidence):
            facts.append(observed(subject, "input_symptom", "input:" + symptom, refs))
            facts.append(observed(subject, "input_provider", "dist:" + distribution, refs))
        if evidence.get("call_signature"):
            facts.append(observed(subject, "signal", "call_signature", refs))
            # Resolve what was called through the project's own imports (read statically).
            for qualified in resolved_calls(evidence, project, legacy=True):
                top = qualified.split(".")[0]
                facts.append(observed(subject, "callee", "callable:" + qualified, refs))
                facts.append(observed(subject, "callee_module", "module:" + top, refs))
                modules.add(top)
        from .local_import_context import for_issue as local_import_context

        candidate = local_import_context(session, issue, project_run, project, environment)
        if candidate:
            evidence["local_import_candidate"] = candidate
            facts.append(observed(subject, "local_import_candidate", candidate["path"], candidate["refs"]))
        details[subject] = evidence
    # The distributions this project builds. Installed (for example in editable mode), their
    # modules are the project's own code, not another library that a project file hides.
    for name in project.get("own_names", []) if project_run else []:
        facts.append(observed("dist:" + name, "is_project", "yes", project_ref))
    contexts = {}
    for module in sorted(modules):
        context = module_context(session, module, project)
        contexts[module] = context
        subject = "module:" + module
        for distribution in context["installed"]:
            facts.append(
                observed(subject, "provided_by", "dist:" + canonicalize_name(distribution), env_ref)
            )
        if context["stdlib"]:
            facts.append(observed(subject, "in_stdlib", "yes", env_ref))
        if project_run:
            for path in context["local"]:
                facts.append(observed(subject, "is_local", path, project_ref))
            for path in context["similar"]:
                facts.append(observed(subject, "similar_local", path, project_ref))
            for source in context["declared"]:
                facts.append(observed(subject, "declared_in", source, project_ref))
    if project_run:
        for issue in diagnosable:
            evidence = details[issue.issue_id]
            module = evidence["missing_module"]
            if module:
                for path in renamed_module_candidates(session, evidence, contexts[module]["similar"]):
                    facts.append(observed(issue.issue_id, "renamed_module_candidate", path,
                                          issue.evidence_refs + project_ref))
    # Requires-Dist remains available even in uv environments without pip. A
    # conflicting lower bound is evidence for upgrading, not for searching back.
    from .dependency_context import context, requirements_for, combined_specifier

    dependency_context = context(environment, {**project, "_run_id": project_run.run_id if project_run else None})
    constrained = set()
    for name, installed_version in dependency_context["installed"].items():
        rows = requirements_for(dependency_context, name)
        try:
            broken = any(r["owner"] != "project" and not SpecifierSet(r["specifier"]).contains(installed_version)
                         for r in rows)
        except InvalidVersion:
            continue
        if not broken:
            continue
        dist = "dist:" + name
        refs = sorted({ref for r in rows for ref in r["refs"]})
        facts.append(observed(dist, "required_spec", combined_specifier(dependency_context, name), refs))
        facts.append(observed(dist, "required_by", "; ".join(sorted({r["source"] for r in rows})), refs))
        constrained.add(dist)
    # pip check: "flask 1.1.4 has requirement Jinja2<3.0,>=2.10.1, but you have jinja2 3.1.6."
    for issue in issues:
        if issue.tool != "pip_check" or issue.kind != "dependency_conflict":
            continue
        for event in (e for e in session.events if e.event_id in issue.event_ids):
            found = PIP_CONFLICT.match(event.message.strip())
            if not found:
                continue
            try:
                requirement = Requirement(found["requirement"])
            except InvalidRequirement:
                continue
            dist = "dist:" + canonicalize_name(requirement.name)
            if dist in constrained:
                continue
            refs = event.evidence_refs
            facts.append(observed(dist, "required_spec", str(requirement.specifier), refs))
            facts.append(observed(dist, "required_by", f"{found['who']} {found['version']}", refs))
    # Ruff findings: the rule code, with the knowledge base, decides whether it may be a bug.
    for issue in issues:
        if issue.tool == "ruff" and issue.kind in ("style_issue", "code_check") and issue.component:
            facts.append(observed(issue.issue_id, "lint_rule", "lint:" + issue.component, issue.evidence_refs))
    if project_run and "lint_config" in project:
        lint = project["lint_config"] or {}
        facts.append(observed("project", "ruff_config", lint.get("ruff") or "none", project_ref))
        if lint.get("other"):
            facts.append(observed("project", "other_linter", lint["other"], project_ref))
    # Versions the project was locked to, for the libraries that raised a failure.
    raising = {f.value for f in facts if f.predicate in ("raised_by_library", "behavior_provider")}
    for index, row in enumerate(project.get("tested_versions", [])):
        dist = "dist:" + row["name"]
        if dist not in raising:
            continue
        try:
            tested = Version(row["version"])
        except InvalidVersion:
            continue
        ref = [f"{project_run.run_id}:stdout:1"]
        facts.append(observed(dist, "tested_version", row["version"], ref))
        facts.append(observed(dist, "tested_in", row["source"], ref))
        # Stay in the release series the project was tested with: behaviour changes also land
        # in minor releases (SQLAlchemy 1.4 already changed result objects).
        facts.append(observed(dist, "tested_series_below", f"{tested.major}.{tested.minor + 1}", ref))
    # The lowest version the project declares, for the libraries involved in a failure: code
    # written for 1.x may not behave the same on 2.x.
    involved = {f.value for f in facts if f.predicate in ("raised_by_library", "provided_by", "behavior_provider")}
    for row in project.get("declarations", []):
        dist = "dist:" + row["name"]
        if dist not in involved:
            continue
        try:
            requirement = Requirement(row["requirement"])
            lows = [
                Version(s.version) for s in requirement.specifier
                if s.operator in (">=", "~=", "==", "===", ">") and "*" not in s.version
            ]
        except (InvalidRequirement, InvalidVersion):
            continue
        if not lows:
            continue
        low, ref = max(lows), [f"{project_run.run_id}:stdout:1"]
        facts.append(observed(dist, "declared_spec", f"{row['name']}{requirement.specifier}", ref))
        facts.append(observed(dist, "declared_minimum", str(low), ref))
        facts.append(observed(dist, "declared_major_below", str(low.major + 1), ref))
        facts.append(observed(dist, "declared_in_file", row["source"], ref))
    # Release searches (versions.py): which releases still provide a name.
    searches = {}
    for run in session.runs:
        if (run.tool == "version_search" and run.source == "executed" and run.status == "completed"
                and run.exit_code == 0 and run.environment_id == environment_id(session.target_python)):
            try:
                data = json.loads(run.stdout)
            except ValueError:
                continue
            if not isinstance(data, dict) or not data.get("api") or not data.get("dist"):
                continue
            current_version = next((p.get("version") for p in environment.get("packages", [])
                                    if canonicalize_name(p.get("name", "")) == canonicalize_name(data["dist"])), None)
            if environment and data.get("installed") != current_version:
                continue  # A later environment change needs a new search.
            if data.get("context_fingerprint"):
                if data["context_fingerprint"] != dependency_context["fingerprint"]:
                    continue
            elif data.get("provides") and requirements_for(dependency_context, data["dist"]):
                continue  # Old name-only trials did not verify these requirements.
            searches[data.get("api", "")] = (run, data)
    for api, (run, data) in searches.items():
        name, ref = "api:" + api, [f"{run.run_id}:stdout:1"]
        facts.append(observed(name, "release_search", "dist:" + canonicalize_name(data["dist"]), ref))
        if not run.verified_pass:
            facts.append(observed(name, "search_inconclusive", "yes", ref))
            continue
        if data.get("provides"):
            facts.append(observed(name, "provided_until_release", data["provides"], ref))
        if data.get("below"):
            facts.append(observed(name, "install_below", data["below"], ref))
        if data.get("status") == "not_found":
            facts.append(observed(name, "not_in_older_releases", str(len(data.get("checked", []))), ref))
    for index, row in enumerate(project.get("declarations", [])):
        if not row.get("constraint"):
            facts.append(
                observed("dist:" + row["name"], "declared_in", row["source"],
                         [f"{project_run.run_id}:declaration:{index}"])
            )
    for issue in diagnosable:
        evidence = details[issue.issue_id]
        evidence["features"] = features(evidence, contexts, project, environment, interface_history=interface_history)
    if session.structured_evidence:
        # Preserve every actual source when the legacy and opt-in projections agree.
        unique = {}
        for fact in facts:
            key = (fact.subject, fact.predicate, fact.value)
            if key in unique:
                unique[key].evidence_refs = list(dict.fromkeys([*unique[key].evidence_refs, *fact.evidence_refs]))
            else:
                unique[key] = fact
        facts = list(unique.values())
    return facts, details


def warning_facts(subject: str, evidence: dict, refs) -> list[Fact]:
    """Facts about the warnings a failing test recorded.

    Only the most telling extra warning is named: one raised outside the project (which the
    project cannot change) is preferred, then a named deprecation over an unnamed one.
    """
    warnings = evidence["warnings"]
    if not warnings:
        return []
    facts = [observed(subject, "recorded_warning_count", str(len(warnings)), refs)]
    if evidence["warning_assertion"]:
        facts.append(observed(subject, "asserts_on", "recorded_warnings", refs))
    external = [w for w in warnings if w["external"]]
    if external:
        primary = min(
            external,
            key=lambda w: (w["origin_kind"] in ("project", "test"), w["entity"].startswith("warning:")),
        )
        name = primary["entity"]
        facts += [
            observed(subject, "extra_warning_count", str(len(external)), refs),
            observed(subject, "extra_warning", name, refs),
            observed(name, "emitted_at", primary["origin"], refs),
            observed(name, "emitted_by", primary["emitted_by"], refs),
            observed(name, "warning_text", primary["message"], refs),
        ]
    return facts


def environment_facts(session: Session, distributions: set[str]) -> list[Fact]:
    """Installed versions for distributions that knowledge facts refer to."""
    environment = current_environment(session)
    if not environment.get("_run_id"):
        return []
    ref = [f"{environment['_run_id']}:stdout:1"]
    facts = []
    installed = {}
    for package in environment.get("packages", []):
        installed.setdefault(canonicalize_name(package.get("name", "")), package.get("version", ""))
    for dist in sorted(distributions):
        if dist == "dist:python":
            version = environment.get("python_version")
        else:
            version = installed.get(dist.split(":", 1)[1])
        if version:
            facts.append(observed(dist, "installed_version", version, ref))
            try:
                parsed = Version(version)
            except InvalidVersion:
                continue
            # Upper bound for "the release series before this one": 9.1.1 -> <9, 0.4.2 -> <0.4.
            bound = str(parsed.major) if parsed.major else f"0.{parsed.minor}"
            if bound not in ("0", "0.0"):
                facts.append(observed(dist, "previous_series_below", bound, ref))
    return facts
