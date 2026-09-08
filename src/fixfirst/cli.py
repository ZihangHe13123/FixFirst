import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import webbrowser

from .models import now
from .reasoning import infer_and_plan
from .report import render, GOALS, STATES
from .runner import TOOLS
from .service import create_session, scan, import_log, mark_fixed
from .storage import Store


def parser():
    cli = argparse.ArgumentParser(prog="fixfirst", description="FixFirst 本地 Python 项目排错助手")
    cli.add_argument(
        "--store", default=os.environ.get("FIXFIRST_STORE", ".fixfirst"), help="排查记录目录"
    )
    sub = cli.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="创建排查记录，不运行项目")
    init.add_argument("project")
    init.add_argument("--python", default=sys.executable)
    init.add_argument("--name")
    init.add_argument("--goal", choices=list(GOALS), default="collect_tests")
    init.add_argument("--grouping", choices=["exact", "tfidf", "sbert"], default="tfidf")
    init.add_argument("--model", help="已训练的 JSON 决策树路径")
    init.add_argument("--sbert-model", help="已下载的本地 SentenceTransformer 模型目录")
    sub.add_parser("list", help="列出排查记录")
    sub.add_parser("interactive", help="交互菜单，无需记命令")
    for name, help_text in [
        ("scan", "主动运行检查（pytest 会执行项目导入）"),
        ("import", "导入历史日志"),
        ("show", "显示当前状态"),
        ("run", "执行行动清单中的预定义检查"),
        ("mark-fixed", "声明手动修改，等待验证"),
        ("report", "生成 HTML 和 JSON 报告"),
        ("export", "导出脱敏分享报告"),
        ("configure", "修改目标或解释器"),
        ("stop", "结束排查"),
        ("resume", "恢复排查"),
        ("delete", "删除某次排查的本地记录"),
        ("graph", "导出证据知识图谱"),
        ("ask", "依据知识图谱查询问题与推荐理由"),
    ]:
        command = sub.add_parser(name, help=help_text)
        command.add_argument("session")
        if name in ("scan", "run"):
            command.add_argument("--timeout", type=float, default=30)
        if name == "scan":
            command.add_argument("--checks", nargs="+", choices=TOOLS)
            command.add_argument(
                "--nodes", nargs="+", help="仅重跑已观察的测试节点，需要 --checks pytest_run"
            )
        if name == "run":
            command.add_argument("action")
        if name == "import":
            command.add_argument(
                "--tool",
                required=True,
                choices=["pip_install", "pip_check", "pytest", "pytest_run", "ruff"],
            )
            command.add_argument("--file", required=True)
            command.add_argument("--exit-code", type=int)
        if name == "mark-fixed":
            command.add_argument("issue")
        if name in ("report", "export"):
            command.add_argument("--open", action="store_true")
        if name == "export":
            command.add_argument("--output", required=True, help="输出 HTML 路径，同时生成 JSON")
        if name == "show":
            command.add_argument("--json", action="store_true")
        if name == "delete":
            command.add_argument("--yes", action="store_true", help="确认删除该排查")
        if name == "configure":
            command.add_argument("--goal", choices=list(GOALS))
            command.add_argument("--python")
        if name == "graph":
            command.add_argument("--output", required=True)
        if name == "ask":
            command.add_argument("question")
            command.add_argument("--entity", help="可选 action / issue / fact 编号")
            command.add_argument("--json", action="store_true")
    demo = sub.add_parser("demo", help="创建并实际运行自建故障案例，不修改用户项目")
    demo.add_argument("--output", default="workbench/demo")
    demo.add_argument("--open", action="store_true")
    demo.add_argument("--scenario", choices=["collection", "execution"], default="collection")
    dataset = sub.add_parser("dataset", help="创建可复现受控案例及独立标签")
    dataset.add_argument("--output", default="workbench/dataset")
    dataset.add_argument("--suite", choices=["collection", "execution"], default="collection")
    evaluation = sub.add_parser("evaluate", help="按项目划分训练并评价规则、归并及决策树")
    evaluation.add_argument("dataset")
    evaluation.add_argument("--output", default="workbench/evaluation")
    evaluation.add_argument("--sbert-model")
    historical = sub.add_parser("historical", help="在新建独立环境离线复现有来源的历史库故障")
    historical.add_argument("--assets", required=True, help="包含 manifest.json 与官方 wheel 的资产目录")
    historical.add_argument("--output", required=True, help="必须使用新的输出目录")
    return cli


def show(session):
    print(f"\n{session.name} · {session.session_id}")
    print(f"目标：{GOALS[session.goal]} | {session.goal_status}")
    for issue in session.issues:
        print(f"  [{STATES[issue.status]}] {issue.issue_id}  {issue.title[:120]}")
    print("\n下一步（手动处理不会自动执行）：")
    for action in session.actions[:5]:
        print(f"  {action.priority}. {action.action_id} — {action.title}")


def main(argv=None):
    args = parser().parse_args(argv)
    store = Store(args.store)
    try:
        if args.command == "historical":
            from .historical_cases import replay

            report = replay(Path(args.output), Path(args.assets))
            print(report)
            complete = json.loads(report.with_name("results.json").read_text())["all_reproduced"]
            return 0 if complete else 2
        if args.command == "interactive":
            from .interactive import menu

            return menu(store.root)
        if args.command in ("demo", "dataset", "evaluate"):
            from . import cases

            if (
                getattr(args, "scenario", None) == "execution"
                or getattr(args, "suite", None) == "execution"
            ):
                from . import execution_cases as cases

            if args.command == "demo":
                path = cases.demo(Path(args.output), store)
                print(f"完整演示报告：{path}")
                if args.open:
                    webbrowser.open(path.as_uri())
            elif args.command == "dataset":
                print(cases.build_dataset(Path(args.output)))
            else:
                from .evaluation import evaluate

                print(evaluate(Path(args.dataset), Path(args.output), args.sbert_model))
            return 0
        if args.command == "list":
            print(json.dumps(store.list(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "init":
            session = create_session(
                args.project,
                args.python,
                args.name,
                args.goal,
                args.grouping,
                args.model,
                args.sbert_model,
            )
            with store.lock(session.session_id):
                infer_and_plan(session)
                store.save(session)
                path = render(
                    session, store.root, store.directory(session.session_id) / "report.html"
                )
            print(session.session_id)
            print(f"下一步：fixfirst --store {str(store.root)!r} scan {session.session_id}")
            print(f"报告：{path}")
            return 0
        with store.lock(args.session):
            session = store.load(args.session)
            path = store.directory(args.session) / "report.html"
            if args.command == "scan":
                scan(session, args.checks, args.timeout, targets=args.nodes)
            elif args.command == "import":
                import_log(session, args.file, args.tool, args.exit_code)
            elif args.command == "run":
                action = next((a for a in session.actions if a.action_id == args.action), None)
                if not action or not action.check or action.blocked_reasons:
                    raise ValueError("这不是可执行的检查行动；手动处理请依照原始证据进行")
                print(f"运行：{action.title}，项目 {session.project_root}", flush=True)
                scan(session, [action.check], args.timeout, targets=action.targets)
            elif args.command == "mark-fixed":
                mark_fixed(session, args.issue)
            elif args.command == "configure":
                if args.goal:
                    session.goal = args.goal
                if args.python:
                    validated = create_session(session.project_root, args.python)
                    session.target_python = validated.target_python
                    session.environment = {}
                session.history.append({"time": now(), "kind": "goal_change"})
                infer_and_plan(session)
                session.goal_status = "unknown"
            elif args.command in ("stop", "resume"):
                session.stopped = args.command == "stop"
                session.history.append({"time": now(), "kind": args.command})
            elif args.command == "delete":
                if not args.yes:
                    raise ValueError("确认删除请加 --yes；用户项目与已导出的副本不会删除")
                shutil.rmtree(store.directory(args.session))
                print("已删除该排查记录")
                return 0
            elif args.command == "show":
                if args.json:
                    print(session.model_dump_json(indent=2))
                else:
                    show(session)
                return 0
            elif args.command == "export":
                path = Path(args.output).expanduser().resolve()
                if path.suffix.lower() != ".html":
                    raise ValueError("导出路径应以 .html 结尾")
                render(session, store.root, path, public=True)
                print(f"已导出：{path}（请预览内容后分享）")
                if args.open:
                    webbrowser.open(path.as_uri())
                return 0
            elif args.command in ("graph", "ask"):
                from .knowledge_graph import build_graph, query_graph
                from .report import public_data
                from .models import Session

                graph = build_graph(Session.model_validate(public_data(session)))
                if args.command == "graph":
                    from .storage import atomic_write

                    atomic_write(
                        Path(args.output).expanduser().resolve(),
                        json.dumps(graph, ensure_ascii=False, indent=2),
                    )
                    print(f"已导出知识图谱：{args.output}")
                else:
                    answer = query_graph(graph, args.question, args.entity)
                    print(
                        json.dumps(answer, ensure_ascii=False, indent=2)
                        if args.json
                        else answer["answer"]
                    )
                return 0
            store.save(session)
            render(session, store.root, path)
        show(session)
        print(f"\n报告：{path}")
        if getattr(args, "open", False):
            webbrowser.open(path.as_uri())
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\n已退出菜单")
        return 0
    except (ValueError, OSError, ImportError, KeyError) as exc:
        print(f"FixFirst：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
