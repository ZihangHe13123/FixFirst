"""Interpret observed native executions; empty or partial tests never prove a fix."""

import re

from .models import Run

FRAME = re.compile(r'^\s*File "([^"]+)", line (\d+)(?:, in .*)?$', re.M)
EXCEPTION = re.compile(r"^([A-Za-z_][\w.]*)(?::\s*(.*))?$", re.M)


def native_failure(run):
    text = run.stderr or run.stdout
    frames = list(FRAME.finditer(text))
    tail = text[frames[-1].end():] if frames else text
    # The first unindented line after the final frame is the exception header.
    # Its message can contain bare field names or even lines resembling another
    # exception; choosing the last match turns Pydantic's "code" field into a type.
    match = EXCEPTION.search(tail) if frames else None
    if match:
        module, _, name = match[1].rpartition(".")
        message = ((match[2] or "") + tail[match.end():]).strip()[:4000]
        frame = frames[-1]
        run.records.extend([
            {"type": "failure", "stage": "run", "nodeid": "", "message": text,
             "record_source": "native_traceback"},
            {"type": "exception", "stage": "run", "nodeid": "",
             "exception_type": name, "exception_module": module, "exception_message": message,
             "source_file": frame[1], "source_line": int(frame[2]),
             "record_source": "native_traceback"},
        ])


def parse_execution(run: Run):
    from .parsers import event, exception_event

    errors = [r for r in run.records if r.get("type") == "execution_tool_error"]
    if errors:
        return [event(run, r["message"], stage="tool", kind="tool_failure",
                      component=r.get("component", "")) for r in errors]
    if run.tool == "unittest_run":
        summarize_unittest(run)
    elif any(r.get("type") == "notebook_finish" for r in run.records):
        finishes = [r for r in run.records if r.get("type") == "notebook_finish"]
        cells = [r for r in run.records if r.get("type") == "cell_outcome"]
        finish = finishes[0]
        run.coverage_complete = bool(
            len(finishes) == 1 and finish.get("expected", 0) > 0
            and finish.get("expected") == finish.get("executed") == len(cells)
            and len({r.get("cell") for r in cells}) == len(cells)
            and all(r.get("status") == "ok" for r in cells)
            and not finish.get("records_dropped", True)
            and finish.get("exit_code") == run.exit_code == 0 and run.source == "executed"
        )
        run.verified_pass = run.coverage_complete
    elif not run.records and run.exit_code == 0 and run.source == "executed":
        # Scripts/modules run as ordinary Python commands; notebook and unittest require records.
        if run.execution_kind in ("script", "module"):
            run.verified_pass = run.coverage_complete = True
    if run.verified_pass:
        return []
    failures = [r for r in run.records if r.get("type") == "failure"]
    if not failures:
        native_failure(run)
        failures = [r for r in run.records if r.get("type") == "failure"]
    result = []
    for failure in failures:
        exception = next((r for r in run.records if r.get("type") == "exception"
                          and r.get("nodeid") == failure.get("nodeid")
                          and r.get("stage") == failure.get("stage")), {})
        name = exception.get("exception_type", "")
        text = f"{name}: {exception.get('exception_message', '')}" if name else failure.get("message", "")
        stage = failure.get("stage", "run")
        item = exception_event(run, text, failure.get("nodeid", ""), stage)
        item.code = name or item.code
        item.source_file = exception.get("source_file", "")
        item.source_line = exception.get("source_line")
        if item.kind not in ("import_failure", "explicit_config_missing"):
            item.kind = "test_assertion" if run.tool == "unittest_run" and name == "AssertionError" else "runtime_error"
        item.evidence_refs = [f"{run.run_id}:probe:{run.records.index(failure)}"]
        if exception:
            item.evidence_refs.append(f"{run.run_id}:probe:{run.records.index(exception)}")
        result.append(item)
    if result:
        return result
    if run.tool == "unittest_run":
        message = ("No tests were discovered. Choose the test directory and pattern, or run a program."
                   if not run.test_summary.get("selected")
                   else "No verifiable passing test run; skipped, expected failures or incomplete tests do not confirm a fix.")
        return [event(run, message, stage="verification", kind="tool_failure")]
    if run.exit_code == 0:
        return [event(run, "No complete execution record; an empty notebook or an imported log does not confirm a run.",
                      stage="verification", kind="tool_failure")]
    missing = re.search(r"No module named\s+['\"]?([\w.]+)", run.stderr)
    if missing:
        return [exception_event(run, f"ModuleNotFoundError: No module named '{missing[1]}'",
                                stage="run", stream="stderr")]
    return [event(run, f"Program exited with code {run.exit_code}. "
                  "Read the original output and the condition that selects this exit code.",
                  stage="run", kind="runtime_exit", stream="stderr" if run.stderr else "stdout")]


def summarize_unittest(run):
    finishes = [r for r in run.records if r.get("type") == "unit_finish"]
    outcomes = [r for r in run.records if r.get("type") == "unit_outcome"]
    selected = finishes[0].get("nodes", []) if len(finishes) == 1 else []
    results = {r.get("nodeid"): r.get("outcome") for r in outcomes}
    run.test_summary = {
        "selected": len(selected), "passed": sum(v == "passed" for v in results.values()),
        "failed": sum(v in ("failed", "xpass") for v in results.values()),
        "skipped": sum(v == "skipped" for v in results.values()),
        "xfail_or_xpass": sum(v in ("xfail", "xpass") for v in results.values()),
    }
    run.coverage_complete = bool(
        len(finishes) == 1 and selected and len(set(selected)) == len(selected) == len(outcomes)
        and set(selected) == set(results) and finishes[0].get("ran") == len(selected)
        and not finishes[0].get("records_dropped", True)
        and finishes[0].get("exit_code") == run.exit_code and run.exit_code in (0, 1)
        and all(v in ("passed", "failed", "skipped", "xfail", "xpass") for v in results.values())
        and run.source == "executed"
    )
    run.passed_nodes = sorted(k for k, v in results.items() if v == "passed") if run.coverage_complete else []
    run.verified_pass = bool(run.coverage_complete and run.exit_code == 0
                             and run.passed_nodes and not run.test_summary["failed"])
