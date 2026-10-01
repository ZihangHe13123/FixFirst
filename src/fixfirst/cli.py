import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import webbrowser

from .models import now
from .reasoning import infer_and_plan
from .report import render, GOALS, issue_state, shell
from .runner import DEFAULT_TIMEOUT, TOOLS
from .service import create_session, scan, import_log, mark_fixed
from .storage import Store


def execution_arguments(command):
    entry = command.add_mutually_exclusive_group()
    entry.add_argument("--script", help="Python script inside the project")
    entry.add_argument("--module", help="Python module, as in python -m package")
    entry.add_argument("--notebook", help="Notebook inside the project")
    entry.add_argument("--unittest-dir", help="unittest discovery directory")
    command.add_argument("--arg", action="append", help="One program argument; use --arg=--flag for flags")
    command.add_argument("--stdin-file", help="UTF-8 file containing standard input for the program")
    command.add_argument("--test-pattern", help="unittest filename pattern (default test*.py)")


def execution_settings(args, previous=None):
    entry = next(((kind, getattr(args, name)) for name, kind in (
        ("script", "script"), ("module", "module"), ("notebook", "notebook"),
        ("unittest_dir", "unittest")) if getattr(args, name, None)), None)
    configured = entry or args.arg is not None or args.stdin_file or args.test_pattern
    if not configured:
        return previous
    value = previous.model_dump() if previous else {}
    if entry:
        value.update(kind=entry[0], entry=entry[1])
    if args.arg is not None:
        value["args"] = args.arg
    if args.stdin_file:
        file = Path(args.stdin_file)
        if file.stat().st_size > 64_000:
            raise ValueError("Standard input is limited to 64 KB")
        value["stdin"] = file.read_text(encoding="utf-8")
    if args.test_pattern:
        value["pattern"] = args.test_pattern
    if "entry" not in value:
        raise ValueError("Choose --script, --module, --notebook or --unittest-dir with these settings")
    return value


def parser():
    cli = argparse.ArgumentParser(
        prog="fixfirst", description="FixFirst: local, evidence-based Python troubleshooting"
    )
    cli.add_argument(
        "--store",
        help="directory that holds troubleshooting sessions (default: $FIXFIRST_STORE, "
        "else .fixfirst; for mcp, ~/.fixfirst/sessions)",
    )
    sub = cli.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a session (does not run the project)")
    init.add_argument("project")
    init.add_argument("--python", help="Project Python; default: discover the project's environment")
    init.add_argument("--name")
    init.add_argument("--goal", choices=["auto", *GOALS], default="auto")
    execution_arguments(init)
    init.add_argument("--grouping", choices=["exact", "tfidf", "sbert"], default="tfidf")
    init.add_argument("--model", help="root-cause decision tree JSON (default: bundled model)")
    init.add_argument("--no-classifier", action="store_true", help="use rules and knowledge only")
    init.add_argument("--sbert-model", help="local SentenceTransformer model directory")
    sub.add_parser("list", help="list sessions")
    sub.add_parser("interactive", help="terminal menu, no commands to remember")
    serve = sub.add_parser("serve", help="open the local web interface")
    serve.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: any free)")
    serve.add_argument("--no-open", action="store_true", help="do not open a browser")
    mcp = sub.add_parser("mcp", help="serve FixFirst to coding agents over MCP (stdio)")
    mcp.add_argument("--facts", action="store_true",
                     help="facts only (one tool, observe): what the checks showed, no diagnosis or advice")
    for name, help_text in [
        ("scan", "run checks (pytest imports project code)"),
        ("import", "import an existing log"),
        ("show", "show the current state"),
        ("run", "run a check action from the plan"),
        ("mark-fixed", "record a manual change and wait for verification"),
        ("accept-baseline", "accept the changed tests and test settings as the new baseline"),
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
            command.add_argument(
                "--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds per check (default 600)"
            )
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
                choices=["pip_install", "pip_check", "pytest", "pytest_run", "ruff", "python_run"],
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
            command.add_argument("--goal", choices=["auto", *GOALS])
            command.add_argument("--python")
            execution_arguments(command)
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
    dataset.add_argument(
        "--suite", choices=["diagnosis", "hard", "multi", "collection", "execution"], default="diagnosis"
    )
    evaluation = sub.add_parser("evaluate", help="run the experiments on a dataset")
    evaluation.add_argument("dataset")
    evaluation.add_argument("--output", default="workbench/evaluation")
    evaluation.add_argument("--sbert-model")
    evaluation.add_argument(
        "--train", help="diagnosis dataset to train the tree on; DATASET is then a held-out test set"
    )
    evaluation.add_argument(
        "--skip-rules", nargs="+", default=[], metavar="RULE", help="leave these rules out (with --train)"
    )
    historical = sub.add_parser("historical", help="replay sourced upstream regressions offline")
    historical.add_argument("--assets", required=True, help="directory with manifest.json and wheels")
    historical.add_argument("--output", required=True, help="a new output directory")
    return cli


def show(session):
    from .workspace import build_view

    print(f"\n{session.name} · {session.session_id}")
    print(f"Goal: {GOALS[session.goal]} | {session.goal_status}")
    for issue in session.issues:
        cause = f"  → {issue.diagnosis} ({issue.diagnosis_source})" if issue.diagnosis else ""
        print(f"  [{issue_state(issue.tool, issue.status)}] {issue.issue_id}  {issue.title[:110]}{cause}")
    print("\nNext steps (manual fixes are never run for you):")
    for rank, step in enumerate(build_view(session)["steps"][:5], 1):
        print(f"  {rank}. {step['id']} — {step['title']}")
        print(f"     {step['explanation']}")
        if step["command"]:
            print(f"     {step['command']}")
        action = next(a for a in session.actions if a.action_id == step["id"])
        if action.check:
            print(f"     Run check: fixfirst run {session.session_id} {action.action_id}")
    print(f"Check again: fixfirst scan {session.session_id}")


def default_store(command):
    # An agent starts the MCP server inside the project it is fixing; keep sessions out of it.
    return str(Path.home() / ".fixfirst" / "sessions") if command == "mcp" else ".fixfirst"


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    args = parser().parse_args(argv)
    store = Store(args.store or os.environ.get("FIXFIRST_STORE") or default_store(args.command))
    try:
        if args.command == "mcp":
            from .mcp_server import serve as serve_mcp

            return serve_mcp(store.root, mode="facts" if args.facts else "full")
        if args.command == "historical":
            from .historical_cases import replay

            report = replay(Path(args.output), Path(args.assets))
            print(report)
            complete = json.loads(report.with_name("results.json").read_text(encoding="utf-8"))["all_reproduced"]
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

                train = Path(args.train) if args.train else None
                print(evaluate(Path(args.dataset), Path(args.output), args.sbert_model, train, args.skip_rules))
                return 0
            if getattr(args, "scenario", None) == "playground":
                from .playground import playground

                session = playground(Path(args.output), store)
                path = render(session, store.root, store.directory(session.session_id) / "report.html")
                show(session)
                print(f"\nFix the project in {Path(args.output) / 'project'} (see FIXES.md), then run:")
                print("  " + shell([sys.executable, "-m", "fixfirst", "--store", str(store.root),
                                    "scan", session.session_id]))
                print(f"Report: {path}  ·  or use `fixfirst serve` for the web interface")
                if args.open:
                    webbrowser.open(path.as_uri())
                return 0
            if getattr(args, "suite", None) == "diagnosis":
                from .diagnosis_cases import build_dataset

                print(build_dataset(Path(args.output)))
                return 0
            if getattr(args, "suite", None) == "hard":
                from .hard_cases import build_dataset as build_hard

                print(build_hard(Path(args.output)))
                return 0
            if getattr(args, "suite", None) == "multi":
                from .multi_cases import build_dataset as build_multi

                print(build_multi(Path(args.output)))
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
            print(json.dumps(store.list(), ensure_ascii=True, indent=2))
            return 0
        if args.command == "init":
            from .workspace import inspect_folder

            folder = inspect_folder(args.project, args.python)
            if not folder["ok"]:
                raise ValueError(folder.get("error") or "; ".join(folder["warnings"]))
            session = create_session(
                args.project,
                folder["python"]["path"],
                args.name,
                args.goal,
                args.grouping,
                args.model,
                args.sbert_model,
                execution=execution_settings(args),
            )
            session.use_classifier = not args.no_classifier
            with store.lock(session.session_id):
                infer_and_plan(session)
                store.save(session)
                path = render(
                    session, store.root, store.directory(session.session_id) / "report.html"
                )
            print(session.session_id)
            print("Next: " + shell([sys.executable, "-m", "fixfirst", "--store", str(store.root),
                                    "scan", session.session_id]))
            print(f"Report: {path}")
            return 0
        if args.command == "delete":
            directory = store.directory(args.session)
            with store.lock(args.session):
                store.load(args.session)
                if not args.yes:
                    raise ValueError(
                        "Add --yes to delete; your project and exported copies are not touched"
                    )
                # Windows cannot delete the open lock file. Remove the records while holding the
                # lock, session.json last: a failure leaves a loadable session, and once it is
                # gone no command can load or save the session.
                for entry in sorted(directory.iterdir(), key=lambda p: p.name == "session.json"):
                    if entry.is_dir() and not entry.is_symlink():
                        shutil.rmtree(entry)
                    elif entry.name != ".lock":
                        entry.unlink()
            # Only the empty lock file is left; a command that opened it meanwhile keeps it.
            shutil.rmtree(directory, ignore_errors=True)
            print("Session records deleted")
            return 0
        with store.lock(args.session):
            session = store.load(args.session)
            path = store.directory(args.session) / "report.html"
            if args.command == "scan":
                scan(session, args.checks, args.timeout, targets=args.nodes)
            elif args.command == "import":
                import_log(session, args.file, args.tool, args.exit_code)
            elif args.command == "run":
                infer_and_plan(session)
                action = next((a for a in session.actions if a.action_id == args.action), None)
                if not action or not action.check or action.blocked_reasons:
                    raise ValueError(
                        "This is not a runnable check; follow the evidence and make manual fixes yourself"
                    )
                print(f"Running: {action.title} in {session.project_root}", flush=True)
                scan(session, [action.check], args.timeout, targets=action.targets)
            elif args.command == "mark-fixed":
                mark_fixed(session, args.issue)
            elif args.command == "accept-baseline":
                from .integrity import accept, describe

                result = accept(session)
                print("New baseline accepted"
                      + (f"; changed since the previous one: {describe(result['changed'])}" if result["changed"]
                         else "; nothing had changed since the previous one")
                      + (f"; could not be compared: {describe(result['unverifiable'], 2)}"
                         if result["unverifiable"] else "")
                      + ". Check again to verify against it.")
            elif args.command == "configure":
                configured = execution_settings(
                    args, session.execution if not args.goal or args.goal == session.goal else None)
                validated = create_session(
                    session.project_root, args.python or session.target_python,
                    goal=args.goal or session.goal, execution=configured)
                session.goal, session.execution = validated.goal, validated.execution
                session.target_python = validated.target_python
                session.environment = {}
                session.history.append({"time": now(), "kind": "execution_change"})
                infer_and_plan(session)
                session.goal_status = "unknown"
            elif args.command in ("stop", "resume"):
                session.stopped = args.command == "stop"
                session.history.append({"time": now(), "kind": args.command})
            elif args.command == "show":
                infer_and_plan(session)
                if args.json:
                    print(json.dumps(session.model_dump(mode="json"), ensure_ascii=True, indent=2))
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
                from .report import public_data, public_entity, public_question
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
                    answer = query_graph(graph, public_question(session, args.question),
                                         public_entity(session, args.entity))
                    print(
                        json.dumps(answer, ensure_ascii=True, indent=2)
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
