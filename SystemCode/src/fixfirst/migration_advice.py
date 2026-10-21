"""Locate documented source migrations using the statement recorded at failure."""

import ast

from . import domain


def relocated_import(statement, entry):
    """Only rewrite one matching absolute import; keep unrelated names and aliases."""
    target = entry.get("replacement_import")
    if not target or len(statement) > 2000 or "#" in statement:
        return None
    try:
        tree = ast.parse(statement)
    except (SyntaxError, ValueError, RecursionError):
        return None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.ImportFrom):
        return None
    node = tree.body[0]
    if node.level or node.module != entry.get("module") or any(n.name == "*" for n in node.names):
        return None
    chosen = [name for name in node.names if name.name == entry["name"]]
    if len(chosen) != 1:
        return None
    module, _, symbol = target.rpartition(".")
    alias = chosen[0]
    result = []
    remaining = [name for name in node.names if name is not alias]
    if remaining:
        result.append(ast.ImportFrom(module=node.module, names=remaining, level=0))
    result.append(ast.ImportFrom(module=module, level=0,
        names=[ast.alias(name=symbol, asname=alias.asname or (alias.name if symbol != alias.name else None))]))
    return "\n".join(ast.unparse(node) for node in result)


def renamed_keyword(statement, entry):
    """Only a documented rename with an explicitly supported literal value."""
    if (not entry.get("rename_to") or entry.get("rename_value") != "string_literal"
            or not statement or len(statement) > 2000 or "\n" in statement or "#" in statement or "`" in statement):
        return None
    try:
        tree = ast.parse(statement + ("\n    pass" if statement.endswith(":") else ""))
    except (SyntaxError, ValueError, RecursionError):
        return None
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    if len(calls) != 1 or len(tree.body) != 1:
        return None
    chosen = [kw for kw in calls[0].keywords if kw.arg == entry["name"].rsplit(".", 1)[-1]]
    if (len(chosen) != 1 or any(kw.arg in (None, entry["rename_to"]) for kw in calls[0].keywords)
            or not isinstance(chosen[0].value, ast.Constant) or type(chosen[0].value.value) is not str):
        return None
    keyword = chosen[0]
    encoded = statement.encode("utf-8")
    start, end = keyword.col_offset, keyword.col_offset + len(keyword.arg.encode("utf-8"))
    if encoded[start:end].decode("utf-8") != keyword.arg:
        return None
    return (encoded[:start] + entry["rename_to"].encode("utf-8") + encoded[end:]).decode("utf-8")


def refine(actions, details):
    for action in actions:
        if "P10" not in action.rule_ids:
            continue
        evidence = [details[i] for i in action.issue_ids if i in details]
        places = sorted({e["source_location"] for e in evidence if e.get("source_location")})
        if places:
            action.explanation = "Observed project location: " + ", ".join(places[:5]) + ". " + action.explanation
        for item in evidence:
            # The generating rule already verified the callable, provider and installed
            # version. Restrict exact edits to that one rule's recorded keyword.
            keyword_entries = [entry for key, entry in domain.load()["removed_index"].items()
                               if entry["kind"] == "kwarg" and f"kb:{key}:replacement" in action.reason_refs]
            if len(keyword_entries) == 1 and not item.get("library"):
                precise = item.get("precise_statement", "")
                renamed = renamed_keyword(precise, keyword_entries[0])
                if renamed and item.get("source_location"):
                    action.explanation = (f"{item['source_location']}: replace `{precise}` with `{renamed}`. "
                                          "Keep surrounding indentation and the original tests unchanged. " + action.explanation)
            statement = item.get("source_statement", "")
            entries = [domain.load()["removed_index"]["api:" + name] for name in item.get("apis", [])
                       if "api:" + name in domain.load()["removed_index"]]
            if len(entries) != 1 or item.get("library") or not item.get("source_location"):
                continue
            replacement = relocated_import(statement, entries[0])
            if replacement:
                action.explanation = (
                    f"{item['source_location']}: replace `{statement}` with `{replacement}`. "
                    "Keep the surrounding indentation and other code unchanged. " + action.explanation)
        # Exact imports/keywords and all restrictions on the documented replacement
        # are part of the operation; an abbreviated rationale must not lose them.
        action.instructions = action.explanation
    return actions
