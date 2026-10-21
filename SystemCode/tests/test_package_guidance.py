"""User-facing guidance when the bounded provider repair cannot be offered."""

import pytest

from fixfirst.package_compatibility import POLICY_ID
from fixfirst.workspace import build_view
from test_package_compatibility import action, setup_case, setuptools_requests
from test_dependency_advice import recorded_session


@pytest.mark.parametrize('pin', ['setuptools>=82', 'setuptools==84.0.0'])
def test_conflicting_provider_requirement_preserves_pin_and_offers_consumer_migration(tmp_path, pin):
    session, _ = setup_case(tmp_path, 'removed', requirement=pin)
    repair = action(session)
    step = next(s for s in build_view(session)['steps'] if s['id'] == repair.action_id)
    assert not setuptools_requests(session) and not step['command']
    assert pin in step['explanation'] and 'requirements.txt:3' in step['explanation']
    assert 'importlib.metadata' in step['explanation']
    assert 'importlib.resources' in step['explanation']
    assert 'dependency that imports pkg_resources' in step['explanation']
    assert 'Keep the recorded requirements' in step['explanation']
    assert 'Adjust the conflicting project pin' not in step['explanation']
    assert not any(a.check in {'version_search', 'dependency_resolve'} for a in session.actions)


def test_other_dependency_conflicts_do_not_receive_pkg_resources_migration(tmp_path):
    session = recorded_session(tmp_path, 'Django==1.10.5\n',
        [{'name': 'Django', 'version': '1.10.5', 'requires': []}],
        "ImportError: cannot import name 'quote' from 'django.utils.six.moves.urllib.parse'",
        {'django': ['Django']})
    assert all('importlib.metadata' not in a.explanation for a in session.actions)


def test_unobserved_import_review_points_to_recorded_project_frame(tmp_path):
    def mutate(env, project, run):
        record = run.records[1]
        record.pop('package_failure')
        record['source_file'] = '/python/lib/python3.12/importlib/__init__.py'
        record['source_line'] = 90
        record['traceback_frames'] = [
            {'file': str(tmp_path / 'loader.py'), 'line': 7},
            {'file': record['source_file'], 'line': 90},
        ]
    session, _ = setup_case(tmp_path, 'absent', mutate=mutate)
    repair = action(session)
    step = next(s for s in build_view(session)['steps'] if s['id'] == repair.action_id)
    assert not repair.command and repair.cause is None
    assert 'recorded pkg_resources failure' in step['title']
    assert 'loader.py:7' in step['explanation']
    assert '__import__' in step['explanation'] and 'importlib.import_module' in step['explanation']
    assert 'or an exception was raised again' in step['explanation']
    assert 'Check whether' in step['explanation']
    assert 'not verified' in step['explanation']


@pytest.mark.parametrize('bad_line', [None, -1, True, '7'])
def test_unobserved_import_review_uses_node_when_source_location_is_unusable(tmp_path, bad_line):
    def mutate(env, project, run):
        record = run.records[1]
        record.pop('package_failure')
        record['source_line'] = bad_line
        record['traceback_frames'] = 'malformed'
        for item in run.records:
            item['nodeid'] = 'tests/test_case.py'
    session, _ = setup_case(tmp_path, 'absent', tool='pytest_run', mutate=mutate)
    repair = action(session)
    assert not repair.command
    assert 'Recorded collection node: tests/test_case.py' in repair.explanation
    assert 'main.py:' not in repair.explanation


@pytest.mark.parametrize('internal_environment', [False, True])
def test_collection_review_never_directs_edits_to_pytest_wrapper(tmp_path, internal_environment):
    def mutate(env, project, run):
        record = run.records[1]
        record.pop('package_failure')
        base = str(tmp_path / '.venv') if internal_environment else '/python'
        record['source_file'] = base + '/lib/python3.12/site-packages/_pytest/python.py'
        record['source_line'] = 538
        record['traceback_frames'] = [{'file': record['source_file'], 'line': 538}]
        for item in run.records:
            item['nodeid'] = 'tests/test_case.py'
    session, _ = setup_case(tmp_path, 'absent', tool='pytest_run', mutate=mutate)
    repair = action(session)
    assert not repair.command
    assert 'Recorded collection node: tests/test_case.py' in repair.explanation
    assert '_pytest' not in repair.explanation


@pytest.mark.parametrize('untrusted', ['imported', 'stale'])
def test_old_or_imported_failure_does_not_get_current_source_review(tmp_path, untrusted):
    def mutate(env, project, run):
        run.records[1].pop('package_failure')
        run.records[1]['source_file'] = str(tmp_path / 'unverified.py')
        if untrusted == 'imported':
            run.source = 'imported'
        else:
            run.environment_id = 'old-environment'
    session, _ = setup_case(tmp_path, 'absent', mutate=mutate)
    if untrusted == 'stale':
        # An old-environment issue is excluded before package planning at all.
        assert not any(POLICY_ID in a.rule_ids for a in session.actions)
        assert not setuptools_requests(session)
        return
    repair = action(session)
    assert not repair.command
    assert 'Refresh the selected environment' in repair.explanation
    assert 'unverified.py' not in repair.explanation
    assert 'Check whether' not in repair.explanation
