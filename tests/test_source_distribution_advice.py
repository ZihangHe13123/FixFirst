"""Source availability is not wheel eligibility or a successful source build."""

import json
import os
import subprocess
import sys
import tarfile

import pytest

from fixfirst import versions
from fixfirst.evidence import project_index
from fixfirst.install_feedback import collect_feedback, prepared_wheels
from fixfirst.models import Run
from fixfirst.parsers import parse
from fixfirst.runner import collect, environment_id
from fixfirst.service import create_session, ingest, scan
from test_dependency_advice import recorded_session
from test_install_feedback import first_action, write_log
from test_dependency_resolution import fixture_session, offline_resolver  # noqa: F401


def artifact(kind, version, requires_python=None):
    suffix = "py3-none-any.whl" if kind == "bdist_wheel" else "tar.gz"
    return {"packagetype": kind, "filename": f"demo-{version}-{suffix}" if kind == "bdist_wheel"
            else f"demo-{version}.{suffix}", "requires_python": requires_python}


def no_sandbox(*args):
    pytest.fail("A source-only or excluded release must not start a probe/build")


@pytest.mark.parametrize("files,status", [
    ([artifact("sdist", "1.0")], "source_build_required"),
    ([artifact("sdist", "1.0", ">=3.13")], "python_requires"),
    ([artifact("sdist", "1.0", "not-a-specifier")], "no_candidates"),
    ([{**artifact("bdist_wheel", "1.0"), "filename": "demo-1.0-cp311-cp311-win_amd64.whl"}], "no_candidates"),
])
def test_version_search_explains_untried_artifacts_without_building(files, status):
    result = versions.search("python", "3.12.13", {}, "demo", "2.0", "demo.old_name",
        fetch=lambda url: {"releases": {"1.0": files}}, sandbox=no_sandbox)
    assert result["status"] == status and result["checked"] == []
    assert result["trial_restriction"] == "wheels_only"
    event, = parse(Run(tool="version_search", exit_code=0, stdout=json.dumps(result)))
    if status == "source_build_required":
        assert result["availability"]["source_only"] == ["1.0"]
        assert "source archives exist" in event.message and "system prerequisites" in event.message
    elif status == "python_requires":
        assert "Requires-Python" in event.message
    else:
        assert "does not prove that the release is absent" in event.message


def test_skipped_source_releases_do_not_prove_the_name_absent_everywhere():
    class Missing:
        def provides(self, *args):
            return "missing"

        def close(self):
            pass

    result = versions.search("python", "3.12.13", {}, "demo", "3.0", "demo.old_name",
        fetch=lambda url: {"releases": {"1.0": [artifact("sdist", "1.0")],
                                       "2.0": [artifact("bdist_wheel", "2.0")]}},
        sandbox=lambda python: Missing())
    assert result["status"] == "not_judged"
    assert result["checked"] == [{"version": "2.0", "result": "missing"}]


def test_compatible_wheel_and_declared_bounds_still_decide_probe_candidates():
    data = {"releases": {"1.0": [artifact("sdist", "1.0")],
                         "1.1": [artifact("sdist", "1.1"), artifact("bdist_wheel", "1.1")]}}
    availability = versions.candidate_availability(data, "2.0", "3.12.13", {}, ">=1.1")
    assert availability["wheels"] == ["1.1"] and not availability["source_only"]
    assert availability["constraints_excluded"] == ["1.0"]


@pytest.mark.parametrize("extra,code,title", [
    ("WARNING: Retrying after connection broken by NewConnectionError: Connection refused\n", "index_access", "index access"),
    ("ERROR: Package 'demo' requires a different Python: 3.12 not in '>=3.13'\n", "python_requires", "Python requirement"),
])
def test_index_and_python_rejections_do_not_turn_into_manual_source_builds(tmp_path, extra, code, title):
    session = recorded_session(tmp_path, "demo==1.0\nrich\n", [], "ModuleNotFoundError: No module named 'rich'")
    install = first_action(session)
    write_log(install, "Skipping link: No sources permitted for demo: file:///index/demo-1.0.tar.gz\n"
              + extra + "ERROR: No matching distribution found for demo==1.0\n")
    ingest(session, collect_feedback(session, project_index(session)[1]))
    assert any(e.code == code and e.component == "demo" for e in session.events)
    action = first_action(session)
    assert title in action.title and not action.command and not action.check


def test_source_link_python_metadata_can_rule_out_the_recorded_interpreter(tmp_path):
    session = recorded_session(tmp_path, "demo==1.0\nrich\n", [], "ModuleNotFoundError: No module named 'rich'")
    write_log(first_action(session),
        "Skipping link: No sources permitted for demo: file:///index/demo-1.0.tar.gz (requires-python:>=99)\n"
        "ERROR: No matching distribution found for demo==1.0\n")
    ingest(session, collect_feedback(session, project_index(session)[1]))
    assert any(e.code == "python_requires" for e in session.events)
    assert not first_action(session).command


def test_source_only_search_reason_reaches_the_existing_nonrepeating_action(tmp_path):
    from packaging.utils import canonicalize_name
    from fixfirst.reasoning import infer_and_plan
    from test_reasoning import run_scenario

    session, _ = run_scenario(tmp_path, "vi_private_moved")
    dist, api = session.actions[0].targets
    installed = next(p["version"] for p in session.environment["packages"]
                     if canonicalize_name(p["name"]) == dist)
    session.runs.append(Run(tool="version_search", exit_code=0,
        environment_id=environment_id(session.target_python),
        stdout=json.dumps({"dist": dist, "api": api, "installed": installed,
                           "status": "source_build_required", "checked": [], "provides": None,
                           "availability": {"source_only": ["1.0"]}})))
    infer_and_plan(session)
    action = next(a for a in session.actions if "P66" in a.rule_ids)
    assert "source archives" in action.explanation and "not built" in action.explanation
    assert not action.command and action.check is None
    assert not any(a.check == "version_search" for a in session.actions)


def local_source(index, name, *, missing_tool=False):
    source = index.parent / (name + "-1.0")
    source.mkdir()
    marker = index.parent / (name + "-built")
    backend = (
        "import pathlib, zipfile\n"
        "def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):\n"
        f"    pathlib.Path({str(marker)!r}).write_text('build ran')\n"
    )
    if missing_tool:
        backend += "    raise RuntimeError('pg_config executable not found')\n"
    else:
        base = name.replace("-", "_")
        backend += (
            f"    filename = '{base}-1.0-py3-none-any.whl'\n"
            "    with zipfile.ZipFile(pathlib.Path(wheel_directory) / filename, 'w') as wheel:\n"
            f"        wheel.writestr('{base}.py', 'value = 1\\n')\n"
            f"        wheel.writestr('{base}-1.0.dist-info/METADATA', 'Metadata-Version: 2.1\\nName: {name}\\nVersion: 1.0\\n')\n"
            f"        wheel.writestr('{base}-1.0.dist-info/WHEEL', 'Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n')\n"
            f"        wheel.writestr('{base}-1.0.dist-info/RECORD', '')\n"
            "    return filename\n"
        )
    (source / "backend.py").write_text(backend)
    (source / "pyproject.toml").write_text(
        '[build-system]\nrequires=[]\nbuild-backend="backend"\nbackend-path=["."]\n')
    with tarfile.open(index / (name + "-1.0.tar.gz"), "w:gz") as archive:
        archive.add(source, arcname=source.name)
    return marker


def test_real_pip_fallback_trial_records_its_source_build_restriction(tmp_path, monkeypatch, request):
    from fixfirst import dependency_resolution

    _, _, index = request.getfixturevalue("offline_resolver")
    marker = local_source(index, "ff-prepared")
    session, _ = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\nff-prepared==1.0\n")
    monkeypatch.setattr(dependency_resolution.shutil, "which", lambda command: None)
    result = json.loads(dependency_resolution.collect(session, ["ff-trial-base", ">1"], 40).stdout)
    assert result["status"] == "not_resolved"
    assert result["trial_restriction"] == "wheels_only"
    assert result["blocked_requirement"] == "ff-prepared==1.0"
    assert result["source_archive_observed"] is True and not marker.exists()
    assert "install_requests" not in result


@pytest.mark.parametrize("output,kind", [
    ("WARNING: Could not fetch URL https://example.invalid/simple: connection failed\n"
     "ERROR: No matching distribution found for demo==1.0\n", "index_access"),
    ("ERROR: Package 'demo' requires a different Python: 3.12 not in '>=99'\n"
     "ERROR: No matching distribution found for demo==1.0\n", "python_requires"),
])
def test_trial_failure_context_does_not_offer_source_builds_for_other_blockers(tmp_path, monkeypatch, output, kind):
    from fixfirst import runner
    from fixfirst.dependency_resolution import collect as resolve, advise
    from fixfirst.models import Action

    session, project = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\ndemo==1.0\n")

    def execute(argv, cwd, tool, scope, interpreter, *args, **kwargs):
        return Run(tool=tool, scope=scope, environment_id=environment_id(interpreter),
                   exit_code=1 if "install" in argv else 0, stderr=output if "install" in argv else "")

    monkeypatch.setattr(runner, "execute", execute)
    trial = resolve(session, ["ff-trial-base"], 20)
    result = json.loads(trial.stdout)
    assert result["failure_kind"] == kind and "trial_restriction" not in result
    ingest(session, [trial])
    action = Action(action_id="trial", kind="manual_fix", title="review", explanation="", verification="")
    advise(session, action, session.environment, project, "ff-trial-base")
    assert not action.command and action.check is None


@pytest.mark.parametrize("missing_tool", [False, True])
def test_real_offline_source_request_build_and_feedback_do_not_loop(tmp_path, monkeypatch, missing_tool):
    index = tmp_path / "index"
    index.mkdir()
    name = "ffsource"
    marker = local_source(index, name, missing_tool=missing_tool)
    env = tmp_path / "env"
    subprocess.run([sys.executable, "-m", "venv", str(env)], check=True, capture_output=True, timeout=40)
    python = str(env / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    project = tmp_path / "project"
    project.mkdir()
    requirement = project / "requirements.txt"
    requirement.write_text("ffsource==1.0\n")
    session = create_session(project, python, goal="pass_tests")
    environment = collect(session, "environment")
    snapshot = collect(session, "project")
    failure = Run(tool="pytest_run", environment_id=environment_id(python), scope="tests:project",
                  exit_code=2, stderr="ModuleNotFoundError: No module named 'ffsource'")
    ingest(session, [environment, snapshot, failure])
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(index))
    monkeypatch.setenv("PIP_CONFIG_FILE", os.devnull)
    first = first_action(session)
    assert first.command[:4] == [python, "-m", "pip", "install"]
    blocked = subprocess.run(first.command, cwd=project, capture_output=True, text=True, timeout=40)
    assert blocked.returncode != 0 and not marker.exists()
    ingest(session, collect_feedback(session, project_index(session)[1]))
    build = first_action(session)
    assert build.command[:4] == [python, "-m", "pip", "wheel"]
    assert "system prerequisites" in build.explanation and "manual operation" in build.explanation
    scan(session, [])
    assert not marker.exists()  # Reading suggested-command feedback never builds.
    built = subprocess.run(build.command, cwd=project, capture_output=True, text=True, timeout=40)
    assert marker.exists()
    ingest(session, collect_feedback(session, project_index(session)[1]))
    assert requirement.read_text() == "ffsource==1.0\n" and session.goal_status != "achieved"
    if missing_tool:
        assert built.returncode != 0
        assert "build prerequisite" in first_action(session).title
        assert "pg_config" in first_action(session).explanation
        assert not any(action.command or action.check == "dependency_resolve" for action in session.actions)
        return
    assert built.returncode == 0 and len(prepared_wheels(session)) == 1
    retry = first_action(session)
    assert "--only-binary=:all:" in retry.command and "--find-links" in retry.command
    installed = subprocess.run(retry.command, cwd=project, capture_output=True, text=True, timeout=40)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    checked = subprocess.run([python, "-m", "pip", "check"], capture_output=True, timeout=20)
    assert checked.returncode == 0 and session.goal_status != "achieved"
