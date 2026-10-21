"""Host-side contract admission, priority and exact-edit boundaries."""
from copy import deepcopy

import pytest

from fixfirst.binding_advice import positional_only_edit, run_with_contract
from fixfirst.models import Fact
from fixfirst.reasoning import rule_base
from fixfirst.symbol_context import valid_record


def contract(**changes):
    return {
        "source": "failed_instruction_namespace", "kind": "python_binding", "operation": "CALL",
        "module": "core", "owner": "", "name": "adapt", "callee_name": "normalise",
        "file": "/project/app.py", "line": 4, "definition_file": "/project/core.py", "definition_line": 1,
        "static_namespace_checked": True, "requested_member_present": True, "dynamic": False,
        "unique": False, "candidates": [],
        "parameters": [{"name": "value", "kind": "positional_only", "required": True}],
        "positional_count": 0, "keyword_names": ["value"], "argument_types": ["int"],
        "binding_errors": {"positional_only_as_keyword": ["value"], "missing": ["value"],
                           "unexpected": [], "duplicate": [], "too_many_positional": False},
        **changes,
    }


@pytest.mark.parametrize("statement", ["return adapt(value=value)", "result = adapt(value=3)"])
def test_exact_edit_keeps_the_supplied_expression_and_call_alias(statement):
    expected = statement.replace("value=", "")
    assert positional_only_edit(statement, contract()) == expected


@pytest.mark.parametrize("statement", [
    "return adapt(value=make_value())", "return adapt(**options)", "return adapt(value=value, other=2)",
    "return different(value=value)", "return factory().adapt(value=value)",
    "return adapt(value=value) + another()", "return adapt(value=value) # comment",
])
def test_no_recipe_for_unproven_or_complex_call_shapes(statement):
    assert positional_only_edit(statement, contract()) is None


@pytest.mark.parametrize("changes", [
    {"binding_errors": {}}, {"positional_count": True}, {"keyword_names": ["value", "value"]},
    {"argument_types": []}, {"parameters": [{"name": "value", "kind": "positional_only", "required": 1}]},
    {"callee_name": "not a name"}, {"definition_line": 0},
])
def test_malformed_or_inconsistent_runtime_contract_is_rejected(changes):
    assert not valid_record(contract(**changes))


def facts_and_details():
    facts = [Fact(fact_id=f"i:{p}:{v}", subject="i", predicate=p, value=v,
                  evidence_refs=["run:probe:1", "run:probe:2"])
             for p, v in (("positional_only_repair", "value"),
                          ("call_binding_observed", "python_binding"),
                          ("call_binding_location", "app.py:4"))]
    details = {"i": {"binding_plan": {"status": "eligible_positional_only", "generated": False}}}
    return facts, details


def test_recorded_contract_overrides_classifier_hypothesis_with_traceable_cause():
    facts, details = facts_and_details()
    facts.append(Fact(fact_id="i:model", subject="i", predicate="model_suggests",
                      value="version_incompatibility", status="hypothesis"))
    result = run_with_contract(rule_base(), facts, details)
    diagnosis = next(f for f in result.facts if f.subject == "i" and f.predicate == "diagnosis")
    assert diagnosis.value == "code_defect" and diagnosis.status == "derived"
    assert diagnosis.rule_id == "runtime-binding-contract"
    assert set(diagnosis.inputs) == {f.fact_id for f in facts[:3]}
    assert diagnosis.evidence_refs == ["run:probe:1", "run:probe:2"]
    assert result.values("i", "remedy") == ["pass_existing_expression_positionally"]


@pytest.mark.parametrize("predicate,value,status", [
    ("diagnosis", "version_incompatibility", "existing_certain_diagnosis"),
    ("remedy", "replace_removed", "existing_specific_remedy"),
])
def test_certain_cause_or_specific_remedy_keeps_priority(predicate, value, status):
    facts, details = facts_and_details()
    facts.append(Fact(fact_id="i:certain", subject="i", predicate=predicate, value=value, status="derived"))
    result = run_with_contract(rule_base(), facts, details)
    assert "pass_existing_expression_positionally" not in result.values("i", "remedy")
    assert details["i"]["binding_plan"]["status"] == status


def test_missing_contract_facts_cannot_be_promoted_from_a_plan_alone():
    facts, details = facts_and_details()
    result = run_with_contract(rule_base(), facts[:1], details)
    assert not result.values("i", "diagnosis")
    assert details["i"]["binding_plan"]["status"] == "missing_contract_facts"


def test_inactive_or_ambiguous_plan_does_not_produce_the_precise_remedy():
    facts, details = facts_and_details()
    for status in ("inactive_issue", "no_value_preserving_recipe", "unproven_callee_origin"):
        row = deepcopy(details)
        row["i"]["binding_plan"]["status"] = status
        result = run_with_contract(rule_base(), facts, row)
        assert "pass_existing_expression_positionally" not in result.values("i", "remedy")
