"""Validate recorded call contracts and plan value-preserving argument repairs."""

import ast

from .symbol_advice import _tree


KINDS = {"python_binding", "builtin_binding"}
PARAMETER_KINDS = {"positional_only", "positional_or_keyword", "keyword_only"}


def binding_errors(parameters, positional_count, keyword_names):
    """Recompute binding failures from names/counts only, never parameter values."""
    positional = [p["name"] for p in parameters if p["kind"] != "keyword_only"]
    keyword_allowed = {p["name"] for p in parameters if p["kind"] != "positional_only"}
    positional_only = {p["name"] for p in parameters if p["kind"] == "positional_only"}
    filled = set(positional[:positional_count])
    duplicates = [name for name in keyword_names if name in filled and name in keyword_allowed]
    filled.update(name for name in keyword_names if name in keyword_allowed)
    return {"positional_only_as_keyword": [name for name in keyword_names if name in positional_only],
            "missing": [p["name"] for p in parameters if p["required"] and p["name"] not in filled],
            "unexpected": [name for name in keyword_names if name not in positional_only | keyword_allowed],
            "duplicate": duplicates, "too_many_positional": positional_count > len(positional)}


def valid_binding(record):
    parameters, keywords = record.get("parameters"), record.get("keyword_names")
    positional = record.get("positional_count")
    if (not isinstance(parameters, list) or not 0 <= len(parameters) <= 32
            or not isinstance(keywords, list) or len(keywords) > 8
            or type(positional) is not int or not 0 <= positional <= 8
            or positional + len(keywords) > 8):
        return False
    names, order = [], []
    for p in parameters:
        if (not isinstance(p, dict) or not isinstance(p.get("name"), str)
                or not p["name"].isidentifier() or len(p["name"]) > 80
                or p.get("kind") not in PARAMETER_KINDS or type(p.get("required")) is not bool):
            return False
        names.append(p["name"])
        order.append({"positional_only": 0, "positional_or_keyword": 1, "keyword_only": 2}[p["kind"]])
    if (len(set(names)) != len(names) or order != sorted(order)
            or any(not isinstance(k, str) or not k.isidentifier() or len(k) > 80 for k in keywords)
            or len(set(keywords)) != len(keywords)):
        return False
    kinds = record.get("argument_types")
    if (not isinstance(kinds, list) or len(kinds) != positional + len(keywords)
            or any(k not in ("str", "bytes", "int", "float", "list", "tuple", "dict", "other") for k in kinds)):
        return False
    callee = record.get("callee_name")
    if not isinstance(callee, str) or not callee.isidentifier() or len(callee) > 80:
        return False
    expected = binding_errors(parameters, positional, keywords)
    if record.get("binding_errors") != expected or not any(expected.values()):
        return False
    if record["kind"] == "builtin_binding":
        return record["module"] == "builtins"
    return (isinstance(record.get("definition_file"), str) and 0 < len(record["definition_file"]) <= 4000
            and type(record.get("definition_line")) is int and record["definition_line"] > 0)


def positional_only_edit(statement, record):
    """Move the sole existing keyword expression into its sole positional slot."""
    if record.get("kind") not in KINDS or not valid_binding(record):
        return None
    parameters, keys = record["parameters"], record["keyword_names"]
    if (not parameters or record["positional_count"] != 0 or len(keys) != 1
            or parameters[0]["kind"] != "positional_only" or parameters[0]["name"] != keys[0]
            or any(p["required"] for p in parameters[1:])
            or any(binding_errors(parameters, 1, []).values())):
        return None
    tree = _tree(statement)
    if tree is None:
        return None
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    if len(calls) != 1:
        return None
    call = calls[0]
    if (call.args or len(call.keywords) != 1 or call.keywords[0].arg != keys[0]
            or not isinstance(call.keywords[0].value, (ast.Name, ast.Constant))):
        return None
    if isinstance(call.func, ast.Name):
        called = call.func.id
    elif isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
        called = call.func.attr
    else:
        return None
    if called != record["name"]:
        return None
    call.args, call.keywords = [call.keywords[0].value], []
    return ast.unparse(tree)


def evidence_facts(session, issue, evidence, project, environment):
    """Use the verified operation context; R10 opt-in factors retain their scope."""
    from .evidence import classify_path, observed

    item = evidence.get("operation_context", {})
    plan = {"status": "no_binding_observation", "generated": False}
    evidence["binding_plan"] = plan
    if item.get("status") != "observed_operation" or item.get("record", {}).get("kind") not in KINDS:
        return []
    record, refs = item["record"], item["refs"]
    if not valid_binding(record):
        plan["status"] = "invalid_binding_contract"
        return []
    facts = [observed(issue.issue_id, "call_binding_observed", record["kind"], refs),
             observed(issue.issue_id, "call_binding_location", item["location"], refs)]
    for p in record["parameters"]:
        facts.append(observed(issue.issue_id, "call_parameter_kind", f"{p['name']}:{p['kind']}", refs))
    for name in record["binding_errors"]["missing"]:
        facts.append(observed(issue.issue_id, "call_missing_parameter", name, refs))
    if issue.status != "open":
        plan["status"] = "inactive_issue"
        return facts
    replacement = positional_only_edit(item["statement"], record)
    if not replacement:
        plan["status"] = "no_value_preserving_recipe"
        return facts
    callee_origin = ("stdlib" if record["kind"] == "builtin_binding" else
                     classify_path(record["definition_file"], session.project_root, environment))
    if item.get("origin") != "project" or callee_origin not in ("project", "test", "stdlib"):
        plan["status"] = "unproven_callee_origin"
        return facts
    name = record["keyword_names"][0]
    facts.append(observed(issue.issue_id, "positional_only_repair", name, refs))
    plan.update(status="eligible_positional_only", parameter=name, location=item["location"],
                before=item["statement"], after=replacement, refs=refs)
    return facts



def run_with_contract(rules, facts, details, phases=("derive", "diagnose", "heuristic", "fallback")):
    """Admit a precise contract only after existing certain rules have priority.

    Start the final inference from observations plus the admitted contract, not
    stale heuristic conclusions. The rule engine's stratified phases stay intact.
    """
    from . import engine
    from .models import Fact

    eligible = {key: row["binding_plan"] for key, row in details.items()
                if row.get("binding_plan", {}).get("status") == "eligible_positional_only"}
    if not eligible:
        return engine.run(rules, facts, phases=phases)
    certain = engine.run(rules, facts, phases=("derive", "diagnose"))
    additions = []
    for issue_id, plan in eligible.items():
        existing = [f for f in certain.facts if f.subject == issue_id and f.status != "hypothesis"]
        if any(f.predicate == "diagnosis" and f.value != "code_defect" for f in existing):
            plan["status"] = "existing_certain_diagnosis"
            continue
        if any(f.predicate == "remedy" for f in existing):
            plan["status"] = "existing_specific_remedy"
            continue
        inputs = [f for f in facts if f.subject == issue_id and f.predicate in
                  ("positional_only_repair", "call_binding_observed", "call_binding_location")]
        if {f.predicate for f in inputs} != {
            "positional_only_repair", "call_binding_observed", "call_binding_location"
        }:
            plan["status"] = "missing_contract_facts"
            continue
        for predicate, value in (("diagnosis", "code_defect"),
                                 ("remedy", "pass_existing_expression_positionally")):
            if predicate == "diagnosis" and any(f.predicate == "diagnosis" for f in existing):
                continue
            additions.append(Fact(
                fact_id=f"{issue_id}:{predicate}:{value}", subject=issue_id,
                predicate=predicate, value=value, status="derived", rule_id="runtime-binding-contract",
                inputs=[f.fact_id for f in inputs],
                evidence_refs=sorted({r for f in inputs for r in f.evidence_refs}),
            ))
    return engine.run(rules, facts + additions, phases=phases)

def refine(actions, details):
    for action in actions:
        if action.rule_ids != ["P_BINDING"] or len(action.issue_ids) != 1:
            continue
        plan = details.get(action.issue_ids[0], {}).get("binding_plan", {})
        if plan.get("status") != "eligible_positional_only":
            continue
        action.explanation = (
            f"{plan['location']}: replace `{plan['before']}` with `{plan['after']}`. "
            "Keep surrounding indentation and the original tests unchanged. "
            f"The recorded callable declares {plan['parameter']} as positional-only. "
            "Pass the same existing expression positionally; its value and evaluation order are preserved. "
            "Re-run the original tests to verify the intended result."
        )
        plan.update(generated=True, action_id=action.action_id)
    return actions
