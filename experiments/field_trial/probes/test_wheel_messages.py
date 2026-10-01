"""Feed recorded real uv wheel-only failures through a build's production collect()/advise() path.

  FF_TESTS=<checkout>/tests FF_REAL=results/round6-365aa84/probe-wheel-messages.json FF_OUT=out.jsonl \
      <build venv>/bin/python -m pytest -q -p no:cacheprovider probes/test_wheel_messages.py

Same monkeypatch as tests/test_dependency_resolution.py::
test_wheel_restriction_names_actual_blocker_without_blaming_changed_package; only the uv output differs.
The outputs were captured with capture_wheel_messages.py.
"""
import json
import os
from pathlib import Path

from fixfirst.dependency_resolution import advise, collect
from fixfirst.models import Action, Run
from fixfirst.runner import environment_id
from fixfirst.service import ingest
import pytest
from test_dependency_resolution import fixture_session

CASES = json.loads(Path(os.environ["FF_REAL"]).read_text())["cases"]


@pytest.mark.parametrize("record", CASES, ids=[" + ".join(r["requests"]) for r in CASES])
def test_real(tmp_path, monkeypatch, record):
    from fixfirst import runner

    session, project = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\ndocopt\n")

    def execute(argv, cwd, tool, scope, interpreter, *args, **kwargs):
        installing = "install" in argv
        return Run(tool=tool, scope=scope, environment_id=environment_id(interpreter),
                   exit_code=1 if installing else 0, stderr=record["output"] if installing else "")
    monkeypatch.setattr(runner, "execute", execute)
    trial = collect(session, ["ff-trial-base"], 20)
    result = json.loads(trial.stdout)
    ingest(session, [trial])
    action = Action(action_id="trial", kind="manual_fix", title="review", explanation="", verification="")
    advise(session, action, session.environment, project, "ff-trial-base")
    line = {"requests": record["requests"], "blocked": result.get("blocked_requirement"), "title": action.title}
    with open(os.environ["FF_OUT"], "a") as fh:
        fh.write(json.dumps(line) + "\n")
