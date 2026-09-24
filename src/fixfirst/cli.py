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
    cli = argparse.ArgumentParser(
        prog="fixfirst", description="FixFirst: local, evidence-based Python troubleshooting"
    )
    cli.add_argument(
        "--store",
        default=os.environ.get("FIXFIRST_STORE", ".fixfirst"),
        help="directory that holds troubleshooting sessions",
    )
    sub = cli.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a session (does not run the project)")
    init.add_argument("project")
    init.add_argument("--python", default=sys.executable)
    init.add_argument("--name")
    init.add_argument("--goal", choices=list(GOALS), default="collect_tests")
    init.add_argument("--grouping", choices=["exact", "tfidf", "sbert"], default="tfidf")
    init.add_argument("--model", help="root-cause decision tree JSON (default: bundled model)")
    init.add_argument("--no-classifier", action="store_true", help="use rules and knowledge only")
    init.add_argument("--sbert-model", help="local SentenceTransformer model directory")
    sub.add_parser("list", help="list sessions")
    sub.add_parser("interactive", help="terminal menu, no commands to remember")
    serve = sub.add_parser("serve", help="open the local web interface")
    serve.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: any free)")
    serve.add_argument("--no-open", action="store_true", help="do not open a browser")
    for name, help_text in [
        ("scan", "run checks (pytest imports project code)"),
        ("import", "import an existing log"),
        ("show", "show the current state"),
        ("run", "run a check action from the plan"),
        ("mark-fixed", "record a manual change and wait for verification"),
        ("report", "write the HTML and JSON report"),
        ("export", "write a redacted report for sharing"),
        ("configure", "change the goal or the interpreter"),
        ("stop", "stop the session"),
        ("resume", "resume the session"),
        ("delete", "delete a session's local records"),
        ("graph", "export the session's evidence graph"),
        ("ask", "ask why an action is advised, what the cause is, what is unverified"),
    ]:
        command = sub.add_parser(name, help=help_text)
        command.add_argument("session")
        if name in ("scan", "run"):
            command.add_argument("--timeout", type=float, default=30)
        if name == "scan":
            command.add_argument("--checks", nargs="+", choices=TOOLS)
            command.add_argument(
                "--nodes", nargs="+", help="re-run observed test nodes only (with --checks pytest_run)"
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
            command.add_argument("--output", required=True, help="HTML path; JSON is written next to it")
        if name == "show":
            command.add_argument("--json", action="store_true")
        if name == "delete":
            command.add_argument("--yes", action="store_true", help="confirm deletion")
        if name == "configure":
            command.add_argument("--goal", choices=list(GOALS))
            command.add_argument("--python")
        if name == "graph":
            command.add_argument("--output", required=True)
        if name == "ask":
            command.add_argument("question")
            command.add_argument("--entity", help="optional action, issue or run id")
            command.add_argument("--json", action="store_true")
    knowledge = sub.add_parser("knowledge", help="export the domain knowledge graph and rule base")
    knowledge.add_argument("--output", required=True)
    demo = sub.add_parser("demo", help="build and run an owned demo project (never your code)")
    demo.add_argument("--output", default="workbench/demo")
    demo.add_argument("--open", action="store_true")
    demo.add_argument(
        "--scenario", choices=["playground", "collection", "execution"], default="collection"
    )
    dataset = sub.add_parser("dataset", help="generate a labelled dataset by real execution")
    dataset.add_argument("--output", default="workbench/dataset")
    dataset.add_argument("--suite", choices=["diagnosis", "collection", "execution"], default="diagnosis")
    evaluation = sub.add_parser("evaluate", help="run the experiments on a dataset")
    evaluation.add_argument("dataset")
    evaluation.add_argument("--output", default="workbench/evaluation")
    evaluation.add_argument("--sbert-model")
    historical = sub.add_parser("historical", help="replay sourced upstream regressions offline")
    historical.add_argument("--assets", required=True, help="directory with manifest.json and wheels")
    historical.add_argument("--output", required=True, help="a new output directory")
    return cli


def show(session):
    print(f"\n{session.name} · {session.session_id}")
    print(f"Goal: {GOALS[session.goal]} | {session.goal_status}")
    for issue in session.issues:
        cause = f"  → {issue.diagnosis} ({issue.diagnosis_source})" if issue.diagnosis else ""
        print(f"  [{STATES[issue.status]}] {issue.issue_id}  {issue.title[:110]}{cause}")
    print("\nNext steps (manual fixes are never run for you):")
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
        if args.command == "serve":
            from .web import serve

            return serve(store.root, args.port, not args.no_open)
        if args.command == "knowledge":
            from . import domain
            from .reasoning import rule_base
            from .storage import atomic_write

            graph = domain.graph()
            graph["rules"] = [
                {"id": r.rule_id, "phase": r.phase, "description": r.description, "source": r.source}
                for r in rule_base()
            ]
            atomic_write(Path(args.output).resolve(), json.dumps(graph, indent=2))
            print(f"Knowledge graph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges, "
                  f"{len(graph['rules'])} rules → {args.output}")
            return 0
        if args.command in ("demo", "dataset", "evaluate"):
            if args.command == "evaluate":
                from .evaluation import evaluate

                print(evaluate(Path(args.dataset), Path(args.output), args.sbert_model))
                return 0
            if getattr(args, "scenario", None) == "playground":
                from .playground import playground

                session = playground(Path(args.output), store)
                path = render(session, store.root, store.directory(session.session_id) / "report.html")
                show(session)
                print(f"\nFix the project in {Path(args.output) / 'project'} (see FIXES.md), then run:")
                print(f"  fixfirst --store {str(store.root)!r} scan {session.session_id}")
                print(f"Report: {path}  ·  or use `fixfirst serve` for the web interface")
                if args.open:
                    webbrowser.open(path.as_uri())
                return 0
            if getattr(args, "suite", None) == "diagnosis":
                from .diagnosis_cases import build_dataset

                print(build_dataset(Path(args.output)))
                return 0
            from . import cases

            if "execution" in (getattr(args, "scenario", None), getattr(args, "suite", None)):
                from . import execution_cases as cases
            if args.command == "demo":
                path = cases.demo(Path(args.output), store)
                print(f"Demo report: {path}")
                if args.open:
                    webbrowser.open(path.as_uri())
            else:
                print(cases.build_dataset(Path(args.output)))
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
            session.use_classifier = not args.no_classifier
            with store.lock(session.session_id):
                infer_and_plan(session)
                store.save(session)
                path = render(
                    session, store.root, store.directory(session.session_id) / "report.html"
                )
            print(session.session_id)
            print(f"Next: fixfirst --store {str(store.root)!r} scan {session.session_id}")
            print(f"Report: {path}")
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
                    raise ValueError(
                        "This is not a runnable check; follow the evidence and make manual fixes yourself"
                    )
                print(f"Running: {action.title} in {session.project_root}", flush=True)
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
                    raise ValueError(
                        "Add --yes to delete; your project and exported copies are not touched"
                    )
                shutil.rmtree(store.directory(args.session))
                print("Session records deleted")
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
                    raise ValueError("The export path must end with .html")
                render(session, store.root, path, public=True)
                print(f"Exported: {path} (preview it before sharing)")
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
                    print(f"Evidence graph exported: {args.output}")
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
        print(f"\nReport: {path}")
        if getattr(args, "open", False):
            webbrowser.open(path.as_uri())
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nExited")
        return 0
    except (ValueError, OSError, ImportError, KeyError) as exc:
        print(f"FixFirst: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
