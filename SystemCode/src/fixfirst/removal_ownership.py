"""Issue-scoped permission to apply removal knowledge to an actual receiver.

Legacy names remain available as observations/features. Only these extra facts
authorize D02/D03; another issue's similarly named object cannot supply them.
"""

import json
import posixpath

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from . import domain


def _incomplete_receiver(row):
    """An explicit failed observation, rather than ordinary absent metadata."""
    from .symbol_context import valid_record

    if row.get("exception_type") != "AttributeError":
        return False
    record = row.get("symbol_observation")
    if not record:
        # The target probe reached the actual attribute opcode and receiver,
        # but its static namespace exceeded a bound or could not be inspected.
        return row.get("symbol_observation_status") == "unsupported_receiver"
    if not isinstance(record, dict) or record.get("kind") not in ("instance", "class"):
        return False
    owners = record.get("receiver_owners")
    if not isinstance(owners, list):
        return False
    # A retained oversized record must not gain a model diagnosis just because
    # the reader discarded its ancestry. Validate the rest of the observation
    # separately; malformed unrelated fields are not evidence of this limit.
    if not valid_record({**record, "receiver_owners": []}):
        return False
    try:
        return len(owners) > 128 or len(json.dumps(owners, ensure_ascii=True, separators=(",", ":"))) > 32768
    except (TypeError, ValueError):
        return False


def classifier_abstention(session, issue, evidence):
    """Withhold a learned cause when a member's receiver observation is bounded.

    Keep the raw model output for audits. Only this issue's executed, same-run
    event references count; other failures and missing legacy fields cannot
    donate an abstention. A grouped valid member cannot erase a bounded member.
    Confirmed rule diagnoses are selected independently by the caller.
    """
    if evidence.get("exception") != "AttributeError":
        return ""
    runs = {run.run_id: run for run in session.runs}
    for event in session.events:
        if (event.event_id not in issue.event_ids or event.tool != issue.tool
                or event.code != "AttributeError"):
            continue
        for ref in event.evidence_refs:
            run_id, separator, position = ref.partition(":probe:")
            run = runs.get(run_id)
            if (not separator or not position.isdigit() or run is None
                    or run_id != event.run_id or run.tool != issue.tool
                    or run.source != "executed" or run.environment_id != issue.environment_id
                    or run.status != "completed" or run.exit_code in (None, 0) or run.truncated
                    or int(position) >= len(run.records)):
                continue
            row = run.records[int(position)]
            if (row.get("type") != "exception" or row.get("stage") != event.stage
                    or not event.location or row.get("nodeid") != event.location
                    or not _incomplete_receiver(row)):
                continue
            return (
                "The failed attribute receiver could not be inspected within the supported bounds. "
                "Its library ancestry remains unconfirmed. The classifier prediction is retained "
                "separately and is not used to choose a cause or repair."
            )
    return ""


def _within(path, directory):
    path, directory = (posixpath.normpath(value.replace("\\", "/")) for value in (path, directory))
    if len(path) > 1 and path[1] == ":":
        path, directory = path.casefold(), directory.casefold()
    return bool(directory and directory != "." and path.startswith(directory.rstrip("/") + "/"))


def _provider(owner, distribution, project, environment):
    """The recorded loaded module must belong to the selected environment."""
    top = owner["module"].split(".")[0]
    if top in {row["name"].split(".")[0] for row in project.get("local_modules", [])}:
        return False
    if distribution in {canonicalize_name(name) for name in project.get("own_names", [])}:
        return False
    providers = {canonicalize_name(name) for name in environment.get("import_distributions", {}).get(top, [])}
    paths, origin = environment.get("paths", {}), owner["file"]
    library = any(_within(origin, paths.get(key, "")) for key in ("purelib", "platlib"))
    if distribution == "python":
        return (not providers and top in environment.get("stdlib_modules", []) and not library
                and (top == "builtins" and not origin
                     or any(_within(origin, paths.get(key, "")) for key in ("stdlib", "platstdlib"))))
    return providers == {distribution} and library


def _owners(entry, name):
    """Explicit owner metadata, or an already qualified identity in the entry."""
    owners = entry.get("owners", [])
    if not owners:
        qualified = entry.get("module", "") if entry["kind"] == "api" else name.rpartition(".")[0]
        owners = [qualified]
    return {owner for owner in owners if isinstance(owner, str) and "." in owner
            and all(part.isidentifier() for part in owner.split("."))}


def _one_failure(session, issue, item):
    """Do not let an unobserved/grouped event borrow the one selected exception."""
    ref = item.get("symbol_record_ref", "")
    run_id, _, index = ref.partition(":probe:")
    run = next((run for run in session.runs if run.run_id == run_id), None)
    if (run is None or not index.isdigit() or int(index) >= len(run.records)
            or run.status != "completed" or run.exit_code in (None, 0) or run.truncated):
        return False
    exception = run.records[int(index)]
    events = [event for event in session.events if event.event_id in issue.event_ids]
    if len(events) != len(set(issue.event_ids)):
        return False
    for event in events:
        if event.run_id != run_id:
            return False
        matched = False
        for evidence_ref in event.evidence_refs:
            owner_run, separator, position = evidence_ref.partition(":probe:")
            if not separator:
                continue
            if owner_run != run_id or not position.isdigit() or int(position) >= len(run.records):
                return False
            row = run.records[int(position)]
            if (row.get("type") in ("exception", "failure")
                    and row.get("nodeid") == exception.get("nodeid")
                    and row.get("stage") == exception.get("stage")):
                matched = True
            else:
                return False
        if not matched:
            return False
    return bool(events)


def _current_snapshots(session, item, project, environment):
    positions = {run.run_id: index for index, run in enumerate(session.runs)}
    failure = positions.get(item.get("symbol_record_ref", "").partition(":probe:")[0], -1)
    for snapshot, tool in ((project, "project"), (environment, "environment")):
        position = positions.get(snapshot.get("_run_id"), -1)
        # Default scans index the project after the failure. Its existing
        # environment_run_id linkage still establishes the provider snapshot;
        # the executed source statement comes only from the failure's own run.
        if position < 0 or failure < 0 or (tool == "environment" and position >= failure):
            return False
        run = session.runs[position]
        if (run.tool != tool or run.source != "executed" or run.status != "completed"
                or run.exit_code != 0 or run.truncated
                or (tool == "environment" and not run.verified_pass)
                or run.environment_id != environment.get("_environment_id")):
            return False
    return True


def evidence_facts(session, issue, evidence, project, environment):
    from .evidence import CANNOT_IMPORT, MODULE_ATTR, NUMPY_REMOVED, observed

    result, entries = [], domain.load()["removed_index"]
    item = evidence.get("operation_context", {})
    # A saved local class spelling cannot exclude an inherited removed API.
    # Current observed ancestry still distinguishes the recorded namesakes.
    if (evidence["exception"] == "AttributeError"
            and set(evidence["owners"]) & set(project.get("defined_names", []))
            and not (item.get("status") == "observed_operation"
                     and item.get("record", {}).get("receiver_owners")
                     and _current_snapshots(session, item, project, environment)
                     and _one_failure(session, issue, item))):
        installed = {canonicalize_name(p.get("name", "")): p.get("version", "")
                     for p in environment.get("packages", [])}
        installed["python"] = environment.get("python_version", "")
        for name in evidence["attributes"]:
            entry = entries.get("attribute:" + name)
            if not entry:
                continue
            try:
                applicable = Version(installed.get(canonicalize_name(entry["distribution"]), "")) >= Version(entry["version"])
            except (InvalidVersion, TypeError):
                applicable = False
            if applicable:
                evidence["removal_ownership_unobserved"] = True
                result.append(observed(issue.issue_id, "removal_owner_unobserved", "yes", issue.evidence_refs))
                break
    # Keep established module/import diagnoses, but never interpret object text
    # or a class spelling as a module identity. Explicit owners require proof.
    message = evidence["message"]
    module_apis = {f"{module}.{name}" for name, module in CANNOT_IMPORT.findall(message)}
    module_apis.update(f"{module}.{name}" for module, name in MODULE_ATTR.findall(message))
    module_apis.update(f"numpy.{name}" for name in NUMPY_REMOVED.findall(message))
    for api in module_apis & set(evidence["apis"]):
        key = "api:" + api
        entry = entries.get(key)
        if entry and not entry.get("owners"):
            result.append(observed(issue.issue_id, "removal_owner", key, issue.evidence_refs))

    if item.get("status") in ("dynamic_receiver", "member_present"):
        # Some exact library classes (pandas.DataFrame) implement __getattr__.
        # NumPy 2.2 also retains descriptors which raise at the removed lookup.
        # Recheck the same operation's provenance; inherited hooks/descriptors
        # still cannot lend a library identity to a project subclass below.
        from .observed_operations import context

        item = context(session, issue, evidence, allow_dynamic=True, allow_present=True)
    record = item.get("record", {})
    if (item.get("status") != "observed_operation"
            or issue.environment_id != environment.get("_environment_id")
            or not environment.get("_run_id") or not project.get("_run_id")
            or not _current_snapshots(session, item, project, environment)
            or not _one_failure(session, issue, item)):
        return result
    if record.get("kind") == "module" and record.get("operation") == "IMPORT_NAME":
        proof = record.get("import_getattr", {})
        key = f"api:{record['module']}.{record['name']}"
        entry = entries.get(key)
        if (entry and not entry.get("owners")
                and _provider({"module": record["module"], "file": proof.get("module_file", "")},
                              canonicalize_name(entry["distribution"]), project, environment)):
            refs = [*item["refs"], f"{environment['_run_id']}:stdout:1", f"{project['_run_id']}:stdout:1"]
            result += [observed(issue.issue_id, "api", key, refs),
                       observed(issue.issue_id, "removal_owner", key, refs)]
        return result
    if record.get("kind") not in ("instance", "class"):
        return result
    owners = record.get("receiver_owners", [])
    refs = list(dict.fromkeys([*item["refs"], f"{environment['_run_id']}:stdout:1", f"{project['_run_id']}:stdout:1"]))
    for key, entry in entries.items():
        if entry["kind"] not in ("attribute", "api") or entry["name"].rsplit(".", 1)[-1] != record["name"]:
            continue
        expected = _owners(entry, entry["name"])
        distribution = canonicalize_name(entry["distribution"])
        if not any(f"{owner['module']}.{owner['owner']}" in expected
                   and (not (record["dynamic"] or record["requested_member_present"]) or owner["direct"])
                   and _provider(owner, distribution, project, environment) for owner in owners):
            continue
        result += [observed(issue.issue_id, entry["kind"], key, refs),
                   observed(issue.issue_id, "removal_owner", key, refs)]
    return result
