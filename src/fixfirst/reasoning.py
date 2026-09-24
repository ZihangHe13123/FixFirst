"""Hybrid reasoning: observations + domain knowledge + classifier -> rule base -> actions.

1. evidence.py turns recorded runs into observed facts and feature vectors;
2. domain.py adds the source-attributed knowledge relevant to those facts;
3. the decision tree adds suggestions (hypotheses) for pytest failures;
4. engine.py runs the rule base (knowledge/rules.toml) phase by phase;
5. plan rules propose remedies, and verification re-runs are added here;
6. actions are ordered by goal impact, strength of support, kind and cost.
"""

from functools import lru_cache
from importlib import resources

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from . import domain, engine
from .classification import MIN_CONFIDENCE, default_model, load_model, suggest
from .evidence import environment_facts, observations, observed, project_index
from .models import GOAL_CHECKS, PROJECT_SCOPES, Action, Fact, Session
from .runner import environment_id

KIND_ORDER = {"inspect": 0, "manual_fix": 1, "rerun": 2}
VERIFY = (
    ("project", "Re-check the project declarations"),
    ("pip_check", "Re-run the dependency consistency check"),
    ("pytest", "Re-run test collection"),
    ("ruff", "Re-run the code check"),
    ("pytest_run", "Run the full test suite"),
)


@lru_cache(maxsize=1)
def rule_base() -> list[engine.Rule]:
    text = resources.files("fixfirst").joinpath("knowledge/rules.toml").read_text("utf-8")
    return engine.load_rules(tomllib.loads(text))


def forward_chain(observed_facts: list[Fact], rules=None) -> list[Fact]:
    """Run every fact-asserting phase of a rule base to a fixpoint."""
    return engine.run(rule_base() if rules is None else rules, observed_facts).facts


def cause_label(value: str) -> str:
    return domain.cause(value).get("label", value).lower()


def classifier(session: Session) -> dict | None:
    if not session.use_classifier:
        return None
    return load_model(session.model_path) if session.model_path else default_model()


def base_facts(session: Session, active, knowledge=True) -> tuple[list[Fact], dict]:
    facts = [
        observed("session", "goal", session.goal, []),
        observed("session", "goal_check", GOAL_CHECKS[session.goal], []),
    ]
    for issue in active:
        values = [("kind", issue.kind), ("stage", issue.stage), ("tool", issue.tool)]
        if issue.component:
            values.append(("component", issue.component))
        facts += [observed(issue.issue_id, p, v, issue.evidence_refs) for p, v in values]
    current = environment_id(session.target_python)
    latest_env = next((r for r in reversed(session.runs) if r.tool == "environment"), None)
    if latest_env and latest_env.environment_id == current and latest_env.verified_pass:
        facts.append(
            observed("environment", "snapshot", "available", [f"{latest_env.run_id}:stdout:1"])
        )
    project_run, _ = project_index(session)
    if project_run:
        facts.append(
            observed("project", "declarations", "available", [f"{project_run.run_id}:stdout:1"])
        )
    evidence_facts, details = observations(session, active)
    facts += evidence_facts
    mentioned = {
        f.value for f in evidence_facts if f.predicate in ("module", "api", "attribute", "kwarg", "usage")
    }
    known = domain.facts_for(mentioned) if knowledge else []
    facts += known
    distributions = (
        {"dist:python"}
        | {f.value for f in known if f.predicate == "removed_from"}
        | {f.subject for f in evidence_facts if f.predicate == "required_spec"}
        | {f.value for f in evidence_facts if f.predicate == "provided_by"}
    )
    facts += environment_facts(session, distributions)
    return facts, details


def diagnose(session: Session, knowledge=True) -> dict:
    """Rule diagnoses and evidence per open pytest issue, without planning (for experiments)."""
    current = environment_id(session.target_python)
    active = [
        i for i in session.issues
        if i.status != "resolved" and i.environment_id in (current, "unknown")
    ]
    facts, details = base_facts(session, active, knowledge)
    base = engine.run(rule_base(), facts, phases=("derive", "diagnose", "heuristic"))
    result = {}
    for issue_id, evidence in details.items():
        found = next(
            (f for f in base.facts if f.subject == issue_id and f.predicate == "diagnosis"), None
        )
        likely = next(
            (f for f in base.facts if f.subject == issue_id and f.predicate == "likely"), None
        )
        result[issue_id] = {
            "rule": found.value if found else None,
            "rule_id": found.rule_id if found else None,
            "likely": likely.value if likely else None,
            "evidence": evidence,
        }
    return result


def apply_classifier(session: Session, active, details) -> list[Fact]:
    suggestions = suggest(details, classifier(session))
    facts = []
    for issue in active:
        issue.prediction, issue.prediction_confidence = suggestions.get(issue.issue_id, (None, None))
        if issue.prediction and issue.prediction_confidence >= MIN_CONFIDENCE:
            facts.append(
                Fact(
                    fact_id=f"{issue.issue_id}:model_suggests:{issue.prediction}",
                    subject=issue.issue_id,
                    predicate="model_suggests",
                    value=issue.prediction,
                    status="hypothesis",
                    rule_id="decision-tree",
                    evidence_refs=issue.evidence_refs,
                )
            )
    return facts


def summarise_diagnoses(session: Session, active, facts: list[Fact]):
    for issue in active:
        issue.diagnosis = issue.diagnosis_source = issue.diagnosis_rule = None
        issue.prediction_note = ""
        derived = next(
            (f for f in facts if f.subject == issue.issue_id and f.predicate == "diagnosis"), None
        )
        suspected = next(
            (f for f in facts if f.subject == issue.issue_id and f.predicate == "suspected"), None
        )
        likely = next(
            (f for f in facts if f.subject == issue.issue_id and f.predicate == "likely"), None
        )
        if derived:
            issue.diagnosis, issue.diagnosis_source = derived.value, "rule"
            issue.diagnosis_rule = derived.rule_id
        elif likely:
            issue.diagnosis, issue.diagnosis_source = likely.value, "heuristic"
            issue.diagnosis_rule = likely.rule_id
        elif suspected:
            issue.diagnosis, issue.diagnosis_source = suspected.value, "model"
            issue.diagnosis_rule = suspected.rule_id
        if derived and issue.prediction and issue.prediction != derived.value:
            issue.prediction_note = (
                f"The classifier suggested {cause_label(issue.prediction)}, but rule "
                f"{derived.rule_id} concluded {cause_label(derived.value)} from the evidence; "
                "the rule's conclusion drives the advice."
            )


def evidence_rank(action_kind, issues, reasons: list[Fact]) -> int:
    if action_kind == "manual_fix" and issues and all(
        i.status == "awaiting_verification" for i in issues
    ):
        return 0
    if any(f.status == "hypothesis" for f in reasons):
        return 0
    if any(f.status == "knowledge" for f in reasons):
        return 3
    return 2 if reasons else 1


def goal_impact(session: Session, issue_ids, facts_by_key) -> int:
    affects = any((i, "affects", session.goal) in facts_by_key for i in issue_ids)
    blocks = any((i, "blocks", session.goal) in facts_by_key for i in issue_ids)
    return int(affects) + int(blocks)


def rule_actions(session: Session, base: engine.FactBase, by_id) -> list[Action]:
    keys = base.keys
    filters = {"cause": cause_label}
    actions = []
    for proposal in engine.propose(rule_base(), base):
        template, bindings = proposal.template, proposal.bindings
        issues = [by_id[i] for i in proposal.issue_ids if i in by_id]
        if "impact" in template:
            goals = template.get("impact_goals", list(GOAL_CHECKS))
            impact = template["impact"] if session.goal in goals else 0
        else:
            impact = goal_impact(session, proposal.issue_ids, keys)
        actions.append(
            Action(
                action_id=proposal.action_id,
                kind=template["kind"],
                title=engine.render(template["title"], bindings, filters=filters),
                explanation=engine.render(template["explanation"], bindings, filters=filters),
                verification=engine.render(template["verification"], bindings, filters=filters),
                check=template.get("check"),
                issue_ids=proposal.issue_ids,
                reason_refs=[f.fact_id for f in proposal.reason_facts],
                preconditions=template.get("preconditions", []),
                goal_impact=impact,
                evidence_rank=evidence_rank(template["kind"], issues, proposal.reason_facts),
                cost=template.get("cost", 2),
                cause=engine.resolve(template.get("cause"), bindings) if template.get("cause") else None,
                rule_ids=proposal.rule_ids,
                # Always the project's own interpreter, so the package lands where the checks run.
                command=[session.target_python, "-m", "pip", "install",
                         engine.render(template["pip_install"], bindings)]
                if template.get("pip_install") else [],
            )
        )
    return actions


def verification_actions(session: Session, active, facts: list[Fact]) -> list[Action]:
    """Re-run the checks that can confirm or refute changes; scope is tracked per tool."""
    current = environment_id(session.target_python)
    goal_tool = GOAL_CHECKS[session.goal]
    actions = []

    def reasons(issues):
        ids = {i.issue_id for i in issues}
        return [f.fact_id for f in facts if f.subject in ids and f.predicate == "affects"]

    for tool, title in VERIFY:
        issues = [i for i in active if i.tool == tool]
        if not issues and tool != goal_tool:
            continue
        refs = reasons(issues)
        actions.append(
            Action(
                action_id="check-" + tool,
                kind="rerun",
                title=title,
                explanation=(
                    "Only the issues this check covers are updated; others keep their state. "
                    "If nothing changed and there is no new evidence, running it again adds nothing."
                ),
                verification="Review the new check record and the status changes",
                check=tool,
                issue_ids=[i.issue_id for i in issues],
                reason_refs=refs,
                cost=3,
                goal_impact=1 if tool == goal_tool else 0,
                evidence_rank=2 if refs else 1,
            )
        )
    failed = [
        i for i in active if i.tool == "pytest_run" and i.targets and i.environment_id == current
    ]
    nodes = sorted({node for i in failed for node in i.targets})
    if nodes and len(nodes) <= 200:
        refs = reasons(failed)
        actions.append(
            Action(
                action_id="check-failed-tests",
                kind="rerun",
                title="Re-run only the related failing tests",
                explanation=(
                    "Runs just the failing test nodes already observed and keeps other issues. "
                    "When they all pass, the full suite still has to confirm the goal."
                ),
                verification=(
                    "Check setup, call and teardown for each node; skipped and xfail do not "
                    "count as fixed"
                ),
                check="pytest_run",
                issue_ids=[i.issue_id for i in failed],
                reason_refs=refs,
                cost=2,
                goal_impact=int(session.goal == "pass_tests"),
                evidence_rank=2 if refs else 1,
                targets=nodes,
            )
        )
    return actions


def order_actions(actions, facts):
    known = {f.fact_id for f in facts if f.status != "hypothesis"}
    for action in actions:
        action.blocked_reasons = [p for p in action.preconditions if p not in known]
    ordered = sorted(
        actions,
        key=lambda a: (
            bool(a.blocked_reasons),
            -a.goal_impact,
            -a.evidence_rank,
            KIND_ORDER[a.kind],
            a.cost,
            a.action_id,
        ),
    )
    for rank, action in enumerate(ordered, 1):
        action.priority = rank
    return ordered


def goal_status(session: Session, active) -> str:
    current = environment_id(session.target_python)
    target = GOAL_CHECKS[session.goal]
    last = next((r for r in reversed(session.runs) if r.tool == target), None)
    eligible = bool(
        last
        and last.source == "executed"
        and last.scope == PROJECT_SCOPES[target]
        and last.environment_id == current
    )
    status = "unknown" if not eligible else "achieved" if last.verified_pass else "blocked"
    if any(i.status == "awaiting_verification" and i.tool == target for i in active):
        status = "unknown"
    if session.goal == "pass_tests":
        if last and last.coverage_complete and last.exit_code == 0 and not last.verified_pass:
            status = "unknown"
        if status == "achieved" and any(
            i.tool == target and i.environment_id == current for i in active
        ):
            status = "unknown"
        if (
            last
            and last.source == "executed"
            and last.environment_id == current
            and last.scope == "tests:selected"
            and last.test_summary.get("failed", 0)
        ):
            status = "blocked"
    return status


def infer_and_plan(session: Session):
    current = environment_id(session.target_python)
    active = [
        i
        for i in session.issues
        if i.status != "resolved" and i.environment_id in (current, "unknown")
    ]
    facts, details = base_facts(session, active)
    facts += apply_classifier(session, active, details)
    base = engine.run(rule_base(), facts)
    session.facts = base.facts
    summarise_diagnoses(session, active, base.facts)
    by_id = {i.issue_id: i for i in active}
    actions = rule_actions(session, base, by_id) + verification_actions(session, active, base.facts)
    session.actions = order_actions(actions, base.facts)
    session.goal_status = goal_status(session, active)
