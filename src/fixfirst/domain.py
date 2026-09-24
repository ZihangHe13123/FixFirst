"""Curated domain knowledge graph: import names, removed APIs, causes and their sources.

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

from .models import Fact

KINDS = {"module", "api", "attribute", "kwarg", "usage"}


def dist_id(name: str) -> str:
    return "dist:python" if name.lower() == "python" else "dist:" + canonicalize_name(name)


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
        entry = kb["removed_index"].get(entity)
        if entry:
            source = entry["source"]
            result += [
                knowledge(entity, "removed_from", dist_id(entry["distribution"]), source),
                knowledge(entity, "removed_in_version", entry["version"], source),
                knowledge(entity, "replacement", entry["replacement"], source),
            ]
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
    return load()["sources"].get(ref[3:])


def cause(label: str) -> dict:
    return load()["causes"].get(label, {"label": label, "description": "", "remedy": ""})


def provider(module: str) -> str | None:
    return load()["import_names"].get(module)


def removal(entity: str) -> dict | None:
    return load()["removed_index"].get(entity)


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
    return {
        "schema_version": 1,
        "title": kb["meta"]["title"],
        "updated": kb["meta"]["updated"],
        "nodes": list(nodes.values()),
        "edges": edges,
    }
