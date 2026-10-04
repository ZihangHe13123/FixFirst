"""A fixed pytest check may pass without covering the user's configured command."""

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from fixfirst import integrity, probe
from fixfirst.facts import facts_view
from fixfirst.mcp_server import render as mcp_render
from fixfirst.models import Run
from fixfirst.reasoning import goal_status
from fixfirst.report import html
from fixfirst.service import create_session, scan
from fixfirst.test_results import pytest_option_coverage, pytest_options_limited
from fixfirst.workspace import build_view


@pytest.fixture(autouse=True)
def isolated_pytest(monkeypatch):
    # Only the copied probe is enabled; a host coverage plugin must not hide N3's
    # missing-plugin case. These projects and settings are all synthetic.
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")


def project(root, addopts=""):
    (root / "pytest.ini").write_text("[pytest]\naddopts = " + addopts + "\n")
    (root / "app.py").write_text("READY = True\n")
    (root / "test_app.py").write_text("import app\n\ndef test_ready():\n    assert app.READY\n")
    return create_session(root, sys.executable, goal="pass_tests")


def original_pytest(root):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root,
                          env=env, capture_output=True, text=True, timeout=30)


def observed(config="", external="", **changes):
    values = {"config_complete": True, "config_file": "pytest.ini",
              "config_addopts": config, "environment_addopts": external}
    values.update(changes)
    return Run(tool="pytest_run", pytest_options=values)


def test_missing_coverage_option_keeps_pass_fact_without_claiming_original_success(tmp_path):
    session = project(tmp_path, "--cov=app")
    original = original_pytest(tmp_path)
    assert original.returncode == 4 and "unrecognized arguments: --cov=app" in original.stderr
    scan(session, ["pytest_run"])
    run = session.runs[-1]
    assert run.exit_code == 0 and run.verified_pass and run.coverage_complete
    assert run.passed_nodes == ["test_app.py::test_ready"]
    assert run.pytest_options["config_addopts"] == "--cov=app"
    assert run.pytest_options["config_file"] == str(tmp_path / "pytest.ini")
    assert not any(r["type"] == "pytest_config" for r in run.records)
    assert session.goal_status == "unknown" and not session.issues
    view = build_view(session)
    assert view["status"]["kind"] == "scope_limited"
    text = mcp_render(session, view)
    assert "The checked tests passed" in text and "Run your usual pytest command" in text
    assert "All tests pass" not in text and "Nothing else is needed" not in text
    page, exported, _ = html(session, tmp_path / "store")
    assert "recorded check passed" in page and "Run your usual pytest command" in page
    assert exported["runs"][-1]["pytest_options"] == run.pytest_options
    check = next(row for row in facts_view(session)["checks"] if row["check"] == "pytest_run")
    assert check["pytest_options"]["config_addopts"] == "--cov=app"
    assert "usual pytest command" not in json.dumps(check)


@pytest.mark.parametrize("addopts", [
    "-k ready", "-m slow", "--ignore=test_app.py", "--maxfail=1", "-x", "--cov=app",
])
def test_execution_changing_options_require_original_command_verification(tmp_path, addopts):
    session = project(tmp_path, addopts)
    scan(session, ["pytest_run"])
    run = session.runs[-1]
    assert run.verified_pass and run.test_summary["passed"] == 1
    assert pytest_option_coverage(run) == "different"
    assert session.goal_status == "unknown" and not session.issues


@pytest.mark.parametrize("addopts", ["", "   ", "-q", "-vv", "--color=yes --tb=short",
                                    "--no-header --show-capture=no"])
def test_empty_and_display_options_preserve_success(tmp_path, addopts):
    session = project(tmp_path, addopts)
    scan(session, ["pytest_run"])
    assert pytest_option_coverage(session.runs[-1]) == "equivalent"
    assert session.goal_status == "achieved"
    assert build_view(session)["status"]["headline"] == "All tests pass"


def test_actual_active_config_wins_over_unselected_file(tmp_path):
    session = project(tmp_path, "-q")
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\naddopts = "--cov=app"\n')
    scan(session, ["pytest_run"])
    assert session.runs[-1].pytest_options["config_addopts"] == "-q"
    assert session.runs[-1].pytest_options["config_file"] == str(tmp_path / "pytest.ini")
    assert session.goal_status == "achieved"


@pytest.mark.parametrize(("filename", "contents", "expected"), [
    ("setup.cfg", "[tool:pytest]\naddopts = --ignore=test_other.py\n", "--ignore=test_other.py"),
    ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = ["-k", "ready"]\n', ["-k", "ready"]),
])
def test_selected_config_formats_are_observed_by_pytest(tmp_path, filename, contents, expected):
    session = project(tmp_path)
    (tmp_path / "pytest.ini").unlink()
    (tmp_path / filename).write_text(contents)
    scan(session, ["pytest_run"])
    assert session.runs[-1].pytest_options["config_addopts"] == expected
    assert session.runs[-1].pytest_options["config_file"] == str(tmp_path / filename)
    assert session.runs[-1].verified_pass and session.goal_status == "unknown"


def test_external_options_are_recorded_but_not_executed(tmp_path, monkeypatch):
    session = project(tmp_path)
    monkeypatch.setenv("PYTEST_ADDOPTS", "--cov=app")
    assert original_pytest(tmp_path).returncode == 4
    scan(session, ["pytest_run"])
    assert session.runs[-1].verified_pass
    assert session.runs[-1].pytest_options["environment_addopts"] == "--cov=app"
    assert session.goal_status == "unknown"
    # Removing the external setting changes the verification baseline as removing
    # file addopts already does. Acceptance still needs a subsequent real check.
    monkeypatch.delenv("PYTEST_ADDOPTS")
    scan(session, ["pytest_run"])
    assert session.baseline_check["state"] == "changed"
    assert "pytest:PYTEST_ADDOPTS" in session.baseline_check["changed"]
    assert session.goal_status == "unknown"
    integrity.accept(session)
    scan(session, ["pytest_run"])
    assert session.goal_status == "achieved"


def test_no_config_and_external_display_options_still_verify(tmp_path, monkeypatch):
    session = project(tmp_path)
    (tmp_path / "pytest.ini").unlink()
    monkeypatch.setenv("PYTEST_ADDOPTS", "-q")
    scan(session, ["pytest_run"])
    observed = session.runs[-1].pytest_options
    assert observed["config_complete"] and observed["config_file"] == ""
    assert observed["config_addopts"] == "" and observed["environment_addopts"] == "-q"
    assert session.goal_status == "achieved"


def test_selected_pass_preserves_nodes_but_does_not_close_the_original_problem(tmp_path):
    session = project(tmp_path, "--cov=app")
    (tmp_path / "app.py").write_text("READY = False\n")
    scan(session, ["pytest_run"])
    [original] = [issue.issue_id for issue in session.issues]
    assert session.goal_status == "blocked"
    (tmp_path / "app.py").write_text("READY = True\n")
    scan(session, ["pytest_run"], targets=["test_app.py::test_ready"])
    run = session.runs[-1]
    issue = next(issue for issue in session.issues if issue.issue_id == original)
    assert run.scope == "tests:selected" and run.passed_nodes == ["test_app.py::test_ready"]
    assert run.verified_pass and issue.status == "awaiting_verification"
    assert issue.verification == "unverifiable" and "usual pytest command" in issue.note
    assert session.goal_status == "unknown" and not build_view(session)["fixed"]


def test_failure_is_still_a_failure_and_options_are_not_a_new_diagnosis(tmp_path):
    session = project(tmp_path, "-k skipped_by_original")
    (tmp_path / "app.py").write_text("READY = False\n")
    scan(session, ["pytest_run"])
    assert session.goal_status == "blocked"
    assert [issue.kind for issue in session.issues] == ["test_assertion"]
    assert "usual pytest command" in build_view(session)["status"]["detail"]


def test_collection_success_also_has_original_option_boundary(tmp_path):
    session = project(tmp_path, "--cov=app")
    session.goal = "collect_tests"
    scan(session, ["pytest"])
    assert session.runs[-1].verified_pass and session.goal_status == "unknown"
    assert build_view(session)["status"]["headline"] == "The checked tests load"


def test_legacy_run_defaults_remain_compatible_but_new_unknown_is_limited(tmp_path):
    session = project(tmp_path)
    scan(session, ["pytest_run"])
    run = session.runs[-1]
    legacy = Run.model_validate({k: v for k, v in run.model_dump().items() if k != "pytest_options"})
    session.runs[-1] = legacy
    assert pytest_option_coverage(legacy) == "legacy"
    assert goal_status(session, []) == "achieved"
    legacy.pytest_options = {"config_complete": False}
    assert pytest_option_coverage(legacy) == "unknown"
    assert goal_status(session, []) == "unknown"


@pytest.mark.parametrize("value", ['"unterminated', None, {"addopts": "-q"}, ["-q", 1], "--color",
                                   "--color=invalid"])
def test_unreadable_options_cannot_claim_equivalence(value):
    assert pytest_option_coverage(observed(value)) == "unknown"


def test_legacy_probe_reads_original_inicfg_without_looking_for_other_files(monkeypatch):
    emitted = []
    monkeypatch.setattr(probe, "emit", emitted.append)
    probe.record_pytest_options(SimpleNamespace(inicfg={"addopts": "--cov=app"}, inipath=None))
    assert emitted[0]["config_complete"] and emitted[0]["config_addopts"] == "--cov=app"


def test_probe_observation_failure_is_explicit_and_does_not_escape(monkeypatch):
    emitted = []
    monkeypatch.setattr(probe, "emit", emitted.append)
    probe.record_pytest_options(SimpleNamespace(inicfg={"addopts": object()}))
    assert emitted[0]["config_complete"] is False
    assert pytest_options_limited(observed(**{k: v for k, v in emitted[0].items() if k != "type"}))
    monkeypatch.setattr(probe, "emit", lambda data: (_ for _ in ()).throw(OSError("closed")))
    probe.record_pytest_options(None)  # no effect on the target pytest exception


def test_new_probe_config_reader_failure_is_unknown_without_fallback(tmp_path, monkeypatch):
    import _pytest.config.findpaths as findpaths

    emitted = []
    attempted = []

    def unreadable(path):
        attempted.append(path)
        raise OSError("unreadable active config")

    path = tmp_path / "selected.ini"
    monkeypatch.setattr(probe, "emit", emitted.append)
    monkeypatch.setattr(findpaths, "load_config_dict_from_file", unreadable)
    probe.record_pytest_options(SimpleNamespace(_inicfg={"addopts": ""}, inipath=path))
    assert attempted == [path]
    assert emitted[0]["config_complete"] is False and emitted[0]["config_addopts"] is None
