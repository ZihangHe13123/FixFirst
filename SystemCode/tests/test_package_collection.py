"""Real pytest collection probes for the bounded pkg_resources provider repair.

Additional installed-provider probes use explicitly supplied disposable Python
paths; ordinary test runs do not install or modify the developer environment.
"""

import importlib.metadata
import json
import os
import subprocess
import sys

import pytest

from fixfirst.models import Run
from fixfirst.package_compatibility import POLICY_ID
from fixfirst.reasoning import infer_and_plan
from fixfirst.service import create_session, scan


@pytest.fixture(scope='module', params=['absent', 'removed', 'old'])
def provider_python(request):
    mode = request.param
    variable = f'FIXFIRST_PKG_RESOURCES_{mode.upper()}_PYTHON'
    python = os.environ.get(variable)
    if not python and mode == 'absent' and sys.version_info[:2] == (3, 12):
        try:
            importlib.metadata.version('setuptools')
        except importlib.metadata.PackageNotFoundError:
            python = sys.executable
    if not python:
        pytest.skip(f'{variable} needs a disposable CPython 3.12 environment with pytest')
    probe = subprocess.run([python, '-c', '''import importlib.metadata as m,json,sys
try: version=m.version('setuptools')
except m.PackageNotFoundError: version=None
print(json.dumps([list(sys.version_info[:2]),version,m.version('pytest')]))
'''], capture_output=True, text=True, check=True, timeout=10)
    version, setuptools, _ = json.loads(probe.stdout)
    assert version == [3, 12]
    assert setuptools == {'absent': None, 'removed': '84.0.0', 'old': '65.7.0'}[mode]
    return mode, python


def project_case(root, layout):
    statement = ('from pkg_resources import get_distribution\n' if layout == 'from-import'
                 else 'import pkg_resources\n')
    test = 'def test_ok():\n    assert True\n'
    if layout == 'direct':
        (root / 'test_case.py').write_text(statement + test)
    elif layout == 'call':
        (root / 'test_case.py').write_text('def test_ok():\n    import pkg_resources\n')
    elif layout == 'conftest':
        (root / 'conftest.py').write_text(statement)
        (root / 'test_case.py').write_text(test)
    else:
        (root / 'consumer.py').write_text(statement)
        if layout == 'twohop':
            (root / 'bridge.py').write_text('import consumer\n')
            (root / 'test_case.py').write_text('import bridge\n' + test)
        else:
            (root / 'test_case.py').write_text('import consumer\n' + test)


def run_case(root, python, layout='direct', tool='pytest_run'):
    project_case(root, layout)
    session = create_session(root, python, goal='pass_tests' if tool == 'pytest_run' else 'collect_tests')
    scan(session, ['environment', 'project', tool])
    return session


def repair(session):
    return next(a for a in session.actions if POLICY_ID in a.rule_ids)


def has_package_command(session):
    return any(any(part.startswith('setuptools') for part in a.command[4:]) for a in session.actions)


@pytest.mark.parametrize('layout', ['direct', 'module', 'twohop', 'from-import', 'call', 'conftest'])
def test_real_pytest_import_keeps_type_and_source_contract(tmp_path, provider_python, layout):
    mode, python = provider_python
    session = run_case(tmp_path, python, layout)
    action = repair(session)
    assert has_package_command(session), action.explanation
    assert action.command[-1] == 'setuptools<82,>=66.1'
    assert action.title.startswith({'absent': 'Install', 'removed': 'Downgrade', 'old': 'Update'}[mode])
    event = next(e for e in session.events if e.tool == 'pytest_run')
    assert event.code == ('AttributeError' if mode == 'old' else 'ModuleNotFoundError')
    record = next(r for run in session.runs for r in run.records if r.get('package_failure'))
    if record['package_failure'].get('wrapper'):
        origin = record['package_failure_exception']
        assert origin['exception_type'] == event.code
        assert origin['source_file'] == record['package_failure']['file']
        assert origin['source_line'] == record['package_failure']['line']
    assert session.goal_status == 'blocked'


def test_real_collect_only_goal_also_offers_bounded_repair(tmp_path, provider_python):
    _, python = provider_python
    session = run_case(tmp_path, python, tool='pytest')
    assert has_package_command(session), repair(session).explanation
    assert session.goal_status == 'blocked'


@pytest.fixture
def missing_collection(tmp_path):
    # Keep these provenance regressions on the actual provider-absent collection
    # wrapper, independent of optional installed-provider runtime probes.
    python = os.environ.get('FIXFIRST_PKG_RESOURCES_ABSENT_PYTHON', sys.executable)
    session = run_case(tmp_path, python)
    record = next((r for run in session.runs for r in run.records
                   if r.get('package_failure', {}).get('wrapper') == 'pytest_collect_error'), None)
    if not record:
        pytest.skip('An absent pkg_resources provider is needed for this live collection probe')
    assert has_package_command(session), repair(session).explanation
    return session, record


@pytest.mark.parametrize('change', ['operation_file', 'operation_line', 'origin_file', 'origin_line',
                                  'origin_type', 'missing_origin', 'wrapper_module', 'outer_file',
                                  'event_code', 'event_node', 'grouped_event'])
def test_collection_observation_cannot_borrow_another_source_or_event(missing_collection, change):
    session, record = missing_collection
    event = next(e for e in session.events if e.tool == 'pytest_run')
    if change == 'operation_file':
        record['package_failure']['file'] = '/another/project.py'
    elif change == 'operation_line':
        record['package_failure']['line'] += 1
    elif change == 'origin_file':
        record['package_failure_exception']['source_file'] = '/another/project.py'
    elif change == 'origin_line':
        record['package_failure_exception']['source_line'] += 1
    elif change == 'origin_type':
        record['package_failure_exception']['exception_type'] = 'ImportError'
    elif change == 'missing_origin':
        record.pop('package_failure_exception')
    elif change == 'wrapper_module':
        record['exception_module'] = 'project_fake_pytest'
    elif change == 'outer_file':
        record['source_file'] = '/another/collector.py'
    elif change == 'event_code':
        event.code = 'ImportError'
    elif change == 'event_node':
        event.location = 'another_test.py'
    elif change == 'grouped_event':
        other = event.model_copy(deep=True)
        other.event_id += '-other'
        other.code = 'ImportError'
        session.events.append(other)
        next(i for i in session.issues if event.event_id in i.event_ids).event_ids.append(other.event_id)
    infer_and_plan(session)
    assert not has_package_command(session)
    assert repair(session).cause is None


@pytest.mark.parametrize('expression', [
    'raise ImportError("ModuleNotFoundError: No module named \'pkg_resources\'")',
    'raise ModuleNotFoundError("No module named \'pkg_resources\'", name="pkg_resources")',
    'raise AttributeError("ModuleNotFoundError: No module named \'pkg_resources\'")',
])
def test_real_collection_message_does_not_fabricate_failed_import(tmp_path, expression):
    (tmp_path / 'test_case.py').write_text(expression + '\n')
    session = create_session(tmp_path, sys.executable, goal='pass_tests')
    scan(session, ['environment', 'project', 'pytest_run'])
    assert not has_package_command(session)
    assert not any(r.get('package_failure') for run in session.runs for r in run.records)


def test_missing_module_parser_records_its_type_without_metadata():
    from fixfirst.parsers import parse
    run = Run(tool='pytest_run', exit_code=2, records=[
        {'type': 'exception', 'stage': 'collect', 'nodeid': 'test_case.py',
         'exception_type': 'CollectError', 'exception_module': '_pytest.nodes',
         'exception_message': "ModuleNotFoundError: No module named 'pkg_resources'"},
        {'type': 'failure', 'stage': 'collect', 'nodeid': 'test_case.py',
         'message': "E   ModuleNotFoundError: No module named 'pkg_resources'"},
    ])
    events = parse(run)
    assert len(events) == 1 and events[0].code == 'ModuleNotFoundError'
    assert not run.records[0].get('package_failure')
