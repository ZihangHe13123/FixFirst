"""Earn test coverage from per-node protocol evidence, never missing failure text."""

from .models import Run


def summarize_tests(run: Run):
    finish = [r for r in run.records if r.get("type") == "finish"]
    phases = {}
    valid = True
    for record in run.records:
        if record.get("type") != "outcome":
            continue
        node, stage, outcome = (record.get(k) for k in ("nodeid", "stage", "outcome"))
        if (
            not isinstance(node, str)
            or stage not in ("setup", "call", "teardown")
            or outcome not in ("passed", "failed", "skipped")
        ):
            valid = False
            continue
        previous = phases.setdefault(node, {})
        if stage in previous:
            valid = False
        previous[stage] = record
    complete, passed, failed, skipped, xfailed = set(), set(), set(), set(), set()
    for node, values in phases.items():
        if (
            "setup" in values
            and "teardown" in values
            and ("call" in values or values["setup"]["outcome"] != "passed")
        ):
            complete.add(node)
        if any(v["outcome"] == "failed" for v in values.values()):
            failed.add(node)
        elif any(v.get("wasxfail") for v in values.values()):
            xfailed.add(node)
        elif any(v["outcome"] == "skipped" for v in values.values()):
            skipped.add(node)
        elif set(values) == {"setup", "call", "teardown"} and all(
            v["outcome"] == "passed" for v in values.values()
        ):
            passed.add(node)
    run.test_summary = {
        "passed": len(passed),
        "failed": len(failed),
        "skipped": len(skipped),
        "xfail_or_xpass": len(xfailed),
    }
    if len(finish) != 1:
        return
    final = finish[0]
    nodes = final.get("nodes")
    if not isinstance(nodes, list) or not all(isinstance(n, str) for n in nodes):
        return
    selected = set(nodes)
    run.test_summary["selected"] = len(selected)
    run.test_summary["incomplete"] = len(selected - complete)
    coverage = bool(
        valid
        and selected
        and len(selected) == len(nodes) == final.get("collected")
        and final.get("collect_only") is False
        and not final.get("records_dropped", True)
        and final.get("exit_code") == run.exit_code
        and run.exit_code in (0, 1)
        and complete == selected
        and set(phases) == selected
        and (not run.targets or set(run.targets) == selected)
        and not any(r.get("type") == "failure" and r.get("stage") == "collect" for r in run.records)
    )
    run.coverage_complete = coverage
    # A different failing node does not erase a fully passed node's verification.
    run.passed_nodes = sorted(passed) if coverage else []
    run.verified_pass = coverage and run.exit_code == 0 and bool(passed) and not failed
    if skipped or xfailed:
        run.notes.append("Skipped, xfail and non-strict xpass results do not prove that an earlier failure is fixed.")
