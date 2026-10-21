"""Bounded pkg_resources repair policy and negative provenance boundaries."""

import json
from pathlib import Path
import sys

from packaging.markers import default_environment
from packaging.requirements import Requirement
import pytest

from fixfirst import domain
from fixfirst.package_compatibility import POLICY_ID
from fixfirst.models import Execution, Run, Session, check_scope
from fixfirst.reasoning import infer_and_plan
from fixfirst.runner import environment_id
from fixfirst.service import create_session, ingest, scan


def setup_case(root, mode='old', *, tool='python_run', requirement='', mutate=None):
    python = str(root / '.venv/bin/python')
    lib, stdlib = str(root / '.venv/lib/python3.12/site-packages'), '/python/lib/python3.12'
    identity = environment_id(python)
    packages = [] if mode == 'absent' else [{'name': 'setuptools', 'version': '65.7.0' if mode == 'old' else '84.0.0', 'requires': []}]
    env = {'python_version': '3.12.13', 'packages': packages,
           'markers': {**default_environment(), 'implementation_name': 'cpython',
                       'python_version': '3.12', 'python_full_version': '3.12.13'},
           'paths': {'purelib': lib, 'platlib': lib, 'stdlib': stdlib},
           'stdlib_modules': ['pkgutil'],
           'import_distributions': {'pkg_resources': ['setuptools']} if mode == 'old' else {}}
    env_run = Run(tool='environment', environment_id=identity, exit_code=0)
    project = {'files': [], 'declarations': [], 'local_modules': [], 'python_files': ['main.py'],
               'requires_python': [], 'environment_run_id': env_run.run_id}
    if requirement:
        project['declarations'] = [{'name': 'setuptools', 'requirement': requirement, 'group': 'required',
                                    'source': 'requirements.txt:3', 'status': 'satisfied'}]
    project_run = Run(tool='project', environment_id=identity, scope='declarations:project', exit_code=0)
    session = Session(name='compatibility', project_root=str(root), target_python=python,
                      goal='run_project' if tool == 'python_run' else 'pass_tests',
                      execution=Execution(entry='main.py') if tool == 'python_run' else None)
    if mode == 'old':
        file, code = lib + '/pkg_resources/__init__.py', 'AttributeError'
        message = "module 'pkgutil' has no attribute 'ImpImporter'"
        operation = {'mechanism': 'pkgutil_impimporter', 'module': 'pkgutil', 'consumer': 'pkg_resources',
                     'module_file': stdlib + '/pkgutil.py', 'file': file, 'line': 2191, 'source': 'failed_instruction'}
        text = f'Traceback (most recent call last):\n  File "{file}", line 2191, in <module>\n    register_finder(pkgutil.ImpImporter, find_on_path)\nAttributeError: {message}\n'
    else:
        file, code, message = str(root / 'main.py'), 'ModuleNotFoundError', "No module named 'pkg_resources'"
        operation = {'mechanism': 'missing_pkg_resources', 'module': 'pkg_resources', 'file': file,
                     'line': 1, 'source': 'failed_instruction'}
        text = f'Traceback (most recent call last):\n  File "{file}", line 1, in <module>\n    import pkg_resources\nModuleNotFoundError: {message}\n'
    stage = 'run' if tool == 'python_run' else 'collect'
    records = [{'type': 'failure', 'stage': stage, 'nodeid': '', 'message': text},
               {'type': 'exception', 'stage': stage, 'nodeid': '', 'exception_type': code,
                'exception_message': message, 'source_file': file, 'source_line': operation['line'],
                'package_failure': {**operation, 'exception_type': code}}]
    run = Run(tool=tool, environment_id=identity, scope=check_scope(session, tool),
              exit_code=1, records=records, stderr=text, execution_kind='script' if tool == 'python_run' else '')
    if mutate:
        mutate(env, project, run)
    env_run.stdout, project_run.stdout = json.dumps(env), json.dumps(project)
    session.environment = {**env, '_run_id': env_run.run_id, '_environment_id': identity}
    ingest(session, [env_run, run, project_run])
    return session, run


def action(session):
    return next(a for a in session.actions if POLICY_ID in a.rule_ids)


def setuptools_requests(session):
    found = []
    for a in session.actions:
        for word in a.command[4:]:
            if word.startswith('setuptools'):
                found.append(Requirement(word))
    return found


@pytest.mark.parametrize('mode,direction', [('old', 'Update'), ('absent', 'Install'), ('removed', 'Downgrade')])
@pytest.mark.parametrize('tool', ['python_run', 'pytest_run'])
def test_observed_provider_repair_has_both_bounds_and_normal_manual_feedback(tmp_path, mode, direction, tool):
    session, _ = setup_case(tmp_path, mode, tool=tool)
    repair = action(session)
    assert repair.title.startswith(direction)
    requests = setuptools_requests(session)
    assert len(requests) == 1
    assert '66.1' in requests[0].specifier and '81.0' in requests[0].specifier
    assert '65.7' not in requests[0].specifier and '82' not in requests[0].specifier
    assert '--log' in repair.command and '--only-binary=:all:' in repair.command
    cause = 'missing_dependency' if mode == 'absent' else 'version_incompatibility'
    assert repair.cause == cause
    assert next(i for i in session.issues if i.tool == tool).diagnosis == cause
    assert next(i for i in session.issues if i.tool == tool).diagnosis_rule == POLICY_ID
    assert session.installation_attempts
    assert any(a.kind == 'rerun' and a.check == tool for a in session.actions)
    for fact in session.facts:
        if fact.subject == POLICY_ID:
            assert domain.source(fact.evidence_refs[0])['url'].startswith('https://')


@pytest.mark.parametrize('pin', ['setuptools==65.7.0', 'setuptools>=82', 'setuptools<66.1', 'setuptools~=65.7'])
def test_project_pin_empty_intersection_cannot_reopen_unbounded_trial(tmp_path, pin):
    session, _ = setup_case(tmp_path, requirement=pin)
    assert not setuptools_requests(session)
    assert not action(session).command
    assert 'requirements.txt:3' in action(session).explanation and pin in action(session).explanation
    assert not any(a.check in {'version_search', 'dependency_resolve'} for a in session.actions)


def test_reverse_dependency_pin_and_target_markers_are_kept(tmp_path):
    def change(env, project, run):
        env['packages'].append({'name': 'legacy-consumer', 'version': '1.0', 'requires': [
            'setuptools<70; python_version == "3.12"', 'setuptools>=82; python_version >= "3.13"']})
    session, _ = setup_case(tmp_path, mutate=change)
    spec = setuptools_requests(session)[0].specifier
    assert '66.1' in spec and '70' not in spec
    assert 'legacy-consumer 1.0 Requires-Dist' in action(session).explanation


def test_transitive_conflict_names_its_source(tmp_path):
    def change(env, project, run):
        env['packages'].append({'name': 'legacy-consumer', 'version': '1.0', 'requires': ['setuptools==65.7.0']})
    session, _ = setup_case(tmp_path, mutate=change)
    assert not action(session).command
    assert 'legacy-consumer 1.0 Requires-Dist' in action(session).explanation


@pytest.mark.parametrize('change', ['imported', 'stale', 'truncated', 'missing_record', 'foreign_package',
                                  'foreign_pkgutil', 'ambiguous', 'local', 'old_record', 'wrong_type', 'wrong_line'])
def test_uncertain_owner_or_provenance_never_suggests_setuptools_change(tmp_path, change):
    def mutate(env, project, run):
        if change == 'wrong_type':
            run.records[1]['exception_type'] = 'ValueError'
        elif change == 'wrong_line':
            run.records[1]['source_line'] = 999
        elif change == 'imported':
            run.source = 'imported'
        elif change == 'stale':
            run.environment_id = 'another-interpreter'
        elif change == 'truncated':
            run.truncated = True
        elif change == 'missing_record':
            run.records[1].pop('package_failure')
        elif change == 'foreign_package':
            run.records[1]['package_failure']['file'] = '/other/site-packages/pkg_resources/__init__.py'
        elif change == 'foreign_pkgutil':
            run.records[1]['package_failure']['module_file'] = str(tmp_path / 'pkgutil.py')
        elif change == 'ambiguous':
            env['import_distributions']['pkg_resources'].append('another-provider')
        elif change == 'local':
            project['local_modules'] = [{'name': 'pkgutil', 'path': 'pkgutil.py'}]
        elif change == 'old_record':
            run.records[1]['stage'] = 'different_failure'
    session, _ = setup_case(tmp_path, mutate=mutate)
    assert not setuptools_requests(session)
    assert all(a.cause is None for a in session.actions if POLICY_ID in a.rule_ids)


@pytest.mark.parametrize('python,implementation', [('3.11.9', 'cpython'), ('3.13.0', 'cpython'),
                                                 ('3.12.13', 'pypy'), ('3.12.0rc1', 'cpython')])
def test_unvalidated_python_receives_review_without_command(tmp_path, python, implementation):
    def change(env, project, run):
        env['python_version'] = python
        env['markers']['implementation_name'] = implementation
    session, _ = setup_case(tmp_path, mutate=change)
    assert not action(session).command
    assert 'limited to CPython' in action(session).explanation


def test_requires_python_conflict_is_a_source_specific_review(tmp_path):
    def change(env, project, run):
        project['requires_python'] = [{'source': 'pyproject.toml [project.requires-python]', 'specifier': '<3.12'}]
    session, _ = setup_case(tmp_path, mutate=change)
    assert not action(session).command
    assert 'pyproject.toml [project.requires-python]' in action(session).explanation


def test_environment_refresh_invalidates_failure_until_same_scope_rerun(tmp_path):
    session, _ = setup_case(tmp_path)
    env = {k: v for k, v in session.environment.items() if not k.startswith('_')}
    refresh = Run(tool='environment', environment_id=environment_id(session.target_python), exit_code=0, stdout=json.dumps(env))
    ingest(session, [refresh])
    assert not setuptools_requests(session)


def test_same_scope_and_newest_run_are_required(tmp_path):
    session, _ = setup_case(tmp_path)
    session.execution.args = ['different']
    infer_and_plan(session)
    assert not setuptools_requests(session)


def test_failed_generated_install_uses_feedback_without_retrying_the_range(tmp_path):
    from fixfirst.evidence import project_index
    from fixfirst.install_feedback import collect_feedback
    session, _ = setup_case(tmp_path)
    repair = action(session)
    log = Path(repair.command[repair.command.index('--log') + 1])
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('Using pip 26.2.1\nERROR: No matching distribution found for setuptools<82,>=66.1\n')
    feedback = collect_feedback(session, project_index(session)[1])
    assert len(feedback) == 1
    ingest(session, feedback)
    assert not setuptools_requests(session)
    assert any(a.action_id == 'review-install-setuptools' for a in session.actions)
    assert not any(a.check == 'dependency_resolve' for a in session.actions)
    assert session.goal_status != 'achieved'


def test_other_missing_declarations_do_not_strip_the_provider_bounds(tmp_path):
    def change(env, project, run):
        project['declarations'] = [
            {'name': name, 'requirement': name, 'group': 'required', 'status': 'missing',
             'source': f'requirements.txt:{line}'}
            for line, name in enumerate(['setuptools', 'another-missing-package'], 1)]
    session, _ = setup_case(tmp_path, 'absent', mutate=change)
    requests = setuptools_requests(session)
    assert len(requests) == 1 and '82' not in requests[0].specifier and '66.1' in requests[0].specifier


@pytest.mark.parametrize('code', ["raise ModuleNotFoundError(\"No module named 'pkg_resources'\", name='pkg_resources')\n",
                                "import unrelated_missing_pkg_resources\n",
                                "import pkgutil\npkgutil.ImpImporter\n"])
def test_actual_wrong_missing_module_manual_raise_and_direct_stdlib_use(tmp_path, code):
    (tmp_path / 'main.py').write_text(code)
    session = create_session(tmp_path, sys.executable, goal='run_project', execution=Execution(entry='main.py'))
    scan(session, ['environment', 'project', 'python_run'])
    assert not setuptools_requests(session)
    if 'pkgutil.ImpImporter' in code:
        assert not any(POLICY_ID in a.rule_ids for a in session.actions)
        assert any(a.kind != 'rerun' for a in session.actions)


def test_policy_never_changes_model_file(tmp_path):
    model = Path(__file__).resolve().parents[1] / 'src/fixfirst/knowledge/diagnosis_tree.json'
    before = model.read_bytes()
    session, _ = setup_case(tmp_path)
    assert setuptools_requests(session)
    assert model.read_bytes() == before
