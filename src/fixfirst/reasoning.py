"""Forward chaining with provenance, then stable goal-sensitive action ordering."""

from .models import Action, Fact, Session
from .runner import environment_id

# Conditions and consequences operate on (predicate, value), keeping issue subjects separate.
RULES = [
    ("R01", ("kind", "import_failure"), ("needs", "environment_check")),
    ("R02", ("kind", "dependency_conflict"), ("needs", "dependency_review")),
    ("R03", ("stage", "collect"), ("affects", "collect_tests")),
    ("R04", ("stage", "lint"), ("affects", "check_style")),
    ("R05", ("kind", "explicit_config_missing"), ("needs", "config_review")),
    ("R06", ("needs", "dependency_review"), ("requires", "verify_environment")),
    ("R07", ("requires", "verify_environment"), ("needs", "environment_check")),
    ("R08", ("kind", "install_failure"), ("needs", "install_review")),
    ("R09", ("kind", "tool_failure"), ("needs", "tool_review")),
    ("R10", ("kind", "style_issue"), ("needs", "style_review")),
    ("R11", ("kind", "code_check"), ("needs", "code_review")),
]


def forward_chain(observations: list[Fact], rules=None) -> list[Fact]:
    rules = RULES if rules is None else rules
    facts = {(f.subject, f.predicate, f.value): f for f in observations}
    changed = True
    while changed:
        changed = False
        for rule_id, condition, consequence in rules:
            for source in list(facts.values()):
                if (source.predicate, source.value) != condition:
                    continue
                key = (source.subject, *consequence)
                if key in facts:
                    continue
                facts[key] = Fact(
                    fact_id=f"{source.subject}:{consequence[0]}:{consequence[1]}",
                    subject=source.subject,
                    predicate=consequence[0],
                    value=consequence[1],
                    status="derived",
                    rule_id=rule_id,
                    inputs=[source.fact_id],
                    evidence_refs=source.evidence_refs,
                )
                changed = True
    return list(facts.values())


def order_actions(actions, facts):
    fact_ids = {f.fact_id for f in facts if f.status != "hypothesis"}
    for action in actions:
        action.blocked_reasons = [p for p in action.preconditions if p not in fact_ids]
    ordered = sorted(
        actions,
        key=lambda a: (
            bool(a.blocked_reasons),
            -a.goal_impact,
            -a.evidence_rank,
            a.cost,
            a.action_id,
        ),
    )
    for rank, action in enumerate(ordered, 1):
        action.priority = rank
    return ordered


def infer_and_plan(session: Session):
    active = [i for i in session.issues if i.status != "resolved"]
    observations = []
    for issue in active:
        for predicate, value in (("kind", issue.kind), ("stage", issue.stage)):
            observations.append(
                Fact(
                    fact_id=f"{issue.issue_id}:{predicate}:{value}",
                    subject=issue.issue_id,
                    predicate=predicate,
                    value=value,
                    evidence_refs=issue.evidence_refs,
                )
            )
    latest_env = next((r for r in reversed(session.runs) if r.tool == "environment"), None)
    if latest_env and latest_env.environment_id != environment_id(session.target_python):
        latest_env = None
    if latest_env and latest_env.verified_pass:
        observations.append(
            Fact(
                fact_id="environment:available",
                subject="environment",
                predicate="snapshot",
                value="available",
                evidence_refs=[f"{latest_env.run_id}:stdout:1"],
            )
        )
    session.facts = forward_chain(observations)
    actions = []
    grouped = {}
    for issue in active:
        grouped.setdefault(issue.kind, []).append(issue)

    def add(
        action_id,
        kind,
        title,
        explanation,
        verification,
        issues,
        check=None,
        cost=1,
        preconditions=None,
        impact=None,
        predicate="needs",
    ):
        ids = [i.issue_id for i in issues]
        evidence = [
            f.fact_id for f in session.facts if f.subject in ids and f.predicate == predicate
        ]
        actions.append(
            Action(
                action_id=action_id,
                kind=kind,
                title=title,
                explanation=explanation,
                verification=verification,
                issue_ids=ids,
                reason_refs=evidence,
                check=check,
                cost=cost,
                preconditions=preconditions or [],
                goal_impact=impact
                if impact is not None
                else int(
                    any(
                        (i.tool == "pytest" and session.goal == "collect_tests")
                        or (i.tool == "ruff" and session.goal == "check_style")
                        for i in issues
                    )
                ),
                evidence_rank=2 if evidence else 1,
            )
        )

    imports = grouped.get("import_failure", [])
    dependencies = grouped.get("dependency_conflict", [])
    if imports or dependencies:
        affected = imports + dependencies
        if not latest_env or not latest_env.verified_pass:
            add(
                "inspect-environment",
                "inspect",
                "先核对当前 Python 环境",
                "导入或依赖检查失败，需要先取得当前解释器和已安装包信息。尚不能断言包未安装或环境选错。",
                "检查快照中的解释器路径与包信息，再决定是否手动调整",
                affected,
                "environment",
                impact=2 if session.goal == "collect_tests" else 0,
            )
        else:
            add(
                "review-import",
                "manual_fix",
                "核对导入路径与依赖声明",
                "已取得当前环境快照。将它与安装时使用的环境核对；import 名可能不同于发行包名，也可能是项目自己的模块。根据证据手动处理。",
                "处理后重新运行测试收集；pip check 通过不代表 import 一定成功",
                affected,
                preconditions=["environment:available"],
                cost=2,
            )
    for kind, title, explanation in [
        (
            "dependency_conflict",
            "检查依赖约束冲突",
            "依据 pip 报告核对项目声明和已安装版本，手动处理；系统不会猜测任意版本号或自动安装。",
        ),
        (
            "explicit_config_missing",
            "补齐明确缺失的配置",
            "按错误指出的配置键和项目说明手动设置。报告只记录缺失键，不索取密钥值。",
        ),
        (
            "install_failure",
            "查看安装失败的具体阶段",
            "安装失败可能来自网络、构建工具或包约束，需要结合原始日志核对，不能一概认定版本冲突。",
        ),
        (
            "tool_failure",
            "检查工具是否可用或是否中断",
            "本次检查没有提供有效结果。核对目标环境、工具及原始输出后，再运行相应检查。",
        ),
        (
            "style_issue",
            "处理代码风格问题",
            "按文件位置和规则码手动修改，再运行代码检查。格式消息数量不决定恢复测试收集的优先级。",
        ),
        (
            "code_check",
            "检查代码诊断",
            "这是代码检查器报告的诊断，可能涉及未定义名称等问题，不能全部称作格式问题。",
        ),
        (
            "other_unknown",
            "补充信息或人工排查",
            "当前输入没有足够证据支持自动判断，请从原文核对；业务逻辑修复超出首版范围。",
        ),
    ]:
        issues = grouped.get(kind, [])
        if issues:
            add(
                "review-" + kind,
                "manual_fix",
                title,
                explanation,
                "处理后重新运行对应范围的检查",
                issues,
                cost=2,
            )
    for tool, title in (
        ("pip_check", "重新检查依赖一致性"),
        ("pytest", "重新验证测试收集"),
        ("ruff", "重新检查代码"),
    ):
        issues = [i for i in active if i.tool == tool]
        if (
            issues
            or (tool == "pytest" and session.goal == "collect_tests")
            or (tool == "ruff" and session.goal == "check_style")
        ):
            add(
                "check-" + tool,
                "rerun",
                title,
                "只更新本次检查覆盖的问题；其他问题保留。若未做改动且没有新证据，无需反复运行同一检查。",
                "查看新的检查记录和状态变化",
                issues,
                tool,
                cost=3,
                impact=1
                if (tool == "pytest" and session.goal == "collect_tests")
                or (tool == "ruff" and session.goal == "check_style")
                else 0,
                predicate="affects",
            )
    session.actions = order_actions(actions, session.facts)
    target = "pytest" if session.goal == "collect_tests" else "ruff"
    last = next((r for r in reversed(session.runs) if r.tool == target), None)
    expected_scope = "collect:project" if target == "pytest" else "lint:project"
    eligible = bool(
        last
        and last.source == "executed"
        and last.scope == expected_scope
        and last.environment_id == environment_id(session.target_python)
    )
    session.goal_status = (
        "unknown" if not eligible else "achieved" if last.verified_pass else "blocked"
    )
    if any(i.status == "awaiting_verification" and i.tool == target for i in active):
        session.goal_status = "unknown"
