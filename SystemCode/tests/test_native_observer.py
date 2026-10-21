"""Compare the observed entry's behavior with a direct selected-Python run."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from fixfirst.execution import collect_execution
from fixfirst.models import Execution, Session, check_scope
from fixfirst.service import ingest


def run_entry(root, code, kind='script', args=(), stdin=''):
    if kind == 'module':
        (root / 'package').mkdir()
        (root / 'package/__init__.py').write_text('')
        (root / 'package/main.py').write_text(code)
        entry = 'package.main'
        command = [sys.executable, '-m', entry, *args]
    else:
        (root / 'main.py').write_text(code)
        entry = 'main.py'
        command = [sys.executable, str(root / entry), *args]
    direct = subprocess.run(command, cwd=root, input=stdin, text=True, capture_output=True)
    session = Session(project_root=str(root), target_python=sys.executable, name='observer',
                      goal='run_project', execution=Execution(kind=kind, entry=entry,
                                                             args=list(args), stdin=stdin))
    observed = collect_execution(session, 'python_run', 10)
    return direct, observed, session


@pytest.mark.parametrize('kind', ['script', 'module'])
def test_native_entry_preserves_globals_arguments_input_and_path(tmp_path, kind):
    code = '''import sys, os, json, __main__
print(json.dumps({'argv': sys.argv, 'orig_argv': sys.orig_argv, 'path0': sys.path[0],
'cwd': os.getcwd(), 'input': input(), 'name': __name__, 'package': __package__,
'file': __file__, 'spec': __spec__.name if __spec__ else None, 'loader': type(__loader__).__name__,
'globals': __main__.__dict__ is globals()}))
'''
    direct, observed, session = run_entry(tmp_path, code, kind, ['first', 'two words'], 'payload\n')
    assert direct.returncode == observed.exit_code == 0
    assert json.loads(direct.stdout) == json.loads(observed.stdout)
    assert not observed.records
    assert '_native_runner.py' in observed.argv[1]
    assert observed.scope == check_scope(session, 'python_run')
    ingest(session, [observed])
    assert session.goal_status == 'achieved'


@pytest.mark.parametrize('name', ['json', 're', 'ast'])
@pytest.mark.parametrize('fails', [False, True])
def test_local_standard_library_name_is_not_preloaded(tmp_path, name, fails):
    (tmp_path / (name + '.py')).write_text("MARKER = 'project module'\n")
    code = f'import {name}\nprint({name}.MARKER)\n'
    if fails:
        code += "raise ValueError('after local import')\n"
    direct, observed, _ = run_entry(tmp_path, code)
    assert direct.returncode == observed.exit_code
    assert direct.stdout == observed.stdout == 'project module\n'
    assert direct.stderr == observed.stderr
    assert not observed.records  # Unsafe post-failure stdlib ownership stays unknown.


@pytest.mark.parametrize('ending', ['raise SystemExit(7)', 'raise SystemExit()',
                                   "raise SystemExit('message')"])
def test_system_exit_is_native_and_has_no_exception_record(tmp_path, ending):
    direct, observed, _ = run_entry(tmp_path, ending)
    assert (direct.returncode, direct.stdout, direct.stderr) == (observed.exit_code, observed.stdout, observed.stderr)
    assert not observed.records


def test_project_exception_hook_remains_in_control(tmp_path):
    code = "import sys\nsys.excepthook = lambda *args: print('project hook')\nraise ValueError('test')\n"
    direct, observed, _ = run_entry(tmp_path, code)
    assert (direct.returncode, direct.stdout, direct.stderr) == (observed.exit_code, observed.stdout, observed.stderr)
    assert not observed.records


def test_user_exception_formatter_keeps_original_import_path(tmp_path):
    (tmp_path / 'json.py').write_text("MARKER = 'local formatter'\n")
    code = '''class CustomError(Exception):
    def __str__(self):
        import json
        return json.MARKER
raise CustomError()
'''
    direct, observed, _ = run_entry(tmp_path, code)
    assert (direct.returncode, direct.stdout, direct.stderr) == (observed.exit_code, observed.stdout, observed.stderr)
    assert not observed.records


def test_actual_exception_metadata_is_recorded_without_bootstrap_frames(tmp_path):
    direct, observed, session = run_entry(tmp_path, "value = []\nvalue.missing()\n")
    assert direct.returncode == observed.exit_code == 1
    assert direct.stderr == observed.stderr
    exception = next(r for r in observed.records if r['type'] == 'exception')
    assert exception['record_source'] == 'native_exception'
    assert exception['attribute_access']['owner_module'] == 'builtins'
    assert all(Path(f['file']).name != '_native_runner.py' for f in exception['traceback_frames'])
    ingest(session, [observed])
    assert session.goal_status == 'blocked'
