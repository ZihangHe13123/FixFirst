"""Guide an observed PyYAML Loader omission without inventing a downgrade."""

import ast
from pathlib import Path
import re

from packaging.version import InvalidVersion, Version

from .binding_advice import valid_binding
from .evidence import classify_path, current_environment
from .models import Action
from .symbol_advice import _tree


SOURCE = "https://github.com/yaml/pyyaml/blob/6.0.3/lib/yaml/__init__.py"


def loader_edit(item, environment, project_root):
    """Use the real failed callable, its binding contract and the recorded source."""
    record = item.get("record", {})
    if (item.get("status") != "observed_operation" or item.get("origin") != "project"
            or record.get("kind") != "python_binding" or record.get("module") != "yaml"
            or record.get("callee_name") not in ("load", "load_all")
            or not valid_binding(record)
            or record.get("static_namespace_checked") is not True
            or record.get("dynamic") is not False):
        return None
    definition = record["definition_file"].replace("\\", "/")
    providers = environment.get("import_distributions", {}).get("yaml", [])
    if (classify_path(definition, project_root, environment) != "third_party"
            or not definition.endswith("/yaml/__init__.py")
            or len(providers) != 1 or str(providers[0]).lower() != "pyyaml"):
        return None
    packages = [p for p in environment.get("packages", [])
                if str(p.get("name", "")).lower() == "pyyaml"]
    if len(packages) != 1:
        return None
    try:
        if not Version("6") <= Version(packages[0]["version"]) < Version("7"):
            return None
    except (InvalidVersion, KeyError, TypeError):
        return None
    if (record["parameters"] != [
            {"name": "stream", "kind": "positional_or_keyword", "required": True},
            {"name": "Loader", "kind": "positional_or_keyword", "required": True}]
            or record["binding_errors"] != {
                "positional_only_as_keyword": [], "missing": ["Loader"],
                "unexpected": [], "duplicate": [], "too_many_positional": False}):
        return None
    tree = _tree(item.get("statement"))
    if tree is None:
        return None
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    matching = [n for n in calls if (
        isinstance(n.func, ast.Name) and n.func.id == record["name"]
        or isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
        and n.func.attr == record["name"])]
    if len(matching) != 1 or any(isinstance(n, ast.Starred) for n in matching[0].args):
        return None
    call = matching[0]
    if (len(call.args) != record["positional_count"]
            or [k.arg for k in call.keywords] != record["keyword_names"]
            or any(k.arg is None for k in call.keywords)):
        return None
    before, callee = ast.unparse(call.func), record["callee_name"]
    target = "safe_load_all" if callee == "load_all" else "safe_load"
    # Renaming a locally chosen alias could change unrelated uses. Add the safe
    # import with a fresh name; a module-qualified call can retain its module alias.
    if isinstance(call.func, ast.Name):
        alias = "fixfirst_" + target
        path = Path(record["file"])
        try:
            if path.is_symlink() or path.stat().st_size > 128000:
                return None
            module = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError, ValueError, RecursionError):
            return None
        identifiers = {n.id for n in ast.walk(module) if isinstance(n, ast.Name)}
        while alias in identifiers:
            alias += "_"
        call.func.id = alias
        import_line = f"from yaml import {target} as {alias}"
    else:
        call.func.attr = target
        import_line = ""
    return {"before": item["statement"], "after": ast.unparse(tree),
            "import": import_line, "call": "yaml." + callee,
            "location": item["location"], "spelled": before}


def refine(session, actions, details, issues):
    environment = current_environment(session)
    eligible = {}
    for issue_id, evidence in details.items():
        issue = issues.get(issue_id)
        if (not issue or issue.status != "open" or issue.diagnosis != "code_defect"
                or issue.diagnosis_source not in ("rule", "heuristic", "model")
                or evidence.get("exception") != "TypeError"):
            continue
        item = evidence.get("operation_context", {})
        record = item.get("record", {})
        callee = record.get("callee_name", "")
        if not re.fullmatch(rf"{re.escape(callee)}\(\) missing 1 required positional argument: ['\"]Loader['\"]",
                            evidence.get("message", "")):
            continue
        edit = loader_edit(item, environment, session.project_root)
        if edit:
            eligible[issue_id] = edit
    if not eligible:
        return actions
    kept, originals = [], []
    for action in actions:
        matches = set(action.issue_ids) & set(eligible)
        if action.kind != "manual_fix" or action.action_id.startswith("consider-") or not matches:
            kept.append(action)
            continue
        originals.append(action)
        if set(action.issue_ids) - matches:
            kept.append(action.model_copy(update={"issue_ids": [i for i in action.issue_ids if i not in matches]}))
    if not originals:
        return actions
    # Keep the rule/heuristic certainty distinct even when the actual repair is known.
    for source in sorted({issues[i].diagnosis_source for i in eligible}):
        selected = [i for i in eligible if issues[i].diagnosis_source == source]
        locations = {eligible[i]["location"]: eligible[i] for i in selected}
        instructions = []
        for edit in locations.values():
            if edit["import"]:
                instructions.append(f"At {edit['location']}, add `{edit['import']}` immediately before the "
                                    "failing statement, keeping its indentation.")
            instructions.append(f"At {edit['location']}, replace `{edit['before']}` with `{edit['after']}`.")
        instructions.append("These changes apply to standard YAML data. Applications that require custom tags "
                            "must review their constructors and select a suitable loader instead.")
        instructions.append("For any other observed multi-document yaml.load_all omission, use "
                            "yaml.safe_load_all, retaining the surrounding generator consumption. "
                            "Keep all tests and existing value checks unchanged.")
        text = " ".join(instructions)
        related = [a for a in originals if set(a.issue_ids) & set(selected)]
        proof = [f.fact_id for f in session.facts if f.subject in selected
                 and f.predicate in ("call_binding_observed", "call_missing_parameter", "call_binding_location")]
        kept.append(Action(
            action_id="yaml-loader-" + source, kind="manual_fix",
            title="Choose an explicit safe YAML loader", instructions=text,
            explanation="The executed PyYAML callable omitted its required Loader argument. "
                        "This is a call-site correction, not evidence that an older release is needed. "
                        "safe_load reads one document and safe_load_all yields multiple documents; "
                        f"both use SafeLoader. Source: {SOURCE}",
            verification=("Re-run the same program with the same Python, arguments and input"
                          if session.goal == "run_project" else
                          "Re-run the original complete tests with the same interpreter"),
            issue_ids=selected, cause="code_defect", rule_ids=["observed-yaml-loader"],
            reason_refs=list(dict.fromkeys([*(r for a in related for r in a.reason_refs), *proof])),
            goal_impact=max(a.goal_impact for a in related),
            evidence_rank=max(a.evidence_rank for a in related), cost=1,
        ))
    return kept
