import sys

import pytest

from fixfirst import __version__, report
from fixfirst.service import create_session


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("state,label", [
    ("unknown", "not yet verified"),
    ("blocked", "goal not reached"),
    ("achieved", "goal verified"),
])
def test_report_shows_running_version_and_goal_state(tmp_path, public, state, label):
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    session.goal_status = state
    text, _, _ = report.html(session, tmp_path, public=public)
    assert f"FixFirst {__version__}" in text
    assert f"Goal: Pass the test suite · {label}" in text
    assert "in progress" not in text


def test_stopped_session_is_identified_separately_from_its_goal(tmp_path):
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    session.goal_status, session.stopped = "achieved", True
    text, _, _ = report.html(session, tmp_path)
    assert "Goal: Pass the test suite · session stopped" in text
    assert "Goal verified" in text
