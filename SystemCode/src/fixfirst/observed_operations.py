"""Opt-in operation projection and bounded advice, with replayable provenance.

No target execution, namespace evaluation, new knowledge or classifier features.
The two factors independently consume existing executed probe records.
"""

import ast

from .symbol_context import qualified_attribute_history, valid_record
from .symbol_advice import _tree, join_edit


def _statement_matches(statement, record):
    tree = _tree(statement)
    if tree is None:
        return False
    if record["operation"] in ("IMPORT_FROM", "IMPORT_NAME"):
        node = tree.body[0]
        return (isinstance(node, ast.ImportFrom) and not node.level
                and node.module == record["module"]
                and sum(a.name == record["name"] for a in node.names) == 1
                and (record["operation"] != "IMPORT_NAME"
                     or [a.name for a in node.names] == record["import_getattr"]["fromlist"]))
    if record["kind"] in ("builtin_call", "python_binding", "builtin_binding"):
        nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        return (len(nodes) == 1 and isinstance(nodes[0].func, (ast.Name, ast.Attribute))
                and (nodes[0].func.id if isinstance(nodes[0].func, ast.Name) else nodes[0].func.attr)
                == record["name"])
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == record["name"]
             and isinstance(n.ctx, ast.Load)]
    return len(nodes) == 1


def context(session, issue, evidence, *, allow_dynamic=False, allow_present=False):
    """Select one executed exception and its same-run statement, retaining indices.

Grouped failures spanning runs/operations remain ambiguous. In particular, an
old carried event must not donate metadata to a newer failure's traceback.
"""
    from .evidence import classify_path, current_environment, shown_path, statement_at_location

    result = {"status": "missing_executed_record", "record": {}, "refs": [],
              "location": "", "statement": "", "symbol_record_ref": None,
              "symbol_statement_ref": None, "linked_failure_ref": None}
    runs = {r.run_id: r for r in session.runs}
    rows = {}
    for event in session.events:
        if event.event_id not in issue.event_ids:
            continue
        for ref in event.evidence_refs:
            run_id, separator, index = ref.partition(":probe:")
            run = runs.get(run_id)
            if separator and run and index.isdigit() and int(index) < len(run.records):
                if run.source != "executed" or run.environment_id != issue.environment_id:
                    result["status"] = "unverified_record"
                    return result
                rows[ref] = (run, run.records[int(index)])
    if not rows:
        return result
    if len({run.run_id for run, _ in rows.values()}) != 1:
        result["status"] = "ambiguous_run"
        return result
    exceptions = [(ref, run, row) for ref, (run, row) in rows.items() if row.get("type") == "exception"]
    failures = [(ref, run, row) for ref, (run, row) in rows.items() if row.get("type") == "failure"]
    if not exceptions and len(failures) == 1:
        ref, run, failure = failures[0]
        if failure.get("stage") == "collect" and failure.get("nodeid"):
            exceptions = [(f"{run.run_id}:probe:{i}", run, row) for i, row in enumerate(run.records)
                          if row.get("type") == "exception" and row.get("exception_type") == "CollectError"
                          and row.get("stage") == "collect" and row.get("nodeid") == failure["nodeid"]]
            result["linked_failure_ref"] = ref
    if len(exceptions) != 1:
        result["status"] = "ambiguous_record" if exceptions else "missing_executed_record"
        return result
    ref, run, exception = exceptions[0]
    record = valid_record(exception.get("symbol_observation"))
    if not record:
        reason = exception.get("symbol_observation_status")
        if reason in {
            "unsupported_exception", "unsupported_call_shape", "unsupported_callable", "variadic_signature",
            "valid_binding_body_error", "unsupported_signature", "ambiguous_receiver", "dynamic_receiver",
            "missing_native_receiver", "unsupported_instruction", "observation_limit", "missing_traceback",
            "signature_limit", "unsupported_receiver", "member_present", "unsupported_observation",
            "traceback_limit",
        }:
            result["status"] = reason
        elif exception.get("symbol_observation"):
            result["status"] = "invalid_observation"
        return result
    # Legacy details can select a different grouped member. Do not combine it.
    if record != evidence.get("symbol_observation"):
        result["status"] = "record_mismatch"
        return result
    record = {k: record[k] for k in (
        "source", "kind", "operation", "module", "owner", "name", "file", "line",
        "static_namespace_checked", "requested_member_present", "dynamic", "unique", "candidates",
        "argument_count_given", "argument_count_expected", "argument_types", "callee_name",
        "parameters", "positional_count", "keyword_names", "binding_errors", "definition_file",
        "definition_line", "receiver_owners", "import_getattr") if k in record}
    record["candidates"] = [{"name": row["name"], "relation": row["relation"]} for row in record["candidates"]]
    result.update(record=record, symbol_record_ref=ref, refs=[ref])
    if record["dynamic"] and not allow_dynamic:
        result["status"] = "dynamic_receiver"
        return result
    if (record["kind"] not in ("builtin_call", "python_binding", "builtin_binding")
            and record["requested_member_present"] and not allow_present):
        result["status"] = "member_present"
        return result
    location = f"{shown_path(record['file'], session.project_root)}:{record['line']}"
    statements = []
    for failure_ref, failure_run, failure in failures:
        if (failure_run.run_id == run.run_id and failure.get("stage") == exception.get("stage")
                and failure.get("nodeid") == exception.get("nodeid")):
            text = statement_at_location(str(failure.get("message", "")), location, session.project_root)
            if text:
                statements.append((failure_ref, text))
    if not statements:
        for stream in ("stdout", "stderr"):
            text = statement_at_location(getattr(run, stream), location, session.project_root)
            if text:
                statements.append((f"{run.run_id}:{stream}:1", text))
    if len(statements) != 1 or not _statement_matches(statements[0][1], record):
        result["status"] = "ambiguous_statement"
        return result
    statement_ref, statement = statements[0]
    result.update(status="observed_operation", location=location, statement=statement,
                  symbol_statement_ref=statement_ref,
                  origin=classify_path(record["file"], session.project_root, current_environment(session)))
    result["refs"] = list(dict.fromkeys([ref, statement_ref, *([result["linked_failure_ref"]]
                                                            if result["linked_failure_ref"] else [])]))
    return result


def projection(session, issue, evidence, project, environment, *, use_history=True):
    from .evidence import observed

    item = context(session, issue, evidence)
    item["projection_status"] = "disabled" if not session.structured_evidence else item["status"]
    if not session.structured_evidence or item["status"] != "observed_operation":
        return [], item
    record, refs = item["record"], item["refs"]
    values = {"operation": record["operation"], "receiver_kind": record["kind"],
              "receiver_type": ".".join(p for p in (record["module"], record["owner"]) if p),
              "operation_member": record["name"], "operation_location": item["location"]}
    if record["kind"] == "builtin_call":
        values.update(operation_argument_count=str(record["argument_count_given"]),
                      operation_argument_types=",".join(record["argument_types"]))
    facts = [observed(issue.issue_id, key, value, refs) for key, value in values.items() if value]
    item["projection_status"] = "operation_only_no_history"
    if not use_history:
        item["projection_status"] = "operation_only_history_disabled"
    if (use_history and record["kind"] in ("instance", "class")
            and qualified_attribute_history({"symbol_observation": record}, project, environment)):
        qualified = ".".join(record[key] for key in ("module", "owner", "name"))
        context_refs = [f"{snapshot['_run_id']}:stdout:1" for snapshot in (project, environment)
                        if snapshot.get("_run_id")]
        facts += [observed(issue.issue_id, "attribute", "attribute:" + qualified, refs + context_refs),
                  observed(issue.issue_id, "module", "module:" + record["module"].split(".")[0], refs + context_refs)]
        item["projection_status"] = "qualified_history_projected"
        item["history_context_refs"] = context_refs
    return facts, item


# Templates known to express generic investigation, rather than a specific fix.
GENERIC_RULES = {"P40", "P50", "P51", "RUN-P2"}


def generic_snapshots(actions):
    return {a.action_id: a.model_dump() for a in actions if a.kind == "manual_fix"
            and len(a.rule_ids) == 1 and a.rule_ids[0] in GENERIC_RULES
            and len(a.issue_ids) == 1 and not a.command and not a.declaration_edits}


def refine(session, actions, details, issues, snapshots):
    """C uses raw operation proof, independent of the B flag and model label."""
    from .evidence import observed

    outcomes = {}
    for issue_id, issue in issues.items():
        item = details.get(issue_id, {}).get("operation_context", {})
        outcome = {"enabled": session.bounded_actions, "eligibility": item.get("status", "missing_executed_record"),
                   "generated": False, "action_id": None}
        outcomes[issue_id] = outcome
        if item.get("status") != "observed_operation":
            continue
        if issue.status != "open" or item.get("origin") != "project":
            outcome["eligibility"] = "non_project_or_inactive"
            continue
        if any(f.subject == issue_id and f.predicate == "diagnosis" for f in session.facts):
            outcome["eligibility"] = "conflicting_rule"
            continue
        related = [a for a in actions if issue_id in a.issue_ids and a.kind == "manual_fix"]
        if any(a.model_dump() != snapshots.get(a.action_id) for a in related):
            outcome["eligibility"] = "specific_action_present"
            continue
        if len(related) != 1:
            outcome["eligibility"] = "no_unique_generic_action"
            continue
        record = item["record"]
        replacement = join_edit(item["statement"], record)
        if not replacement:
            outcome["eligibility"] = "name_similarity_only" if record["candidates"] else "unsupported_operation"
            continue
        outcome["eligibility"] = "accepted_observed_contract"
        if not session.bounded_actions:
            continue
        action = related[0]
        fact = observed(issue_id, "observed_call_contract", "builtin_str_join_separate_strings", item["refs"])
        session.facts.append(fact)
        action.title = f"Correct the observed call at {item['location']}"
        action.explanation = (
            f"{item['location']}: replace `{item['statement']}` with `{replacement}`. "
            "Keep surrounding indentation and the original tests unchanged. "
            "The executed builtin str.join call received separate strings. It accepts one iterable of strings; "
            "group these arguments while preserving their order. "
            "Reference: https://docs.python.org/3/library/stdtypes.html#str.join."
        )
        action.cause = "code_defect"
        action.rule_ids = [*action.rule_ids, "observed-contract:builtin_join_arguments"]
        action.reason_refs = list(dict.fromkeys([*action.reason_refs, fact.fact_id]))
        outcome.update(generated=True, action_id=action.action_id)
    return outcomes


def trace(session, issues, details, outcomes):
    """Bounded diagnostics only: never a classifier input or ranking signal."""
    rows = []
    for issue_id, issue in list(issues.items())[:100]:
        candidates = [f for f in session.facts if f.subject == issue_id
                      and f.predicate in ("diagnosis", "likely", "suspected", "model_suggests")]
        first = next((a for a in session.actions if issue_id in a.issue_ids), None)
        action = dict(outcomes.get(issue_id, {}))
        action["became_first_for_issue"] = bool(action.get("generated") and first and first.action_id == action["action_id"])
        action["became_first_step"] = bool(action.get("generated") and session.actions
                                            and session.actions[0].action_id == action["action_id"])
        rows.append({"issue_id": issue_id, "operation": details.get(issue_id, {}).get("operation_context", {}),
                     "prediction": issue.prediction, "prediction_confidence": issue.prediction_confidence,
                     "prediction_note": issue.prediction_note,
                     "diagnosis": issue.diagnosis, "diagnosis_source": issue.diagnosis_source,
                     "diagnosis_rule": issue.diagnosis_rule,
                     "adoption": ("certain_rule_priority" if issue.diagnosis_source == "rule" else
                                  "heuristic_priority" if issue.diagnosis_source == "heuristic" else
                                  "model_hypothesis" if issue.diagnosis_source == "model" else "unconfirmed"),
                     "diagnosis_candidates": [{"fact_id": f.fact_id, "predicate": f.predicate,
                                               "value": f.value, "rule_id": f.rule_id} for f in candidates[:20]],
                     "candidates_omitted": max(0, len(candidates) - 20), "bounded_action": action,
                     "binding_plan": details.get(issue_id, {}).get("binding_plan", {}),
                     "first_related_action_id": first.action_id if first else None,
                     "first_related_action_rules": first.rule_ids if first else []})
    return {"structured_evidence": session.structured_evidence, "bounded_actions": session.bounded_actions,
            "issues": rows, "issues_omitted": max(0, len(issues) - len(rows)),
            "first_action_scope": "raw_ordered_plan",
            "global_first_action_id": session.actions[0].action_id if session.actions else None}
