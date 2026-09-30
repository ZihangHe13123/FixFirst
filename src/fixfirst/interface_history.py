"""Source-cited interface history, matched to observed owners and versions.

These are knowledge metadata, not a classifier prediction. Model experiments must
report their contribution separately from features obtained solely from a project.
An unrecognised interface is unknown, not evidence that a call is correct or wrong.
"""

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from . import domain
from .source_context import resolved_calls


def matching_history(evidence, project, environment):
    installed = {canonicalize_name(p.get("name", "")): p.get("version", "")
                 for p in environment.get("packages", [])}
    installed["python"] = environment.get("python_version", "")
    local = {r["name"] for r in project.get("local_modules", [])}
    providers = environment.get("import_distributions", {})
    calls = set(resolved_calls(evidence, project, legacy=True))
    index = project.get("source_context", {})
    bases = {base for owner in evidence.get("owners", [])
             for base in index.get("class_bases", {}).get(owner, []) if base}
    names = set(evidence.get("apis", []))
    attributes = {name.rsplit(".", 1)[-1] for name in names}
    kwargs = {name.rsplit(".", 1)[-1] for name in evidence.get("kwargs", [])}
    result = []

    def provided_by(target, distribution):
        top = target.split(".")[0]
        if top in local:
            return False
        if distribution == "python":
            return top in environment.get("stdlib_modules", [])
        return distribution in {canonicalize_name(p) for p in providers.get(top, [])}

    for entry in domain.load().get("removed", []):
        distribution = canonicalize_name(entry["distribution"])
        try:
            if Version(installed.get(distribution, "")) < Version(entry["version"]):
                continue
        except InvalidVersion:
            continue
        kind = entry["kind"]
        matched = []
        if kind == "module":
            name = evidence.get("missing_module")
            if name in entry["names"] and name.split(".")[0] not in local:
                matched = [name]
        elif kind == "api":
            matched = [f"{entry['module']}.{name}" for name in entry["names"]
                       if f"{entry['module']}.{name}" in names
                       and provided_by(entry["module"], distribution)]
        elif kind == "kwarg" and len(calls) == 1:
            target = next(iter(calls))
            if target in entry.get("callables", []) and provided_by(target, distribution):
                matched = [name for name in entry["names"] if name.rsplit(".", 1)[-1] in kwargs]
        elif kind == "attribute":
            owners = set(entry.get("owners", [])) & bases
            if any(provided_by(owner, distribution) for owner in owners):
                matched = sorted(attributes & set(entry["names"]))
        for name in matched:
            result.append({"kind": kind, "name": name, "distribution": distribution,
                           "removed_in": entry["version"], "source": entry["source"]})
    return result


def feature_values(evidence, values, project, environment, *, use_history=True):
    history = matching_history(evidence, project, environment) if use_history else []
    signature = values["call_signature_mismatch"]
    local_call = signature and values["callee_project"]
    local_import = (values["module_local"] and values["signal_cannot_import_name"]
                    and not values["signal_partially_initialized"])
    index = project.get("source_context", {})
    # Similar names must be members of the named class, not an unrelated file.
    import difflib

    near_member = any(
        difflib.get_close_matches(api.rsplit(".", 1)[-1], members, n=1, cutoff=0.75)
        for owner in evidence.get("owners", [])
        for members in [index.get("class_members", {}).get(owner, [])]
        for api in evidence.get("apis", [])
    )
    plain_local_owner = (values["owner_defined_locally"] and values["signal_no_attribute"]
                         and any(not index.get("class_bases", {}).get(owner, ["unknown"])
                                 for owner in evidence.get("owners", [])))
    return {
        "interface_history_match": bool(history),
        "context_local_symbol": bool(local_call or local_import or near_member or plain_local_owner),
        "context_local_cycle": bool(values["module_local"] and values["signal_partially_initialized"]),
        "external_call_without_history": bool(values["callee_external"] and signature and not history),
    }


FEATURE_NAMES = ["interface_history_match", "context_local_symbol", "context_local_cycle",
                 "external_call_without_history"]
