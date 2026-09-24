"""Typed evidence graph for a session, and bounded deterministic queries over it.

The session graph links the goal, actions, issues, diagnosed causes, the facts and rules
behind them, and the evidence in recorded runs or cited knowledge sources. Queries map a
question (English or Chinese) to one of a few supported intents and answer by breadth-first
traversal, or by looking up the static domain graph (domain.py). Nothing here asks a
language model; unsupported questions say so.
"""

from collections import deque
import re

from . import domain
from .models import GOAL_CHECKS, Session

NODE_TYPES = {"Goal", "Action", "Fact", "Issue", "Event", "Run", "Evidence", "Cause", "Rule", "Source"}
RELATIONS = {
    "recommends": ("Goal", "Action"),
    "has_open_issue": ("Goal", "Issue"),
    "evaluated_by": ("Goal", "Run"),
    "addresses": ("Action", "Issue"),
    "justified_by": ("Action", "Fact"),
    "proposed_by": ("Action", "Rule"),
    "diagnosed_as": ("Issue", "Cause"),
    "suspected_as": ("Issue", "Cause"),
    "inferred_from": ("Fact", "Fact"),
    "derived_by": ("Fact", "Rule"),
    "supported_by": ("Fact", "Evidence"),
    "documented_in": ("Fact", "Source"),
    "has_event": ("Issue", "Event"),
    "cites": ("Event", "Evidence"),
    "observed_in": ("Evidence", "Run"),
}
RELATION_NAMES = {
    "recommends": "recommends",
    "has_open_issue": "has open issue",
    "evaluated_by": "last checked by",
    "addresses": "addresses",
    "justified_by": "justified by",
    "proposed_by": "proposed by rule",
    "diagnosed_as": "diagnosed as",
    "suspected_as": "suspected (model) as",
    "inferred_from": "inferred from",
    "derived_by": "derived by rule",
    "supported_by": "supported by",
    "documented_in": "documented in",
    "has_event": "has event",
    "cites": "cites",
    "observed_in": "observed in",
}
GOAL_NAMES = {
    "collect_tests": "Restore test collection",
    "check_style": "Pass the code check",
    "pass_tests": "Pass the test suite",
}


def build_graph(session: Session) -> dict:
    from .reasoning import rule_base

    rules = {r.rule_id: r for r in rule_base()}
    nodes, edges = {}, set()

    def node(key, entity_type, label, **attributes):
        nodes[key] = {"id": key, "type": entity_type, "label": label, "attributes": attributes}

    def edge(source, relation, target):
        if source in nodes and target in nodes:
            if (nodes[source]["type"], nodes[target]["type"]) != RELATIONS[relation]:
                raise ValueError("Knowledge graph relation has the wrong entity types")
            edges.add((source, relation, target))

    def rule_node(rule_id):
        key = "rule:" + rule_id
        if rule_id in rules and key not in nodes:
            rule = rules[rule_id]
            node(key, "Rule", f"{rule_id} · {rule.description}", phase=rule.phase, source=rule.source)
        return key

    goal = "goal:" + session.goal
    node(goal, "Goal", GOAL_NAMES[session.goal], status=session.goal_status)
    for run in session.runs:
        node(
            run.run_id,
            "Run",
            f"{run.tool} · {run.started_at}",
            tool=run.tool,
            status=run.status,
            source=run.source,
            scope=run.scope,
            exit_code=run.exit_code,
            verified_pass=run.verified_pass,
            targets=run.targets,
            summary=run.test_summary,
        )
    refs = {ref for e in session.events for ref in e.evidence_refs}
    refs.update(ref for f in session.facts for ref in f.evidence_refs)
    for ref in sorted(refs):
        cited = domain.source(ref)
        if cited:
            node("source:" + ref[3:], "Source", cited["title"], url=cited["url"])
            continue
        run_id = ref.split(":", 1)[0]
        if run_id in nodes and nodes[run_id]["type"] == "Run":
            node("evidence:" + ref, "Evidence", ref)
            edge("evidence:" + ref, "observed_in", run_id)
    for event in session.events:
        node(event.event_id, "Event", event.message[:240], stage=event.stage,
             location=event.location, kind=event.kind)
        for ref in event.evidence_refs:
            edge(event.event_id, "cites", "evidence:" + ref)
    for issue in session.issues:
        node(issue.issue_id, "Issue", issue.title, status=issue.status, tool=issue.tool,
             targets=issue.targets, note=issue.note, diagnosis=issue.diagnosis,
             diagnosis_source=issue.diagnosis_source, prediction=issue.prediction,
             prediction_confidence=issue.prediction_confidence)
        for event_id in issue.event_ids:
            edge(issue.issue_id, "has_event", event_id)
    for fact in session.facts:
        node(fact.fact_id, "Fact", f"{fact.subject} {fact.predicate} {fact.value}",
             rule=fact.rule_id, status=fact.status, subject=fact.subject, predicate=fact.predicate)
    for fact in session.facts:
        for parent in fact.inputs:
            edge(fact.fact_id, "inferred_from", parent)
        if fact.rule_id and fact.rule_id in rules:
            edge(fact.fact_id, "derived_by", rule_node(fact.rule_id))
        for ref in fact.evidence_refs:
            edge(fact.fact_id, "documented_in" if ref.startswith("kb:") else "supported_by",
                 ("source:" + ref[3:]) if ref.startswith("kb:") else ("evidence:" + ref))
        if fact.predicate == "affects" and fact.value == session.goal:
            edge(goal, "has_open_issue", fact.subject)
        if fact.predicate in ("diagnosis", "suspected") and fact.subject in nodes:
            cause = domain.cause(fact.value)
            node("cause:" + fact.value, "Cause", cause.get("label", fact.value),
                 description=cause.get("description", ""))
            edge(fact.subject, "diagnosed_as" if fact.predicate == "diagnosis" else "suspected_as",
                 "cause:" + fact.value)
    for action in session.actions:
        node(action.action_id, "Action", action.title, priority=action.priority,
             explanation=action.explanation, verification=action.verification,
             targets=action.targets, goal_impact=action.goal_impact, cause=action.cause)
        if action.goal_impact > 0:
            edge(goal, "recommends", action.action_id)
        for issue_id in action.issue_ids:
            edge(action.action_id, "addresses", issue_id)
        for fact_id in action.reason_refs:
            edge(action.action_id, "justified_by", fact_id)
        for rule_id in action.rule_ids:
            edge(action.action_id, "proposed_by", rule_node(rule_id))
    latest = next((r for r in reversed(session.runs) if r.tool == GOAL_CHECKS[session.goal]), None)
    if latest:
        edge(goal, "evaluated_by", latest.run_id)
    return {
        "schema_version": 2,
        "session_id": session.session_id,
        "goal": goal,
        "ontology": {
            "entities": sorted(NODE_TYPES),
            "relations": {k: list(v) for k, v in RELATIONS.items()},
        },
        "nodes": list(nodes.values()),
        "edges": [{"source": s, "relation": r, "target": t} for s, r, t in sorted(edges)],
        "meaning": "Provenance and rule relations; similarity never creates a causal edge.",
    }


def trace_graph(graph: dict, entity: str, limit=120, depth=10):
    """Breadth-first traversal from an entity, keeping every path that reaches a Run."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    adjacency = {}
    for edge in graph["edges"]:
        adjacency.setdefault(edge["source"], []).append(edge)
    queue, visited, paths = deque([(entity, [], 0)]), set(), []
    while queue and len(visited) < limit:
        at, path, level = queue.popleft()
        if at in visited or at not in nodes:
            continue
        visited.add(at)
        if nodes[at]["type"] == "Run":
            paths.append(path)
        if level < depth:
            queue.extend((e["target"], path + [e], level + 1) for e in adjacency.get(at, []))
    return {
        "nodes": [n for n in graph["nodes"] if n["id"] in visited],
        "edges": [e for e in graph["edges"] if e["source"] in visited and e["target"] in visited],
        "paths": paths,
        "bounded": bool(queue),
    }


INTENTS = [
    ("unchecked", r"(not (been )?(checked|verified)|unchecked|unverified|pending|still to verify|未检查|待验证|没验证|还没.*(检查|验证))"),
    ("provider", r"(which (package|distribution)|what (package|distribution)|provides?|install .* for|哪个包|提供)"),
    ("removed", r"(removed|was .* dropped|replace(ment|d)?|deprecated|移除|删除了|替代|弃用)"),
    ("cause", r"(root cause|cause|diagnos|why (did|does) .* fail|原因|根因|诊断)"),
    ("goal", r"(goal|block|what is left|remaining|目标|阻塞|有哪些问题|待处理)"),
    ("why", r"(why|explain|reason|justif|为什么|依据|推荐.*(原因|理由))"),
]


def unsupported(message=None):
    return {
        "supported": False,
        "answer": message
        or (
            "This question is outside what FixFirst can answer from its graph. Try: 'why is "
            "this action recommended', 'what is the root cause', 'what blocks the goal', 'what "
            "has not been verified', 'which package provides cv2' or 'was numpy.float removed'."
        ),
        "nodes": [],
        "edges": [],
        "paths": [],
    }


def names_in(question: str) -> list[str]:
    return re.findall(r"[A-Za-z_][\w.]*", question)


def domain_answer(intent: str, question: str) -> dict | None:
    for name in names_in(question):
        if intent == "provider" and domain.provider(name):
            dist = domain.provider(name)
            return {
                "supported": True,
                "entity": "module:" + name,
                "answer": f"The import name {name} is provided by the PyPI distribution {dist}. "
                f"Install it into the target interpreter (python -m pip install {dist}) and "
                "declare it in the project. Source: knowledge base (PyPI project pages).",
                "nodes": [], "edges": [], "paths": [],
            }
        if intent == "removed":
            entry = next(
                (domain.removal(prefix + name) for prefix in ("api:", "module:", "attribute:", "kwarg:")
                 if domain.removal(prefix + name)),
                None,
            )
            if entry:
                source = domain.load()["sources"][entry["source"]]
                owner = "Python" if entry["distribution"] == "python" else entry["distribution"]
                return {
                    "supported": True,
                    "entity": entry["id"],
                    "answer": f"{name} was removed in {owner} {entry['version']}. Use "
                    f"{entry['replacement']} instead. Source: {source['title']} ({source['url']}).",
                    "nodes": [], "edges": [], "paths": [],
                }
    return None


def query_graph(graph: dict, question: str, entity: str | None = None) -> dict:
    nodes = {n["id"]: n for n in graph["nodes"]}
    intent = None
    if not entity:
        matches = [
            key for key, value in nodes.items()
            if value["type"] in ("Action", "Issue", "Goal", "Run") and key in question
        ]
        if len(matches) == 1:
            entity = matches[0]
        else:
            intent = next((name for name, pattern in INTENTS if re.search(pattern, question, re.I)), None)
            if intent in ("provider", "removed"):
                return domain_answer(intent, question) or unsupported(
                    "The knowledge base has no entry for the name in this question."
                )
            if intent == "goal":
                entity = graph["goal"]
            elif intent in ("why", "cause", "unchecked"):
                ranked = sorted(
                    (n for n in nodes.values() if n["type"] == "Action"),
                    key=lambda n: n["attributes"]["priority"],
                )
                if intent == "why" and ranked:
                    entity = ranked[0]["id"]
                elif intent == "cause":
                    issues = [n for n in nodes.values() if n["type"] == "Issue"
                              and n["attributes"]["status"] != "resolved"]
                    entity = issues[0]["id"] if issues else None
                else:
                    pending = [n for n in nodes.values() if n["type"] == "Issue"
                               and n["attributes"]["status"] in ("not_observed", "awaiting_verification", "unknown")]
                    lines = ["Issues whose fix has not been verified by a completed check:"]
                    lines += [f"• {n['label']} [{n['attributes']['status']}] {n['id']}" for n in pending]
                    if not pending:
                        lines = ["Every recorded issue is either still failing or verified as resolved."]
                    return {"supported": True, "entity": graph["goal"], "answer": "\n".join(lines),
                            "nodes": pending, "edges": [], "paths": []}
    if entity not in nodes:
        return unsupported()
    root = nodes[entity]
    trace = trace_graph(graph, entity)
    lines = [f"{root['type']}: {root['label']} ({entity})"]
    attributes = root["attributes"]
    if root["type"] == "Action":
        lines += [attributes["explanation"], "How to verify: " + attributes["verification"]]
        rules = [nodes[e["target"]]["label"] for e in graph["edges"]
                 if e["source"] == entity and e["relation"] == "proposed_by"]
        lines += [f"Proposed by rule {label}" for label in rules]
    elif root["type"] == "Goal":
        lines.append("Recorded goal status: " + attributes["status"])
        issues = [nodes[e["target"]] for e in graph["edges"]
                  if e["source"] == entity and e["relation"] == "has_open_issue"]
        lines += [f"• {n['label']} [{n['attributes']['status']}] {n['id']}" for n in issues]
        if not issues:
            lines.append("No known issue is linked to this goal; a completed check still decides whether it passes.")
    elif root["type"] == "Issue":
        lines.append("Status: " + attributes["status"])
        if attributes.get("diagnosis"):
            cause = domain.cause(attributes["diagnosis"])
            how = "a diagnosis rule" if attributes.get("diagnosis_source") == "rule" else "the classifier (unconfirmed)"
            lines.append(f"Root cause: {cause.get('label', attributes['diagnosis'])}, from {how}. {cause.get('description', '')}")
            diagnoses = {
                n["id"] for n in nodes.values()
                if n["type"] == "Fact" and n["attributes"]["subject"] == entity
                and n["attributes"]["predicate"] in ("diagnosis", "suspected")
            }
            lines += [
                "Rule: " + nodes[e["target"]]["label"] for e in graph["edges"]
                if e["source"] in diagnoses and e["relation"] == "derived_by"
            ]
        else:
            lines.append("Root cause: not identified from the recorded evidence.")
    lines.append("Evidence paths:")
    for path in trace["paths"][:8]:
        if not path:
            lines.append(entity + " is itself a check record")
            continue
        lines.append(" → ".join([path[0]["source"], *[RELATION_NAMES[e["relation"]] + ": " + e["target"] for e in path]]))
    if not trace["paths"]:
        lines.append("No path reaches a recorded check yet: verification is pending or the source is missing.")
    sources = [n for n in trace["nodes"] if n["type"] == "Source"]
    if sources:
        lines.append("Knowledge sources: " + "; ".join(f"{n['label']} ({n['attributes']['url']})" for n in sources))
    lines.append("These links record evidence and rule inferences; they do not prove a shared root cause.")
    return {"supported": True, "entity": entity, "answer": "\n".join(lines), **trace}
