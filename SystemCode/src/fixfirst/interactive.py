"""Small terminal menu over the same public CLI; no separate execution path."""

from datetime import datetime
from pathlib import Path

from .storage import Store

GOALS = {"0": "auto", "1": "collect_tests", "2": "check_style", "3": "pass_tests",
         "4": "run_project", "5": "pass_unittest"}


def entry_arguments(goal):
    if goal == "run_project":
        kind = input("Entry type: 1 script / 2 module / 3 notebook (Enter = 1): ").strip() or "1"
        option = {"1": "--script", "2": "--module", "3": "--notebook"}.get(kind)
        if not option:
            raise ValueError("Unknown entry type")
        return [option, input("Entry path or module name: ").strip().strip("'\"")]
    if goal == "pass_unittest":
        return ["--unittest-dir", input("Test directory (Enter = .): ").strip() or "."]
    return []


def menu(store_root):
    from .cli import main

    store = Store(store_root)
    prefix = ["--store", str(store.root)]
    while True:
        print(
            "\nFixFirst · Python troubleshooting\n"
            "1 Demo: import error and style findings\n"
            "2 Troubleshoot my own project\n"
            "3 Continue an existing session\n"
            "4 Demo: failing tests and the evidence graph\n"
            "5 Open the web interface\n"
            "0 Quit"
        )
        choice = input("Choose: ").strip()
        if choice == "0":
            return 0
        if choice == "5":
            return main(prefix + ["serve"])
        if choice in ("1", "4"):
            output = Path("workbench") / ("demo-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
            main(
                prefix
                + [
                    "demo",
                    "--output",
                    str(output),
                    "--scenario",
                    "execution" if choice == "4" else "collection",
                    "--open",
                ]
            )
            continue
        if choice == "2":
            project = input("Project directory (full path): ").strip().strip("'\"")
            python = (
                input("Project's Python interpreter (Enter to auto-detect): ")
                .strip()
                .strip("'\"")
            )
            goal = (
                input("Goal: 0 auto / 1 test collection / 2 code check / 3 pytest / 4 program / 5 unittest (Enter = 0): ")
                .strip()
                or "0"
            )
            if goal not in GOALS:
                print("Unknown goal")
                continue
            try:
                entry = entry_arguments(GOALS[goal])
            except ValueError as exc:
                print(exc)
                continue
            python_args = ["--python", python] if python else []
            if main(prefix + ["init", project, *python_args, "--goal", GOALS[goal], *entry]) != 0:
                continue
        if choice not in ("2", "3"):
            continue
        rows = store.list()
        if not rows:
            print("No sessions yet")
            continue
        for i, row in enumerate(rows, 1):
            print(f"{i} {row['name']} · {row['goal_status']} · {row['session_id']}")
        try:
            index = int(input("Session number: ")) - 1
            if index < 0:
                continue
            session_id = rows[index]["session_id"]
        except (ValueError, IndexError):
            print("Invalid choice")
            continue
        while True:
            print(
                "\n1 Run the checks for the current goal\n2 Check test collection only\n"
                "3 Run the code check only\n4 Open the report\n5 Import a log\n6 Change the goal\n"
                "7 Record a manual change\n8 Export a shareable report\n9 Run the full test suite\n"
                "10 Re-run the related failing tests\n11 Ask about the advice\n0 Back"
            )
            action = input("Choose: ").strip()
            if action == "0":
                break
            commands = {
                "1": ["scan", session_id],
                "2": ["scan", session_id, "--checks", "pytest"],
                "3": ["scan", session_id, "--checks", "ruff"],
                "4": ["report", session_id, "--open"],
                "9": ["scan", session_id, "--checks", "pytest_run"],
                "10": ["run", session_id, "check-failed-tests"],
            }
            if action in ("1", "2"):
                print("Test collection imports project code; only check projects you trust.")
            if action == "5":
                tool = input("Source: pip_install / pip_check / pytest / pytest_run / ruff / python_run: ").strip()
                if tool not in ("pip_install", "pip_check", "pytest", "pytest_run", "ruff", "python_run"):
                    print("Unsupported source")
                    continue
                file = input("Log file path: ").strip().strip("'\"")
                command = ["import", session_id, "--tool", tool, "--file", file]
            elif action == "6":
                goal = input("0 auto / 1 test collection / 2 code check / 3 pytest / 4 program / 5 unittest: ").strip()
                if goal not in GOALS:
                    continue
                try:
                    command = ["configure", session_id, "--goal", GOALS[goal], *entry_arguments(GOALS[goal])]
                except ValueError as exc:
                    print(exc)
                    continue
            elif action == "7":
                main(prefix + ["show", session_id])
                issue = input("Issue id (starts with issue-): ").strip()
                command = ["mark-fixed", session_id, issue]
            elif action == "8":
                path = input("Output HTML path: ").strip().strip("'\"")
                command = ["export", session_id, "--output", path, "--open"]
            elif action == "11":
                question = input(
                    "Question (e.g. why is this recommended / what is the root cause / "
                    "what is not verified / which package provides cv2): "
                ).strip()
                command = ["ask", session_id, question]
            else:
                command = commands.get(action)
            if command:
                main(prefix + command)
