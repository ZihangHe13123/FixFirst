from pathlib import Path
import os

from .classification import classify
from .grouping import group_events
from .models import Run, Session, now
from .parsers import parse
from .reasoning import infer_and_plan
from .runner import collect, environment_id, redact, MAX_OUTPUT


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
        if passed:
            copy.status = "resolved"
            copy.note = "同一环境与检查范围已实际通过"
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
    target = "pytest" if session.goal == "collect_tests" else "ruff"
    last = next((r for r in reversed(session.runs) if r.tool == target), None)
    if last and last.environment_id != environment_id(session.target_python):
        session.goal_status = "unknown"


def scan(session, checks, timeout=30):
    if session.stopped:
        raise ValueError("排查已结束；使用 resume 恢复后再检查")
    if len(checks) != len(set(checks)):
        raise ValueError("同一批检查不能重复")
    runs = []
    for check in checks:
        run = collect(session, check, timeout)
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
