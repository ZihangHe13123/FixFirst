"""Curated domain knowledge graph: import names, removed and deprecated APIs, pytest plugin
fixtures, causes and their sources.

The rule base only sees the part of this graph that is relevant to the current evidence
(``facts_for``). Every knowledge fact cites the upstream document it comes from.
"""

from functools import lru_cache
from importlib import resources

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .models import Fact

KINDS = {"module", "api", "attribute", "kwarg", "usage", "fixture"}


def dist_id(name: str) -> str:
    return "dist:python" if name.lower() == "python" else "dist:" + canonicalize_name(name)


def _tool_failure_index(rows, sources):
    """Validate bounded, source-cited failure mechanisms, not general support tables."""
    index = {}
    required = ("id", "distribution", "affected_from", "fixed_version", "python_from",
                "python_before", "summary", "source")
    for entry in rows:
        if not isinstance(entry, dict) or any(
                not isinstance(entry.get(name), str) or not entry[name].strip() for name in required):
            raise ValueError("invalid tool failure knowledge entry")
        key = "tool-failure:" + entry["id"]
        if key in index or entry["source"] not in sources:
            raise ValueError(f"invalid tool failure source or duplicate entry {key}")
        try:
            bounds = [Version(entry[name]) for name in required[2:6]]
        except InvalidVersion as error:
            raise ValueError(f"invalid tool failure version bound {key}") from error
        if (any(v.is_prerelease or v.is_devrelease or v.local for v in bounds)
                or not bounds[0] < bounds[1] or not bounds[2] < bounds[3]):
            raise ValueError(f"invalid tool failure version interval {key}")
        index[key] = entry
    return index


@lru_cache(maxsize=1)
def load() -> dict:
    text = resources.files("fixfirst").joinpath("knowledge/domain.toml").read_text("utf-8")
    data = tomllib.loads(text)
    index = {}
    for entry in data.get("removed", []):
        if entry["kind"] not in KINDS or entry["source"] not in data["sources"]:
            raise ValueError(f"invalid knowledge entry {entry.get('names')}")
        for name in entry["names"]:
            key = (
                f"api:{entry['module']}.{name}"
                if entry["kind"] == "api"
                else f"{entry['kind']}:{name}"
            )
            index[key] = {**entry, "name": name, "id": key}
    data["removed_index"] = index
    for migration in data.get("consumer_migration", []):
        if migration["api"] not in index or migration["source"] not in data["sources"]:
            raise ValueError("invalid consumer migration source")
    deprecated = {}
    for entry in data.get("deprecated", []):
        if entry["source"] not in data["sources"]:
            raise ValueError(f"invalid deprecation entry {entry.get('names')}")
        for name in entry["names"]:
            key = f"api:{entry['module']}.{name}"
            deprecated[key] = {**entry, "name": name, "id": key}
    data["deprecated_index"] = deprecated
    behaviors = {}
    for entry in data.get("behavior", []):
        key = "behavior:" + entry["id"]
        if key in behaviors or entry["source"] not in data["sources"]:
            raise ValueError(f"invalid behavior entry {key}")
        behaviors[key] = entry
    data["behavior_index"] = behaviors
    inputs = {}
    for entry in data.get("input_error", []):
        key = "input:" + entry["id"]
        if key in inputs or entry["source"] not in data["sources"]:
            raise ValueError(f"invalid input contract {key}")
        inputs[key] = entry
    data["input_index"] = inputs
    data["tool_failure_index"] = _tool_failure_index(data.get("tool_failure", []), data["sources"])
    data["unmaintained_index"] = {dist_id(e["distribution"]): e for e in data.get("unmaintained", [])}
    # Fixtures are cited by the plugin's PyPI page unless the entry names another source.
    lint = data.setdefault("lint", {"likely_bug": [], "categories": {}})
    if lint.get("likely_bug") and lint.get("source") not in data["sources"]:
        raise ValueError("invalid lint source")
    data["fixture_index"] = {
        "fixture:" + name: entry for entry in data.get("fixture", []) for name in entry["names"]
    }
    return data


def knowledge(subject, predicate, value, source) -> Fact:
    return Fact(
        fact_id=f"kb:{subject}:{predicate}",
        subject=subject,
        predicate=predicate,
        value=value,
        status="knowledge",
        evidence_refs=[f"kb:{source}"],
    )


def facts_for(entities) -> list[Fact]:
    """Knowledge facts about the modules, APIs and arguments named in current evidence."""
    kb = load()
    result = []
    for entity in sorted(set(entities)):
        entry = kb["tool_failure_index"].get(entity)
        if entry:
            result += [
                knowledge(entity, "tool_distribution", dist_id(entry["distribution"]), entry["source"]),
                *[knowledge(entity, field, entry[field], entry["source"])
                  for field in ("affected_from", "fixed_version", "python_from", "python_before")],
                knowledge(entity, "change_summary", entry["summary"], entry["source"]),
            ]
        entry = kb["input_index"].get(entity)
        if entry:
            result += [
                knowledge(entity, "input_rejected_by", dist_id(entry["distribution"]), entry["source"]),
                knowledge(entity, "action_title", entry["action_title"], entry["source"]),
                knowledge(entity, "input_guidance", entry["guidance"], entry["source"]),
            ]
        entry = kb["behavior_index"].get(entity)
        if entry:
            if entry.get("without_version_record"):
                result.append(knowledge(entity, "without_version_record", "yes", entry["source"]))
            result += [
                knowledge(entity, "changed_in", dist_id(entry["distribution"]), entry["source"]),
                knowledge(entity, "changed_in_version", entry["version"], entry["source"]),
                knowledge(entity, "change_summary", entry["summary"], entry["source"]),
                knowledge(entity, "replacement", entry["replacement"], entry["source"]),
                knowledge(entity, "action_title", entry["action_title"], entry["source"]),
            ]
        entry = kb["removed_index"].get(entity)
        if entry:
            source = entry["source"]
            result += [
                knowledge(entity, "removed_from", dist_id(entry["distribution"]), source),
                knowledge(entity, "removed_in_version", entry["version"], source),
                knowledge(entity, "replacement", entry["replacement"], source),
            ]
            result += [knowledge(entity, "removed_callable", "callable:" + target, source)
                       for target in entry.get("callables", [])]
            if entry["kind"] == "api":
                result.append(knowledge(entity, "api_module", "module:" + entry["module"], source))
            for migration in kb.get("consumer_migration", []):
                if migration["api"] != entity:
                    continue
                mid = "migration:" + canonicalize_name(migration["consumer"]) + ":" + entity
                result += [knowledge(entity, "consumer_migration", mid, migration["source"]),
                           knowledge(mid, "consumer", dist_id(migration["consumer"]), migration["source"]),
                           *[knowledge(mid, field, migration[field], migration["source"])
                             for field in ("legacy_before", "target_minimum", "target_before")]]
        entry = kb["deprecated_index"].get(entity)
        if entry:
            source = entry["source"]
            result += [
                knowledge(entity, "deprecated_in", dist_id(entry["distribution"]), source),
                knowledge(entity, "deprecated_in_version", entry["version"], source),
                knowledge(entity, "replacement", entry["replacement"], source),
            ]
            if entry.get("removal"):
                result.append(knowledge(entity, "scheduled_removal", entry["removal"], source))
        entry = kb["fixture_index"].get(entity)
        if entry:
            result.append(
                knowledge(entity, "provided_by_plugin", dist_id(entry["distribution"]),
                          entry.get("source", "pypi:" + canonicalize_name(entry["distribution"])))
            )
        entry = kb["unmaintained_index"].get(entity)
        if entry:
            result += [
                knowledge(entity, "unmaintained", entry["last"], entry["source"]),
                knowledge(entity, "replacement", entry["replacement"], entry["source"]),
            ]
        if entity.startswith("lint:") and likely_bug(entity[len("lint:"):]):
            result.append(knowledge(entity, "indicates", "possible_bug", kb["lint"]["source"]))
        if entity.startswith("module:"):
            distribution = kb["import_names"].get(entity.split(":", 1)[1])
            if distribution:
                result.append(knowledge(entity, "import_name_of", dist_id(distribution), "pypi"))
    return result


def usages_in(text: str) -> list[str]:
    """Knowledge entries for removed usages whose error message appears in the text."""
    return [
        key for key, entry in load()["removed_index"].items()
        if entry["kind"] == "usage" and entry["pattern"] in text
    ]


def source(ref: str) -> dict | None:
    """Resolve an evidence reference such as ``kb:numpy-1.24`` to its title and URL."""
    if not ref.startswith("kb:"):
        return None
    if ref.startswith("kb:pypi:"):
        name = ref[len("kb:pypi:"):]
        return {"title": f"{name} on PyPI", "url": f"https://pypi.org/project/{name}/"}
    return load()["sources"].get(ref[3:])


def cause(label: str) -> dict:
    return load()["causes"].get(label, {"label": label, "description": "", "remedy": ""})


def provider(module: str) -> str | None:
    return load()["import_names"].get(module)


def removal(entity: str) -> dict | None:
    return load()["removed_index"].get(entity)


def likely_bug(code: str) -> bool:
    """Whether a lint rule usually means the code fails or misbehaves when it runs."""
    return any(code == p or (code.startswith(p) and code[len(p):len(p) + 1].isdigit()) or
               (code.startswith(p) and p[-1].isdigit())
               for p in load()["lint"]["likely_bug"])


def lint_category(code: str) -> str:
    """Plain name of a lint rule's family, by the longest matching prefix."""
    categories = load()["lint"]["categories"]
    matches = [p for p in categories if code == p or (
        code.startswith(p) and (p[-1].isdigit() or code[len(p):len(p) + 1].isdigit())
    )]
    return categories[max(matches, key=len)] if matches else "Other checks"


def deprecation(entity: str) -> dict | None:
    return load()["deprecated_index"].get(entity)


def exception_hint(name: str) -> dict | None:
    return next((e for e in load().get("exception", []) if e["type"] == name), None)


def graph() -> dict:
    """The static knowledge graph, exported for inspection and the report."""
    kb = load()
    nodes, edges = {}, []

    def node(key, entity_type, label, **attributes):
        nodes.setdefault(
            key, {"id": key, "type": entity_type, "label": label, "attributes": attributes}
        )

    for key, row in kb["causes"].items():
        node("cause:" + key, "Cause", row["label"], description=row["description"])
    for key, row in kb["sources"].items():
        node("source:" + key, "Source", row["title"], url=row["url"])
    for row in kb.get("exception", []):
        node("exception:" + row["type"], "ExceptionType", row["type"], hint=row["hint"])
        edges += [
            {"source": "exception:" + row["type"], "relation": "may_indicate", "target": "cause:" + c}
            for c in row["candidates"]
        ]
    for module, distribution in kb["import_names"].items():
        node("module:" + module, "Module", module)
        node(dist_id(distribution), "Distribution", distribution)
        edges.append(
            {"source": "module:" + module, "relation": "import_name_of", "target": dist_id(distribution)}
        )
    for key, row in kb["removed_index"].items():
        node(key, "RemovedName", key.split(":", 1)[1], kind=row["kind"], version=row["version"],
             replacement=row["replacement"])
        node(dist_id(row["distribution"]), "Distribution", row["distribution"])
        edges += [
            {"source": key, "relation": "removed_from", "target": dist_id(row["distribution"])},
            {"source": key, "relation": "documented_in", "target": "source:" + row["source"]},
            {"source": key, "relation": "indicates", "target": "cause:version_incompatibility"},
        ]
    for key, row in kb["deprecated_index"].items():
        node(key, "DeprecatedName", key.split(":", 1)[1], version=row["version"],
             removal=row.get("removal"), replacement=row["replacement"])
        node(dist_id(row["distribution"]), "Distribution", row["distribution"])
        edges += [
            {"source": key, "relation": "deprecated_in", "target": dist_id(row["distribution"])},
            {"source": key, "relation": "documented_in", "target": "source:" + row["source"]},
        ]
    for key, row in kb["fixture_index"].items():
        node(key, "Fixture", key.split(":", 1)[1])
        node(dist_id(row["distribution"]), "Distribution", row["distribution"])
        edges.append(
            {"source": key, "relation": "provided_by_plugin", "target": dist_id(row["distribution"])}
        )
    for key, row in kb["behavior_index"].items():
        node(key, "BehaviorChange", row["summary"], version=row["version"], replacement=row["replacement"])
        node(dist_id(row["distribution"]), "Distribution", row["distribution"])
        edges += [
            {"source": key, "relation": "changed_in", "target": dist_id(row["distribution"])},
            {"source": key, "relation": "documented_in", "target": "source:" + row["source"]},
        ]
    for key, row in kb["input_index"].items():
        node(key, "InputContract", row["action_title"], guidance=row["guidance"])
        node(dist_id(row["distribution"]), "Distribution", row["distribution"])
        edges += [
            {"source": key, "relation": "validated_by", "target": dist_id(row["distribution"])},
            {"source": key, "relation": "documented_in", "target": "source:" + row["source"]},
        ]
    for key, row in kb["tool_failure_index"].items():
        node(key, "ToolFailure", row["summary"],
             **{name: row[name] for name in ("affected_from", "fixed_version", "python_from", "python_before")})
        node(dist_id(row["distribution"]), "Distribution", row["distribution"])
        edges += [
            {"source": key, "relation": "tool_distribution", "target": dist_id(row["distribution"])},
            {"source": key, "relation": "documented_in", "target": "source:" + row["source"]},
        ]
    return {
        "schema_version": 1,
        "title": kb["meta"]["title"],
        "updated": kb["meta"]["updated"],
        "nodes": list(nodes.values()),
        "edges": edges,
    }
