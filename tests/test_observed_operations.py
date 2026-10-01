"""Independent checks for operation provenance and limited action adoption."""

from copy import deepcopy
import json
import sys

import pytest

from fixfirst.models import Action, Event, Fact, Issue, Run, Session
from fixfirst.observed_operations import context, generic_snapshots, projection, refine, trace


def symbol(**changes):
    return {
        "source": "failed_instruction_namespace", "kind": "instance", "operation": "LOAD_ATTR",
        "module": "sqlalchemy.engine.base", "owner": "Engine", "name": "execute",
        "file": "/project/app.py", "line": 3, "static_namespace_checked": True,
        "requested_member_present": False, "dynamic": False, "unique": False, "candidates": [],
        **changes,
    }


def join_symbol(**changes):
    return symbol(**{"kind": "builtin_call", "operation": "CALL", "module": "builtins", "owner": "str",
                     "name": "join", "requested_member_present": True, "argument_count_expected": 1,
                     "argument_count_given": 2, "argument_types": ["str", "str"], **changes})


def recorded_case(record=None, statement="return engine.execute(query)", *, collect=False):
    record = symbol() if record is None else record
    stage, nodeid = ("collect", "test_app.py") if collect else ("call", "test_app.py::test_call")
    failure = {"type": "failure", "stage": stage, "nodeid": nodeid,
               "message": f'  File "/project/app.py", line 3, in call\n    {statement}\nAttributeError: unavailable'}
    exception = {"type": "exception", "stage": stage, "nodeid": nodeid,
                 "exception_type": "CollectError" if collect else "AttributeError",
                 "symbol_observation": record}
    # The unused equal record deliberately precedes the actual cited exception.
    run = Run(run_id="run-current", tool="pytest_run", environment_id="env-one",
              records=[deepcopy(exception), failure, exception])
    refs = ["run-current:probe:1"] if collect else ["run-current:probe:1", "run-current:probe:2"]
    if collect:
        # Normal collection has exactly one wrapper; the duplicate is used by a separate negative test.
        run.records[0] = {"type": "metadata"}
    event = Event(event_id="event-current", run_id=run.run_id, tool="pytest_run", stage=stage,
                  kind="test_error", message="unavailable", evidence_refs=refs)
    issue = Issue(issue_id="issue-one", fingerprint="one", tool="pytest_run", stage=stage,
                  kind="test_error", title="unavailable", event_ids=[event.event_id], evidence_refs=refs,
                  member_keys=[nodeid], scope="tests:project", environment_id="env-one")
    session = Session(name="observed-operation-test", project_root="/project", target_python=sys.executable,
                      runs=[run], events=[event], issues=[issue])
    return session, issue, {"symbol_observation": deepcopy(record)}


def environment(**changes):
    return {"packages": [{"name": "SQLAlchemy", "version": "2.1.1"}],
            "import_distributions": {"sqlalchemy": ["SQLAlchemy"]}, **changes}


def generic_action(issue_id="issue-one", **changes):
    return Action(action_id="generic-action", kind="manual_fix", title="Inspect this failure",
                  explanation="Inspect the failed operation", verification="Run the original tests",
                  issue_ids=[issue_id], rule_ids=["P51"], evidence_rank=0, goal_impact=2,
                  cost=2, preconditions=["baseline-present"], **changes)


def planned_join(*, enabled=True, structured=False):
    session, issue, evidence = recorded_case(join_symbol(), "return ','.join(a, b)")
    session.bounded_actions, session.structured_evidence = enabled, structured
    action = generic_action()
    details = {issue.issue_id: {"operation_context": context(session, issue, evidence)}}
    return session, issue, action, details


def test_direct_record_refs_preserve_the_cited_index_even_when_an_equal_record_precedes_it():
    session, issue, evidence = recorded_case()
    result = context(session, issue, evidence)
    assert result["status"] == "observed_operation"
    assert result["symbol_record_ref"] == "run-current:probe:2"
    assert result["symbol_statement_ref"] == "run-current:probe:1"
    assert result["linked_failure_ref"] is None
    assert set(result["refs"]) == {"run-current:probe:1", "run-current:probe:2"}
    assert result["location"] == "app.py:3"
    assert result["statement"] == "return engine.execute(query)"


def test_collect_wrapper_retains_the_actual_indirect_probe_and_failure_refs():
    session, issue, evidence = recorded_case(collect=True)
    result = context(session, issue, evidence)
    assert result["status"] == "observed_operation"
    assert result["symbol_record_ref"] == "run-current:probe:2"
    assert result["symbol_statement_ref"] == result["linked_failure_ref"] == "run-current:probe:1"
    assert set(result["refs"]) == {"run-current:probe:1", "run-current:probe:2"}


def test_equal_collection_wrappers_are_ambiguous_instead_of_collapsing_by_content():
    session, issue, evidence = recorded_case(collect=True)
    session.runs[0].records.append(deepcopy(session.runs[0].records[2]))
    assert context(session, issue, evidence)["status"] == "ambiguous_record"


@pytest.mark.parametrize("changed", ["nodeid", "stage"])
def test_collect_wrapper_must_match_the_referenced_failure(changed):
    session, issue, evidence = recorded_case(collect=True)
    session.runs[0].records[2][changed] = "another"
    assert context(session, issue, evidence)["status"] == "missing_executed_record"


def test_collection_cannot_borrow_an_uncited_other_runs_matching_nodeid():
    session, issue, evidence = recorded_case(collect=True)
    other = session.runs[0].model_copy(deep=True, update={"run_id": "run-other"})
    session.runs[0].records[2] = {"type": "metadata"}
    session.runs.append(other)
    assert context(session, issue, evidence)["status"] == "missing_executed_record"


def test_carried_events_from_an_older_run_do_not_donate_operation_proof():
    session, issue, evidence = recorded_case()
    old_run = session.runs[0].model_copy(deep=True, update={"run_id": "run-old"})
    old_event = session.events[0].model_copy(deep=True, update={"event_id": "event-old", "run_id": "run-old",
                           "evidence_refs": ["run-old:probe:1", "run-old:probe:2"]})
    session.runs.append(old_run)
    session.events.append(old_event)
    issue.event_ids.append(old_event.event_id)
    assert context(session, issue, evidence)["status"] == "ambiguous_run"


@pytest.mark.parametrize("change", ["imported", "wrong_environment"])
def test_only_same_environment_executed_records_supply_operation_proof(change):
    session, issue, evidence = recorded_case()
    if change == "imported":
        session.runs[0].source = "imported"
    else:
        session.runs[0].environment_id = "env-other"
    assert context(session, issue, evidence)["status"] == "unverified_record"


@pytest.mark.parametrize("ref", ["run-current:probe:999", "run-current:probe:-1", "run-current:probe:x",
                               "run-absent:probe:1", "run-current:stdout:1"])
def test_invalid_or_text_only_refs_cannot_authorize_structured_observations(ref):
    session, issue, evidence = recorded_case()
    session.events[0].evidence_refs = [ref]
    assert context(session, issue, evidence)["status"] == "missing_executed_record"


@pytest.mark.parametrize("changes,status", [({"dynamic": True}, "dynamic_receiver"),
                                           ({"requested_member_present": True}, "member_present")])
def test_dynamic_or_present_descriptor_members_do_not_project_missing_attribute_facts(changes, status):
    session, issue, evidence = recorded_case(symbol(**changes))
    session.structured_evidence = True
    facts, result = projection(session, issue, evidence, {}, environment())
    assert result["status"] == result["projection_status"] == status
    assert not facts


def test_legacy_selected_record_must_equal_the_record_whose_refs_are_cited():
    session, issue, evidence = recorded_case()
    evidence["symbol_observation"]["name"] = "another"
    assert context(session, issue, evidence)["status"] == "record_mismatch"


@pytest.mark.parametrize("message", [
    '  File "/project/other.py", line 3, in call\n    return engine.execute(query)',
    '  File "/project/app.py", line 4, in call\n    return engine.execute(query)',
    '  File "/project/app.py", line 3, in call\n    return engine.begin(query)',
    '  File "/project/app.py", line 3, in call\n    return engine.execute(other.execute(query))',
    '  File "/project/app.py", line 3, in call\n    return engine.execute(query) # ambiguous source',
])
def test_a_wrong_or_ambiguous_source_excerpt_is_rejected(message):
    session, issue, evidence = recorded_case()
    session.runs[0].records[1]["message"] = message
    assert context(session, issue, evidence)["status"] == "ambiguous_statement"


def test_multiple_matching_failure_excerpts_remain_ambiguous_even_when_text_is_equal():
    session, issue, evidence = recorded_case()
    session.runs[0].records.append(deepcopy(session.runs[0].records[1]))
    session.events[0].evidence_refs.append("run-current:probe:3")
    assert context(session, issue, evidence)["status"] == "ambiguous_statement"


def test_history_projection_uses_the_actual_wrapper_index_for_every_new_fact():
    session, issue, evidence = recorded_case(collect=True)
    session.structured_evidence = True
    facts, result = projection(session, issue, evidence, {}, environment())
    assert result["projection_status"] == "qualified_history_projected"
    assert {(f.predicate, f.value) for f in facts} >= {
        ("attribute", "attribute:sqlalchemy.engine.base.Engine.execute"), ("module", "module:sqlalchemy")}
    assert all(set(f.evidence_refs) == {"run-current:probe:1", "run-current:probe:2"} for f in facts)
    assert all(f.status == "observed" for f in facts)
    assert not any(f.predicate in {"diagnosis", "likely", "suspected"} for f in facts)


@pytest.mark.parametrize("project,env", [
    ({}, environment(packages=[{"name": "SQLAlchemy", "version": "1.4.54"}])),
    ({}, environment(import_distributions={"sqlalchemy": ["SQLAlchemy", "other-provider"]})),
    ({"local_modules": [{"name": "sqlalchemy"}]}, environment()),
    ({"own_names": ["SQLAlchemy"]}, environment()),
    ({}, environment(import_distributions={})),
])
def test_history_projection_requires_the_existing_version_and_ownership_proof(project, env):
    session, issue, evidence = recorded_case()
    session.structured_evidence = True
    facts, result = projection(session, issue, evidence, project, env)
    assert result["projection_status"] == "operation_only_no_history"
    assert not any(f.predicate in {"attribute", "module", "diagnosis", "likely"} for f in facts)


def test_unknown_type_with_a_similar_name_is_only_an_observation():
    record = symbol(module="unknown_provider", owner="Bucket", name="appned", unique=True,
                    candidates=[{"name": "append", "relation": "swap"}])
    session, issue, evidence = recorded_case(record, "return item.appned(value)")
    session.structured_evidence = True
    facts, result = projection(session, issue, evidence, {}, {})
    assert result["projection_status"] == "operation_only_no_history"
    assert not any(f.predicate in {"attribute", "module", "diagnosis", "spelling_from", "spelling_to"}
                   for f in facts)


def test_disabled_projection_keeps_context_but_adds_no_facts():
    session, issue, evidence = recorded_case()
    facts, result = projection(session, issue, evidence, {}, environment())
    assert not facts and result["projection_status"] == "disabled"
    assert result["status"] == "observed_operation"


@pytest.mark.parametrize("source", [None, "model", "heuristic"])
@pytest.mark.parametrize("structured", [False, True])
def test_join_adoption_is_independent_of_the_model_label_and_evidence_factor(source, structured):
    session, issue, action, details = planned_join(structured=structured)
    issue.diagnosis_source = source
    issue.diagnosis = "version_incompatibility" if source else None
    issue.diagnosis_rule = "test-source" if source else None
    before_issue, before_action = issue.model_dump(), action.model_dump()
    outcome = refine(session, [action], details, {issue.issue_id: issue}, generic_snapshots([action]))
    assert outcome[issue.issue_id]["generated"]
    assert outcome[issue.issue_id]["eligibility"] == "accepted_observed_contract"
    assert issue.model_dump() == before_issue
    assert "return ','.join((a, b))" in action.explanation
    assert all(action.model_dump()[key] == before_action[key] for key in (
        "action_id", "verification", "preconditions", "cost", "goal_impact", "evidence_rank", "priority"))
    assert len(session.facts) == 1
    assert action.reason_refs == [session.facts[0].fact_id]
    assert set(session.facts[0].evidence_refs) == {"run-current:probe:1", "run-current:probe:2"}
    assert not any("model_suggests" in ref for ref in action.reason_refs)


def test_disabled_action_factor_reports_eligibility_without_mutating_actions_or_facts():
    session, issue, action, details = planned_join(enabled=False)
    before = action.model_dump()
    outcome = refine(session, [action], details, {issue.issue_id: issue}, generic_snapshots([action]))
    assert outcome[issue.issue_id]["eligibility"] == "accepted_observed_contract"
    assert not outcome[issue.issue_id]["generated"]
    assert action.model_dump() == before and not session.facts


@pytest.mark.parametrize("diagnosis", ["version_incompatibility", "code_defect"])
def test_every_certain_diagnosis_retains_priority_even_when_join_has_matching_proof(diagnosis):
    session, issue, action, details = planned_join()
    session.facts = [Fact(fact_id="certain", subject=issue.issue_id, predicate="diagnosis",
                          value=diagnosis, status="derived", rule_id="certain-test")]
    before = action.model_dump()
    outcome = refine(session, [action], details, {issue.issue_id: issue}, generic_snapshots([action]))
    assert outcome[issue.issue_id]["eligibility"] == "conflicting_rule"
    assert action.model_dump() == before and len(session.facts) == 1


@pytest.mark.parametrize("changed", ["explanation", "rule_ids", "command", "declaration_edits"])
def test_a_generic_action_changed_by_an_earlier_refiner_is_preserved(changed):
    session, issue, action, details = planned_join()
    snapshots = generic_snapshots([action])
    setattr(action, changed, {"explanation": "A more specific repair", "rule_ids": ["P51", "specific-repair"],
                             "command": ["python", "-m", "pip", "install", "example"],
                             "declaration_edits": [{"file": "requirements.txt", "after": "example==1"}]}[changed])
    before = action.model_dump()
    outcome = refine(session, [action], details, {issue.issue_id: issue}, snapshots)
    assert outcome[issue.issue_id]["eligibility"] == "specific_action_present"
    assert action.model_dump() == before and not session.facts


def test_specific_multi_issue_action_also_prevents_generic_join_refinement():
    session, issue, action, details = planned_join()
    snapshots = generic_snapshots([action])
    other = generic_action()
    other.action_id, other.rule_ids, other.issue_ids = "specific", ["P10"], [issue.issue_id, "issue-other"]
    outcome = refine(session, [action, other], details, {issue.issue_id: issue}, snapshots)
    assert outcome[issue.issue_id]["eligibility"] == "specific_action_present"
    assert not outcome[issue.issue_id]["generated"] and not session.facts


@pytest.mark.parametrize("record,statement", [
    (symbol(name="appned", unique=True, candidates=[{"name": "append", "relation": "swap"}]),
     "return item.appned(value)"),
    (symbol(kind="module", module="example", owner="", name="msort", unique=True,
            candidates=[{"name": "sort", "relation": "other"}]), "return item.msort(value)"),
    (join_symbol(argument_types=["str", "other"]), "return ','.join(a, b)"),
    (join_symbol(), "return ','.join(a(), b)"),
    (join_symbol(), "return ','.join(a, *b)"),
    (join_symbol(owner="", name="len"), "return len(a, b)"),
])
def test_bounded_actions_do_not_generalize_to_similar_names_other_builtins_or_complex_arguments(record, statement):
    session, issue, evidence = recorded_case(record, statement)
    session.bounded_actions = True
    action = generic_action()
    before = action.model_dump()
    details = {issue.issue_id: {"operation_context": context(session, issue, evidence)}}
    outcome = refine(session, [action], details, {issue.issue_id: issue}, generic_snapshots([action]))
    assert not outcome[issue.issue_id]["generated"]
    assert action.model_dump() == before and not session.facts


def test_a_real_join_failure_gets_a_limited_action_with_no_classifier_or_evidence_projection(tmp_path):
    from fixfirst.service import create_session, scan

    source = "def combine(a, b):\n    return ','.join(a, b)\n"
    original_test = "from app import combine\ndef test_combination():\n    assert combine('a', 'b') == 'a,b'\n"
    (tmp_path / "app.py").write_text(source)
    (tmp_path / "test_app.py").write_text(original_test)
    session = create_session(tmp_path, sys.executable, goal="pass_tests", bounded_actions=True)
    session.use_classifier = False
    scan(session, ["environment", "project", "pytest_run"])
    precise = [a for a in session.actions if "observed-contract:builtin_join_arguments" in a.rule_ids]
    assert len(precise) == 1
    assert "return ','.join((a, b))" in precise[0].explanation
    observed = [f for f in session.facts if f.predicate == "observed_call_contract"]
    assert len(observed) == 1
    for ref in observed[0].evidence_refs:
        run_id, _, index = ref.partition(":probe:")
        run = next(r for r in session.runs if r.run_id == run_id)
        assert run.source == "executed" and run.records[int(index)]["type"] in {"exception", "failure"}
    assert not session.structured_evidence and not session.use_classifier
    assert (tmp_path / "app.py").read_text() == source
    assert (tmp_path / "test_app.py").read_text() == original_test


def test_knowledge_disabled_diagnosis_never_consults_history_for_structured_projection(monkeypatch):
    from fixfirst.reasoning import diagnose
    from fixfirst.runner import environment_id

    session, issue, evidence = recorded_case()
    session.structured_evidence = True
    current = environment_id(session.target_python)
    issue.environment_id = current
    session.runs[0].environment_id = current
    monkeypatch.setattr("fixfirst.evidence.current_environment", lambda session: environment())

    def no_history(*args, **kwargs):
        raise AssertionError("knowledge=False must not consult interface history")

    monkeypatch.setattr("fixfirst.observed_operations.qualified_attribute_history", no_history)
    diagnosed = diagnose(session, knowledge=False)
    item = diagnosed[issue.issue_id]["evidence"]["operation_context"]
    assert item["status"] == "observed_operation"
    assert item["projection_status"] == "operation_only_history_disabled"
    facts, _ = projection(session, issue, evidence, {}, environment(), use_history=False)
    assert any(f.predicate == "operation" for f in facts)
    assert not any(f.predicate in {"attribute", "module", "diagnosis"} for f in facts)


@pytest.mark.parametrize("first_kind,first_related", [("inspect", False), ("rerun", False), ("rerun", True)])
def test_trace_distinguishes_first_for_issue_from_global_raw_plan(first_kind, first_related):
    session, issue, action, details = planned_join()
    outcomes = refine(session, [action], details, {issue.issue_id: issue}, generic_snapshots([action]))
    other_issue = issue.model_copy(deep=True, update={"issue_id": "issue-other"})
    first = Action(action_id="earlier-action", kind=first_kind, title="Earlier step", explanation="Earlier evidence",
                   verification="Check again", issue_ids=[issue.issue_id if first_related else other_issue.issue_id])
    session.actions = [first, action]
    result = trace(session, {issue.issue_id: issue, other_issue.issue_id: other_issue}, details, outcomes)
    assert result["first_action_scope"] == "raw_ordered_plan"
    assert result["global_first_action_id"] == first.action_id
    row = next(row for row in result["issues"] if row["issue_id"] == issue.issue_id)
    assert row["first_related_action_id"] == (first.action_id if first_related else action.action_id)
    assert row["bounded_action"]["became_first_for_issue"] is not first_related
    assert not row["bounded_action"]["became_first_step"]


def test_trace_reports_global_first_step_only_when_the_generated_action_is_first():
    session, issue, action, details = planned_join()
    outcomes = refine(session, [action], details, {issue.issue_id: issue}, generic_snapshots([action]))
    session.actions = [action]
    result = trace(session, {issue.issue_id: issue}, details, outcomes)
    assert result["global_first_action_id"] == action.action_id
    assert result["issues"][0]["bounded_action"]["became_first_step"]
    assert result["issues"][0]["bounded_action"]["became_first_for_issue"]


def test_public_export_recursively_redacts_nested_trace_without_mutating_private_session():
    from fixfirst.report import public_data

    session = Session(name="trace privacy", project_root="/Users/trace-user/private-project",
                      target_python="/Users/trace-user/private-project/.venv/bin/python")
    action = generic_action()
    session.actions = [action]
    session.inference_trace = {
        "first_action_scope": "raw_ordered_plan", "global_first_action_id": action.action_id,
        "issues": [{"issue_id": "issue-one", "first_related_action_id": action.action_id,
                    "operation": {"record": {"file": "/Users/trace-user/private-project/app.py"},
                                  "statement": "return ','.join('password=trace-private-value', value)",
                                  "refs": ["run-current:probe:2"]},
                    "prediction_note": "Authorization: Bearer trace-private-token",
                    "bounded_action": {"action_id": action.action_id}}],
    }
    before = session.model_dump()
    public = public_data(session)
    rendered = json.dumps(public["inference_trace"])
    assert all(private not in rendered for private in (
        "trace-user", "private-project", "trace-private-value", "trace-private-token"))
    row = public["inference_trace"]["issues"][0]
    assert row["operation"]["record"]["file"] == "<project>/app.py"
    assert row["operation"]["refs"] == ["run-current:probe:2"]
    assert row["bounded_action"]["action_id"] == public["actions"][0]["action_id"]
    assert public["inference_trace"]["global_first_action_id"] == public["actions"][0]["action_id"]
    assert session.model_dump() == before
