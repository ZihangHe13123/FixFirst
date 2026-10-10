"""Conservative per-tool parsers. Unknown nonzero results remain visible."""

import json
import re

from .models import Event, Run
from .test_results import summarize_tests

IMPORT = re.compile(r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]")
EXCEPTION = re.compile(r"\b([A-Za-z_]\w*(?:Error|Exception)):\s*(.*)")
CONFIG = re.compile(
    r"(?:Missing (?:required )?(?:configuration|environment variable|config)|"
    r"(?:configuration|environment variable) (?:missing|not set))[:\s]+['\"]?([A-Z][A-Z0-9_]+)",
    re.I,
)
STYLE_PREFIXES = ("E1", "E2", "E3", "E5", "W", "Q", "COM", "I", "D")
TRACEBACK_HEADER = "Traceback (most recent call last):"
CHAIN_SEPARATORS = {
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
}
TERMINAL_EXCEPTION = re.compile(r"^(?:E\s+)?((?:[A-Za-z_]\w*\.)*[A-Z]\w*):\s*(.*)$")
TRACEBACK_FRAME = re.compile(r'^\s*File "(.+)", line (\d+)(?:, in .*)?$|^(.+\.py):(\d+): in .*$')
ERROR_BLOCK = re.compile(
    r"^(?:_+\s+)?ERROR collecting (.+?)(?:\s+_+)?$"
    r"|^ImportError while loading conftest ['\"](.+)['\"]\.?$"
)
OUTPUT_SECTION = re.compile(r"^([_=\-])\1{2,}.*\1{3,}$")
NONFAILURE_SECTION = re.compile(r"warnings summary|captured (?:stdout|stderr|log)|short test summary info", re.I)


def event(
    run, message, *, stage, kind, component="", location="", line=1, code="", stream="stdout"
):
    return Event(
        run_id=run.run_id,
        tool=run.tool,
        stage=stage,
        kind=kind,
        message=message.strip(),
        component=component,
        location=location,
        line=line,
        code=code,
        evidence_refs=[f"{run.run_id}:{stream}:{line}"],
    )


def exception_event(run, text, location="", stage="collect", line=1, stream="stdout"):
    match = IMPORT.search(text)
    if match:
        return event(
            run,
            match.group(0),
            stage=stage,
            kind="import_failure",
            component=match.group(1),
            code="ModuleNotFoundError",
            location=location,
            line=line,
            stream=stream,
        )
    match = CONFIG.search(text)
    if match:
        return event(
            run,
            match.group(0),
            stage=stage,
            kind="explicit_config_missing",
            component=match.group(1),
            location=location,
            line=line,
            stream=stream,
        )
    matches = list(EXCEPTION.finditer(text))
    if matches:
        match = matches[-1]
        return event(
            run,
            match.group(0),
            stage=stage,
            kind=(
                "import_failure"
                if match.group(1) == "ImportError"
                else "test_assertion"
                if stage == "call" and match.group(1) == "AssertionError"
                else "test_runtime_error"
                if stage in ("call", "setup", "teardown")
                else "other_unknown"
            ),
            location=location,
            line=line,
            code=match.group(1),
            stream=stream,
        )
    return event(
        run,
        text[-2000:] or "Unknown test failure",
        stage=stage,
        kind="test_runtime_error" if stage in ("call", "setup", "teardown") else "other_unknown",
        location=location,
        line=line,
        stream=stream,
    )


def _terminal_failure(run, lines, location, stage, stream="stdout", offset=0):
    """Read a Warning, or the terminal exception of an explicit standard chain.

    The caller establishes that these lines belong to a failed block/probe record.
    Anchored headers avoid treating source code, a warning location or a wrapper's
    quoted exception name as the terminal exception.
    """
    terminal, source = None, ("", None)
    traceback_count = 0
    chained = False
    for index, value in enumerate(lines):
        if OUTPUT_SECTION.match(value) and NONFAILURE_SECTION.search(value):
            break
        if value == TRACEBACK_HEADER:
            traceback_count += 1
        if value in CHAIN_SEPARATORS:
            chained = True
        frame = TRACEBACK_FRAME.match(value)
        if frame:
            source = (frame.group(1) or frame.group(3), int(frame.group(2) or frame.group(4)))
        match = TERMINAL_EXCEPTION.match(value)
        if match:
            terminal = index, match, source
    if terminal is None:
        return None
    index, match, source = terminal
    code = match.group(1).rsplit(".", 1)[-1]
    if not code.endswith("Warning") and not (chained and traceback_count >= 2):
        return None
    line = offset + index + 1
    message = f"{match.group(1)}: {match.group(2)}"
    if code.endswith("Warning"):
        # Warning text may mention another error/configuration; its observed type wins.
        item = event(run, message, stage=stage, kind="test_runtime_error"
                     if stage in ("call", "setup", "teardown") else "other_unknown",
                     location=location, line=line, code=code, stream=stream)
    else:
        item = exception_event(run, message, location, stage, line, stream)
        item.code = code
    item.source_file, item.source_line = source
    return item


def _text_failure_blocks(lines):
    """Bound collection/conftest errors and standard tracebacks, excluding summaries."""
    start, location, terminal_seen, chain_pending = None, "", False, False
    allow_traceback = True
    for index, value in enumerate(lines):
        context = ERROR_BLOCK.match(value)
        traceback = value == TRACEBACK_HEADER
        if context or (traceback and allow_traceback and (start is None or (terminal_seen and not chain_pending))):
            if start is not None:
                yield start, index, location
            start, location = index, (context.group(1) or context.group(2)) if context else ""
            terminal_seen, chain_pending = False, False
            allow_traceback = True
        elif OUTPUT_SECTION.match(value):
            if start is not None:
                yield start, index, location
            start, location, terminal_seen, chain_pending = None, "", False, False
            allow_traceback = not NONFAILURE_SECTION.search(value)
        if start is not None:
            if value in CHAIN_SEPARATORS and terminal_seen:
                chain_pending = True
            elif traceback:
                chain_pending = False
            if TERMINAL_EXCEPTION.match(value):
                terminal_seen = True
    if start is not None:
        yield start, len(lines), location


def parse(run: Run) -> list[Event]:
    from .legacy_pytest import normalize_records

    normalize_records(run)
    run.verified_pass = False
    run.coverage_complete = False
    run.passed_nodes = []
    run.test_summary = {}
    if run.status != "completed" or run.truncated:
        return [
            event(
                run,
                f"Check did not complete: {run.status}. {run.stderr[:500]}",
                stage="tool",
                kind="tool_failure",
                stream="stderr",
            )
        ]
    text = run.stdout + "\n" + run.stderr
    if run.tool in ("python_run", "unittest_run"):
        from .execution_parsers import parse_execution

        return parse_execution(run)
    missing_tool = re.search(r"No module named ['\"]?(pytest|ruff|pip)\b", text)
    if missing_tool and run.tool != "pip_install":
        # A project's own import failure is not necessarily a missing runner.
        if not run.records and ("-m" in run.argv or run.source == "imported"):
            return [
                event(
                    run,
                    f"Could not start {missing_tool.group(1)} in the target environment: {text.strip()[:500]}",
                    stage="tool",
                    kind="tool_failure",
                    component=missing_tool.group(1),
                )
            ]
    if run.tool == "dependency_resolve":
        try:
            data = json.loads(run.stdout)
        except ValueError:
            data = {}
        # This has its own scope. Even a successful installation cannot close a
        # pytest/program issue or claim that the goal has been reached.
        run.verified_pass = run.exit_code == 0 and data.get("status") == "resolved"
        run.coverage_complete = run.verified_pass
        return []
    if run.tool == "version_search":
        try:
            data = json.loads(run.stdout)
        except ValueError:
            data = {}
        run.verified_pass = data.get("status") in ("found", "not_found", "partial")
        run.coverage_complete = run.verified_pass
        if run.verified_pass:
            return []
        reason = {
            "offline": "PyPI could not be reached",
            "no_candidates": "the queried metadata contains no eligible older wheel for this Python/platform; this does not prove that the release is absent",
            "source_build_required": "matching older source archives exist, but this search only installs wheels; source builds and their system prerequisites have not been tested",
            "python_requires": "the older release artifacts were excluded by their recorded Requires-Python metadata; building from source does not bypass that requirement",
            "constraints_exclude_candidates": "available older wheels are excluded by the project's or installed packages' requirements",
            "not_judged": "the search budget ended or some older releases could not be installed or imported here",
        }
        return [
            event(
                run,
                f"Release search for {data.get('dist', '?')} did not finish: "
                + reason.get(data.get("status"), "the output was not recognised"),
                stage="tool",
                kind="tool_failure",
                component="version_search",
            )
        ]
    if run.tool == "environment":
        try:
            payload = json.loads(run.stdout)
            valid = isinstance(payload, dict) and isinstance(payload.get("packages"), list)
            run.verified_pass = run.exit_code == 0 and valid
            run.coverage_complete = run.verified_pass
        except ValueError:
            pass
        return (
            []
            if run.verified_pass
            else [event(run, "The environment snapshot could not be taken", stage="tool", kind="tool_failure")]
        )
    if run.tool == "project":
        try:
            payload = json.loads(run.stdout)
            rows = payload["declarations"] + payload["requires_python"]
            results = []
            for index, row in enumerate(rows):
                state = row["status"]
                if state not in ("missing", "version_mismatch", "python_mismatch"):
                    continue
                requirement = row.get("requirement", "Python " + row.get("specifier", ""))
                item = event(
                    run,
                    f"{row['source']} declares {requirement}; installed: {row['installed']}. "
                    + {
                        "missing": "Required dependency missing",
                        "version_mismatch": "Installed version does not satisfy the declaration",
                        "python_mismatch": "Python version does not satisfy the declaration",
                    }[state],
                    stage="dependency",
                    kind="environment_mismatch"
                    if state == "python_mismatch"
                    else "dependency_conflict",
                    component=row.get("name", "python"),
                    location=row["source"],
                    code=state,
                )
                item.evidence_refs = [f"{run.run_id}:declaration:{index}"]
                results.append(item)
            run.coverage_complete = bool(
                payload.get("environment_run_id")
                and payload.get("files")
                and not payload.get("notes")
                and all(
                    r["status"]
                    in (
                        "satisfied",
                        "missing",
                        "version_mismatch",
                        "python_mismatch",
                        "inactive_marker",
                        "optional",
                    )
                    for r in rows
                )
            )
            run.verified_pass = run.coverage_complete and not results and run.exit_code == 0
            run.notes.extend(payload.get("notes", []))
            return results
        except (ValueError, KeyError, TypeError):
            return [event(run, "The project declaration snapshot could not be parsed", stage="tool", kind="tool_failure")]
    if run.tool == "ruff":
        try:
            rows = json.loads(run.stdout)
            if not isinstance(rows, list) or run.exit_code not in (0, 1):
                raise ValueError()
            events = []
            for index, row in enumerate(rows):
                if not isinstance(row, dict) or not all(
                    k in row for k in ("message", "location", "filename")
                ):
                    raise ValueError()
                code = row.get("code") or "invalid-syntax"
                kind = "style_issue" if code.startswith(STYLE_PREFIXES) else "code_check"
                events.append(
                    event(
                        run,
                        row["message"],
                        stage="lint",
                        kind=kind,
                        component=code,
                        code=code,
                        location=row["filename"],
                        line=row["location"].get("row", 1),
                    )
                )
                events[-1].evidence_refs = [f"{run.run_id}:json:{index}"]
            if not events and run.exit_code != 0:
                raise ValueError()
            run.coverage_complete = True
            run.verified_pass = run.exit_code == 0 and not events
            return events
        except (ValueError, KeyError, TypeError, AttributeError):
            return [
                event(
                    run,
                    "Ruff output was not recognised or the tool failed: " + text[:1000],
                    stage="tool",
                    kind="tool_failure",
                )
            ]
    if run.tool == "pip_check":
        run.verified_pass = run.exit_code == 0 and "No broken requirements found" in text
        run.coverage_complete = run.verified_pass
        if run.verified_pass:
            return []
        results = []
        for stream in ("stdout", "stderr"):
            for line, value in enumerate(getattr(run, stream).splitlines(), 1):
                if re.search(
                    r"has requirement .+but you have|requires .+(?:not installed|not compatible)",
                    value,
                ):
                    component = value.split()[0]
                    results.append(
                        event(
                            run,
                            value,
                            stage="dependency",
                            kind="dependency_conflict",
                            component=component,
                            line=line,
                            stream=stream,
                        )
                    )
        # pip lists every broken requirement it finds. When each line was understood, the run
        # is a complete account: a conflict it no longer reports is gone.
        listed = [line for line in run.stdout.splitlines() if line.strip()]
        understood = [r for r in results if r.evidence_refs[0].split(":")[1] == "stdout"]
        run.coverage_complete = bool(
            results and run.exit_code == 1 and len(understood) == len(listed)
        )
        return results or [
            event(run, text[:1000] or "Dependency check result unknown", stage="tool", kind="other_unknown")
        ]
    if run.tool == "pip_install":
        from .install_errors import parse_install

        return parse_install(run, event)
    if run.tool in ("pytest", "pytest_run"):
        failures = [r for r in run.records if r.get("type") == "failure"]
        finishes = [r for r in run.records if r.get("type") == "finish"]
        if run.records:
            result = []
            for index, record in enumerate(run.records):
                if record.get("type") == "failure":
                    item = exception_event(
                        run,
                        str(record.get("message", "")),
                        str(record.get("nodeid", "")),
                        str(record.get("stage", "unknown")),
                    )
                    item.evidence_refs = [f"{run.run_id}:probe:{index}"]
                    exception = next(
                        (
                            r
                            for r in run.records
                            if r.get("type") == "exception"
                            and r.get("nodeid") == record.get("nodeid")
                            and r.get("stage") == record.get("stage")
                        ),
                        {},
                    )
                    if run.exit_code not in (None, 0) and (
                        "exception_message" not in exception
                        or (item.stage == "collect" and exception.get("exception_type") == "CollectError")
                    ):
                        terminal = _terminal_failure(
                            run, str(record.get("message", "")).splitlines(), item.location, item.stage,
                        )
                        if terminal:
                            item = terminal
                            item.evidence_refs = [f"{run.run_id}:probe:{index}"]
                    if "exception_message" in exception and not (
                        item.stage == "collect" and exception.get("exception_type") == "CollectError"
                    ):
                        exception_type = str(exception.get("exception_type", "Exception"))
                        message = str(exception["exception_message"])
                        # The emitted type is the actual unhandled exception. Message contents
                        # can mention other errors without having those errors as their type.
                        item.message = f"{exception_type}: {message}"
                        item.code = exception_type
                        item.component = ""
                        item.source_file = str(exception.get("source_file", ""))
                        item.source_line = exception.get("source_line")
                        item.kind = (
                            "test_runtime_error"
                            if item.stage in ("call", "setup", "teardown")
                            else "other_unknown"
                        )
                        if exception_type in ("ModuleNotFoundError", "ImportError"):
                            item.kind = "import_failure"
                            match = IMPORT.search(item.message)
                            item.component = match.group(1) if match else ""
                        elif exception_type != "AssertionError" and CONFIG.search(message):
                            item.kind = "explicit_config_missing"
                            item.component = CONFIG.search(message).group(1)
                        exception_index = run.records.index(exception)
                        item.evidence_refs.append(f"{run.run_id}:probe:{exception_index}")
                    if exception.get("exception_type") == "AssertionError" and item.stage == "call":
                        item.kind, item.code = "test_assertion", "AssertionError"
                    result.append(item)
            run.verified_pass = bool(
                finishes
                and finishes[-1].get("collected", 0) > 0
                and run.exit_code == 0
                and not failures
                and finishes[-1].get("exit_code") == 0
                and not finishes[-1].get("records_dropped", False)
            )
            run.coverage_complete = run.verified_pass
            if run.tool == "pytest_run":
                run.verified_pass = False
                run.coverage_complete = False
                summarize_tests(run)
            if result:
                return result
            if run.verified_pass:
                return []
            if run.tool == "pytest_run" and run.coverage_complete and run.exit_code == 0:
                return [
                    event(
                        run,
                        "No test actually passed; skipping everything or marking it as expected to fail is not a fix",
                        stage="verification",
                        kind="other_unknown",
                    )
                ]
        else:
            # Text imports retain context but cannot prove collection coverage.
            # An executed run without probe records never reached collection (for example a
            # conftest that fails to import), so whatever failed blocks every test.
            stage = (
                "collect"
                if run.source == "executed"
                or re.search(r"while loading conftest|ERROR collecting|while importing test module", text)
                else "unknown"
            )
            result = []
            location = ""
            for stream in ("stdout", "stderr"):
                lines = getattr(run, stream).splitlines()
                terminal_events, consumed = {}, set()
                if run.exit_code not in (None, 0):
                    for start, end, block_location in _text_failure_blocks(lines):
                        item = _terminal_failure(run, lines[start:end], block_location, stage, stream, start)
                        if item:
                            terminal_events[item.line] = item
                            consumed.update(range(start + 1, end + 1))
                for line, value in enumerate(lines, 1):
                    context = re.search(
                        r"(?:ERROR collecting|ERROR|FAILED)\s+([^\s]+\.py[^\s]*)"
                        r"|while loading conftest '([^']+)'",
                        value,
                    )
                    if context:
                        location = context.group(1) or context.group(2)
                    if line in terminal_events:
                        result.append(terminal_events[line])
                        continue
                    if line in consumed:
                        continue
                    if IMPORT.search(value) or CONFIG.search(value) or EXCEPTION.search(value):
                        result.append(exception_event(run, value, location, stage, line, stream))
            if result:
                return result
        descriptions = {
            2: "Collection error or interruption",
            3: "pytest internal error",
            4: "pytest usage error",
            5: "No tests were collected",
        }
        message = descriptions.get(
            run.exit_code, "No verifiable completion record; tests may all have been skipped or not run"
        )
        return [event(run, message + "; see the original output", stage="tool", kind="tool_failure")]
    raise ValueError("Unsupported source")
