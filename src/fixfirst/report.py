import json
from pathlib import Path
import re
import shlex
import sys

from jinja2 import Environment, PackageLoader, select_autoescape

from .models import Session
from .runner import redact
from .storage import atomic_write
from .knowledge_graph import build_graph, query_graph

GOALS = {
    "collect_tests": "恢复测试收集",
    "check_style": "通过代码检查",
    "pass_tests": "通过测试运行",
}
STATES = {
    "open": "仍存在",
    "resolved": "已验证解决",
    "not_observed": "本次未检查",
    "awaiting_verification": "待验证",
    "unknown": "信息不足",
}
TOOL_NAMES = {
    "environment": "环境快照",
    "pip_check": "依赖一致性",
    "pip_install": "安装日志",
    "pytest": "测试收集",
    "pytest_run": "测试执行",
    "ruff": "代码检查",
}


def public_data(session: Session):
    replacements = [(session.project_root, "<project>"), (session.target_python, "<python>")]

    def clean(value):
        if isinstance(value, str):
            for private, alias in replacements:
                value = value.replace(private, alias)
            value = re.sub(r"/(?:Users|home)/[^/\s]+", "<home>", value)
            value = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", "<home>", value)
            return redact(value)
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value

    data = clean(session.model_dump())
    data["model_path"] = "<local-model>" if session.model_path else None
    data["sbert_model"] = "<local-model>" if session.sbert_model else None
    return data


def render(session: Session, store_root: Path, output: Path, public=False):
    env = Environment(
        loader=PackageLoader("fixfirst", "templates"), autoescape=select_autoescape(["html"])
    )
    data = public_data(session) if public else session.model_dump()
    graph = build_graph(Session.model_validate(data))
    views = [
        query_graph(graph, "依据", n["id"])
        for n in graph["nodes"]
        if n["type"] in ("Goal", "Action", "Issue")
    ]
    counts = {state: sum(i.status == state for i in session.issues) for state in STATES}
    command_prefix = shlex.join([sys.executable, "-m", "fixfirst", "--store", str(store_root)])
    commands = {}
    for action in session.actions:
        if action.check and not action.blocked_reasons and not public:
            commands[action.action_id] = (
                f"{command_prefix} run {session.session_id} {action.action_id}"
            )
    latest = {}
    for run in data["runs"]:
        latest[run["tool"]] = run
    text = env.get_template("report.html").render(
        session=data,
        goal_name=GOALS[session.goal],
        states=STATES,
        tools=TOOL_NAMES,
        counts=counts,
        commands=commands,
        latest=latest,
        public=public,
        graph=graph,
        graph_views=views,
    )
    atomic_write(output, text)
    atomic_write(output.with_suffix(".json"), json.dumps(data, ensure_ascii=False, indent=2))
    atomic_write(output.with_suffix(".graph.json"), json.dumps(graph, ensure_ascii=False, indent=2))
    return output
