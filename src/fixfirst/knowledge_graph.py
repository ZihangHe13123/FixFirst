"""Typed evidence graph and bounded, deterministic queries over recorded relationships."""

from collections import deque
import re

from .models import Session, GOAL_CHECKS

NODE_TYPES = {"Goal", "Action", "Fact", "Issue", "Event", "Run", "Evidence"}
RELATIONS = {
    "recommends": ("Goal", "Action"),
    "has_open_issue": ("Goal", "Issue"),
    "evaluated_by": ("Goal", "Run"),
    "addresses": ("Action", "Issue"),
    "justified_by": ("Action", "Fact"),
    "inferred_from": ("Fact", "Fact"),
    "supported_by": ("Fact", "Evidence"),
    "has_event": ("Issue", "Event"),
    "cites": ("Event", "Evidence"),
    "observed_in": ("Evidence", "Run"),
}
RELATION_NAMES = {
    "recommends": "推荐",
    "has_open_issue": "保留待处理问题",
    "evaluated_by": "最近检查",
    "addresses": "处理",
    "justified_by": "依据事实",
    "inferred_from": "由事实推导",
    "supported_by": "由证据支持",
    "has_event": "包含事件",
    "cites": "引用证据",
    "observed_in": "记录于检查",
}


def build_graph(session: Session) -> dict:
    nodes, edges = {}, set()

    def node(key, entity_type, label, **attributes):
        nodes[key] = {"id": key, "type": entity_type, "label": label, "attributes": attributes}

    def edge(source, relation, target):
        if source in nodes and target in nodes:
            expected = RELATIONS[relation]
            if (nodes[source]["type"], nodes[target]["type"]) != expected:
                raise ValueError("知识图谱关系类型不匹配")
            edges.add((source, relation, target))

    goal = "goal:" + session.goal
    node(
        goal,
        "Goal",
        {
            "collect_tests": "恢复测试收集",
            "check_style": "通过代码检查",
            "pass_tests": "通过测试运行",
        }[session.goal],
        status=session.goal_status,
    )
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
        run_id = ref.split(":", 1)[0]
        if run_id in nodes and nodes[run_id]["type"] == "Run":
            node("evidence:" + ref, "Evidence", ref)
            edge("evidence:" + ref, "observed_in", run_id)
    for event in session.events:
        node(
            event.event_id,
            "Event",
            event.message[:240],
            stage=event.stage,
            location=event.location,
            kind=event.kind,
        )
        for ref in event.evidence_refs:
            edge(event.event_id, "cites", "evidence:" + ref)
    for issue in session.issues:
        node(
            issue.issue_id,
            "Issue",
            issue.title,
            status=issue.status,
            tool=issue.tool,
            targets=issue.targets,
            note=issue.note,
        )
        for event_id in issue.event_ids:
            edge(issue.issue_id, "has_event", event_id)
    for fact in session.facts:
        node(
            fact.fact_id,
            "Fact",
            f"{fact.predicate} = {fact.value}",
            rule=fact.rule_id,
            status=fact.status,
            subject=fact.subject,
        )
    for fact in session.facts:
        for parent in fact.inputs:
            edge(fact.fact_id, "inferred_from", parent)
        for ref in fact.evidence_refs:
            edge(fact.fact_id, "supported_by", "evidence:" + ref)
        if fact.predicate == "affects" and fact.value == session.goal:
            edge(goal, "has_open_issue", fact.subject)
    for action in session.actions:
        node(
            action.action_id,
            "Action",
            action.title,
            priority=action.priority,
            explanation=action.explanation,
            verification=action.verification,
            targets=action.targets,
            goal_impact=action.goal_impact,
        )
        if action.goal_impact > 0:
            edge(goal, "recommends", action.action_id)
        for issue_id in action.issue_ids:
            edge(action.action_id, "addresses", issue_id)
        for fact_id in action.reason_refs:
            edge(action.action_id, "justified_by", fact_id)
    latest = next((r for r in reversed(session.runs) if r.tool == GOAL_CHECKS[session.goal]), None)
    if latest:
        edge(goal, "evaluated_by", latest.run_id)
    return {
        "schema_version": 1,
        "session_id": session.session_id,
        "goal": goal,
        "ontology": {
            "entities": sorted(NODE_TYPES),
            "relations": {k: list(v) for k, v in RELATIONS.items()},
        },
        "nodes": list(nodes.values()),
        "edges": [{"source": s, "relation": r, "target": t} for s, r, t in sorted(edges)],
        "meaning": "来源与规则关系；不从文本相似度生成因果边。",
    }


def trace_graph(graph: dict, entity: str, limit=80, depth=8):
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


def query_graph(graph: dict, question: str, entity: str | None = None) -> dict:
    nodes = {n["id"]: n for n in graph["nodes"]}
    if not entity:
        matches = [
            key
            for key, value in nodes.items()
            if value["type"] in ("Action", "Issue", "Goal") and key in question
        ]
        if len(matches) == 1:
            entity = matches[0]
        elif re.search(r"(目标|阻塞|有哪些问题|待处理|goal|block)", question, re.I):
            entity = graph["goal"]
        elif re.search(
            r"(为什么|依据|why|explain).*(推荐|行动|先处理|recommend|action)|推荐.*(依据|原因)",
            question,
            re.I,
        ):
            actions = [n for n in nodes.values() if n["type"] == "Action"]
            if actions:
                entity = min(actions, key=lambda n: n["attributes"]["priority"])["id"]
    if entity not in nodes:
        return {
            "supported": False,
            "answer": "未匹配到图谱实体。可问“当前目标有哪些问题”“为什么推荐这个行动”，或附上 action / issue 编号查询依据。",
            "nodes": [],
            "edges": [],
            "paths": [],
        }
    root = nodes[entity]
    trace = trace_graph(graph, entity)
    lines = [f"{root['type']}：{root['label']}（{entity}）"]
    if root["type"] == "Action":
        lines += [
            root["attributes"]["explanation"],
            "验证方法：" + root["attributes"]["verification"],
        ]
    elif root["type"] == "Goal":
        lines.append("记录中的目标状态：" + root["attributes"]["status"])
        issues = [
            nodes[e["target"]]
            for e in graph["edges"]
            if e["source"] == entity and e["relation"] == "has_open_issue"
        ]
        lines += [f"• {n['label']} [{n['attributes']['status']}] {n['id']}" for n in issues]
        if not issues:
            lines.append("图谱没有该目标关联的已知问题；仍需检查完成证据判断是否通过。")
    elif root["type"] == "Issue":
        lines.append("问题状态：" + root["attributes"]["status"])
    lines.append("证据路径：")
    for path in trace["paths"][:8]:
        if not path:
            lines.append(entity + " 是检查记录本身")
            continue
        lines.append(
            " → ".join(
                [
                    path[0]["source"],
                    *[RELATION_NAMES[e["relation"]] + "：" + e["target"] for e in path],
                ]
            )
        )
    if not trace["paths"]:
        lines.append("尚无可追溯到检查记录的证据；这是待执行验证或缺少来源。")
    lines.append("以上是记录与推理的关联，不表示已经证实共同根因。")
    return {"supported": True, "entity": entity, "answer": "\n".join(lines), **trace}
