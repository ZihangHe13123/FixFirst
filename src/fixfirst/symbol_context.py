"""Feature projection of bounded, actually executed symbol observations.

Names are retained for explanations, never encoded as case/package identifiers.
The separate history bit reads existing sourced metadata; it is not a diagnosis.
"""

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


FEATURE_NAMES = [
    "symbol_namespace_observed", "symbol_requested_member_present",
    "symbol_candidate_found", "symbol_candidate_unique", "symbol_candidate_simple_edit",
    "symbol_candidate_case", "symbol_candidate_swap", "symbol_candidate_repeat", "symbol_candidate_other",
    "symbol_receiver_module", "symbol_receiver_registered_type",
    "symbol_use_project", "symbol_use_library", "symbol_dynamic_namespace", "symbol_builtin_arity",
]
HISTORY_FEATURE_NAMES = ["qualified_attribute_history_match"]


def valid_record(value):
    if not isinstance(value, dict) or value.get("source") != "failed_instruction_namespace":
        return {}
    if value.get("static_namespace_checked") is not True:
        return {}
    if (not isinstance(value.get("file"), str) or not value["file"] or len(value["file"]) > 4000
            or type(value.get("line")) is not int or value["line"] <= 0):
        return {}
    if not all(type(value.get(key)) is bool for key in ("requested_member_present", "dynamic", "unique")):
        return {}
    kind = value.get("kind")
    operations = {"module": ("LOAD_ATTR", "LOAD_METHOD", "IMPORT_FROM"),
                  "instance": ("LOAD_ATTR", "LOAD_METHOD"), "class": ("LOAD_ATTR", "LOAD_METHOD"),
                  "builtin_call": ("CALL", "CALL_FUNCTION", "CALL_METHOD"),
                  "python_binding": ("CALL", "CALL_FUNCTION", "CALL_METHOD", "CALL_KW"),
                  "builtin_binding": ("CALL", "CALL_FUNCTION", "CALL_METHOD", "CALL_KW")}
    if kind not in operations or value.get("operation") not in operations[kind]:
        return {}
    name, module, owner = value.get("name"), value.get("module"), value.get("owner")
    if not isinstance(name, str) or not name.isidentifier() or len(name) > 80:
        return {}
    if not all(isinstance(s, str) and len(s) <= 200 for s in (module, owner)):
        return {}
    if any(s and not all(part.isidentifier() for part in s.split(".")) for s in (module, owner)):
        return {}
    if kind == "module" and not module:
        return {}
    owners = value.get("receiver_owners", [])
    if not isinstance(owners, list) or len(owners) > 32:
        return {}
    for row in owners:
        if (not isinstance(row, dict) or set(row) != {"module", "owner", "file", "direct"}
                or any(not isinstance(row.get(key), str) or not row[key] or len(row[key]) > 200
                       or not all(part.isidentifier() for part in row[key].split("."))
                       for key in ("module", "owner"))
                or not isinstance(row.get("file"), str) or len(row["file"]) > 4000
                or type(row.get("direct")) is not bool):
            return {}
    candidates = value.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 5:
        return {}
    for row in candidates:
        if (not isinstance(row, dict) or not isinstance(row.get("name"), str)
                or not row["name"].isidentifier() or row["name"].startswith("_") or len(row["name"]) > 80
                or row.get("relation") not in ("case", "swap", "repeat", "other")):
            return {}
    if value.get("unique") is True and len(candidates) != 1:
        return {}
    if len({row["name"] for row in candidates}) != len(candidates):
        return {}
    if kind in ("python_binding", "builtin_binding"):
        from .binding_advice import valid_binding

        if not valid_binding(value):
            return {}
    if kind == "builtin_call":
        expected, given = value.get("argument_count_expected"), value.get("argument_count_given")
        if (module != "builtins" or type(expected) is not int or type(given) is not int
                or not 0 <= expected <= 8 or not 1 <= given <= 8 or expected == given):
            return {}
        supplied = value.get("argument_types")
        if (not isinstance(supplied, list) or len(supplied) != given
                or any(kind not in ("str", "bytes", "int", "float", "list", "tuple", "dict", "other")
                       for kind in supplied)):
            return {}
    return value


def feature_values(evidence):
    record = valid_record(evidence.get("symbol_observation"))
    if not record:
        return {name: False for name in FEATURE_NAMES}
    relations = {row["relation"] for row in record["candidates"]}
    origin = evidence.get("symbol_use_origin")
    return {
        "symbol_namespace_observed": True,
        "symbol_requested_member_present": record.get("requested_member_present") is True,
        "symbol_candidate_found": bool(record["candidates"]),
        "symbol_candidate_unique": record.get("unique") is True,
        "symbol_candidate_simple_edit": bool(relations & {"case", "swap", "repeat"}),
        **{f"symbol_candidate_{relation}": relation in relations for relation in ("case", "swap", "repeat", "other")},
        "symbol_receiver_module": record["kind"] == "module",
        "symbol_receiver_registered_type": record["kind"] in ("instance", "class")
                                             and bool(record["module"] and record["owner"]),
        "symbol_use_project": origin in ("project", "test"),
        "symbol_use_library": origin in ("third_party", "stdlib"),
        "symbol_dynamic_namespace": record.get("dynamic") is True,
        "symbol_builtin_arity": record["kind"] == "builtin_call",
    }


def qualified_attribute_history(evidence, project, environment):
    """An already-recorded registered type, one provider and a supported removal entry."""
    from . import domain

    attribute = valid_record(evidence.get("symbol_observation"))
    if not attribute or attribute["kind"] not in ("instance", "class"):
        return False
    parts = [attribute.get(key) for key in ("module", "owner", "name")]
    if not all(isinstance(value, str) and value and all(p.isidentifier() for p in value.split(".")) for value in parts):
        return False
    module = parts[0].split(".")[0]
    if module in {r["name"] for r in project.get("local_modules", [])}:
        return False
    providers = {canonicalize_name(p) for p in environment.get("import_distributions", {}).get(module, [])}
    stdlib = module in environment.get("stdlib_modules", [])
    if stdlib and not providers:
        providers = {"python"}
    if len(providers) != 1:
        return False
    distribution = next(iter(providers))
    if distribution in {canonicalize_name(p) for p in project.get("own_names", [])}:
        return False
    installed = {canonicalize_name(p.get("name", "")): p.get("version", "")
                 for p in environment.get("packages", [])}
    installed["python"] = environment.get("python_version", "")
    for entry in domain.load().get("removed", []):
        if (entry["kind"] == "attribute" and ".".join(parts) in entry["names"]
                and canonicalize_name(entry["distribution"]) == distribution):
            try:
                return Version(installed.get(distribution, "")) >= Version(entry["version"])
            except (InvalidVersion, TypeError):
                return False
    return False
