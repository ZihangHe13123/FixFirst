"""Match project-level HTTP 404 evidence without inventing global package absence."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import sys
import threading

import pytest

from fixfirst.evidence import project_index
from fixfirst.install_feedback import collect_feedback
from fixfirst.models import Action, Run
from fixfirst.parsers import parse
from fixfirst.runner import environment_id
from fixfirst.service import ingest
from test_dependency_advice import recorded_session
from test_dependency_resolution import fixture_session
from test_install_feedback import first_action, write_log


def fetch_404(url):
    return f'Could not fetch URL {url}: 404 Client Error: Not Found for url: {url} - skipping\n'


def parsed(output, requirement='docoptt==0.6.2'):
    run = Run(tool='pip_install', source='imported', stdout=output +
              f'ERROR: No matching distribution found for {requirement}\n',
              records=[{'type': 'installation_context', 'python_version': '3.12.13'}])
    event = next(e for e in parse(run) if e.message.startswith('ERROR: No matching distribution'))
    return run, event


@pytest.mark.parametrize('url,requirement', [
    ('https://pypi.org/simple/docoptt/', 'docoptt==0.6.2'),
    ('https://mirror.invalid/repository/simple/Doc_OpT..T/', 'doc-opt-t[extra]==0.6.2'),
    ('https://private.invalid/simple/docoptt', 'Docoptt>=0.6,<1'),
])
def test_project_404_matches_final_requirement_with_pep503_normalization(url, requirement):
    run, event = parsed(fetch_404(url), requirement)
    assert event.code == 'index_project_missing'
    assert url in event.message
    assert f'{run.run_id}:stdout:1' in event.evidence_refs
    assert 'index access was incomplete' not in event.message


@pytest.mark.parametrize('url,expected', [
    ('https://pypi.org/simple/', 'index_access'),
    ('https://pypi.org/simple', 'index_access'),
    ('https://files.invalid/packages/docoptt-0.6.2.tar.gz', 'index_access'),
    ('https://pypi.org/simple/docoptt/docoptt-0.6.2.whl', 'index_access'),
    ('https://pypi.org/not-simple/docoptt/', 'index_access'),
    ('https://pypi.org/simple/?name=docoptt', 'index_access'),
    ('https://pypi.org/simple/docopt/', 'no_distribution'),
    ('https://pypi.org/simple/docopt/#/simple/docoptt/', 'no_distribution'),
])
def test_root_artifact_and_other_project_404_cannot_prove_target_absence(url, expected):
    _, event = parsed(fetch_404(url))
    assert event.code == expected
    assert event.code != 'index_project_missing'


def test_other_project_404_is_not_lent_as_a_network_failure_or_evidence_ref():
    other = fetch_404('https://private.invalid/simple/other/')
    target = fetch_404('https://pypi.org/simple/docoptt/')
    run, event = parsed(other + target)
    assert event.code == 'index_project_missing'
    assert f'{run.run_id}:stdout:1' not in event.evidence_refs
    assert f'{run.run_id}:stdout:2' in event.evidence_refs
    assert 'private.invalid' not in event.message


@pytest.mark.parametrize('failure', [
    'Could not fetch URL https://private.invalid/simple/docoptt/: 401 Client Error: Unauthorized',
    'Could not fetch URL https://private.invalid/simple/docoptt/: 403 Client Error: Forbidden',
    'Could not fetch URL https://private.invalid/simple/docoptt/: 503 Server Error: Unavailable',
    'WARNING: Retrying after NameResolutionError: name resolution failed',
    'WARNING: Retrying after SSLCertVerificationError: certificate verify failed',
    'WARNING: Retrying after ReadTimeoutError: read timed out',
    'WARNING: Retrying after ConnectTimeoutError: connection timed out',
])
def test_real_access_failure_on_another_index_takes_priority(failure):
    _, event = parsed(fetch_404('https://pypi.org/simple/docoptt/') + failure + '\n')
    assert event.code == 'index_access'
    assert failure in event.message


def test_404_text_without_pip_fetch_evidence_does_not_classify_project_absence():
    _, event = parsed('https://pypi.org/simple/docoptt/ returned 404\n')
    assert event.code == 'no_distribution'


def test_observed_matching_source_archive_survives_another_index_404():
    output = (fetch_404('https://private.invalid/simple/docoptt/') +
              'Skipping link: No sources permitted for docoptt: https://files.invalid/docoptt-0.6.2.tar.gz\n')
    _, event = parsed(output)
    assert event.code == 'no_wheel'


@pytest.mark.parametrize('python_evidence', [
    "ERROR: Package 'docoptt' requires a different Python: 3.12 not in '>=3.13'\n",
    'Skipping link: No sources permitted for docoptt: https://files.invalid/docoptt-0.6.2.tar.gz (requires-python:>=3.13)\n',
])
def test_python_requirement_rejection_is_not_overridden_by_project_404(python_evidence):
    _, event = parsed(fetch_404('https://private.invalid/simple/docoptt/') + python_evidence)
    assert event.code == 'python_requires'


def test_recorded_installation_404_gives_index_scoped_review_without_trial_or_build(tmp_path):
    session = recorded_session(tmp_path, 'docoptt==0.6.2\n', [],
                               "ModuleNotFoundError: No module named 'docoptt'")
    install = first_action(session)
    assert '--only-binary=:all:' in install.command
    write_log(install, fetch_404('https://pypi.org/simple/docoptt/') +
              'ERROR: No matching distribution found for docoptt==0.6.2\n')
    ingest(session, collect_feedback(session, project_index(session)[1]))
    action = first_action(session)
    assert 'package name and expected index' in action.title
    assert 'requirements.txt:1' in action.explanation
    assert 'spelling' in action.explanation and 'private-index permissions remain unknown' in action.explanation
    assert 'other indexes' in action.explanation
    assert not action.command and not action.check
    assert not any(a.command or a.check == 'dependency_resolve' for a in session.actions if a.kind != 'rerun')


def test_trial_propagates_project_404_and_suppresses_wheel_or_version_workarounds(tmp_path, monkeypatch):
    from fixfirst import runner
    from fixfirst.dependency_resolution import collect, advise
    session, project = fixture_session(tmp_path / 'project', 'ff-trial-base==1.0\nff-trial-ext\ndocoptt==0.6.2\n')
    output = (fetch_404('https://private.invalid/simple/docoptt/') +
              'ERROR: No matching distribution found for docoptt==0.6.2\n')

    def execute(argv, cwd, tool, scope, interpreter, *args, **kwargs):
        return Run(tool=tool, scope=scope, environment_id=environment_id(interpreter),
                   exit_code=1 if 'install' in argv else 0, stderr=output if 'install' in argv else '')

    monkeypatch.setattr(runner, 'execute', execute)
    trial = collect(session, ['ff-trial-base'], 20)
    result = json.loads(trial.stdout)
    assert result['failure_kind'] == 'index_project_missing'
    assert 'trial_restriction' not in result and 'install_requests' not in result
    ingest(session, [trial])
    action = Action(action_id='trial', kind='manual_fix', title='review', explanation='', verification='')
    advise(session, action, session.environment, project, 'ff-trial-base')
    assert 'package name and index' in action.title
    assert 'private-index permissions remain unknown' in action.explanation
    assert not action.command and action.check is None and not action.declaration_edits


@pytest.mark.parametrize('response,expected', [(404, 'index_project_missing'), (403, 'index_access'), (503, 'index_access')])
def test_real_pip_local_simple_endpoint_failure_is_classified(tmp_path, response, expected):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(response)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        index = f'http://127.0.0.1:{server.server_port}/simple/'
        command = [sys.executable, '-m', 'pip', 'install', '--dry-run', '--ignore-installed',
                   '--no-deps', '--no-input', '--no-cache-dir', '--disable-pip-version-check',
                   '--only-binary=:all:', '--retries', '0', '--timeout', '2', '-vv',
                   '--index-url', index, 'docoptt==0.6.2']
        environment = {k: v for k, v in os.environ.items() if not k.startswith('PIP_')}
        environment['PIP_CONFIG_FILE'] = os.devnull
        completed = subprocess.run(command, cwd=tmp_path, env=environment,
                                   capture_output=True, text=True, timeout=15)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert completed.returncode != 0
    assert paths and set(paths) == {'/simple/docoptt/'}
    log = completed.stdout + completed.stderr
    (tmp_path / 'pip-local-index.log').write_text(log)
    run = Run(tool='pip_install', source='imported', argv=command, stdout=log)
    failures = [e for e in parse(run) if e.component == 'docoptt' and e.code]
    # Verbose pip prints both its internal DistributionNotFound traceback and
    # the final ERROR line. Both must retain the same scoped classification.
    assert failures and all(e.code == expected for e in failures), log
    assert any(e.message.startswith('ERROR: No matching distribution') for e in failures)
    assert not run.verified_pass
