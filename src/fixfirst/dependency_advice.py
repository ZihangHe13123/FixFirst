"""Constrain installation advice using recorded project and environment facts."""

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion
import re

from .dependency_context import bounded_adjustment, combined_specifier, context, contradicts, requirements_for
from .models import Action
from .install_feedback import declarations_key, has_prepared_wheel, offer_build


def refine(session, actions, by_id, facts):
    from .evidence import current_environment, observed, project_index

    environment = current_environment(session)
    project_run, project = project_index(session)
    data = context(environment, {**project, "_run_id": project_run.run_id if project_run else None})
    consumer_context = {a.action_id: a.explanation for a in actions if "P83" in a.rule_ids}
    migrated_issues = {i for a in actions if a.action_id in consumer_context for i in a.issue_ids}
    if migrated_issues:
        actions = [a for a in actions if a.action_id in consumer_context or a.kind == "rerun"
                   or not migrated_issues.intersection(a.issue_ids)]

    def evidence(action, rows):
        for row in rows:
            fact = observed("dist:" + row["name"], "repair_constraint",
                            f"{row['source']}: {row['requirement']}", row["refs"])
            if not any(f.fact_id == fact.fact_id for f in facts):
                facts.append(fact)
            if fact.fact_id not in action.reason_refs:
                action.reason_refs.append(fact.fact_id)

    excluded_searches, trials = {}, {}
    for action in actions:
        if action.check != "version_search" or len(action.targets) != 2:
            continue
        name = canonicalize_name(action.targets[0])
        installed = data["installed"].get(name)
        rows = requirements_for(data, name)
        if not installed or not contradicts(combined_specifier(data, name, f"<{installed}")):
            continue
        evidence(action, rows)
        action.action_id = "review-release-constraints-" + name
        action.kind, action.check, action.targets = "manual_fix", None, []
        action.title = f"Review the {name} requirement and Python version before searching older releases"
        action.explanation = (
            f"No version below the installed {name} {installed} can satisfy these recorded constraints: "
            + "; ".join(f"{r['source']} requires {r['requirement']}" for r in rows)
            + f". The current failure was observed with Python {environment.get('python_version', 'unknown')}. "
            "Do not repeatedly downgrade and then upgrade. If the legacy pin must stay, create a separate "
            "environment using the Python version documented for that dependency set. Otherwise revise the "
            "conflicting declaration and its dependent packages together, then check installation and rerun "
            "the original failure. This rules out this constrained older-version search; it does not prove "
            "that no other repair or interpreter combination exists.")
        if name in excluded_searches:
            first = excluded_searches[name]
            first.issue_ids = sorted(set(first.issue_ids + action.issue_ids))
            first.reason_refs = sorted(set(first.reason_refs + action.reason_refs))
        else:
            excluded_searches[name] = action
            # An impossible downgrade under a pin supplies no evidence for an
            # upgrade. Old consumers may omit upper bounds yet break at runtime.
    if excluded_searches:
        actions = [a for a in actions if not a.action_id.startswith("review-release-constraints-")
                   or any(a is first for first in excluded_searches.values())]

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
                f"Keeping this fixed requirement while changing only {name} cannot satisfy both requirements; "
                "a coordinated declaration and dependency update may work.")
            trials[action.action_id] = (name, str(Requirement(requested).specifier))
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
    # A missing test runner can prevent collection before any project import is
    # observed. The selected goal itself supplies evidence that this tool is needed.
    goal_tool = {"pass_tests": "pytest", "collect_tests": "pytest", "check_style": "ruff"}.get(session.goal)
    tool_issues = [i for i in by_id.values() if i.stage == "tool" and i.component == goal_tool
                   and i.kind == "tool_failure"] if goal_tool else []
    if tool_issues and goal_tool not in data["installed"]:
        actions = [a for a in actions if a.kind == "rerun" or not set(a.issue_ids) & {i.issue_id for i in tool_issues}]
        actions.append(Action(action_id="install-runner-" + goal_tool, kind="manual_fix",
            title=f"Install {goal_tool} for the selected check",
            explanation=f"The selected check could not start because {goal_tool} is absent in its interpreter.",
            verification="Run the original check with the same interpreter",
            command=[session.target_python, "-m", "pip", "install", goal_tool],
            issue_ids=[i.issue_id for i in tool_issues], cause="missing_dependency", goal_impact=2, evidence_rank=3))
        missing.add(goal_tool)
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
        requested, extras_by_name = {}, {}
        for row in project.get("declarations", []):
            if (row.get("constraint") or row.get("group") != "required"
                    or row.get("status") not in ("missing", "satisfied", "version_mismatch")
                    or row.get("installer", "pip") != "pip"):
                continue
            requirement = Requirement(row["requirement"])
            combined_extras = extras_by_name.setdefault(row["name"], set())
            combined_extras.update(requirement.extras)
            extras = "[" + ",".join(sorted(combined_extras)) + "]" if combined_extras else ""
            requested[row["name"]] = requirement.name + extras + combined_specifier(data, row["name"])
        if requested and len(requested) <= 100 and not any(
                contradicts(str(Requirement(text).specifier)) for text in requested.values()):
            if tool_issues and goal_tool not in requested:
                requested[goal_tool] = goal_tool
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
    indirect_blocker = False
    events = {event.event_id: event for event in session.events}
    # Read the latest named failure per package first. A failed manual source
    # build supersedes the older wheel-only miss that led to that build.
    seen_blockers, conflict_ids = set(), set()
    run_order = {r.run_id: n for n, r in enumerate(session.runs)}
    for issue in sorted(by_id.values(), key=lambda i: max(
            (run_order.get(events[e].run_id, -1) for e in i.event_ids if e in events), default=-1), reverse=True):
        if issue.tool != "pip_install":
            continue
        members = [events[e] for e in issue.event_ids if e in events]
        source_runs = [r for r in session.runs if r.run_id in {e.run_id for e in members}]
        if source_runs and any((rec.get("declarations") != declarations_key(project)
                or rec.get("environment_id") != source_runs[-1].environment_id
                or rec.get("python_version") != environment.get("python_version"))
                for rec in source_runs[-1].records if rec.get("type") == "installation_context"):
            historical.add(issue.issue_id)
            continue
        if issue.kind == "dependency_conflict":
            raw = (source_runs[-1].stdout + "\n" + source_runs[-1].stderr) if source_runs else issue.title
            lines = raw.splitlines()
            details = []
            for n, text in enumerate(lines):
                if re.search(r"conflict is caused|Cannot install|ResolutionImpossible|depends on", text, re.I):
                    details.extend(lines[n:n + 5])
            blockers.append(Action(action_id="review-install-conflict", kind="manual_fix",
                title="Resolve the conflicting requirements reported by pip",
                explanation="The recorded resolver found incompatible requests: " + "\n".join(dict.fromkeys(details))[:2500]
                    + ". Review the named requirements and their declaration locations together before retrying. "
                    "This is a version-constraint conflict; building a source package or changing build tools "
                    "does not resolve it. The failed installation command must not be repeated unchanged.",
                verification="Resolve the named requirements, then check dependencies and the original goal",
                issue_ids=[issue.issue_id], goal_impact=2, evidence_rank=3, cost=0))
            conflict_ids.add(issue.issue_id)
            historical.add(issue.issue_id)
            continue
        failed = next((e for e in members if e.code in ("build_failure", "no_distribution", "no_wheel", "python_requires",
                                                       "missing_build_tool", "legacy_build_config")
                       and e.component), None)
        if not failed:
            continue
        name = canonicalize_name(failed.component)
        if name in seen_blockers:
            historical.add(issue.issue_id)
            continue
        seen_blockers.add(name)
        rows = [r for r in data["requirements"] if r["name"] == name and r["owner"] == "project"]
        bound_log = source_runs and any(rec.get("type") == "installation_context"
                                       for rec in source_runs[-1].records)
        if not rows and not bound_log:
            continue
        request = (re.search(r"Requested requirement: (\S+)", failed.message)
                   or re.search(r"No matching distribution found for (\S+)", failed.message, re.I))
        recorded = None
        if request:
            try:
                recorded = Requirement(request[1].rstrip("."))
                if recorded.url or canonicalize_name(recorded.name) != name:
                    recorded = None
            except InvalidRequirement:
                pass
        requested_range = str(recorded.specifier) if recorded and not rows else ""
        requirement = name + combined_specifier(data, name, requested_range)
        if (failed.code == "no_wheel"
                and has_prepared_wheel(session, requirement)):
            historical.add(issue.issue_id)
            continue
        installed = data["installed"].get(name)
        try:
            if installed and Requirement(requirement).specifier.contains(installed):
                historical.add(issue.issue_id)
                continue
        except InvalidVersion:
            pass
        if recorded and rows:
            pins = [s.version for s in recorded.specifier if s.operator == "==" and "*" not in s.version]
            still_pinned = any(s.operator == "==" and s.version in pins
                               for row in rows for s in SpecifierSet(row["specifier"]))
            if pins and not still_pinned:
                historical.add(issue.issue_id)
                continue  # The recorded failed pin has already been changed.
        requirements = "; ".join(f"{r['source']}: {r['requirement']}" for r in rows)
        if not rows:
            requirements = requirement + " (requested by pip in this session's recorded command)"
            indirect_blocker = True
        blocker = Action(
            action_id="review-install-" + name, kind="manual_fix",
            title=f"Review the failed installation of {name} before retrying the dependency set",
            explanation=(
                f"The imported pip log records an installation/build failure for {name}: {failed.message.strip()}. "
                f"The current declaration is {requirements}; the selected Python is {environment.get('python_version', 'unknown')}. "
                "Use the build output to decide the next change. An explicit dependency trial can propose "
                "a replacement for a versioned declaration while preserving the other requirements; it "
                "must record the chosen set before recommending an installation. Keep declarations and "
                "installed versions consistent, then rerun pip check and the original failing check. "
                "An imported log may come from another environment; this failure alone does not establish "
                "that the selected Python is unsupported or that all releases of this package are incompatible."),
            verification="Check installation output, declared versions and the original failing check",
            issue_ids=[issue.issue_id], goal_impact=2, evidence_rank=3, cost=0,
            reason_refs=[f.fact_id for f in facts if f.subject == issue.issue_id and f.predicate == "kind"],
        )
        evidence(blocker, rows)
        trial = bool(rows)
        if failed.code == "legacy_build_config":
            trial = False
            blocker.title = f"Update the legacy build configuration of {name}"
            blocker.explanation = (
                f"The build reports: {failed.message.strip()}. This is a build-backend/configuration failure. "
                "Changing the project Python alone will not change the backend selected in pip's isolated "
                "build environment. Use the package's documented supported build-backend version in a separate "
                "build environment, or migrate the dependency; keep this failure log. Do not repeat the "
                "same source build. No compatible build or alternative release has been verified.")
        elif failed.code == "missing_build_tool":
            trial = False
            blocker.title = f"Provide the build prerequisite reported while installing {name}"
            blocker.explanation = (
                f"The installation log reports: {failed.message.strip()}. Current declaration: {requirements}. "
                "This is evidence of a missing build prerequisite, not evidence that another Python or "
                "package version is required. Provide the named tool/header in the environment used to build, "
                "then retry the declared installation and Check again.")
            if name in ("psycopg2", "psycopg2-binary") and "pg_config" in failed.message:
                blocker.explanation += (
                    " pg_config comes from the PostgreSQL client development tools and must be on PATH "
                    "during a source build. For a local development environment, the upstream psycopg2-binary "
                    "distribution is an alternative providing the same psycopg2 import. If choosing that "
                    "route, change the psycopg2 declaration to psycopg2-binary, retaining any version range, "
                    "before installing; do not install both distributions. The binary route still needs "
                    "a wheel compatible with this interpreter. Source: https://www.psycopg.org/docs/install/")
        elif failed.code == "no_distribution":
            trial = False
            blocker.title = f"Check the requested {name} release and package index"
            blocker.explanation = (
                f"pip reports: {failed.message.strip()}. Current declaration: {requirements}. "
                "The recorded output does not establish that a matching source archive is available. "
                "Check the package spelling, configured index, version and interpreter compatibility. "
                "No source-build command or replacement version is justified yet; do not repeat the same request.")
        elif failed.code == "no_wheel":
            offered = offer_build(session, blocker, requirement,
                "The wheel-only installation request found no matching distribution. This may be a "
                "missing wheel or an unavailable version; it does not establish a Python incompatibility.")
            trial = bool(rows) and not offered
        if not rows:
            blocker.explanation += (
                f" The logged requirement {requirement} is an indirect dependency, not a direct project declaration. "
                "Its failure came from this session's proposed pip command with unchanged declarations. "
                "Preserve the project's direct requirements; no change to this indirect dependency's "
                "version range or application compatibility has been verified.")
        if not any(b.action_id == blocker.action_id for b in blockers):
            blockers.append(blocker)
            if trial:
                trials[blocker.action_id] = (name, "")
        historical.add(issue.issue_id)
    actions = [a for a in actions if a.kind == "rerun" or not a.issue_ids
               or not set(a.issue_ids) <= historical]
    if conflict_ids or indirect_blocker:
        actions = [a for a in actions if a.command[:4] != [session.target_python, "-m", "pip", "install"]]
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
    result = [*blockers, *actions]
    # A known alternative distribution can supply the import without satisfying
    # the project's differently named requirement. Resolve the visible mismatch
    # before a trial blindly reinstalls the original distribution.
    binary = data["installed"].get("psycopg2-binary")
    source_rows = [r for r in data["requirements"] if r["name"] == "psycopg2" and r["owner"] == "project"]
    providers = {canonicalize_name(n) for n in environment.get("import_distributions", {}).get("psycopg2", [])}
    if binary and "psycopg2" not in data["installed"] and source_rows and providers == {"psycopg2-binary"} and trials:
        for action in result:
            if action.action_id in trials:
                action.kind, action.check, action.targets, action.command = "manual_fix", None, [], []
                places = "; ".join(f"{r['source']}: {r['requirement']}" for r in source_rows)
                action.title = "Align the psycopg2 declaration with the installed binary distribution"
                action.explanation = (
                    f"The selected environment has psycopg2-binary {binary} providing the psycopg2 import, "
                    f"but the project still declares {places}. The resolver treats these as distinct "
                    "distributions and would install psycopg2 again. If this local development setup "
                    "intentionally uses the binary distribution, replace psycopg2 with psycopg2-binary "
                    "at those declaration locations, keeping its version range, then Check again. "
                    "Otherwise restore the source distribution and its documented build prerequisites. "
                    "Do not install both together. This is a declaration change requiring review; "
                    "no code/test success is implied. Source: https://www.psycopg.org/docs/install/")
                evidence(action, source_rows)
        trials = {}
    from .dependency_resolution import advise

    for action in result:
        if action.action_id in trials:
            name, direction = trials[action.action_id]
            trial_run = advise(session, action, environment, project, name, direction)
            if trial_run:
                fact = observed("dist:" + name, "dependency_trial", trial_run.run_id,
                                [f"{trial_run.run_id}:stdout:1"])
                facts.append(fact)
                action.reason_refs.append(fact.fact_id)
        if action.action_id in consumer_context and not action.explanation.startswith(consumer_context[action.action_id]):
            action.explanation = consumer_context[action.action_id] + " " + action.explanation
        if (project.get("conda_declarations") and action.kind != "rerun"
                and action.cause in (None, "missing_dependency") and action.goal_impact > 0):
            unresolved = "; ".join(f"{r['source']}: {r['requirement']}" for r in project["conda_declarations"][:8])
            action.explanation += (
                " Also declared in the Conda environment file, without an assumed PyPI equivalent: "
                + unresolved + ". Use the project's Conda environment instructions, or confirm each PyPI "
                "distribution name before installing into this interpreter. These entries are not included "
                "in a pip installation command.")
    if any("hash-checked requirements" in n for n in project.get("notes", [])):
        for action in result:
            if action.command[:4] in ([session.target_python, "-m", "pip", "install"],
                                     [session.target_python, "-m", "pip", "wheel"]):
                action.command = []
                action.title = "Preserve the project's hash-checked installation requirements"
                action.explanation = (
                    "This project pins distribution archive hashes. Use its original requirements or lock "
                    "file and documented installer; rebuilding a wheel changes the archive hash. "
                    "FixFirst cannot generate a replacement installation/build command that preserves those "
                    "checks. Review the failed artifact and update the lock through the project's workflow.")
    return result
