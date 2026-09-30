import json
import subprocess
import sys

from fixfirst.cases import create_project, inject, repair_fixture
from fixfirst.models import Run
from fixfirst.runner import collect
from fixfirst.service import create_session, scan, ingest
from fixfirst.storage import Store


def cli(store, *args):
    return subprocess.run(
        [sys.executable, "-m", "fixfirst", "--store", str(store), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_real_probe_reports_collection_and_restore(tmp_path):
    root = tmp_path / "project"
    create_project(root, "integration")
    session = create_session(root, sys.executable)
    scan(session, ["pytest", "ruff"])
    assert session.goal_status == "achieved"
    inject(root, "mixed")
    scan(session, ["pytest", "ruff"])
    assert session.goal_status == "blocked"
    assert len(session.issues) == 2
    assert len(next(i for i in session.issues if i.kind == "import_failure").event_ids) == 2
    repair_fixture(root, "mixed")
    scan(session, ["pytest", "ruff"])
    assert session.goal_status == "achieved"
    assert all(i.status == "resolved" for i in session.issues)


def test_ruff_config_cannot_enable_mutation(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nfix=true\nfix-only=true\n[tool.ruff.lint]\nselect=["F401"]\n'
    )
    source = tmp_path / "example.py"
    source.write_text("import os\n")
    session = create_session(tmp_path, sys.executable, goal="check_style")
    scan(session, ["ruff"])
    assert source.read_text() == "import os\n"
    assert session.issues


def test_real_config_failure_and_tool_missing(tmp_path):
    root = tmp_path / "project"
    create_project(root, "config")
    inject(root, "missing_config")
    session = create_session(root, sys.executable)
    scan(session, ["pytest"])
    assert {i.kind for i in session.issues} == {"explicit_config_missing"}
    assert session.goal_status == "blocked"


def test_cli_create_import_export_stop_delete(tmp_path):
    project, store = tmp_path / "project", tmp_path / "store"
    create_project(project, "CLI")
    result = cli(store, "init", str(project), "--python", sys.executable, "--goal", "collect_tests")
    assert result.returncode == 0, result.stderr
    sid = result.stdout.splitlines()[0]
    assert cli(store, "scan", sid, "--checks", "pytest").returncode == 0
    data = json.loads(cli(store, "show", sid, "--json").stdout)
    assert data["goal_status"] == "achieved"
    log = tmp_path / "install.txt"
    log.write_text("ERROR: ResolutionImpossible: conflicting dependencies")
    assert cli(store, "import", sid, "--tool", "pip_install", "--file", str(log)).returncode == 0
    exported = tmp_path / "share.html"
    assert cli(store, "export", sid, "--output", str(exported)).returncode == 0
    assert exported.exists() and exported.with_suffix(".json").exists()
    assert cli(store, "stop", sid).returncode == 0
    assert cli(store, "scan", sid).returncode == 2
    assert cli(store, "resume", sid).returncode == 0
    assert cli(store, "delete", sid).returncode == 2
    assert cli(store, "delete", sid, "--yes").returncode == 0
    assert project.is_dir()
    assert not (store / sid).exists()


def test_imported_success_does_not_claim_goal(tmp_path):
    session = create_session(tmp_path, sys.executable, goal="check_style")
    run = Run(tool="ruff", source="imported", stdout="[]", exit_code=0)
    ingest(session, [run])
    assert session.goal_status == "unknown"


def test_scope_different_does_not_resolve(tmp_path):
    root = tmp_path / "project"
    create_project(root, "scope")
    inject(root, "mixed")
    session = create_session(root, sys.executable)
    scan(session, ["pytest"])
    repair_fixture(root, "mixed")
    run = collect(session, "pytest")
    run.scope = "collect:one-file"
    ingest(session, [run])
    assert session.issues[0].status == "not_observed"
    # Restricted scope cannot prove the whole-project goal.
    assert session.goal_status != "achieved"


def test_new_interpreter_invalidates_old_snapshot(tmp_path):
    root = tmp_path / "project"
    create_project(root, "env")
    inject(root, "mixed")
    session = create_session(root, sys.executable)
    scan(session, ["environment", "pytest"])
    session.target_python = str(tmp_path / "new-venv" / "python")
    from fixfirst.reasoning import infer_and_plan

    infer_and_plan(session)
    assert not any(f.fact_id == "environment:snapshot:available" for f in session.facts)


def test_argv_metacharacters_are_not_shell(tmp_path):
    from fixfirst.runner import execute

    marker = tmp_path / "SHOULD_NOT_EXIST"
    run = execute(
        [sys.executable, "-c", "import sys;print(sys.argv[1])", f"$(touch {marker})"],
        str(tmp_path),
        "environment",
        "test",
        sys.executable,
    )
    assert not marker.exists()
    assert "$(touch" in run.stdout


def test_store_conflicting_writer_is_rejected(tmp_path):
    store = Store(tmp_path / "store")
    session = create_session(tmp_path, sys.executable)
    store.save(session)
    with store.lock(session.session_id):
        result = cli(store.root, "configure", session.session_id, "--goal", "check_style")
        assert result.returncode == 2
        assert "already running" in result.stderr
