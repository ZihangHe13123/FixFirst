"""Connect manual pip operations to later scans without executing those operations."""

from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import zipfile

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from .models import Run
from .runner import environment_id, redact

MAX_LOG = 1_000_000
MAX_LOG_READ = 16_000_000
MAX_WHEEL = 25_000_000


def directory(session):
    return (Path(session.project_root) / ".fixfirst" / "installation"
            / session.session_id / environment_id(session.target_python))


def declarations_key(project, *, edits=(), semantic=False):
    rows = [{k: r.get(k) for k in ("requirement", "source", "group", "constraint", "installer")}
            for r in project.get("declarations", [])]
    for row in rows:
        for edit in edits:
            if row["source"] == edit["source"] and row["requirement"] == edit["before"]:
                row["requirement"] = edit["after"]
    files = [r["path"] for r in project.get("files", [])] if semantic else project.get("files", [])
    value = {"requirements": rows, "files": files, "notes": project.get("notes", []),
             "requires_python": [{k: r.get(k) for k in ("source", "specifier")}
                                 for r in project.get("requires_python", [])]}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_regular(path, limit, *, tail=False):
    """Never wait on a FIFO or follow a supplied symlink, including its parents."""
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Installation feedback path contains a symbolic link")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Installation feedback must be a regular file")
        if info.st_size > limit:
            if not tail:
                raise ValueError("Installation artifact exceeds the size limit")
            stream.seek(-limit, os.SEEK_END)
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Installation artifact changed while reading")
        return data, info.st_size > limit


def prepared_wheels(session, *, contents=False):
    """Only use valid wheels explicitly requested by this session's manual build steps."""
    identity = environment_id(session.target_python)
    requests = []
    for attempt in session.installation_attempts:
        if (attempt.get("environment_id") == identity and attempt.get("operation") == "wheel"
                and attempt.get("python_version") == session.environment.get("python_version")):
            for text in attempt.get("requests", []):
                try:
                    req = Requirement(text)
                    if not req.url:
                        requests.append(req)
                except InvalidRequirement:
                    pass
    folder = directory(session) / "wheels"
    manifest, files = [], {}
    empty = ([], {}) if contents else []
    if not requests or not folder.is_dir() or any(p.is_symlink() for p in (folder, *folder.parents)):
        return (manifest, files) if contents else manifest
    total = 0
    paths = sorted(folder.glob("*.whl"))
    if len(paths) > 100:
        return empty
    for path in paths:
        try:
            name, version, _, _ = parse_wheel_filename(path.name)
            from .versions import wheel_fits
            if not wheel_fits(path.name, Version(session.environment.get("python_version", "")),
                              session.environment.get("markers", {})):
                return empty
            if not any(canonicalize_name(r.name) == name and version in r.specifier for r in requests):
                return empty
            raw, _ = read_regular(path, MAX_WHEEL)
            total += len(raw)
            if total > 100_000_000:
                return empty
            with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
                metadata = [i for i in wheel.infolist() if i.filename.endswith(".dist-info/METADATA")]
                if len(metadata) != 1 or metadata[0].file_size > 256_000:
                    return empty
                package = BytesParser().parsebytes(wheel.read(metadata[0]))
                if canonicalize_name(package.get("Name", "")) != name or Version(package["Version"]) != version:
                    return empty
            manifest.append({"filename": path.name, "name": name, "version": str(version),
                             "sha256": hashlib.sha256(raw).hexdigest()})
            if contents:
                files[path.name] = raw
        except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile):
            return empty
    return (manifest, files) if contents else manifest


def has_prepared_wheel(session, requirement):
    try:
        req = Requirement(requirement)
        return any(w["name"] == canonicalize_name(req.name) and Version(w["version"]) in req.specifier
                   for w in prepared_wheels(session))
    except InvalidRequirement:
        return False


def build_command(session, requirement):
    req = Requirement(requirement)
    if req.url:
        raise ValueError("A manual wheel build needs a named package requirement")
    return [session.target_python, "-m", "pip", "wheel", "--no-deps",
            "--wheel-dir", str(directory(session) / "wheels"), str(req)]


def offer_build(session, action, requirement, reason):
    """Offer an explicit manual operation once, preserving failed build evidence."""
    try:
        req = Requirement(requirement)
    except InvalidRequirement:
        return False
    if req.url or has_prepared_wheel(session, requirement):
        return False
    from .evidence import project_index
    if any("hash" in n.lower() for n in project_index(session)[1].get("notes", [])):
        return False
    for run in reversed(session.runs):
        if (run.environment_id == environment_id(session.target_python)
                and run.argv[:4] == [session.target_python, "-m", "pip", "wheel"]
                and run.argv[-1] == str(req)
                and any(e.run_id == run.run_id and e.kind != "other_unknown" for e in session.events)):
            return False
    action.kind, action.check, action.targets = "manual_fix", None, []
    action.title = f"Prepare a wheel for {req} before retrying the dependency set"
    action.explanation = (
        reason + f" Run the following pip wheel command for {req}. It downloads or builds just this "
        "declared package into this session's wheel directory, without installing it into the project. "
        "Building from source executes the package's build scripts; this is a manual operation, not "
        "something Check again runs for you. Build dependencies may be downloaded into a temporary "
        "build environment. After it finishes, Check again reads the log and any valid wheel. "
        "If building fails, the next step must address that output; do not repeat the same build. "
        "A built wheel does not mean the project has been repaired.")
    action.command = build_command(session, str(req))
    return True


def bind_commands(session, actions, project):
    """Attach a distinct log to each proposed command; do not create or run anything."""
    identity, declarations = environment_id(session.target_python), declarations_key(project)
    wheels = prepared_wheels(session)
    for action in actions:
        command = action.command
        if (command[:3] != [session.target_python, "-m", "pip"] or len(command) < 5
                or command[3] not in ("install", "wheel") or "--log" in command):
            continue
        operation = command[3]
        if wheels and operation == "install":
            command[4:4] = ["--find-links", str(directory(session) / "wheels")]
        command[4:4] = ["--disable-pip-version-check"]
        python_version = session.environment.get("python_version")
        key = hashlib.sha256(json.dumps([command, declarations, python_version], sort_keys=True).encode()).hexdigest()[:24]
        record = next((r for r in session.installation_attempts if r.get("key") == key), None)
        if record is None:
            record = {"key": key, "environment_id": identity, "declarations": declarations,
                      "python_version": python_version,
                      "operation": operation, "command": command[:], "action_id": action.action_id,
                      "requests": [command[-1]] if operation == "wheel" else [], "digest": ""}
            session.installation_attempts.append(record)
        if action.declaration_edits:
            record["declarations_after"] = declarations_key(project, edits=action.declaration_edits, semantic=True)
        log = directory(session) / (key + ".log")
        command[4:4] = ["--log", str(log)]
        action.explanation += (
            " This manual command saves pip output for this session. After it finishes, use Check again "
            "(CLI: fixfirst scan " + session.session_id + "); FixFirst reads that log and updates the next "
            "step. The log alone never proves that the program or tests passed.")
        if record.get("read_error"):
            action.explanation += " Saved output was not used: " + record["read_error"] + "."


def collect_feedback(session, project):
    """Imported observations only: unknown exit code and no verification credit."""
    identity, declarations = environment_id(session.target_python), declarations_key(project)
    observed = []
    for record in session.installation_attempts[-100:]:
        compatible = record.get("declarations") == declarations or (
            record.get("declarations_after") == declarations_key(project, semantic=True))
        if (record.get("environment_id") != identity or not compatible
                or record.get("python_version") != session.environment.get("python_version")
                or not re.fullmatch(r"[a-f0-9]{24}", record.get("key", ""))):
            continue
        path = directory(session) / (record["key"] + ".log")
        try:
            raw, clipped = read_regular(path, MAX_LOG_READ, tail=True)
        except FileNotFoundError:
            continue
        except (ValueError, OSError) as error:
            record["read_error"] = str(error)
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if record.get("digest") == digest:
            continue
        record["digest"] = digest
        record.pop("read_error", None)
        text = raw.decode("utf-8-sig", errors="replace")
        # pip --log appends. A later successful invocation must not inherit an
        # earlier error from the same file. A bounded tail is kept as partial input.
        starts = list(re.finditer(r"(?m)^.*?Using pip \d[^\n]*$", text))
        if starts:
            text = text[starts[-1].start():]
        header = re.search(r"Using pip \S+ from (.+?) \(python [^)]+\)", text)
        prefix = session.environment.get("prefix")
        if header and prefix and not Path(header[1]).resolve().is_relative_to(Path(prefix).resolve()):
            record["read_error"] = "This pip log names a different interpreter environment"
            continue
        if len(text.encode()) > MAX_LOG:
            # Verbose index listings can put the pinned sdist link far before
            # the final error. Keep matching archive lines, never infer sdist
            # availability from the generic 'from versions: none' message.
            from .install_errors import source_archive
            tail = text.encode()[-(MAX_LOG - 12_000):].decode("utf-8", errors="replace")
            wanted = []
            for value in re.findall(r"No matching distribution found for ([^\s]+)", tail):
                try:
                    wanted.append(Requirement(value))
                except InvalidRequirement:
                    pass
            matching = []
            for line in text.splitlines():
                archive = source_archive(line)
                if archive and any(archive[0] == canonicalize_name(r.name) and archive[1] in r.specifier for r in wanted):
                    matching.append(line[:2000])
                    if len(matching) == 5:
                        break
            text = "\n".join(matching) + "\n" + tail
            clipped = True
        run = Run(tool="pip_install", source="imported", exit_code=None,
                  environment_id=identity, scope="manual-install:" + record["key"],
                  cwd=session.project_root, argv=record["command"], stdout=redact(text),
                  records=[{"type": "installation_context", "declarations": declarations,
                            "environment_id": identity, "python_version": session.environment.get("python_version")}])
        run.notes.append("Output from a suggested manual pip command; its execution and exit code are unverified.")
        if clipped:
            run.notes.append("At most 16 MB of pip output was read; the last 1 MB and matching source-link excerpts are retained. Earlier context may be missing.")
        observed.append(run)
    return observed
