"""Narrow first-step refinements supported by actual failure-site observations.

The classifier still chooses only a hypothesis. These recipes do not edit files,
change the rule ordering, or claim that nearby members have identical semantics.
"""

import ast

from .symbol_context import valid_record


def _tree(statement):
    if not statement or len(statement) > 2000 or "\n" in statement or "#" in statement or "`" in statement:
        return None
    try:
        tree = ast.parse(statement)
    except (SyntaxError, ValueError, RecursionError):
        return None
    return tree if len(tree.body) == 1 else None


def spelling_edit(statement, record):
    tree = _tree(statement)
    if (tree is None or record.get("dynamic") or record.get("requested_member_present")
            or not record.get("unique") or len(record.get("candidates", [])) != 1):
        return None
    candidate = record["candidates"][0]
    if candidate["relation"] not in ("case", "swap", "repeat"):
        return None
    before, after = record["name"], candidate["name"]
    if before.startswith("_"):
        return None
    if record["operation"] == "IMPORT_FROM":
        node = tree.body[0]
        if not isinstance(node, ast.ImportFrom) or node.level or node.module != record["module"]:
            return None
        chosen = [alias for alias in node.names if alias.name == before]
        if len(chosen) != 1:
            return None
        alias = chosen[0]
        alias.name, alias.asname = after, alias.asname or before
    else:
        matches = [node for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == before]
        if len(matches) != 1 or not isinstance(matches[0].ctx, ast.Load):
            return None
        # Complex receivers are not reconstructed from a traceback excerpt.
        if not isinstance(matches[0].value, (ast.Name, ast.Constant)):
            return None
        matches[0].attr = after
    return ast.unparse(tree)


def join_edit(statement, record):
    """The observed builtin str.join received separate string arguments, not an iterable."""
    if (record.get("kind"), record.get("module"), record.get("owner"), record.get("name")) != (
            "builtin_call", "builtins", "str", "join"):
        return None
    count = record.get("argument_count_given")
    if (record.get("argument_count_expected") != 1 or not isinstance(count, int) or count < 2
            or record.get("argument_types") != ["str"] * count):
        return None
    tree = _tree(statement)
    if tree is None:
        return None
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    if len(calls) != 1:
        return None
    node = calls[0]
    if (not isinstance(node.func, ast.Attribute) or node.func.attr != "join" or node.keywords
            or len(node.args) != count or not isinstance(node.func.value, (ast.Name, ast.Constant))
            or any(not isinstance(arg, (ast.Name, ast.Constant)) for arg in node.args)):
        return None
    node.args = [ast.Tuple(elts=node.args, ctx=ast.Load())]
    return ast.unparse(tree)


def unsupported_version_claim(prediction, evidence):
    """A current near member alone cannot distinguish a typo from a removed API."""
    if prediction != "version_incompatibility":
        return False
    record = valid_record(evidence.get("symbol_observation"))
    if not record or not record["candidates"] or record["dynamic"] or record["requested_member_present"]:
        return False
    from .evidence import FEATURE_NAMES

    features = dict(zip(FEATURE_NAMES, evidence.get("features", [])))
    supported = (features.get("interface_history_match") or features.get("qualified_attribute_history_match")
                 or features.get("signal_partially_initialized") or evidence.get("version_conflicts"))
    return not supported


def refine(actions, details, issues):
    for action in actions:
        if action.kind != "manual_fix" or not set(action.rule_ids) & {"P40", "P50"} or len(action.issue_ids) != 1:
            continue
        issue_id = action.issue_ids[0]
        issue, evidence = issues.get(issue_id), details.get(issue_id, {})
        if (issue is None or issue.status != "open" or issue.diagnosis != "code_defect"
                or issue.diagnosis_source != "model" or evidence.get("symbol_use_origin") != "project"):
            continue
        record = valid_record(evidence.get("symbol_observation"))
        location, statement = evidence.get("symbol_location"), evidence.get("symbol_statement")
        if not record or not location or not statement:
            continue
        replacement = spelling_edit(statement, record)
        recipe = "observed_member"
        if replacement is None:
            replacement = join_edit(statement, record)
            recipe = "builtin_join_arguments"
        if replacement is None or replacement == statement:
            continue
        explanation = (
            f"The failing operation requested {record['name']}; its actual receiver has the unique "
            f"nearby member {record['candidates'][0]['name']}. This supports a spelling hypothesis; "
            "verify the intended behavior with the original tests."
            if recipe == "observed_member" else
            "The executed builtin str.join call received separate strings. It accepts one iterable of strings; "
            "group these arguments while preserving their order. "
            "Reference: https://docs.python.org/3/library/stdtypes.html#str.join."
        )
        action.title = f"Correct the observed call at {location}" if recipe != "observed_member" else f"Check the observed member spelling at {location}"
        action.explanation = (f"{location}: replace `{statement}` with `{replacement}`. "
                              "Keep surrounding indentation and the original tests unchanged. " + explanation)
        action.cause = "code_defect"
        action.rule_ids = [*action.rule_ids, "observed-symbol:" + recipe]
        action.reason_refs = list(dict.fromkeys([*action.reason_refs, f"{issue_id}:model_suggests:code_defect"]))
        # Keep the generic action's ranking: the model remains a hypothesis.
    return actions
