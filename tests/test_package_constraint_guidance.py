"""Constraint direction changes review guidance without reopening provider trials."""

import pytest

from fixfirst.dependency_context import range_side
from fixfirst.workspace import build_view
from test_package_compatibility import action, setup_case, setuptools_requests


def assert_review_only(session):
    repair = action(session)
    step = next(s for s in build_view(session)['steps'] if s['id'] == repair.action_id)
    assert not repair.command and not step['command'] and not setuptools_requests(session)
    assert not session.installation_attempts
    assert not any(a.check in {'version_search', 'dependency_resolve'} for a in session.actions)
    return step


@pytest.mark.parametrize('pin', [
    'setuptools==65.7.0', 'setuptools<66', 'setuptools<=66',
    'setuptools~=65.7', 'setuptools==65.*',
])
@pytest.mark.parametrize('mode', ['old', 'removed'])
def test_low_provider_requirement_reviews_declaration_before_installation(tmp_path, pin, mode):
    session, _ = setup_case(tmp_path, mode, requirement=pin)
    step = assert_review_only(session)
    assert pin in step['explanation'] and 'requirements.txt:3' in step['explanation']
    assert 'Review the old setuptools requirement' in step['title']
    assert 'Python 3.12.13' in step['explanation'] and 'pkgutil.ImpImporter' in step['explanation']
    assert 'Review raising' in step['explanation'] and 'setuptools>=66.1,<82' in step['explanation']
    assert 'Python version documented for that stack' in step['explanation']
    assert 'Keep the recorded requirements' not in step['explanation']
    assert 'importlib.metadata' not in step['explanation']


@pytest.mark.parametrize('pin', ['setuptools>=82', 'setuptools==84.0.0', 'setuptools~=84.0', 'setuptools==84.*'])
def test_high_provider_requirement_keeps_consumer_migration(tmp_path, pin):
    session, _ = setup_case(tmp_path, 'removed', requirement=pin)
    step = assert_review_only(session)
    assert 'Keep the recorded requirements' in step['explanation']
    assert 'importlib.metadata' in step['explanation'] and 'importlib.resources' in step['explanation']
    assert 'Review raising' not in step['explanation']


@pytest.mark.parametrize('project_pin,dependency_pin', [
    ('setuptools<66', 'setuptools>=82'),
    ('setuptools>=82', 'setuptools<66'),
    ('setuptools>=65,<66,!=65.*', ''),
    ('setuptools===65.7.0', ''),
    ('setuptools<0', ''),
    ('setuptools==65.7.0rc1', ''),
])
def test_mixed_or_unproven_constraints_require_coordinated_review(tmp_path, project_pin, dependency_pin):
    def mutate(env, project, run):
        if dependency_pin:
            env['packages'].append({'name': 'consumer', 'version': '1.0', 'requires': [dependency_pin]})
    session, _ = setup_case(tmp_path, 'old', requirement=project_pin, mutate=mutate)
    step = assert_review_only(session)
    assert 'Review the setuptools requirements together' in step['title']
    assert 'do not establish a single direction' in step['explanation']
    assert 'requirements.txt:3' in step['explanation']
    if dependency_pin:
        assert dependency_pin in step['explanation'] and 'consumer 1.0 Requires-Dist' in step['explanation']
    assert 'Review raising' not in step['explanation']
    assert 'Keep the recorded requirements' not in step['explanation']


def test_low_reverse_dependency_constraint_names_its_owner(tmp_path):
    def mutate(env, project, run):
        env['packages'].append({'name': 'consumer', 'version': '1.0', 'requires': [
            'setuptools<66; python_version == "3.12"',
            'setuptools>=82; python_version >= "3.13"']})
    session, _ = setup_case(tmp_path, 'old', mutate=mutate)
    step = assert_review_only(session)
    assert 'consumer 1.0 Requires-Dist' in step['explanation']
    assert 'Review raising' in step['explanation']
    assert 'If a dependency supplies the constraint' in step['explanation']


@pytest.mark.parametrize('specifier,side', [
    ('<66.1', 'below'), ('==65.*', 'below'), ('~=65.7', 'below'),
    ('>=82', 'above'), ('==82', 'above'), ('==84.*', 'above'),
    ('<=66.1', None), ('==66.1', None), ('>=66.1,<82', None),
    ('<66,>=82', None), ('<0', None), ('>=65,<66,!=65.*', None),
    ('===65.7.0', None), ('==65.7.0.post1', None), ('==1!84.*', None),
])
def test_constraint_direction_uses_proven_nonempty_intersections(specifier, side):
    assert range_side(specifier, '66.1', '82') == side
