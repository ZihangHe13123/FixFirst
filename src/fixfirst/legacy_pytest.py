"""Canonical addresses for the standard class Instance node in pytest 3.x."""

from packaging.version import InvalidVersion, Version

from .test_selection import canonical_nodeid


def legacy_names(run):
    if run.tool not in ("pytest", "pytest_run") or run.source != "executed":
        return False
    try:
        return Version(run.tool_version).major == 3
    except (InvalidVersion, TypeError):
        return False


def normalize_records(run):
    if not legacy_names(run):
        return
    for row in run.records:
        node = row.get("nodeid")
        normalized = canonical_nodeid(node)
        if normalized != node:
            row.setdefault("original_nodeid", node)
            row["nodeid"] = normalized
        if row.get("type") == "finish" and isinstance(row.get("nodes"), list):
            nodes = row["nodes"]
            normalized = [canonical_nodeid(node) for node in nodes]
            if normalized != nodes:
                row.setdefault("original_nodes", nodes)
                row["nodes"] = normalized
                if len(set(normalized)) != len(set(nodes)):
                    row["records_dropped"] = True
                    run.notes.append("Legacy test addresses overlap; this run cannot verify the original tests.")


def normalize_history(session):
    legacy = {run.run_id: run for run in session.runs if legacy_names(run)}
    for run in legacy.values():
        normalize_records(run)
        run.passed_nodes = [canonical_nodeid(node) for node in run.passed_nodes]
    for event in session.events:
        if event.run_id in legacy:
            event.location = canonical_nodeid(event.location)
    events = {event.event_id: event for event in session.events}
    for issue in session.issues:
        if issue.tool in ("pytest", "pytest_run") and any(
                events.get(key) and events[key].run_id in legacy for key in issue.event_ids):
            issue.targets = [canonical_nodeid(node) for node in issue.targets]
