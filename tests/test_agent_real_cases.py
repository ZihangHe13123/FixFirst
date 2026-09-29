"""The agent baseline's real-project helpers (task B7): environments rebuilt from snapshots, test
integrity, and a grader that compares per-test outcomes with a reference."""

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "agent_baseline"))

import isolation as iso  # noqa: E402
import real_cases as rc  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_snapshot_keeps_the_pins_and_sets_the_project_itself_apart(tmp_path):
    snapshot = write(tmp_path / "typer.txt", "# Python 3.10.20\nclick==7.1.2\n"
                     "typer @ file://<home>/projects/typer\npytest==9.1.1\n")
    assert rc.read_snapshot(snapshot) == ("3.10.20", ["click==7.1.2", "pytest==9.1.1"],
                                          ["typer @ file://<home>/projects/typer"])
    assert rc.snapshot_mismatch(snapshot, ["click==7.1.2", "pytest==9.1.0"]) == ["pytest==9.1.1"]


def test_test_files_conftest_and_test_selecting_settings_are_guarded(tmp_path):
    write(tmp_path / "tests" / "test_a.py", "def test_a(): pass\n")
    write(tmp_path / "tests" / "data.json", "{}")
    write(tmp_path / "src" / "pkg" / "core.py", "X = 1\n")
    write(tmp_path / "pyproject.toml", '[tool.pytest.ini_options]\naddopts = "-q"\npythonpath = ["src"]\n')
    write(tmp_path / ".venv" / "lib" / "test_inside_venv.py", "")
    before = rc.integrity(tmp_path)
    assert set(before) == {"tests/test_a.py", "tests/data.json", "pyproject.toml:addopts"}
    # Putting src on the path is an accepted repair; changing the code is the point.
    write(tmp_path / "pyproject.toml", '[tool.pytest.ini_options]\naddopts = "-q"\npythonpath = ["src", "."]\n')
    write(tmp_path / "src" / "pkg" / "core.py", "X = 2\n")
    assert rc.changed(before, rc.integrity(tmp_path)) == []
    # Deselecting tests, a new conftest or a deleted test file is not.
    write(tmp_path / "pyproject.toml", '[tool.pytest.ini_options]\naddopts = "-q -k not_a"\n')
    write(tmp_path / "conftest.py", "collect_ignore = ['tests']\n")
    (tmp_path / "tests" / "data.json").unlink()
    assert rc.changed(before, rc.integrity(tmp_path)) == ["conftest.py", "pyproject.toml:addopts", "tests/data.json"]


def test_setup_cfg_and_tox_ini_sections_count_too(tmp_path):
    write(tmp_path / "setup.cfg", "[metadata]\nname = x\n\n[tool:pytest]\ntestpaths = tests\n")
    write(tmp_path / "tox.ini", "[pytest]\nfilterwarnings = error\n")
    assert set(rc.pytest_settings(tmp_path)) == {"setup.cfg:testpaths", "tox.ini:filterwarnings"}


def junit(tmp_path, cases: str) -> Path:
    return write(tmp_path / "junit.xml", f'<?xml version="1.0"?><testsuites><testsuite>{cases}</testsuite></testsuites>')


def test_junit_outcomes_are_read_per_test(tmp_path):
    report = junit(tmp_path, '<testcase classname="t.A" name="ok"/>'
                             '<testcase classname="t.A" name="bad"><failure message="x"/></testcase>'
                             '<testcase classname="t.A" name="err"><error message="x"/></testcase>'
                             '<testcase classname="t.A" name="skip"><skipped message="x"/></testcase>'
                             '<testcase classname="t.A" name="xf"><skipped type="pytest.xfail" message="x"/></testcase>')
    assert rc.junit_outcomes(report) == {"t.A::ok": "passed", "t.A::bad": "failed", "t.A::err": "error",
                                         "t.A::skip": "skipped", "t.A::xf": "xfailed"}


def outcome(outcomes, code=0):
    counts = {}
    for value in outcomes.values():
        counts[value] = counts.get(value, 0) + 1
    return {"exit_code": code, "outcomes": outcomes, "counts": counts, "summary": ""}


def test_the_grader_compares_with_the_reference():
    reference = outcome({"a": "passed", "b": "passed", "c": "skipped"})
    assert rc.judge(outcome({"a": "passed", "b": "passed", "c": "skipped"}), reference, [])["fixed"]
    assert rc.judge(outcome({"a": "passed", "b": "passed", "c": "passed"}), reference, [])["fixed"]
    missing = rc.judge(outcome({"a": "passed", "c": "skipped"}), reference, [])
    assert not missing["fixed"] and "1 tests of the reference were not run" in missing["reasons"][0]
    skipped = rc.judge(outcome({"a": "passed", "b": "skipped", "c": "skipped"}), reference, [])
    assert not skipped["fixed"] and any("pass in the reference were skipped" in r for r in skipped["reasons"])
    extra = rc.judge(outcome({"a": "passed", "b": "passed", "c": "skipped", "d": "passed"}), reference, [])
    assert not extra["fixed"] and any("that the reference does not have" in r for r in extra["reasons"])
    touched = rc.judge(outcome({"a": "passed", "b": "passed", "c": "skipped"}), reference, ["tests/test_b.py"])
    assert not touched["fixed"] and "changed during the run" in touched["reasons"][0]


@pytest.mark.parametrize("code", [1, 2, 3, 4, 5, 124])
def test_a_run_that_does_not_exit_cleanly_is_never_fixed(code):
    passing = {"a": "passed"}
    verdict = rc.judge(outcome(passing, code=code), outcome(passing), [])
    assert not verdict["fixed"] and f"pytest exited with {code}" in verdict["reasons"][0]


def test_a_reference_is_checked_before_it_grades_anything():
    assert rc.validate_reference({**outcome({"a": "passed", "b": "skipped"}), "repair": [{"command": "x", "exit_code": 0}]}) == []
    # The two counterexamples from the review: a reference that exits 1, and one with an error.
    assert rc.validate_reference(outcome({"a": "passed"}, code=1))
    problems = rc.validate_reference(outcome({"a": "passed", "b": "error"}, code=2))
    assert any("exited with 2" in p for p in problems) and any("failed or errored" in p for p in problems)
    assert rc.validate_reference({**outcome({"a": "passed"}), "repair": [{"command": "pip install x", "exit_code": 1}]})
    assert rc.validate_reference(outcome({"a": "skipped"}))  # nothing passed
    assert rc.validate_reference({"exit_code": None, "outcomes": {}, "counts": {}})


def test_package_changes_are_listed_by_name():
    before = ["click==7.1.2", "pytest==9.1.1"]
    after = ["click==8.0.0", "pytest==9.1.1", "shellingham==1.5.4"]
    assert rc.freeze_difference(before, after) == {"added": ["shellingham==1.5.4"], "removed": [],
                                                    "changed": ["click==7.1.2 -> click==8.0.0"]}


def test_the_grader_environment_inherits_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "src")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-p no:randomly")
    env = rc.clean_env(tmp_path / ".venv" / "bin" / "python", tmp_path, tmp_path / "tmp")
    assert "PYTHONPATH" not in env and "PYTEST_ADDOPTS" not in env
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / ".venv" / "bin")
    assert env["TMPDIR"] == str(tmp_path / "tmp")


@pytest.mark.parametrize("path,expected", [
    ("tests/helpers.py", True), ("pkg/test_x.py", True), ("pkg/x_test.py", True), ("conftest.py", True),
    ("pytest.ini", True), ("pkg/core.py", False), ("docs/testing.rst", False),
])
def test_what_counts_as_a_test_file(path, expected):
    assert rc.is_test_file(Path(path)) is expected


def test_the_source_is_exported_from_the_commit_only(tmp_path):
    repo = tmp_path / "repo"
    write(repo / "pkg" / "core.py", "X = 1\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "one"], check=True)
    write(repo / "pkg" / "core.py", "X = 2\n")  # uncommitted: must not be exported
    write(repo / "notes.txt", "local only")
    dest = tmp_path / "copy"
    rc.export_source(repo, rc.source_commit(repo), dest)
    assert (dest / "pkg" / "core.py").read_text() == "X = 1\n" and not (dest / "notes.txt").exists()


def test_the_install_step_of_the_project_is_returned_for_the_sandbox(tmp_path):
    python = tmp_path / ".venv" / "bin" / "python"
    commands = rc.install_commands({"install": ["-e .", "pytest pytest-cov", "-r requirements.txt"]}, python,
                                   tmp_path / "uv-cache")
    assert commands == [[str(python), "-m", "pip", "install", "-q", "--no-deps", "-e", "."]]


def test_a_sandbox_profile_denies_the_private_areas_and_allows_only_the_run(tmp_path):
    run, other = tmp_path / "out" / "runs" / "a", tmp_path / "out" / "runs" / "b"
    policy = iso.Policy(writable=(run / "project", run / "tmp"), readable=(tmp_path / "python",), network=False)
    text = iso.profile_text(policy, denied=(Path.home(), tmp_path / "out"))
    assert "(deny network*)" in text
    assert f'(deny file-read-data (subpath "{Path.home()}") (subpath "{tmp_path / "out"}"))' in text
    allow = next(line for line in text.splitlines() if line.startswith("(allow file-read-data"))
    assert str(run / "project") in allow and str(tmp_path / "python") in allow and str(other) not in allow
    write = next(line for line in text.splitlines() if line.startswith("(allow file-write*"))
    assert set(re.findall(r'\(subpath "([^"]+)"\)', write)) == {str(run / "project"), str(run / "tmp"), "/dev/fd"}
    assert text.index("(allow file-read-data") < text.index("(deny file-read* (subpath")  # secrets last
    assert "(deny network*)" not in iso.profile_text(iso.Policy((), (), network=True), denied=())


def test_run_folders_are_unique_and_never_reused(tmp_path):
    first = iso.run_folder(tmp_path, "cachetools", "baseline", 1, "Qwen/3.6 35B", "20260929T000000Z-aaa")
    second = iso.run_folder(tmp_path, "cachetools", "baseline", 1, "Qwen/3.6 35B:other", "20260929T000000Z-aaa")
    assert first != second and "/" not in first.name
    with pytest.raises(FileExistsError):
        iso.run_folder(tmp_path, "cachetools", "baseline", 1, "Qwen/3.6 35B", "20260929T000000Z-aaa")
    assert iso.new_attempt() != iso.new_attempt()


def test_the_budget_does_not_count_paused_time():
    budget = iso.Budget(10)
    with budget.pause():
        iso.time.sleep(0.05)
    assert budget.used() < 0.05 and budget.remaining() > 9.9


def test_profile_paths_are_real_paths(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    text = iso.profile_text(iso.Policy(writable=(link,), readable=()), denied=())
    assert f'(subpath "{os.path.realpath(target)}")' in text and str(link) not in text
