"""Contract and boundary checks for source-cited, mechanism-specific knowledge."""

from copy import deepcopy
from urllib.parse import urlparse

import pytest

from fixfirst import domain
from fixfirst.engine import load_rules, run
from fixfirst.models import Fact


EXPECTED = {
    "tool-failure:py-apipkg-spec": ("py", "1.10.0", "1.11.0"),
    "tool-failure:pytest-ast-str": ("pytest", "6.2.5", "7.3.2"),
}
FIELDS = {"tool_distribution", "affected_from", "fixed_version", "python_from", "python_before", "change_summary"}


def test_entries_are_independent_sourced_mechanisms_with_conservative_scope():
    index = domain.load()["tool_failure_index"]
    assert set(index) == set(EXPECTED)
    for key, (distribution, affected_from, fixed_version) in EXPECTED.items():
        row = index[key]
        assert (row["distribution"], row["affected_from"], row["fixed_version"]) == (
            distribution, affected_from, fixed_version)
        assert (row["python_from"], row["python_before"]) == ("3.12", "3.13")
        source = domain.source("kb:" + row["source"])
        assert source and source["title"]
        assert urlparse(source["url"]).hostname == "github.com"
        assert source["url"].startswith("https://github.com/pytest-dev/")
        assert "support" not in row["summary"].lower()
    assert "apipkg" in index["tool-failure:py-apipkg-spec"]["summary"]
    assert "ast.Str" in index["tool-failure:pytest-ast-str"]["summary"]


@pytest.mark.parametrize("key", EXPECTED)
def test_facts_are_available_only_for_the_explicitly_observed_mechanism(key):
    facts = domain.facts_for([key, key])
    assert len(facts) == len(FIELDS)
    assert {fact.subject for fact in facts} == {key}
    assert {fact.predicate for fact in facts} == FIELDS
    assert len({fact.fact_id for fact in facts}) == len(facts)
    row = domain.load()["tool_failure_index"][key]
    assert all(fact.status == "knowledge" and fact.evidence_refs == ["kb:" + row["source"]]
               for fact in facts)
    assert next(f.value for f in facts if f.predicate == "tool_distribution") == "dist:" + row["distribution"]
    # A package name or an unknown signature cannot activate either mechanism.
    unrelated = domain.facts_for(["dist:py", "dist:pytest", "module:_pytest", "tool-failure:unknown"])
    assert not any(f.predicate in FIELDS for f in unrelated)
    assert not any(f.predicate in {"diagnosis", "likely", "suspected", "model_suggests"} for f in facts)


@pytest.mark.parametrize("key,tool_version,python_version,expected", [
    ("py-apipkg-spec", "1.9.0", "3.12.13", False),
    ("py-apipkg-spec", "1.10.0", "3.10.20", False),
    ("py-apipkg-spec", "1.10.0", "3.11.9", False),
    ("py-apipkg-spec", "1.10.0", "3.12.0", True),
    ("py-apipkg-spec", "1.10.0", "3.12.13", True),
    ("py-apipkg-spec", "1.10.0", "3.13.0", False),
    ("py-apipkg-spec", "1.11.0", "3.12.13", False),
    ("pytest-ast-str", "6.2.4", "3.12.13", False),
    ("pytest-ast-str", "6.2.5", "3.12.13", True),
    ("pytest-ast-str", "7.0.1", "3.12.13", True),
    ("pytest-ast-str", "7.1.3", "3.12.13", True),
    ("pytest-ast-str", "7.2.2", "3.12.13", True),
    ("pytest-ast-str", "7.3.0", "3.12.13", True),
    ("pytest-ast-str", "7.3.1", "3.12.13", True),
    ("pytest-ast-str", "7.3.2", "3.12.13", False),
    ("pytest-ast-str", "7.4.4", "3.12.13", False),
    ("pytest-ast-str", "8.3.5", "3.12.13", False),
    ("pytest-ast-str", "7.3.1", "3.11.9", False),
    ("pytest-ast-str", "7.3.1", "3.13.0", False),
    ("pytest-ast-str", "unknown", "3.12.13", False),
])
def test_engine_can_apply_both_inclusive_lower_and_exclusive_upper_bounds(
        key, tool_version, python_version, expected):
    # This validates the knowledge/engine contract, not a reproduction of a tool crash.
    rules = load_rules({"rule": [{
        "id": "bounded-mechanism", "phase": "derive",
        "when": [["?i", "observed_mechanism", "?m"],
                 ["?m", "tool_distribution", "?d"], ["?d", "installed_version", "?v"],
                 ["?m", "affected_from", "?lo"], ["?m", "fixed_version", "?hi"],
                 ["?m", "python_from", "?plo"], ["?m", "python_before", "?phi"],
                 ["dist:python", "installed_version", "?p"],
                 ["test", "version_gte", "?v", "?lo"], ["test", "version_lt", "?v", "?hi"],
                 ["test", "version_gte", "?p", "?plo"], ["test", "version_lt", "?p", "?phi"]],
        "then": [["?i", "in_registered_range", "?m"]],
    }]})
    mechanism = "tool-failure:" + key
    distribution = EXPECTED[mechanism][0]
    facts = domain.facts_for([mechanism]) + [
        Fact(fact_id="mechanism", subject="issue", predicate="observed_mechanism", value=mechanism),
        Fact(fact_id="tool", subject="dist:" + distribution, predicate="installed_version", value=tool_version),
        Fact(fact_id="python", subject="dist:python", predicate="installed_version", value=python_version),
    ]
    assert bool(run(rules, facts).values("issue", "in_registered_range")) is expected


@pytest.mark.parametrize("change", [
    {"source": "missing-source"}, {"fixed_version": "not-a-version"},
    {"fixed_version": "1.10.0"}, {"affected_from": "1.12.0"},
    {"python_before": "3.12"}, {"python_from": "3.14"},
    {"fixed_version": "1.11.0rc1"}, {"fixed_version": "1.11.0.dev1"},
    {"fixed_version": "1.11.0+patched"}, {"summary": ""},
])
def test_invalid_or_unsubstantiated_table_boundaries_are_rejected(change):
    kb = domain.load()
    row = deepcopy(kb["tool_failure_index"]["tool-failure:py-apipkg-spec"])
    row.update(change)
    with pytest.raises(ValueError, match="tool failure"):
        domain._tool_failure_index([row], kb["sources"])


def test_duplicate_mechanism_ids_are_rejected():
    kb = domain.load()
    row = kb["tool_failure_index"]["tool-failure:py-apipkg-spec"]
    with pytest.raises(ValueError, match="duplicate"):
        domain._tool_failure_index([row, deepcopy(row)], kb["sources"])


def test_knowledge_graph_retains_version_scope_and_upstream_provenance():
    graph = domain.graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["source"], edge["relation"], edge["target"]) for edge in graph["edges"]}
    for key, row in domain.load()["tool_failure_index"].items():
        assert nodes[key]["type"] == "ToolFailure"
        assert nodes[key]["attributes"] == {
            field: row[field] for field in ("affected_from", "fixed_version", "python_from", "python_before")}
        assert (key, "tool_distribution", "dist:" + row["distribution"]) in edges
        assert (key, "documented_in", "source:" + row["source"]) in edges
        assert nodes["source:" + row["source"]]["attributes"]["url"]
        assert not any(source == key and relation == "indicates" for source, relation, _ in edges)
