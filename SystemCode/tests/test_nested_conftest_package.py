"""Bounded real ConftestImportFailure support; no arbitrary wrapper unwrapping."""

import os
from pathlib import Path
import sys

import pytest

from fixfirst import _runtime_evidence
from fixfirst.package_compatibility import POLICY_ID
from fixfirst.reasoning import infer_and_plan
from fixfirst.service import create_session, scan
from test_package_collection import provider_python, has_package_command, repair  # noqa: F401


def nested_case(root, python, *, tool='pytest_run', statement='import pkg_resources\n'):
    folder = root / 'nested' / 'suite'
    folder.mkdir(parents=True)
    (folder / 'conftest.py').write_text(statement)
    (folder / 'test_case.py').write_text('def test_ok():\n    assert True\n')
    session = create_session(root, python, goal='pass_tests' if tool == 'pytest_run' else 'collect_tests')
    scan(session, ['environment', 'project', tool])
    return session


@pytest.mark.parametrize('tool', ['pytest', 'pytest_run'])
@pytest.mark.parametrize('statement', ['import pkg_resources\n', 'from pkg_resources import get_distribution\n'])
def test_real_nested_conftest_retains_provider_failure_in_both_scopes(tmp_path, provider_python, tool, statement):  # noqa: F811
    mode, python = provider_python
    session = nested_case(tmp_path, python, tool=tool, statement=statement)
    action = repair(session)
    assert has_package_command(session), action.explanation
    assert action.command[-1] == 'setuptools<82,>=66.1'
    assert action.title.startswith({'absent': 'Install', 'removed': 'Downgrade', 'old': 'Update'}[mode])
    event = next(e for e in session.events if e.tool == tool)
    assert event.code == 'ConftestImportFailure' and event.stage == 'collect'
    record = next(r for run in session.runs for r in run.records if r.get('package_failure'))
    operation, origin = record['package_failure'], record['package_failure_exception']
    assert operation['wrapper'] == 'pytest_conftest_import_failure'
    assert record['exception_type'] == 'ConftestImportFailure'
    assert record['exception_module'] == '_pytest.config'
    assert record['nodeid'] == event.location
    assert event.source_file == record['source_file'] == record['traceback_frames'][-1]['file']
    assert origin['exception_type'] == ('AttributeError' if mode == 'old' else 'ModuleNotFoundError')
    assert origin['source_file'] == operation['file'] and origin['source_line'] == operation['line']
    assert session.goal_status == 'blocked'


@pytest.fixture
def nested_failure(tmp_path):
    python = os.environ.get('FIXFIRST_PKG_RESOURCES_ABSENT_PYTHON', sys.executable)
    session = nested_case(tmp_path, python)
    record = next((r for run in session.runs for r in run.records
                   if r.get('package_failure', {}).get('wrapper') == 'pytest_conftest_import_failure'), None)
    if not record:
        pytest.skip('A disposable provider-absent Python is needed for this nested conftest probe')
    assert has_package_command(session), repair(session).explanation
    return session, record


@pytest.mark.parametrize('change', ['fake_module', 'fake_type', 'wrapper_tag', 'malformed_tag',
                                  'origin_file', 'origin_line', 'origin_type', 'outer_file',
                                  'outer_function', 'wrong_site_packages', 'event_source',
                                  'event_line', 'event_type', 'event_node', 'event_stage',
                                  'record_stage', 'imported', 'foreign_environment'])
def test_nested_wrapper_cannot_borrow_type_source_or_run(nested_failure, change):
    session, record = nested_failure
    event = next(e for e in session.events if e.tool == 'pytest_run')
    run = next(r for r in session.runs if r.run_id == event.run_id)
    if change == 'fake_module':
        record['exception_module'] = 'project_pytest'
    elif change == 'fake_type':
        record['exception_type'] = 'ProjectConftestImportFailure'
    elif change in {'wrapper_tag', 'malformed_tag'}:
        record['package_failure']['wrapper'] = 'pytest_collect_error' if change == 'wrapper_tag' else {}
    elif change == 'origin_file':
        record['package_failure_exception']['source_file'] = '/another/conftest.py'
    elif change == 'origin_line':
        record['package_failure_exception']['source_line'] += 1
    elif change == 'origin_type':
        record['package_failure_exception']['exception_type'] = 'ImportError'
    elif change == 'outer_file':
        record['source_file'] = '/another/collector.py'
    elif change == 'outer_function':
        record['traceback_frames'][-1]['function'] = 'project_wrapper'
    elif change == 'wrong_site_packages':
        path = '/different/env/site-packages/_pytest/config/__init__.py'
        record['source_file'] = record['traceback_frames'][-1]['file'] = event.source_file = path
    elif change == 'event_source':
        event.source_file = '/another/collector.py'
    elif change == 'event_line':
        event.source_line += 1
    elif change == 'event_type':
        event.code = 'ModuleNotFoundError'
    elif change == 'event_node':
        event.location = 'another/suite'
    elif change == 'event_stage':
        event.stage = 'call'
    elif change == 'record_stage':
        record['stage'] = 'call'
    elif change == 'imported':
        run.source = 'imported'
    elif change == 'foreign_environment':
        run.environment_id = 'different-interpreter'
    infer_and_plan(session)
    assert not has_package_command(session)
    assert all(a.cause is None for a in session.actions if POLICY_ID in a.rule_ids)


@pytest.mark.parametrize('statement', [
    'import yaml\n',
    'import importlib\nimportlib.import_module("pkg_resources")\n',
    'raise ModuleNotFoundError("No module named \'pkg_resources\'", name="pkg_resources")\n',
    'class ConftestImportFailure(Exception):\n    pass\nraise ConftestImportFailure("No module named \'pkg_resources\'")\n',
    'from _pytest.config import ConftestImportFailure\nfrom pathlib import Path\n'
    'try:\n    import pkg_resources\nexcept ModuleNotFoundError as error:\n'
    '    raise ConftestImportFailure(Path(__file__), cause=error) from error\n',
])
def test_unrelated_missing_import_dynamic_import_and_handwritten_wrappers_stay_unconfirmed(tmp_path, statement):
    python = os.environ.get('FIXFIRST_PKG_RESOURCES_ABSENT_PYTHON', sys.executable)
    session = nested_case(tmp_path, python, statement=statement)
    assert not has_package_command(session)
    assert not any(r.get('package_failure') for run in session.runs for r in run.records)
    if statement == 'import yaml\n':
        run = next(r for r in session.runs if r.tool == 'pytest_run')
        assert run.verified_pass or any('yaml' in e.message for e in session.events if e.tool == 'pytest_run')


def test_actual_pytest_wrapper_raised_by_project_does_not_capture_a_cause():
    from _pytest.config import ConftestImportFailure
    try:
        # The real IMPORT_NAME failure alone cannot authorize a project-created
        # instance of the pytest wrapper. Its raising frame must be pytest's.
        namespace = {'__name__': 'project'}
        exec(compile('import pkg_resources', 'conftest.py', 'exec'), namespace)
    except ModuleNotFoundError as cause:
        try:
            raise ConftestImportFailure(Path('conftest.py'), cause=cause) from cause
        except ConftestImportFailure as error:
            result = _runtime_evidence.exception_metadata(error, error.__traceback__)
            assert not result['package_failure']
    else:
        pytest.skip('Provider-absent host Python needed for this exact-type guard')
