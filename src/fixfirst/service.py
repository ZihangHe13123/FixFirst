from pathlib import Path
import os

from .classification import classify
from .grouping import group_events, digest, member_key
from .models import Run, Session, now, GOAL_CHECKS
from .parsers import parse
from .reasoning import infer_and_plan
from .runner import collect, environment_id, redact, MAX_OUTPUT, DEFAULT_CHECKS, validate_targets


def create_session(
    project, python, name=None, goal="collect_tests", grouping="tfidf", model=None, sbert_model=None
):
    root = Path(project).expanduser().resolve()
    interpreter = Path(os.path.abspath(os.path.expanduser(python)))
    if not root.is_dir():
        raise ValueError("项目目录不存在")
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise ValueError("Python 解释器不存在或不可执行")
    if grouping == "sbert" and not sbert_model:
        raise ValueError("SBERT 需要本地模型路径")
    if model:
        model = str(Path(model).expanduser().resolve())
        if not Path(model).is_file():
            raise ValueError("分类模型文件不存在")
    if sbert_model:
        sbert_model = str(Path(sbert_model).expanduser().resolve())
        if not Path(sbert_model).is_dir():
            raise ValueError("语义模型目录不存在")
    return Session(
        name=name or root.name,
        project_root=str(root),
        target_python=str(interpreter),
        goal=goal,
        grouping=grouping,
        model_path=model,
        sbert_model=sbert_model,
    )


def ingest(session: Session, runs: list[Run]):
    fresh = []
    event_batch = []
    for run in runs:
        events = parse(run)
        event_batch.extend(events)
        fresh.extend(
            group_events(events, run, session.grouping, session.threshold, session.sbert_model)
        )
    classify(fresh, session.model_path)
    updated_tools = {r.tool for r in runs}
    previous = session.issues
    by_id = {i.issue_id: i for i in previous}
    claimed = set()
    for issue in fresh:
        # The same text in different interpreters must not overwrite the prior environment.
        if issue.issue_id in by_id and by_id[issue.issue_id].environment_id != issue.environment_id:
            issue.issue_id = "issue-" + digest(issue.fingerprint + issue.environment_id)
        if issue.tool != "pytest_run" or not issue.targets:
            continue
        candidates = [
            old
            for old in previous
            if old.issue_id not in claimed
            and (old.tool, old.environment_id, old.kind, old.stage, old.component)
            == (issue.tool, issue.environment_id, issue.kind, issue.stage, issue.component)
            and set(old.targets) & set(issue.targets)
        ]
        if len(candidates) != 1:
            continue
        old = candidates[0]
        issue.issue_id, issue.first_seen = old.issue_id, old.first_seen
        claimed.add(old.issue_id)
        passed = {
            node
            for run in runs
            if run.tool == issue.tool
            and run.environment_id == issue.environment_id
            and run.source == "executed"
            for node in run.passed_nodes
        }
        represented = {
            node
            for other in fresh
            if other.tool == issue.tool
            and other.environment_id == issue.environment_id
            and other.kind == issue.kind
            and other.stage == issue.stage
            and other.component == issue.component
            for node in other.targets
        }
        pending = set(old.targets) - passed - represented if old.status != "resolved" else set()
        carried = [
            e for e in session.events if e.event_id in old.event_ids and e.location in pending
        ]
        if carried:
            issue.targets = sorted(set(issue.targets) | pending)
            issue.event_ids += [e.event_id for e in carried]
            issue.evidence_refs = sorted(
                set(issue.evidence_refs) | {ref for e in carried for ref in e.evidence_refs}
            )
            issue.member_keys = sorted(set(issue.member_keys) | {member_key(e) for e in carried})
            issue.note = f"本轮只重新观察部分成员；{len(pending)} 个节点保留先前未验证证据"
    fresh_ids = {i.issue_id for i in fresh}
    changes = []
    for issue in fresh:
        if issue.issue_id in by_id:
            old = by_id[issue.issue_id]
            issue.first_seen = old.first_seen
            changes.append(
                {
                    "issue_id": issue.issue_id,
                    "change": "reopened" if old.status == "resolved" else "persisting",
                }
            )
        else:
            changes.append({"issue_id": issue.issue_id, "change": "new"})
    for old in previous:
        if old.issue_id in fresh_ids:
            continue
        copy = old.model_copy(deep=True)
        matching = [
            r
            for r in runs
            if r.tool == old.tool
            and r.scope == old.scope
            and r.environment_id == old.environment_id
        ]
        # Imported logs never assert that an executed project's old failure was fixed.
        passed = any(
            r.verified_pass and r.coverage_complete and r.source == "executed" for r in matching
        )
        if old.tool == "pytest_run" and old.targets:
            passed = any(
                r.tool == old.tool
                and r.environment_id == old.environment_id
                and r.source == "executed"
                and r.coverage_complete
                and set(old.targets).issubset(r.passed_nodes)
                for r in runs
            )
        if passed:
            copy.status = "resolved"
            copy.note = (
                "同一环境中的全部关联测试节点已执行通过"
                if old.targets
                else "同一环境与检查范围已实际通过"
            )
        elif old.status != "resolved":
            copy.status = "not_observed" if old.status != "awaiting_verification" else old.status
            copy.note = "本轮未覆盖该问题，或检查未成功完成；保留之前证据"
            if old.tool in updated_tools and not matching:
                copy.note = "环境或检查范围不同，不能直接比较"
        if copy.status != old.status:
            changes.append({"issue_id": old.issue_id, "change": copy.status})
        fresh.append(copy)
    session.runs.extend(runs)
    session.events.extend(event_batch)
    session.issues = fresh
    session.history.append(
        {"time": now(), "kind": "checks", "run_ids": [r.run_id for r in runs], "changes": changes}
    )
    infer_and_plan(session)
    # Prevent stale success after changing the target interpreter.
    target = GOAL_CHECKS[session.goal]
    last = next((r for r in reversed(session.runs) if r.tool == target), None)
    if last and last.environment_id != environment_id(session.target_python):
        session.goal_status = "unknown"


def scan(session, checks=None, timeout=30, targets=None):
    if session.stopped:
        raise ValueError("排查已结束；使用 resume 恢复后再检查")
    if checks is None:
        checks = [
            "pytest_run" if c == "pytest" and session.goal == "pass_tests" else c
            for c in DEFAULT_CHECKS
        ]
    if targets:
        if list(checks) != ["pytest_run"]:
            raise ValueError("--nodes 必须与 --checks pytest_run 单独使用")
        validate_targets(session, targets)
    if len(checks) != len(set(checks)):
        raise ValueError("同一批检查不能重复")
    runs = []
    for check in checks:
        run = collect(session, check, timeout, targets=targets)
        runs.append(run)
        if run.status == "cancelled":
            break
    ingest(session, runs)


def import_log(session, path, tool, exit_code=None):
    file = Path(path)
    if file.stat().st_size > MAX_OUTPUT:
        raise ValueError("日志超过 1 MB，请先按一次检查拆分")
    text = redact(file.read_text(encoding="utf-8", errors="replace"))
    run = Run(
        tool=tool,
        source="imported",
        stdout=text,
        exit_code=exit_code,
        cwd=session.project_root,
        scope="imported:" + file.name,
        environment_id="unknown",
    )
    run.notes.append("导入历史日志，环境和完整检查范围尚未核实；不会据此关闭之前的问题。")
    ingest(session, [run])


def mark_fixed(session, issue_id):
    issue = next((i for i in session.issues if i.issue_id == issue_id), None)
    if issue is None:
        raise ValueError("没有这个问题编号")
    if issue.status == "resolved":
        raise ValueError("该问题已验证解决")
    issue.status = "awaiting_verification"
    session.history.append({"time": now(), "kind": "manual_change", "issue_id": issue_id})
    infer_and_plan(session)
