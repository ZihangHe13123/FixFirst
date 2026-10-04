"""Issue-bound import-path candidates from executed failures and static snapshots."""

import ast

from .local_imports import candidate_matches
from .models import check_scope
from .runner import environment_id


def for_issue(session, issue, project_run, project, environment):
    """Do not let one issue's local name donate ownership to another issue.

    The new layout index is only used for a direct import in project/test code,
    with a unique exact candidate and no external provider. Old/imported or
    grouped conflicting failures keep the existing generic review route.
    """
    from .evidence import issue_evidence

    current = environment_id(session.target_python)
    env_run = next((r for r in session.runs if r.run_id == environment.get('_run_id')), None)
    latest_env = next((r for r in reversed(session.runs) if r.tool == 'environment'), None)
    latest_project = next((r for r in reversed(session.runs) if r.tool == 'project'), None)
    run = next((r for r in reversed(session.runs) if r.tool == issue.tool), None)
    if (not project_run or project_run is not latest_project or not env_run or latest_env is not env_run
            or not run or issue.environment_id != current or run.scope != issue.scope
            or run.scope != check_scope(session, issue.tool)
            or project_run.cwd != session.project_root or run.cwd != session.project_root
            or any(r.source != 'executed' or r.status != 'completed' or r.truncated
                   or r.environment_id != current for r in (project_run, env_run, run))
            or project_run.exit_code != 0 or not env_run.verified_pass or run.exit_code in (0, None)
            or session.runs.index(env_run) >= session.runs.index(run)):
        return None
    events = [e for e in session.events if e.event_id in issue.event_ids]
    if (not events or len(events) != len(issue.event_ids)
            or any(e.run_id != run.run_id or e.tool != issue.tool for e in events)):
        return None
    rows, refs = [], []
    for event in events:
        if not event.evidence_refs:
            return None
        for ref in event.evidence_refs:
            owner, _, suffix = ref.partition(':')
            if owner != run.run_id:
                return None
            if suffix.startswith('probe:'):
                index = suffix.removeprefix('probe:')
                if not index.isdigit() or int(index) >= len(run.records):
                    return None
                row = run.records[int(index)]
                if (row.get('type') not in {'exception', 'failure'}
                        or row.get('nodeid') != event.location or row.get('stage') != event.stage):
                    return None
        detail = issue_evidence(session, issue.model_copy(update={'event_ids': [event.event_id]}))
        module = detail.get('missing_module')
        if (detail.get('exception') != 'ModuleNotFoundError' or not module
                or detail.get('raised_in') not in {'project', 'test'}):
            return None
        try:
            tree = ast.parse(detail.get('precise_statement') or detail.get('source_statement') or '')
        except (SyntaxError, ValueError):
            return None
        if len(tree.body) != 1:
            return None
        node = tree.body[0]
        names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                 [node.module] if isinstance(node, ast.ImportFrom) and not node.level and node.module else [])
        if not any(name == module or name.startswith(module + '.') for name in names):
            return None
        candidates = candidate_matches(module, project, environment)
        if len(candidates) != 1:
            return None
        if (candidates[0].get('source') == 'test-helper-layout'
                and (detail.get('raised_in') != 'test'
                     or not detail.get('source_location', '').replace('\\', '/').startswith('tests/'))):
            return None
        rows.append(candidates[0])
        refs.extend(event.evidence_refs)
    if any(row != rows[0] for row in rows[1:]):
        return None
    return {**rows[0], 'refs': list(dict.fromkeys([
        *refs, f'{project_run.run_id}:stdout:1', f'{env_run.run_id}:stdout:1']))}
