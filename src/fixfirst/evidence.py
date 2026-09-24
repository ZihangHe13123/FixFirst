"""Turn recorded check output into structured evidence, observed facts and features.

Everything here is read from runs that FixFirst actually recorded: pytest probe records,
the environment snapshot and the static project index. Nothing is taken from labels or
from the parser's issue category, so the learned classifier cannot simply echo the rules.
"""

import difflib
import json
from pathlib import PurePosixPath
import re

from packaging.utils import canonicalize_name

from .models import Fact, Issue, Run, Session
from .runner import environment_id

MODULE_MISSING = re.compile(r"No module named '([\w.]+)'")
CANNOT_IMPORT = re.compile(
    r"cannot import name '(\w+)' from (?:partially initialized module )?'([\w.]+)'"
)
MODULE_ATTR = re.compile(r"module '([\w.]+)' has no attribute '(\w+)'")
OBJECT_ATTR = re.compile(r"'(\w+)' object has no attribute '(\w+)'")
KWARG = re.compile(r"(?:([\w.]+)\(\) )?got an unexpected keyword argument '(\w+)'")
POSITIONAL = re.compile(r"([\w.]+)\(\) (?:takes|missing) \d+ (?:positional|required)")
MISSING_FILE = re.compile(r"No such file or directory: '([^']+)'")
EXPLICIT_CONFIG = re.compile(
    r"(?:Missing (?:required )?(?:configuration|environment variable|config)|"
    r"(?:configuration|environment variable) (?:missing|not set))[:\s]+['\"]?([A-Z][A-Z0-9_]+)",
    re.I,
)
EXCEPTION_LINE = re.compile(r"^E\s+([A-Za-z_][\w.]*(?:Error|Exception|Exit|Warning)):?\s?(.*)$", re.M)
FRAME = re.compile(r"^(\S.*?\.py|<[^>]+>):(\d+):? (?:in \S+|\w+(?:Error|Exception))?\s*$", re.M)
IMPORT_STATEMENT = re.compile(r"^(?:from ([\w.]+) import ([\w, ()]+)|import ([\w.]+))")
NUMPY_REMOVED = re.compile(r"`(?:np|numpy)\.(\w+)` was removed")
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
FEATURE_NAMES = [
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


WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:/")


def classify_path(path: str, project_root: str, environment: dict) -> str:
    """Where a traceback frame lives. Accepts POSIX and Windows paths."""
    if not path:
        return "unknown"
    path = path.replace("\\", "/")
    root = (project_root or "").replace("\\", "/").rstrip("/")
    if "site-packages" in path or "dist-packages" in path:
        return "third_party"
    windows = bool(WINDOWS_ABSOLUTE.match(path))
    relative = None
    if root and (path.lower() if windows else path).startswith(
        (root.lower() if windows else root) + "/"
    ):
        relative = path[len(root) + 1 :]
    elif path.startswith("<"):
        return "stdlib" if path.startswith("<frozen") else "unknown"
    elif not path.startswith("/") and not windows:
        relative = path
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
        if line.startswith(">"):
            executed.append(line[1:].strip())
        elif FRAME.match(line) and " in " in line and index + 1 < len(lines):
            following = lines[index + 1]
            if following.startswith("    ") and following.strip():
                executed.append(following.strip())
    return executed


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
    traceback = str(failure_record.get("message") or "")
    if not traceback:
        traceback = "\n".join(e.message for e in events)
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

    frames = [m[0] for m in FRAME.findall(traceback)]
    source_file = str(exception_record.get("source_file") or "")
    last = source_file if source_file and exception_record.get("stage") != "collect" else ""
    if not last and frames:
        last = frames[-1]
    raised_in = classify_path(last, session.project_root, environment)
    kinds = [classify_path(f, session.project_root, environment) for f in frames]
    # The last frame in the user's own code is where they should look.
    root = session.project_root.replace("\\", "/").rstrip("/") + "/"
    where = ""
    for (path, line), kind in zip(FRAME.findall(traceback), kinds):
        if kind in ("project", "test"):
            shown = path.replace("\\", "/")
            where = f"{shown[len(root):] if shown.startswith(root) else shown}:{line}"

    evidence = {
        "issue_id": issue.issue_id,
        "exception": exception,
        "message": message[:2000],
        "stage": issue.stage,
        "raised_in": raised_in,
        "where": where,
        "third_party_frame_ratio": round(kinds.count("third_party") / len(kinds), 3) if kinds else 0.0,
        "missing_module": None,
        "modules": [],
        "apis": [],
        "attributes": [],
        "kwargs": [],
        "owners": [],
        "config_keys": [],
        "missing_files": [],
        "signals": [],
    }

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
        if owner != "NoneType":
            add("apis", f"{owner}.{name}")
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
        add("missing_files", path)

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


def features(evidence: dict, contexts: dict, project: dict) -> list[float]:
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
    values["module_local"] = bool(context.get("local"))
    values["module_similar_local"] = bool(context.get("similar"))
    values["module_declared"] = bool(context.get("declared") or top.get("declared"))
    values["missing_module_dotted"] = bool(evidence["missing_module"] and "." in module)
    values["api_mentioned"] = bool(evidence["apis"] or evidence["kwargs"])
    values["owner_defined_locally"] = any(o in defined for o in evidence["owners"])
    values.update({f"signal_{name}": name in evidence["signals"] for name in SIGNALS})
    return [float(values[name]) for name in FEATURE_NAMES]


def observed(subject, predicate, value, refs) -> Fact:
    return Fact(
        fact_id=f"{subject}:{predicate}:{value}",
        subject=subject,
        predicate=predicate,
        value=value,
        evidence_refs=sorted(set(refs)),
    )


def observations(session: Session, issues: list[Issue]) -> tuple[list[Fact], dict]:
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
        if i.tool in ("pytest", "pytest_run") and i.kind != "tool_failure" and i.stage != "verification"
    ]
    modules = set()
    for issue in diagnosable:
        evidence = issue_evidence(session, issue)
        refs = issue.evidence_refs
        subject = issue.issue_id
        if evidence["exception"]:
            facts.append(observed(subject, "exception", evidence["exception"], refs))
        facts.append(observed(subject, "raised_in", evidence["raised_in"], refs))
        for module in evidence["modules"]:
            facts.append(observed(subject, "module", "module:" + module, refs))
            modules.add(module)
        if evidence["missing_module"]:
            facts.append(
                observed(subject, "missing_module", "module:" + evidence["missing_module"], refs)
            )
            modules.add(evidence["missing_module"])
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
        details[subject] = evidence
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
    for index, row in enumerate(project.get("declarations", [])):
        if row.get("group") == "required" and not row.get("constraint"):
            facts.append(
                observed("dist:" + row["name"], "declared_in", row["source"],
                         [f"{project_run.run_id}:declaration:{index}"])
            )
    for issue in diagnosable:
        evidence = details[issue.issue_id]
        evidence["features"] = features(evidence, contexts, project)
    return facts, details


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
    return facts
