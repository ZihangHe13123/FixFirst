"""Installation failure -> next action, with actual local logs and wheel artifacts."""

import json
import os
from pathlib import Path
import subprocess
import tarfile
import zipfile

import pytest

from fixfirst.evidence import project_index
from fixfirst.install_feedback import bind_commands, collect_feedback, directory, prepared_wheels
from fixfirst.models import Action, Run, Session
from fixfirst.runner import environment_id
from fixfirst.service import ingest, scan
from fixfirst.workspace import build_view
from test_dependency_advice import recorded_session
from test_dependency_resolution import fixture_session, wheel, offline_resolver  # noqa: F401


def first_action(session):
    step = build_view(session)["steps"][0]
    return next(a for a in session.actions if a.action_id == step["id"])


def write_log(action, text):
    path = Path(action.command[action.command.index("--log") + 1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_failed_batch_offers_manual_build_and_records_feedback_only_once(tmp_path):
    session = recorded_session(tmp_path, "rich\nFlask-Mail==0.9.1\n", [],
                               "ModuleNotFoundError: No module named 'rich'")
    before = first_action(session)
    write_log(before, "Using pip 26.2.1\nSkipping link: No sources permitted for flask-mail: https://files.pythonhosted.org/Flask-Mail-0.9.1.tar.gz\nERROR: No matching distribution found for Flask-Mail==0.9.1\n")
    feedback = collect_feedback(session, project_index(session)[1])
    assert len(feedback) == 1 and feedback[0].source == "imported" and feedback[0].exit_code is None
    ingest(session, feedback)
    after = first_action(session)
    assert after.command[3] == "wheel" and after.command[-1] == "flask-mail==0.9.1"
    assert not any(a.command == before.command for a in session.actions)
    assert collect_feedback(session, project_index(session)[1]) == []
    assert session.goal_status != "achieved"
    assert Session.model_validate_json(session.model_dump_json()).installation_attempts == session.installation_attempts


def test_new_successful_invocation_does_not_reuse_appended_failure(tmp_path):
    session = recorded_session(tmp_path, "rich\nclick\n", [], "ModuleNotFoundError: No module named 'rich'")
    action = first_action(session)
    write_log(action, "2026-10-01T01:00:00 Using pip 26.2.1\nERROR: No matching distribution found for rich\n"
              "2026-10-01T02:00:00 Using pip 26.2.1\nSuccessfully installed rich\n")
    runs = collect_feedback(session, project_index(session)[1])
    assert "No matching" not in runs[0].stdout
    ingest(session, runs)
    assert not runs[0].verified_pass and session.goal_status != "achieved"
    assert not any(e.code == "no_distribution" for e in session.events)


@pytest.mark.parametrize("changed", ["declaration", "interpreter"])
def test_feedback_does_not_cross_changed_context(tmp_path, changed):
    session = recorded_session(tmp_path, "rich\nclick\n", [], "ModuleNotFoundError: No module named 'rich'")
    write_log(first_action(session), "ERROR: No matching distribution found for rich\n")
    project = project_index(session)[1]
    if changed == "declaration":
        project = {**project, "declarations": []}
    else:
        session.target_python = str(tmp_path / "another-env/bin/python")
    assert not collect_feedback(session, project)


@pytest.mark.parametrize("special", ["symlink", "fifo", "oversized"])
def test_feedback_is_bounded_and_never_waits_on_special_files(tmp_path, special):
    session = recorded_session(tmp_path, "rich\nclick\n", [], "ModuleNotFoundError: No module named 'rich'")
    action = first_action(session)
    path = Path(action.command[action.command.index("--log") + 1])
    path.parent.mkdir(parents=True)
    if special == "symlink":
        target = tmp_path / "other.log"
        target.write_text("ERROR: No matching distribution found for rich")
        path.symlink_to(target)
    elif special == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO requires POSIX")
        os.mkfifo(path)
    else:
        path.write_bytes(b"x" * 1_100_000 + b"\nERROR: No matching distribution found for rich\n")
    result = collect_feedback(session, project_index(session)[1])
    if special == "oversized":
        assert len(result[0].stdout.encode()) <= 1_000_000 and any("last 1 MB" in n for n in result[0].notes)
    else:
        assert not result and session.installation_attempts[-1]["read_error"]


def test_scan_automatically_reads_the_suggested_command_log(tmp_path):
    session = recorded_session(tmp_path, "rich\nFlask-Mail==0.9.1\n", [],
                               "ModuleNotFoundError: No module named 'rich'")
    write_log(first_action(session), "Skipping link: No sources permitted for flask-mail: https://files.pythonhosted.org/Flask-Mail-0.9.1.tar.gz\nERROR: No matching distribution found for Flask-Mail==0.9.1\n")
    scan(session, [])
    assert first_action(session).command[3] == "wheel"


def test_missing_pg_config_is_a_build_prerequisite_not_an_unpinned_version_change(tmp_path):
    session = recorded_session(tmp_path, "psycopg2\nrich\n", [], "ModuleNotFoundError: No module named 'rich'")
    run = Run(tool="pip_install", source="imported", exit_code=1,
        stdout="Collecting psycopg2\nError: pg_config executable not found.\n"
               "ERROR: Failed to build 'psycopg2' when getting requirements to build wheel\n")
    ingest(session, [run])
    action = first_action(session)
    assert "pg_config" in action.explanation and "psycopg2-binary" in action.explanation
    assert "fixed requirement" not in action.explanation
    assert action.check is None and not action.command
    assert "not evidence that another Python" in action.explanation
    detail = next(e for e in session.events if e.code == "missing_build_tool")
    assert f"{run.run_id}:stdout:2" in detail.evidence_refs


def test_missing_runner_still_proposes_the_required_project_set(tmp_path):
    session = recorded_session(tmp_path, "Flask\nclick<9\n", [], "")
    ingest(session, [Run(tool="pytest_run", environment_id=environment_id(session.target_python),
                        argv=[session.target_python, "-m", "pytest"], exit_code=1, scope="tests:project",
                        stderr=f"{session.target_python}: No module named pytest")])
    action = first_action(session)
    assert {"Flask", "click<9", "pytest"} <= set(action.command)
    assert "Install the declared dependency set" in action.title


def test_alternative_distribution_is_explained_before_resolving_again(tmp_path):
    session = recorded_session(tmp_path, "psycopg2\npandas==1.1.0\n", [
        {"name": "psycopg2-binary", "version": "2.9.9", "requires": []}],
        "ModuleNotFoundError: No module named 'pandas'", {"psycopg2": ["psycopg2-binary"]})
    ingest(session, [Run(tool="pip_install", source="imported", exit_code=1,
                        stdout="Collecting pandas==1.1.0\nERROR: Failed to build 'pandas'\n")])
    action = first_action(session)
    assert "Align the psycopg2 declaration" in action.title
    assert "requirements.txt:1" in action.explanation and "2.9.9" in action.explanation
    assert not any(a.check == "dependency_resolve" for a in session.actions)


def register_build(session, project, requirement):
    from fixfirst.install_feedback import build_command
    action = Action(action_id="build", kind="manual_fix", title="build", explanation="", verification="",
                    command=build_command(session, requirement))
    bind_commands(session, [action], project)
    return action


def test_real_manual_sdist_build_unblocks_isolated_trial_and_content_change_invalidates_it(tmp_path, request):
    from fixfirst.dependency_resolution import collect, latest

    _, _, index = request.getfixturevalue("offline_resolver")
    session, project = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\nff-prepared==1.0\n")
    before = collect(session, ["ff-trial-base", ">1"], 20)
    assert json.loads(before.stdout)["status"] == "not_resolved"
    source = tmp_path / "ff-prepared-1.0"
    source.mkdir()
    (source / "pyproject.toml").write_text('[build-system]\nrequires=[]\nbuild-backend="backend"\nbackend-path=["."]\n')
    (source / "backend.py").write_text("""import os, zipfile
def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    name = 'ff_prepared-1.0-py3-none-any.whl'
    with zipfile.ZipFile(os.path.join(wheel_directory, name), 'w') as z:
        z.writestr('ff_prepared-1.0.dist-info/METADATA', 'Metadata-Version: 2.1\\nName: ff-prepared\\nVersion: 1.0\\n')
        z.writestr('ff_prepared-1.0.dist-info/WHEEL', 'Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n')
        z.writestr('ff_prepared-1.0.dist-info/RECORD', '')
    return name
""")
    (source / "prepared.py").write_text("value = 1\n")
    with tarfile.open(index / "ff-prepared-1.0.tar.gz", "w:gz") as tar:
        tar.add(source, arcname=source.name)
    action = register_build(session, project, "ff-prepared==1.0")
    built = subprocess.run([*action.command, "--no-index", "--no-build-isolation", "--find-links", str(index)],
                           cwd=tmp_path, capture_output=True, text=True, timeout=40)
    assert built.returncode == 0, built.stdout + built.stderr
    assert len(prepared_wheels(session)) == 1
    trial = collect(session, ["ff-trial-base", ">1"], 20)
    result = json.loads(trial.stdout)
    assert result["status"] == "resolved" and not result["application_verified"]
    assert result["prepared_wheels"][0]["name"] == "ff-prepared"
    ingest(session, [trial])
    assert latest(session, session.environment, project, "ff-trial-base", ">1")[0] == trial
    path = next((directory(session) / "wheels").glob("*.whl"))
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("extra.txt", "different content")
    assert latest(session, session.environment, project, "ff-trial-base", ">1") == (None, None)


def test_unrequested_or_mislabeled_wheelhouse_is_not_used(tmp_path):
    session, project = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\n")
    register_build(session, project, "ff-prepared==1.0")
    folder = directory(session) / "wheels"
    folder.mkdir(parents=True)
    wheel(folder, "ff-prepared", "1.0")
    assert len(prepared_wheels(session)) == 1
    wheel(folder, "unrequested", "1.0")
    assert not prepared_wheels(session)  # Not even the otherwise valid file is passed to pip.


def test_pip_debug_resolution_exception_does_not_turn_a_missing_wheel_into_a_conflict(tmp_path):
    from fixfirst.parsers import parse
    run = Run(tool="pip_install", source="imported", stdout=(
        "Skipping link: No sources permitted for flask-mail: https://files.pythonhosted.org/Flask-Mail-0.9.1.tar.gz\n"
        "ERROR: No matching distribution found for Flask-Mail==0.9.1\n"
        "    raise ResolutionImpossible(e.criterion.information) from e\n"
        "pip._vendor.resolvelib.resolvers.exceptions.ResolutionImpossible: [RequirementInformation(...)]\n"))
    events = parse(run)
    assert any(e.code == "no_wheel" and e.component == "flask-mail" for e in events)
    assert not any(e.kind == "dependency_conflict" for e in events)


def test_absent_version_is_not_called_source_only(tmp_path):
    session = recorded_session(tmp_path, "six==9999\nrich\n", [], "ModuleNotFoundError: No module named 'rich'")
    action = first_action(session)
    write_log(action, "Using pip 26.2.1\n"
              "Skipping link: No sources permitted for six: https://files.pythonhosted.org/six-1.16.0.tar.gz\n"
              "ERROR: No matching distribution found for six==9999\n")
    ingest(session, collect_feedback(session, project_index(session)[1]))
    step = first_action(session)
    assert "package index" in step.title and not step.command and not step.check


def test_legacy_build_configuration_has_its_own_explanation(tmp_path):
    session = recorded_session(tmp_path, "anyjson==0.3.3\nrich\n", [], "ModuleNotFoundError: No module named 'rich'")
    ingest(session, [Run(tool="pip_install", source="imported", stdout=(
        "Collecting anyjson==0.3.3\nerror in anyjson setup command: use_2to3 is invalid.\n"
        "ERROR: Failed to build 'anyjson' when getting requirements to build wheel\n"))])
    step = first_action(session)
    assert "legacy build configuration" in step.title
    assert "use_2to3" in step.explanation and not step.check


def test_real_conflict_is_not_repeated_or_turned_into_a_build(tmp_path):
    session = recorded_session(tmp_path, "requests==2.31.0\nurllib3==1.20\n", [],
                               "ModuleNotFoundError: No module named 'requests'")
    action = first_action(session)
    write_log(action, "Using pip 26.2.1\n"
        "ERROR: Cannot install requests==2.31.0 and urllib3==1.20 because these package versions have conflicting dependencies.\n"
        "The conflict is caused by:\nThe user requested urllib3==1.20\nrequests 2.31.0 depends on urllib3>=1.21.1,<3\n"
        "ERROR: ResolutionImpossible: dependency conflict\n")
    ingest(session, collect_feedback(session, project_index(session)[1]))
    step = first_action(session)
    assert "conflicting requirements" in step.title
    assert "requests" in step.explanation and "urllib3" in step.explanation
    assert not any(a.command[:4] == action.command[:4] for a in session.actions)


def test_hash_checked_requirements_do_not_lose_hashes_in_generated_commands(tmp_path):
    session = recorded_session(tmp_path, "rich==13.0.0 --hash=sha256:abc\nclick\n", [],
                               "ModuleNotFoundError: No module named 'rich'")
    step = first_action(session)
    assert "hash-checked" in step.title and not step.command


def test_long_verbose_log_preserves_the_source_link_for_the_failed_pin(tmp_path):
    session = recorded_session(tmp_path, "rich\nFlask-Mail==0.9.1\n", [],
                               "ModuleNotFoundError: No module named 'rich'")
    action = first_action(session)
    write_log(action, "Using pip 26.2.1\n"
        "Skipping link: No sources permitted for flask-mail: https://files.pythonhosted.org/Flask-Mail-0.9.1.tar.gz\n"
        + ("Unrelated wheel link\n" * 100000)
        + "ERROR: No matching distribution found for Flask-Mail==0.9.1\n")
    feedback = collect_feedback(session, project_index(session)[1])
    assert len(feedback[0].stdout.encode()) <= 1_000_000
    ingest(session, feedback)
    assert first_action(session).command[3] == "wheel"


def test_log_from_another_python_is_not_imported_as_current_feedback(tmp_path):
    session = recorded_session(tmp_path, "rich\nclick\n", [], "ModuleNotFoundError: No module named 'rich'")
    session.environment["prefix"] = str(tmp_path / "expected")
    write_log(first_action(session), "Using pip 26.2.1 from /other/env/lib/python3.12/site-packages/pip (python 3.12)\n"
              "ERROR: No matching distribution found for rich\n")
    assert not collect_feedback(session, project_index(session)[1])
    assert "different interpreter" in session.installation_attempts[-1]["read_error"]


def test_wheel_for_a_different_interpreter_is_not_an_available_prepared_package(tmp_path):
    session, project = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\n")
    register_build(session, project, "ff-prepared==1.0")
    folder = directory(session) / "wheels"
    folder.mkdir(parents=True)
    wheel(folder, "ff-prepared", "1.0")
    next(folder.glob("*.whl")).rename(folder / "ff_prepared-1.0-cp311-cp311-win_amd64.whl")
    assert prepared_wheels(session) == []


def test_candidate_failure_is_read_after_the_exact_suggested_declaration_edit(tmp_path):
    from fixfirst.project import assess_project, read_project
    session = recorded_session(tmp_path, "rich==13.0.0\nclick\n", [], "ModuleNotFoundError: No module named 'rich'")
    project = project_index(session)[1]
    action = Action(action_id="candidate", kind="manual_fix", title="apply candidate", explanation="", verification="",
        command=[session.target_python, "-m", "pip", "install", "--only-binary=:all:", "rich==13.9.4", "click"],
        declaration_edits=[{"source": "requirements.txt:1", "before": "rich==13.0.0", "after": "rich==13.9.4"}])
    bind_commands(session, [action], project)
    write_log(action, "Using pip 26.2.1\nERROR: No matching distribution found for rich==13.9.4\n")
    (tmp_path / "requirements.txt").write_text("rich==13.9.4\nclick\n")
    current = assess_project(read_project(tmp_path), session.environment)
    assert len(collect_feedback(session, current)) == 1
    (tmp_path / "requirements.txt").write_text("rich==14\nclick\n")
    assert collect_feedback(session, assess_project(read_project(tmp_path), session.environment)) == []
