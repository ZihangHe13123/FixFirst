"""Constrain installation advice using recorded project and environment facts."""

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion
import re

from .dependency_context import bounded_adjustment, combined_specifier, context, contradicts, requirements_for
from .models import Action


def refine(session, actions, by_id, facts):
    from .evidence import current_environment, observed, project_index

    environment = current_environment(session)
    project_run, project = project_index(session)
    data = context(environment, {**project, "_run_id": project_run.run_id if project_run else None})

    def evidence(action, rows):
        for row in rows:
            fact = observed("dist:" + row["name"], "repair_constraint",
                            f"{row['source']}: {row['requirement']}", row["refs"])
            if not any(f.fact_id == fact.fact_id for f in facts):
                facts.append(fact)
            if fact.fact_id not in action.reason_refs:
                action.reason_refs.append(fact.fact_id)

    for action in actions:
        if action.command[:4] != [session.target_python, "-m", "pip", "install"]:
            continue
        try:
            requests = [Requirement(text) for text in action.command[4:]]
        except InvalidRequirement:
            continue
        if any(r.url for r in requests):
            continue
        changed, conflicts, sources = [], [], []
        for request in requests:
            name = canonicalize_name(request.name)
            rows = requirements_for(data, name)
            sources += rows
            specifier = combined_specifier(data, name, str(request.specifier))
            if contradicts(specifier):
                conflicts.append((name, str(request), rows))
                continue
            installed = data["installed"].get(name)
            if installed and request.specifier:
                specifier = bounded_adjustment(specifier, installed)
            extras = "[" + ",".join(sorted(request.extras)) + "]" if request.extras else ""
            changed.append(request.name + extras + specifier)
        evidence(action, sources)
        if conflicts:
            name, requested, rows = conflicts[0]
            action.command = []
            action.title = f"Resolve the {name} version constraints before changing it"
            constraints = "; ".join(f"{r['source']} requires {r['requirement']}" for r in rows)
            action.explanation = (
                f"The proposed {requested} conflicts with the recorded requirements: {constraints}. "
                "Adjust the conflicting project pin or dependent package together, then resolve the complete "
                "dependency set in a separate environment. If the fixed legacy versions must remain, use "
                "a separate Python environment compatible with their documented requirements. "
                "An unconstrained upgrade or a further downgrade would not resolve this conflict.")
        elif changed:
            action.command = [session.target_python, "-m", "pip", "install", "--only-binary=:all:", *changed]
            if sources:
                action.explanation += " Recorded constraints: " + "; ".join(
                    f"{r['source']} requires {r['requirement']}" for r in sources) + "."
            action.explanation += (
                " This command requests wheels and lets the resolver check the requirements; "
                "a satisfiable range is not proof that the application works. Check pip output, "
                "run pip check, and rerun the original failing check.")

    # Batch only required, statically understood dependencies when a blocking
    # import already calls for installation. Unused declarations do not turn a
    # healthy script into a failed goal, and optional groups remain opt-in.
    missing = {row["name"] for row in project.get("declarations", [])
               if row.get("status") == "missing" and row.get("group") == "required"
               and row.get("installer", "pip") == "pip"}
    hosts = []
    for action in actions:
        if action.goal_impact <= 0 or action.cause != "missing_dependency":
            continue
        if action.command[:4] != [session.target_python, "-m", "pip", "install"]:
            continue
        names = set()
        for text in action.command[4:]:
            if text.startswith("-"):
                continue
            try:
                names.add(canonicalize_name(Requirement(text).name))
            except InvalidRequirement:
                pass
        if names & missing:
            hosts.append(action)
    if len(missing) > 1 and hosts:
        host = hosts[0]
        rows = [r for r in data["requirements"] if r["owner"] == "project"]
        requested = {}
        for row in project.get("declarations", []):
            if (row.get("constraint") or row.get("group") != "required"
                    or row.get("status") not in ("missing", "satisfied", "version_mismatch")
                    or row.get("installer", "pip") != "pip"):
                continue
            requirement = Requirement(row["requirement"])
            extras = "[" + ",".join(sorted(requirement.extras)) + "]" if requirement.extras else ""
            requested[row["name"]] = requirement.name + extras + combined_specifier(data, row["name"])
        if requested and len(requested) <= 100 and not any(
                contradicts(str(Requirement(text).specifier)) for text in requested.values()):
            host.title = f"Install the declared dependency set together ({len(missing)} missing)"
            host.explanation = (
                "Several required dependencies are missing. Install the declared set in one resolver operation, "
                "preserving its version requirements, instead of installing one import per round. "
                "Read any installation failure before retrying; a failed batch may leave every dependency missing. "
                "Optional groups, direct references and unsupported declarations are not included.")
            host.command = [session.target_python, "-m", "pip", "install", "--only-binary=:all:",
                            *sorted(requested.values())]
            host.issue_ids = sorted({i for a in hosts for i in a.issue_ids})
            evidence(host, rows)
            actions = [a for a in actions if a not in hosts[1:]]
    # Imported installation output is historical evidence, never a successful
    # target-environment check. Connect a named failed request to its current
    # declaration instead of silently dropping the pin and installing latest.
    blockers, historical = [], set()
    events = {event.event_id: event for event in session.events}
    for issue in by_id.values():
        if issue.tool != "pip_install":
            continue
        members = [events[e] for e in issue.event_ids if e in events]
        failed = next((e for e in members if e.code in ("build_failure", "no_distribution", "python_requires")
                       and e.component), None)
        if not failed:
            continue
        name = canonicalize_name(failed.component)
        rows = [r for r in requirements_for(data, name) if r["owner"] == "project"]
        if not rows:
            continue
        installed = data["installed"].get(name)
        try:
            if installed and SpecifierSet(combined_specifier(data, name)).contains(installed):
                historical.add(issue.issue_id)
                continue
        except InvalidVersion:
            pass
        request = re.search(r"Requested requirement: (\S+)", failed.message)
        if request:
            try:
                recorded = Requirement(request[1])
                pins = [s.version for s in recorded.specifier if s.operator == "==" and "*" not in s.version]
            except InvalidRequirement:
                pins = []
            if pins and not SpecifierSet(combined_specifier(data, name)).contains(pins[0]):
                historical.add(issue.issue_id)
                continue  # The recorded failed pin has already been changed.
        requirements = "; ".join(f"{r['source']}: {r['requirement']}" for r in rows)
        blocker = Action(
            action_id="review-install-" + name, kind="manual_fix", cause="version_incompatibility",
            title=f"Review the failed installation of {name} before retrying the dependency set",
            explanation=(
                f"The imported pip log records an installation/build failure for {name}: {failed.message.strip()}. "
                f"The current declaration is {requirements}; the selected Python is {environment.get('python_version', 'unknown')}. "
                "First review and change that fixed requirement to a release compatible with the selected Python "
                "and the project's API usage, or create a separate environment using the Python version supported "
                "by the fixed dependencies. Keep the remaining requirements. Then install the complete declared "
                "set with python -m pip install --only-binary=:all: -r requirements.txt if that is its source, "
                "and rerun pip check and the original failing check. Do not install a newer package while leaving "
                "a contradictory pin in the project. An imported log may come from another environment; it does "
                "not prove every release is incompatible with the current interpreter."),
            verification="Check installation output, declared versions and the original failing check",
            issue_ids=[issue.issue_id], goal_impact=2, evidence_rank=3, cost=0,
            reason_refs=[f.fact_id for f in facts if f.subject == issue.issue_id and f.predicate == "kind"],
        )
        evidence(blocker, rows)
        if not any(b.action_id == blocker.action_id for b in blockers):
            blockers.append(blocker)
        historical.add(issue.issue_id)
    actions = [a for a in actions if a.kind == "rerun" or not a.issue_ids
               or not set(a.issue_ids) <= historical]
    if blockers:
        blocked_names = {b.action_id.removeprefix("review-install-") for b in blockers}
        # Do not leave the known failing installation as an alternative step.
        for action in actions:
            if action.command[:4] != [session.target_python, "-m", "pip", "install"]:
                continue
            for text in action.command[4:]:
                try:
                    name = canonicalize_name(Requirement(text).name)
                except InvalidRequirement:
                    continue
                if name in blocked_names:
                    action.command = []
                    action.title = "Install the dependency set after reviewing the failed requirement"
                    action.explanation = "Resolve the named installation blocker first, keeping the project declarations and environment consistent."
                    break
    return [*blockers, *actions]
