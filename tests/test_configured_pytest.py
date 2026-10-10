"""Configured confirmation must observe the user's tests, not merely a zero exit."""

import json
import os
import sys

import pytest

from fixfirst import integrity
from fixfirst.configured_pytest import confirmed, read_config, state
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")


def project(root, options="--maxfail=1", tests=None, source=None, python=None):
    (root / "pytest.ini").write_text("[pytest]\naddopts = " + options + "\n")
    (root / "app.py").write_text("READY = False\n")
    (root / "test_app.py").write_text(source or "import app\ndef test_ready():\n    assert app.READY\n")
    return create_session(root, python or sys.executable, goal="pass_tests", tests=tests)


def pytest_runs(session):
    return [r for r in session.runs if r.tool == "pytest_run"]


def fix(root, session):
    scan(session, ["pytest_run"])
    assert session.goal_status != "achieved"
    original = [i.issue_id for i in session.issues if i.tool == "pytest_run"]
    (root / "app.py").write_text("READY = True\n")
    scan(session, ["pytest_run"])
    return original


@pytest.mark.parametrize("tests", [None, ["test_app.py::test_ready"]])
def test_closes_only_after_both_real_runs_pass_with_the_original_nodes(tmp_path, tests):
    session = project(tmp_path, tests=tests)
    original = fix(tmp_path, session)
    initial, fixed, configured = pytest_runs(session)
    assert initial.exit_code == 1 and fixed.exit_code == configured.exit_code == 0
    assert "addopts=" in fixed.argv and "addopts=" not in configured.argv
    assert fixed.argv[:3] == configured.argv[:3] and fixed.cwd == configured.cwd
    assert fixed.requested_tests == configured.requested_tests == (tests or [])
    assert confirmed(configured) and configured.passed_nodes == fixed.passed_nodes
    assert state(configured)["first_run_id"] == fixed.run_id
    assert session.goal_status == "achieved" and build_view(session)["status"]["kind"] == "done"
    for issue in session.issues:
        if issue.issue_id in original:
            assert issue.status == "resolved" and "project's pytest options" in issue.note


def test_warning_as_error_cannot_inherit_the_first_pass(tmp_path):
    session = project(tmp_path, "-W error", source=(
        "import app, warnings\ndef test_ready():\n    assert app.READY\n    warnings.warn('project warning')\n"))
    original = fix(tmp_path, session)
    first, second = pytest_runs(session)[-2:]
    assert first.verified_pass and first.exit_code == 0
    assert second.exit_code == 1 and not confirmed(second)
    assert any(i.issue_id in original and i.status != "resolved" for i in session.issues)
    assert session.goal_status != "achieved"
    assert "still failed" in build_view(session)["status"]["detail"]
    assert "The checked tests passed" not in json.dumps(build_view(session))


@pytest.mark.parametrize("options", ["-k absent", "-m absent", "--deselect=test_app.py::test_ready"])
def test_excluded_original_tests_never_close(tmp_path, options):
    session = project(tmp_path, options)
    original = fix(tmp_path, session)
    assert pytest_runs(session)[-2].verified_pass
    assert not confirmed(pytest_runs(session)[-1])
    assert session.goal_status != "achieved"
    assert all(i.status != "resolved" for i in session.issues if i.issue_id in original)


def test_additional_doctests_are_not_silently_accepted(tmp_path):
    session = project(tmp_path, "--doctest-modules")
    (tmp_path / "app.py").write_text('""">>> 1 + 1\n2\n"""\nREADY = True\n')
    scan(session, ["pytest_run"])
    first, second = pytest_runs(session)
    assert first.passed_nodes == ["test_app.py::test_ready"]
    assert second.verified_pass and second.test_summary["passed"] == 2
    assert not confirmed(second) and session.goal_status != "achieved"
    assert "1 additional node(s)" in build_view(session)["status"]["detail"]


@pytest.mark.parametrize("outcome", ["skip", "xfail", "xpass"])
def test_skips_and_expected_results_in_followup_are_not_fixes(tmp_path, outcome):
    body = {"skip": "pytest.skip('not exercised')", "xfail": "pytest.xfail('not fixed')",
            "xpass": "pass"}[outcome]
    marker = "@pytest.mark.xfail(strict=False)\n" if outcome == "xpass" else ""
    # xpass is conditional so the first run still has ordinary pass evidence.
    if marker:
        marker = "@pytest.mark.xfail(condition=False, strict=False)\n"
        source = ("import app, pytest\ndef test_ready(request):\n    assert app.READY\n"
                  "    if request.config.getini('addopts'):\n"
                  "        request.node.add_marker(pytest.mark.xfail(strict=False))\n")
    else:
        source = ("import app, pytest\ndef test_ready(request):\n    assert app.READY\n"
                  "    if request.config.getini('addopts'):\n        " + body + "\n")
    session = project(tmp_path, source=source)
    original = fix(tmp_path, session)
    assert pytest_runs(session)[-2].verified_pass
    assert not confirmed(pytest_runs(session)[-1]) and session.goal_status != "achieved"
    assert all(i.status != "resolved" for i in session.issues if i.issue_id in original)


@pytest.mark.parametrize("options", ["-n 0", "-n2", "-qn2", "--numprocesses=0", "--dist=load", "--tx=popen",
                                      "--workers=1", "--collect-only", "--setup-only", "--pdb",
                                      "-o addopts=", "-p no:_fixfirst_probe", "-c other.ini"])
def test_unsafe_or_parallel_modes_do_not_start_a_followup(tmp_path, options):
    session = project(tmp_path, options)
    (tmp_path / "app.py").write_text("READY = True\n")
    scan(session, ["pytest_run"])
    [run] = pytest_runs(session)
    assert run.verified_pass and state(run)["state"] == "blocked"
    assert session.goal_status != "achieved" and "manually" in build_view(session)["status"]["detail"]


def test_reports_written_by_project_options_are_not_test_changes(tmp_path):
    session = project(tmp_path, "--junitxml=report.xml")
    (tmp_path / "conftest.py").write_text(
        "from pathlib import Path\ndef pytest_sessionfinish(session, exitstatus):\n"
        "    if session.config.getini('addopts'):\n"
        "        Path('.coverage').write_bytes(b'data')\n"
        "        Path('report.html').write_text('<html>report</html>')\n")
    fix(tmp_path, session)
    assert (tmp_path / "report.xml").is_file() and (tmp_path / ".coverage").is_file()
    assert session.goal_status == "achieved" and session.baseline_check["state"] == "unchanged"
    scan(session, ["pytest_run"])
    assert confirmed(pytest_runs(session)[-1]) and session.baseline_check["state"] == "unchanged"


@pytest.mark.parametrize("change", ["future_option", "masking_file", "test_file"])
def test_baseline_cannot_be_weakened_by_unknown_options_or_new_config_files(tmp_path, change):
    session = project(tmp_path)
    scan(session, ["pytest_run"])
    (tmp_path / "app.py").write_text("READY = True\n")
    if change == "future_option":
        (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = --maxfail=1\nfuture_result_option = weakened\n")
    elif change == "masking_file":
        (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\nstrict_xfail = true\n')
    else:
        (tmp_path / "test_app.py").write_text("def test_ready():\n    pass\n")
    scan(session, ["pytest_run"])
    assert len(pytest_runs(session)) == 2  # no configured run
    assert state(pytest_runs(session)[-1])["state"] == "blocked"
    assert session.goal_status != "achieved" and not build_view(session)["fixed"]


def test_configuration_changed_by_a_test_is_not_used_for_confirmation(tmp_path):
    session = project(tmp_path, source=(
        "from pathlib import Path\ndef test_ready():\n"
        "    Path('pytest.ini').write_text('[pytest]\\naddopts = --maxfail=1\\npythonpath = src\\n')\n"))
    scan(session, ["pytest_run"])
    [run] = pytest_runs(session)
    assert run.verified_pass and state(run)["state"] == "blocked"
    assert "during this check" in state(run)["reason"] and session.goal_status != "achieved"


def test_output_overwriting_a_test_is_still_rejected(tmp_path):
    session = project(tmp_path, "--junitxml=test_app.py")
    original = fix(tmp_path, session)
    assert state(pytest_runs(session)[-1])["state"] == "failed"
    assert all(i.status != "resolved" for i in session.issues if i.issue_id in original)
    assert session.baseline_check["state"] == "changed" and session.goal_status != "achieved"


def test_old_session_requires_new_baseline_before_configured_confirmation(tmp_path):
    session = project(tmp_path)
    scan(session, ["pytest_run"])
    integrity.current_baseline(session).pop("configured_pytest")
    (tmp_path / "app.py").write_text("READY = True\n")
    scan(session, ["pytest_run"])
    assert state(pytest_runs(session)[-1])["state"] == "blocked"
    assert "older session" in state(pytest_runs(session)[-1])["reason"]
    integrity.accept(session)
    scan(session, ["pytest_run"])
    assert session.goal_status == "achieved" and confirmed(pytest_runs(session)[-1])


def test_old_session_without_any_baseline_does_not_invent_past_configuration_evidence(tmp_path):
    session = project(tmp_path)
    scan(session, ["pytest_run"])
    session.verification_baseline = {}  # A pre-baseline saved session still has its old runs.
    (tmp_path / "app.py").write_text("READY = True\n")
    scan(session, ["pytest_run"])
    assert len(pytest_runs(session)) == 2 and session.goal_status != "achieved"
    assert state(pytest_runs(session)[-1])["state"] == "blocked"
    assert "older session" in state(pytest_runs(session)[-1])["reason"]
    assert not integrity.current_baseline(session).get("configured_pytest")


def test_external_execution_options_are_not_adopted(tmp_path, monkeypatch):
    session = project(tmp_path)
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k absent")
    (tmp_path / "app.py").write_text("READY = True\n")
    scan(session, ["pytest_run"])
    [run] = pytest_runs(session)
    assert run.verified_pass and not state(run) and session.goal_status != "achieved"


@pytest.mark.parametrize("kind", ["oversized", "symlink", "fifo"])
def test_unsafe_configuration_cannot_block_the_host_or_earn_confirmation(tmp_path, kind):
    if kind == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("Named-pipe creation is unavailable on this platform")
        path = tmp_path / "pipe.ini"
        os.mkfifo(path)
        with pytest.raises(ValueError, match="not a regular file"):
            read_config(path, tmp_path)
        return
    session = project(tmp_path)
    path = tmp_path / "pytest.ini"
    if kind == "oversized":
        path.write_text("[pytest]\naddopts=--maxfail=1\n#" + "x" * 128000)
    else:
        path.rename(tmp_path / "config.ini")
        path.symlink_to(tmp_path / "config.ini")
    (tmp_path / "app.py").write_text("READY = True\n")
    scan(session, ["pytest_run"])
    assert len(pytest_runs(session)) == 1
    assert state(pytest_runs(session)[-1])["state"] == "blocked" and session.goal_status != "achieved"


def test_followup_timeout_is_retained_without_retry(tmp_path):
    session = project(tmp_path, source=(
        "import app, time\ndef test_ready(request):\n    assert app.READY\n"
        "    if request.config.getini('addopts'):\n        time.sleep(5)\n"))
    scan(session, ["pytest_run"])
    (tmp_path / "app.py").write_text("READY = True\n")
    scan(session, ["pytest_run"], timeout=1.5)
    first, second = pytest_runs(session)[-2:]
    assert first.verified_pass and second.status == "timeout"
    assert first.duration_s + second.duration_s < 2
    assert state(second)["state"] == "failed" and session.goal_status != "achieved"
    assert len(pytest_runs(session)) == 3


def test_internal_error_in_followup_does_not_confirm_the_first_pass(tmp_path):
    session = project(tmp_path)
    (tmp_path / "conftest.py").write_text(
        "def pytest_runtestloop(session):\n"
        "    if session.config.getini('addopts'):\n        raise RuntimeError('configured internal error')\n")
    original = fix(tmp_path, session)
    first, second = pytest_runs(session)[-2:]
    assert first.verified_pass and second.exit_code == 3 and not confirmed(second)
    assert session.goal_status != "achieved" and all(i.status != "resolved" for i in session.issues if i.issue_id in original)
    assert "interrupted" in build_view(session)["status"]["detail"]


def test_followup_retains_late_failure_when_passing_records_fill_the_budget(tmp_path):
    session = project(tmp_path, source=(
        "def test_bulk(value):\n    if value == 2599:\n        raise ValueError('CONFIGURED_TAIL_FAILURE')\n"))
    (tmp_path / "conftest.py").write_text(
        "def pytest_generate_tests(metafunc):\n"
        "    metafunc.parametrize('value', range(2600) if metafunc.config.getini('addopts') else [0])\n")
    scan(session, ["pytest_run"])
    first, second = pytest_runs(session)
    assert first.verified_pass and second.exit_code == 1 and not second.coverage_complete
    assert any(r.get('type') == 'exception' and r.get('exception_message') == 'CONFIGURED_TAIL_FAILURE'
               for r in second.records)
    assert not confirmed(second) and session.goal_status != "achieved"
    warning = next(step for step in build_view(session)["steps"] if step["id"] == "pytest-incomplete-records")
    assert warning["cause"] is None and warning["possible"] is None


@pytest.mark.parametrize("filename,contents", [
    ("tox.ini", "[pytest]\naddopts = --maxfail=1\n"),
    (".pytest.ini", "[pytest]\naddopts = --maxfail=1\n"),
    ("pytest.toml", '[pytest]\naddopts = ["--maxfail=1"]\n'),
    (".pytest.toml", '[pytest]\naddopts = ["--maxfail=1"]\n'),
])
def test_active_config_formats_are_bound_without_combining_files(tmp_path, filename, contents):
    session = project(tmp_path)
    (tmp_path / "pytest.ini").unlink()
    (tmp_path / filename).write_text(contents)
    (tmp_path / "app.py").write_text("READY = True\n")
    scan(session, ["pytest_run"])
    first, second = pytest_runs(session)
    assert first.pytest_options["config_file"] == str(tmp_path / filename)
    assert confirmed(second) and session.goal_status == "achieved"


def test_configuration_selected_outside_the_project_is_not_confirmed(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts=--maxfail=1\n")
    root = tmp_path / "project"
    root.mkdir()
    session = project(root)
    (root / "pytest.ini").unlink()
    (root / "app.py").write_text("READY = True\n")
    scan(session, ["pytest_run"])
    [first] = pytest_runs(session)
    assert first.verified_pass and state(first)["state"] == "blocked"
    assert "outside the project" in state(first)["reason"]


@pytest.mark.parametrize("version,variable", [("3.2.1", "FIXFIRST_TEST_PYTEST32_PYTHON"),
                                               ("3.10.1", "FIXFIRST_TEST_PYTEST310_PYTHON")])
def test_followup_uses_legacy_version_command_and_class_node_normalization(tmp_path, version, variable):
    python = os.environ.get(variable)
    if not python:
        pytest.skip("Optional real legacy pytest interpreter was not supplied")
    session = project(tmp_path, python=python, source=(
        "import app\nclass TestReady:\n    def test_ready(self):\n        assert app.READY\n"))
    original = fix(tmp_path, session)
    first, second = pytest_runs(session)[-2:]
    assert second.tool_version == version and confirmed(second)
    assert ("--rootdir" in second.argv) is (version == "3.10.1")
    assert first.passed_nodes == second.passed_nodes == ["test_app.py::TestReady::test_ready"]
    assert all(i.status == "resolved" for i in session.issues if i.issue_id in original)
