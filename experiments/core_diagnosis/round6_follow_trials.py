"""Strictly execute a recorded proposal on the disposable development fixtures.

First build the cases with Claude's acceptance.py. Run this using the FixFirst
checkout's interpreter. This records manual follow-through separately; it never
rewrites an automatic REVIEW to PASS and never chooses a version itself.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from fixfirst.storage import Store
from fixfirst.workspace import build_view

parser = argparse.ArgumentParser(description="Follow the dependency trial on freshly built A2/D2b/C development fixtures. Modifies only those disposable fixture declarations/environments.")
parser.add_argument("--cases-root", type=Path, required=True, help="Acceptance RUNS/TAG directory; cases must not have been repaired")
parser.add_argument("--output", type=Path, required=True, help="New JSON file (raw local evidence; redact before publishing)")
args = parser.parse_args()
BASE = args.cases_root.resolve()
OUT = args.output.resolve()
if OUT.exists():
    parser.error("Choose a new output file; previous evidence is never overwritten")
OUT.parent.mkdir(parents=True, exist_ok=True)
source_head = subprocess.check_output(["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"], text=True).strip()
results = []

def call(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=360)
    return {'argv': argv, 'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}

for name in ('A2', 'D2b', 'C'):
    folder = BASE / name
    store = Store(folder / 'store')
    sid = next(p.name for p in (folder / 'store').iterdir() if p.name.startswith('session-'))
    session = store.load(sid)
    before = build_view(session)['steps'][0]
    action = next(a for a in session.actions if a.action_id == before['id'])
    row = {'case': name, 'source': source_head, 'before': before}
    results.append(row)
    test = folder / 'project' / 'test_app.py'
    test_hash = hashlib.sha256(test.read_bytes()).hexdigest() if test.is_file() else None
    cli = [str(Path(sys.executable).with_name('fixfirst')), '--store', str(folder / 'store')]
    if action.check != 'dependency_resolve':
        row['outcome'] = 'No executable dependency trial'
        OUT.write_text(json.dumps(results, indent=2))
        continue
    row['trial_command'] = call([*cli, 'run', sid, action.action_id, '--timeout', '300'])
    session = store.load(sid)
    trial = next((r for r in reversed(session.runs) if r.tool == 'dependency_resolve'), None)
    row['trial'] = json.loads(trial.stdout) if trial else None
    row['after_trial'] = build_view(session)['steps'][0]
    action = next(a for a in session.actions if a.action_id == row['after_trial']['id'])
    print(name, row['trial']['status'] if row['trial'] else 'No trial', flush=True)
    if row['trial'] and row['trial']['status'] == 'resolved' and action.command:
        # Follow exactly the named edit and command. No version selection here.
        edits = []
        for edit in row['trial']['edits']:
            source, line = edit['source'].rsplit(':', 1)
            path = (folder / 'project' / source).resolve()
            assert path.is_relative_to((folder / 'project').resolve()), edit
            lines = path.read_text().splitlines(keepends=True)
            assert lines[int(line)-1].strip() == edit['before'], (name, edit, lines)
            lines[int(line)-1] = edit['after'] + '\n'
            path.write_text(''.join(lines))
            edits.append(edit)
        row['executed_edits'] = edits
        row['installation'] = call(action.command, folder / 'project')
        row['pip_check'] = call([session.target_python, '-m', 'pip', 'check'], folder / 'project')
        row['recheck'] = call([*cli, 'scan', sid])
        session = store.load(sid)
        row['after'] = build_view(session)
        row['test_unchanged'] = test_hash == (hashlib.sha256(test.read_bytes()).hexdigest() if test.is_file() else None)
        row['goal_status'] = session.goal_status
        print(name, 'goal', session.goal_status, 'pip check', row['pip_check']['exit_code'], flush=True)
    OUT.write_text(json.dumps(results, indent=2, default=str))
