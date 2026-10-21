"""Exercise installation entry points only; no model training or benchmark runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import urllib.request

p = argparse.ArgumentParser()
p.add_argument('--project', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
a = p.parse_args()
root, out = a.project.resolve(), a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
python, cli = root / '.venv/bin/python', root / '.venv/bin/fixfirst'
store = out / 'sessions'
env = os.environ.copy()
for key in ('PYTHONPATH', 'VIRTUAL_ENV', 'PYTEST_ADDOPTS', 'FIXFIRST_STORE'):
    env.pop(key, None)
env['PYTHONNOUSERSITE'] = '1'
commands = []


def run(name, args):
    r = subprocess.run([str(x) for x in args], cwd=root, env=env, capture_output=True, text=True, timeout=90)
    (out / (name + '.log')).write_text(r.stdout + r.stderr)
    commands.append({'name': name, 'exit_code': r.returncode})
    if r.returncode:
        raise AssertionError(f'{name}: exit {r.returncode}; see log')
    return r.stdout


def ff(name, *args):
    return run(name, [cli, '--store', store, *args])


identity = json.loads(run('identity', [python, '-c', '''import fixfirst,importlib.metadata as m,hashlib,json,sys
from importlib.resources import files
print(json.dumps({"module_version":fixfirst.__version__,"installed_version":m.version("fixfirst-local"),"source":fixfirst.__file__,"python":sys.version,"model_sha256":hashlib.sha256(files("fixfirst").joinpath("knowledge/diagnosis_tree.json").read_bytes()).hexdigest(),"packages":sorted({d.metadata["Name"]+"=="+d.version for d in m.distributions() if d.metadata["Name"]})}))''']))
assert identity['module_version'] == identity['installed_version'] == '0.7.0'
assert Path(identity['source']).is_relative_to(root)
assert identity['model_sha256'] == '4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3'
run('cli-help', [cli, '--help'])
ff('demo-create', 'demo', '--scenario', 'playground', '--output', out / 'sample')
rows = json.loads(ff('list-initial', 'list'))
assert len(rows) == 1
sample_id = rows[0]['session_id']
project = out / 'sample/project'
test_hashes = {q.name: hashlib.sha256(q.read_bytes()).hexdigest() for q in project.glob('test_*.py')}
initial = json.loads(ff('sample-initial', 'show', sample_id, '--json'))
assert initial['goal_status'] == 'blocked'
# The already documented demo's FIXES.md; this is an operation smoke, not diagnosis scoring.
replacements = [('pricing.py', 'from collections import Mapping', 'from collections.abc import Mapping'),
                ('reports.py', 'from helper import double', 'from helpers import double')]
for name, old, new in replacements:
    q = project / name
    assert old in q.read_text()
    q.write_text(q.read_text().replace(old, new))
ff('sample-after-imports', 'scan', sample_id, '--checks', 'pytest_run')
for name, old, new in [('orders.py', 'os.environ["SHOP_API_TOKEN"]', 'os.environ.get("SHOP_API_TOKEN", "demo-token")'),
                       ('stats.py', 'numpy.float(sum(values))', 'float(sum(values))')]:
    q = project / name
    assert old in q.read_text()
    q.write_text(q.read_text().replace(old, new))
ff('sample-final-scan', 'scan', sample_id, '--checks', 'pytest_run')
final = json.loads(ff('sample-final', 'show', sample_id, '--json'))
assert final['goal_status'] == 'achieved'
assert all(hashlib.sha256((project / name).read_bytes()).hexdigest() == digest for name, digest in test_hashes.items())
last = next(r for r in reversed(final['runs']) if r['tool'] == 'pytest_run')
assert last['verified_pass'] and last['test_summary']['passed'] == 4
ff('report', 'report', sample_id)
ff('export', 'export', sample_id, '--output', out / 'shared.html')
assert (out / 'shared.html').is_file() and (out / 'shared.json').is_file()
assert str(project) not in (out / 'shared.html').read_text()
# Minimal no-test execution entry check; not an evaluation task.
hello = out / 'script project 中文'
hello.mkdir()
(hello / 'main.py').write_text('import sys\nprint("entry-ok", sys.argv[1:])\n')
created = ff('script-init', 'init', hello, '--python', python, '--script', 'main.py', '--arg', 'hello')
script_id = re.search(r'session-[0-9a-f]{12}', created)[0]
ff('script-scan', 'scan', script_id, '--checks', 'python_run')
script = json.loads(ff('script-result', 'show', script_id, '--json'))
assert script['goal_status'] == 'achieved'
assert any(r['tool'] == 'python_run' and 'entry-ok' in r['stdout'] for r in script['runs'])
# Actual CLI server process; no browser automation or screenshot claim.
web = []
for index in (1, 2):
    log_path = out / f'web-{index}.log'
    with log_path.open('w') as log:
        proc = subprocess.Popen([str(cli), '--store', str(store), 'serve', '--no-open'], cwd=root,
                                env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            url = None
            while time.monotonic() < deadline and proc.poll() is None:
                match = re.search(r'http://127\.0\.0\.1:\d+/', log_path.read_text())
                if match:
                    url = match[0]
                    break
                time.sleep(.1)
            assert url, 'server did not start'
            for route in ('', f'sessions/{sample_id}', f'sessions/{sample_id}/details', f'sessions/{sample_id}/export'):
                with urllib.request.urlopen(url + route, timeout=5) as response:
                    body = response.read()
                    assert response.status == 200 and b'html' in body[:150].lower()
                    web.append({'start': index, 'route': route or '/', 'status': response.status})
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
            proc.wait(timeout=10)
    assert proc.returncode == 0
reopened = json.loads(ff('reopened-session', 'show', sample_id, '--json'))
assert reopened['goal_status'] == 'achieved'
receipt = {'purpose': 'clean source installation and existing entry-point smoke; not performance evaluation',
           'identity': identity, 'commands': commands, 'sample_goal_before': initial['goal_status'],
           'sample_goal_after': final['goal_status'], 'sample_original_tests_unchanged': True,
           'sample_passed': 4, 'sample_repairs_source': 'existing playground FIXES.md',
           'no_test_script_goal': script['goal_status'], 'web_http_checks': web,
           'web_stop_and_restart': True, 'session_reopened': True, 'browser_visual_test': False,
           'windows_test': False, 'notebook_optional_install_test': False, 'model_training': False}
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({k: v for k, v in receipt.items() if k not in ('identity', 'commands', 'web_http_checks')}))
