"""A real resolver checks the proposed set using small, offline wheel fixtures."""

import json
from pathlib import Path
import shutil
import sys
import zipfile

from packaging.markers import default_environment
import pytest

from fixfirst.dependency_resolution import collect, inputs, latest
from fixfirst.models import Run
from fixfirst.project import assess_project, read_project
from fixfirst.runner import environment_id
from fixfirst.service import create_session, ingest


def fixture_session(root, requirements):
    root.mkdir()
    (root / "requirements.txt").write_text(requirements)
    session = create_session(root, sys.executable, goal="pass_tests")
    env = {"python_version": "3.12.13", "markers": default_environment(),
           "packages": [{"name": "ff-trial-base", "version": "1.0", "requires": []},
                        {"name": "ff-trial-ext", "version": "1.0", "requires": ["ff-trial-base<2"]},
                        {"name": "ff-trial-other", "version": "1.0", "requires": []}]}
    identity = environment_id(session.target_python)
    env_run = Run(tool="environment", exit_code=0, environment_id=identity, stdout=json.dumps(env))
    session.environment = {**env, "_run_id": env_run.run_id, "_environment_id": identity}
    project = assess_project(read_project(root), env)
    project["environment_run_id"] = env_run.run_id
    project_run = Run(tool="project", exit_code=0, environment_id=identity,
                      stdout=json.dumps(project), scope="declarations:project")
    ingest(session, [env_run, project_run])
    return session, project


def wheel(folder, name, version, requires=()):
    base = name.replace("-", "_")
    dist_info = f"{base}-{version}.dist-info"
    with zipfile.ZipFile(folder / f"{base}-{version}-py3-none-any.whl", "w") as z:
        z.writestr(dist_info + "/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
                   + "".join(f"Requires-Dist: {r}\n" for r in requires))
        z.writestr(dist_info + "/WHEEL", "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(dist_info + "/RECORD", "")


@pytest.fixture
def offline_resolver(tmp_path, monkeypatch):
    if not shutil.which("uv"):
        pytest.skip("Real offline wheel test uses uv")
    from fixfirst import runner

    wheels = tmp_path / "wheels"
    wheels.mkdir()
    for name in ("ff-trial-base", "ff-trial-other"):
        for version in ("1.0", "2.0"):
            wheel(wheels, name, version)
    wheel(wheels, "ff-trial-ext", "1.0", ["ff-trial-base<2"])
    wheel(wheels, "ff-trial-ext", "2.0", ["ff-trial-base>=2,<3"])
    original = runner.execute
    created, commands = [], []

    def execute(argv, *args, **kwargs):
        commands.append(argv)
        if "install" in argv:
            argv = [*argv, "--no-index", "--find-links", str(wheels)]
        if "venv" in argv:
            created.append(Path(argv[-1]).parent)
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(runner, "execute", execute)
    return created, commands, wheels


def test_joint_resolution_uses_new_metadata_and_preserves_other_requirements(tmp_path, offline_resolver):
    session, project = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\n")
    original = (tmp_path / "project" / "requirements.txt").read_bytes()
    run = collect(session, ["ff-trial-base", ">1.0"], 20)
    result = json.loads(run.stdout)
    assert result["status"] == "resolved", result
    assert result["application_verified"] is False
    assert result["edits"][0]["after"] == "ff-trial-base==2.0"
    assert result["install_requests"] == ["ff-trial-base==2.0", "ff-trial-ext==2.0", "ff-trial-other==1.0"]
    assert all(c["exit_code"] == 0 for c in result["checks"])
    assert (tmp_path / "project" / "requirements.txt").read_bytes() == original
    assert all(not p.exists() for p in offline_resolver[0])
    assert run.run_id not in {r.run_id for r in session.runs}  # No implicit session mutation.
    ingest(session, [run])
    assert latest(session, session.environment, project, "ff-trial-base", ">1.0")[0] == run
    project["declarations"][0]["requirement"] = "ff-trial-base==1.1"
    assert latest(session, session.environment, project, "ff-trial-base", ">1.0") == (None, None)


def test_resolution_keeps_other_pin_and_retains_real_resolver_failure(tmp_path, offline_resolver):
    session, _ = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext==1.0\n")
    run = collect(session, ["ff-trial-base", ">1.0"], 20)
    result = json.loads(run.stdout)
    assert result["status"] == "not_resolved"
    assert "ff-trial-ext==1.0" in result["requests"]
    assert "install_requests" not in result
    assert result["checks"][-1]["exit_code"] != 0
    assert "ff-trial" in result["checks"][-1]["output"]
    assert all(not p.exists() for p in offline_resolver[0])


def test_transitive_dependency_can_update_but_unrelated_package_stays_pinned(tmp_path, offline_resolver):
    session, _ = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\n")
    session.environment["packages"][0]["requires"] = ["ff-trial-helper>=1"]
    session.environment["packages"].append({"name": "ff-trial-helper", "version": "1.0", "requires": []})
    wheels = offline_resolver[2]
    for version in ("1.0", "2.0"):
        wheel(wheels, "ff-trial-helper", version)
    wheel(wheels, "ff-trial-base", "2.0", ["ff-trial-helper>=2"])
    result = json.loads(collect(session, ["ff-trial-base", ">1.0"], 20).stdout)
    assert result["status"] == "resolved", result
    assert "ff-trial-helper==2.0" in result["install_requests"]
    assert "ff-trial-other==1.0" in result["install_requests"]


def test_obsolete_installed_dependency_cannot_disappear_from_installation_trial(tmp_path, offline_resolver):
    session, _ = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\n")
    session.environment["packages"][0]["requires"] = ["ff-trial-obsolete"]
    session.environment["packages"] += [
        {"name": "ff-trial-obsolete", "version": "1.0", "requires": ["ff-trial-helper<2"]},
        {"name": "ff-trial-helper", "version": "1.0", "requires": []},
    ]
    wheels = offline_resolver[2]
    for version in ("1.0", "2.0"):
        wheel(wheels, "ff-trial-helper", version)
    wheel(wheels, "ff-trial-obsolete", "1.0", ["ff-trial-helper<2"])
    wheel(wheels, "ff-trial-base", "2.0", ["ff-trial-helper>=2"])
    result = json.loads(collect(session, ["ff-trial-base", ">1.0"], 20).stdout)
    # An in-place pip install leaves obsolete packages installed. Omitting one
    # from the temporary environment would falsely validate a conflicting set.
    assert result["status"] == "not_resolved", result
    assert "install_requests" not in result


@pytest.mark.parametrize("requirements", ["ff-trial-base==1.0\nother @ https://example.org/other.whl\n",
                                          "ff-trial-base==1.0\n-e .\n"])
def test_incomplete_declarations_never_become_complete_installation_proof(tmp_path, requirements):
    session, _ = fixture_session(tmp_path / "project", requirements)
    run = collect(session, ["ff-trial-base"], 1)
    result = json.loads(run.stdout)
    assert result["status"] == "not_resolved" and not result["checks"]


def test_target_markers_optional_groups_and_pin_sources(tmp_path):
    session, project = fixture_session(tmp_path / "project", "ff-trial-base[speed]==1.0\n")
    project["declarations"] += [
        {"requirement": "foreign; sys_platform=='win32'", "source": "requirements.txt:2", "group": "required"},
        {"requirement": "docs-extra", "source": "pyproject.toml", "group": "docs"},
        {"requirement": "ff-trial-ext<3", "source": "constraints.txt:1", "constraint": True},
    ]
    session.environment["markers"]["sys_platform"] = "linux"
    plan = inputs(session.environment, project, "ff-trial-base", ">1.0")
    assert "ff-trial-base[speed]>1.0" in plan["requests"]
    assert not any("foreign" in r or "docs-extra" in r for r in plan["requests"])
    assert plan["constraints"] == ["ff-trial-ext<3"]
    assert plan["edits"][0]["source"] == "requirements.txt:1"


def test_dependency_trial_does_not_close_original_failure(tmp_path, monkeypatch):
    from fixfirst.dependency_resolution import advise
    from fixfirst.models import Action

    session, project = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\n")
    original = Run(tool="pytest_run", environment_id=environment_id(session.target_python), scope="tests:project",
                   exit_code=1, stderr="E AssertionError: original failure")
    ingest(session, [original])
    before = session.goal_status
    from fixfirst.dependency_resolution import fingerprint
    result = {"dist": "ff-trial-base", "direction": ">1.0", "status": "resolved", "python": "3.12.13",
              "context_fingerprint": fingerprint(session.environment, project),
              "edits": [{"source": "requirements.txt:1", "before": "ff-trial-base==1.0", "after": "ff-trial-base==2.0"}],
              "install_requests": ["ff-trial-base==2.0", "ff-trial-ext==2.0"]}
    trial = Run(tool="dependency_resolve", exit_code=0, scope="dependencies:ff-trial-base",
                environment_id=environment_id(session.target_python), stdout=json.dumps(result))
    ingest(session, [trial])
    action = Action(action_id="trial", kind="manual_fix", title="review", explanation="", verification="")
    advise(session, action, session.environment, project, "ff-trial-base", ">1.0")
    assert "replace ff-trial-base==1.0 with ff-trial-base==2.0" in action.explanation
    assert "NOT run" in action.explanation
    assert session.goal_status == before and session.goal_status != "reached"
    assert next(i for i in session.issues if i.tool == "pytest_run").status != "resolved"


def test_documented_python_is_only_a_hint_and_conda_unknowns_are_kept(tmp_path):
    (tmp_path / "README.md").write_text("# Setup\nPython 3.5.2\n")
    (tmp_path / "environment.yml").write_text("dependencies:\n - scipy\n - scikit-learn\n - matplotlib\n - pandas\n - pillow\n - joblib\n - cuda-toolkit\n - conda-forge::special=1.2=build\n")
    project = read_project(tmp_path)
    assert {r["name"] for r in project["declarations"]} == {"scipy", "scikit-learn", "matplotlib", "pandas", "pillow", "joblib"}
    assert len(project["conda_declarations"]) == 2
    assert all(m["source"].startswith("https://") and m["conda_source"].startswith("https://") for m in project["conda_mappings"])
    assert project["python_hints"] == [{"version": "3.5.2", "source": "README.md:2"}]
    assert not project["requires_python"]


def test_expired_trial_is_not_cached_as_success_and_does_not_install(tmp_path, monkeypatch):
    from fixfirst import runner
    from fixfirst.parsers import parse

    session, project = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\n")
    def should_not_run(*args, **kwargs):
        pytest.fail("An expired trial must not start a subprocess")
    monkeypatch.setattr(runner, "execute", should_not_run)
    run = collect(session, ["ff-trial-base", ">1"], 0)
    assert run.status == "timeout"
    data = json.loads(run.stdout)
    assert data["status"] == "not_resolved" and not data["checks"]
    assert "install_requests" not in data
    parse(run)
    assert not run.verified_pass
    run.source = "imported"
    session.runs.append(run)
    assert latest(session, session.environment, project, "ff-trial-base", ">1") == (None, None)


@pytest.mark.parametrize("blocker,output", [
    ("docopt==0.6.2", "Because docopt==0.6.2 has no usable wheels and you require docopt==0.6.2"),
    ("docopt", "Because all versions of docopt have no usable wheels and you require docopt"),
    ("docopt==0.6.2", "╰─▶ Because docopt==0.6.2 has no\n    │ usable wheels and you require docopt==0.6.2"),
    ("docopt>=0.6", "Because all versions of docopt>=0.6 have no usable wheels"),
    ("docopt<0.7,>=0.6", "Because docopt >= 0.6, <0.7 has no usable wheels"),
])
def test_wheel_restriction_names_actual_blocker_without_blaming_changed_package(tmp_path, monkeypatch, blocker, output):
    from fixfirst import runner
    from fixfirst.dependency_resolution import advise
    from fixfirst.models import Action

    session, project = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\ndocopt\n")
    def execute(argv, cwd, tool, scope, interpreter, *args, **kwargs):
        installing = "install" in argv
        return Run(tool=tool, scope=scope, environment_id=environment_id(interpreter),
                   exit_code=1 if installing else 0,
                   stderr=output if installing else "")
    monkeypatch.setattr(runner, "execute", execute)
    trial = collect(session, ["ff-trial-base"], 20)
    result = json.loads(trial.stdout)
    assert result["trial_restriction"] == "wheels_only"
    assert result["blocked_requirement"] == blocker
    ingest(session, [trial])
    action = Action(action_id="trial", kind="manual_fix", title="review", explanation="Change the Python version", verification="")
    advise(session, action, session.environment, project, "ff-trial-base")
    assert blocker in action.title and "ff-trial-base" not in action.title
    assert "does not establish a version conflict" in action.explanation
    assert "Change the Python version" not in action.explanation
    assert action.command[3] == "wheel" and not action.check
