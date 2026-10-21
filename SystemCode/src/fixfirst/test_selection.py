"""Saved pytest selections are separate from observed nodes used for a partial rerun."""

import hashlib
import json
from pathlib import Path
import stat


def canonical_nodeid(value):
    """Remove the old Python class Instance segment, never text inside parameters."""
    if not isinstance(value, str):
        return value
    head, bracket, parameters = value.partition("[")
    parts = head.split("::")
    if not parts[0].endswith(".py"):
        return value
    if (len(parts) >= 4 and parts[-2] == "()" and parts[-1].isidentifier()
            and all(part.isidentifier() for part in parts[1:-2])):
        del parts[-2]
    elif len(parts) >= 3 and parts[-1] == "()" and all(part.isidentifier() for part in parts[1:-1]):
        parts.pop()
    return "::".join(parts) + bracket + parameters


def normalize_tests(root, tests, *, require_files=True):
    if tests is None:
        return []
    if not isinstance(tests, list) or len(tests) > 200:
        raise ValueError("Choose up to 200 project test files or pytest node IDs")
    root = Path(root).resolve()
    normalized = []
    for target in tests:
        if (not isinstance(target, str) or not target or len(target) > 4096
                or target.startswith("-") or any(ord(c) < 32 or ord(c) == 127 for c in target)):
            raise ValueError("Use a project test file or pytest node ID, not a command or option")
        file, separator, node = target.partition("::")
        if not file or separator and (not node or any(not part for part in node.split("::"))):
            raise ValueError("A pytest node ID needs a file and nonempty node components")
        path = Path(file)
        if not path.is_absolute():
            path = root / path
        # Preserve the path pytest uses, but require both it and its referent to stay inside.
        path = Path(path.absolute())
        try:
            relative = path.relative_to(root)
            resolved = path.resolve()
            resolved.relative_to(root)
        except (ValueError, OSError, RuntimeError):
            raise ValueError("Selected tests must be inside the project") from None
        if ".." in relative.parts:
            raise ValueError("Selected tests must use a path inside the project without '..'")
        for parent in [path, *path.parents]:
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError("Selected test paths must not contain symbolic links")
        if require_files:
            try:
                regular = stat.S_ISREG(path.stat().st_mode)
            except OSError:
                regular = False
            if not regular:
                raise ValueError(f"Selected test file does not exist or is not a regular file: {relative}")
        value = canonical_nodeid(relative.as_posix() + (separator + node if separator else ""))
        if value in normalized:
            raise ValueError("Choose distinct test files or node IDs")
        normalized.append(value)
    return normalized


def selection_id(session):
    payload = {"project": session.project_root, "tests": session.test_targets}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]


def comparable_scopes(left, right):
    """Legacy full/partial checks remain comparable; saved scopes never cross."""
    if ":requested:" in left or ":requested:" in right:
        return left.removesuffix(":partial") == right.removesuffix(":partial")
    return True


def node_selected(selector, node):
    selector, node = canonical_nodeid(selector), canonical_nodeid(node)
    return node == selector or node.startswith(selector + "::") or node.startswith(selector + "[")


def selection_observed(selectors, nodes):
    return (all(any(node_selected(selector, node) for node in nodes) for selector in selectors)
            and all(any(node_selected(selector, node) for selector in selectors) for node in nodes))


def configure_tests(session, tests):
    if session.goal != "pass_tests":
        raise ValueError("Test selection is only available for the pass_tests goal")
    selected = normalize_tests(session.project_root, tests)
    if selected != session.test_targets:
        from .models import now

        session.test_targets = selected
        session.goal_status = "unknown"
        session.history.append({"time": now(), "kind": "test_scope_change", "tests": selected})


def missing_optional_tool(session, issue):
    from .models import GOAL_CHECKS
    from .runner import environment_id

    if issue.tool not in ("pip_check", "ruff") or issue.kind != "tool_failure":
        return False
    if GOAL_CHECKS[session.goal] == issue.tool:
        return False
    snapshot = next((r for r in reversed(session.runs) if r.tool == "environment"), None)
    if not snapshot or not snapshot.verified_pass or snapshot.environment_id != environment_id(session.target_python):
        return False
    packages = session.environment.get("packages")
    package = "pip" if issue.tool == "pip_check" else "ruff"
    return isinstance(packages, list) and not any(p.get("name", "").lower() == package for p in packages)


def refine_empty_discovery(session, actions):
    """Give an empty default discovery its own actionable step without changing knowledge."""
    if session.goal != "pass_tests" or session.test_targets:
        return actions
    run = next((r for r in reversed(session.runs) if r.tool == "pytest_run"), None)
    if (not run or run.source != "executed" or run.status != "completed" or run.exit_code != 5
            or run.test_summary.get("selected", 0)):
        return actions
    issues = [i for i in session.issues if i.tool == "pytest_run" and i.status == "open"
              and run.run_id in {e.run_id for e in session.events if e.event_id in i.event_ids}]
    if not issues:
        return actions
    from .models import Action
    from .project_test_commands import declared_commands

    ids = {i.issue_id for i in issues}
    kept = []
    for action in actions:
        remaining = [i for i in action.issue_ids if i not in ids]
        if action.issue_ids and not remaining:
            continue
        if remaining != action.issue_ids:
            action = action.model_copy(update={"issue_ids": remaining})
        kept.append(action)
    instructions = (
        "Select a test file or pytest node ID inside the project. In the web interface, use "
        "Python and run settings → Tests to run. In the CLI, use fixfirst configure SESSION "
        "--tests path/to/tests.py, then scan SESSION. With MCP, call diagnose with tests: "
        "[\"path/to/tests.py\"]. Check again will reuse this selection."
    )
    commands = declared_commands(Path(session.project_root))
    if commands:
        instructions += " Project test-command declarations (quoted, not executed): " + "; ".join(
            f"{source}: {command}" for source, command in commands)
    step = Action(action_id="choose-test-files", kind="manual_fix", issue_ids=sorted(ids),
                  title="Default pytest did not find any tests", explanation=instructions,
                  instructions=instructions, verification="Run the selected tests again", goal_impact=1)
    return [step, *kept]
