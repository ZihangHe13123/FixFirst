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


def parse(run: Run) -> list[Event]:
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
            run.coverage_complete = True
            run.verified_pass = run.exit_code == 0 and not events
            if not events and run.exit_code != 0:
                raise ValueError()
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
        return results or [
            event(run, text[:1000] or "Dependency check result unknown", stage="tool", kind="other_unknown")
        ]
    if run.tool == "pip_install":
        results = []
        for stream in ("stdout", "stderr"):
            for line, value in enumerate(getattr(run, stream).splitlines(), 1):
                if "ERROR" not in value and not re.search(
                    r"ResolutionImpossible|Could not find|Failed building", value
                ):
                    continue
                conflict = bool(
                    re.search(
                        r"ResolutionImpossible|conflicting dependencies|dependency conflict",
                        value,
                        re.I,
                    )
                )
                results.append(
                    event(
                        run,
                        value,
                        stage="install",
                        kind="dependency_conflict" if conflict else "install_failure",
                        line=line,
                        stream=stream,
                    )
                )
        # Installation input is historical evidence; an empty log does not prove installation.
        return results or [
            event(
                run,
                "No recognisable failure in the installation log; this does not prove installation succeeded",
                stage="install",
                kind="other_unknown",
            )
        ]
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
            result = []
            location = ""
            for stream in ("stdout", "stderr"):
                for line, value in enumerate(getattr(run, stream).splitlines(), 1):
                    context = re.search(
                        r"(?:ERROR collecting|ERROR|FAILED)\s+([^\s]+\.py[^\s]*)", value
                    )
                    if context:
                        location = context.group(1)
                    if IMPORT.search(value) or CONFIG.search(value) or EXCEPTION.search(value):
                        result.append(
                            exception_event(run, value, location, "unknown", line, stream)
                        )
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
