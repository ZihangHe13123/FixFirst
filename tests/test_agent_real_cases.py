"""The agent baseline's real-project helpers (task B7): environments rebuilt from snapshots, test
integrity, and a grader that compares per-test outcomes with a reference."""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
from xml.etree import ElementTree

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


def test_registered_failing_install_steps_are_marked_and_checked_before_any_run(tmp_path):
    python = tmp_path / ".venv" / "bin" / "python"
    project = {"install": ["-e .", "-r tests/requirements.txt"], "install_fails": ["-e ."]}
    steps = rc.install_steps(project, python, tmp_path / "uv-cache")
    assert [(s["line"], s["expected_failure"]) for s in steps] == [("-e .", True)]
    assert rc.install_commands(project, python, tmp_path / "uv-cache") == [steps[0]["argv"]]
    assert rc.install_fails_problems(project) == []
    assert rc.install_fails_problems({"install": ["-e ."]}) == []  # nothing registered
    assert rc.install_fails_problems({"install": ["-e ."], "install_fails": ["."]})  # not an install line
    assert rc.install_fails_problems({"install": ["-e .", "pytest"], "install_fails": ["pytest"]})  # third party
    assert rc.install_fails_problems({"install": ["-e ."], "install_fails": "-e ."})  # not a list
    assert rc.install_fails_problems({"install": ["-e ."], "install_fails": ["-e .", "-e ."]})  # twice
    assert rc.install_fails_registered(project) == 1 and rc.install_fails_registered({"install": ["-e ."]}) == 0


@pytest.mark.parametrize("line", ["-e .", "-e .[tests]", ".", ".[dev,docs]", "--editable=.", "--editable .[test]",
                                  '-e "."'])
def test_a_plain_install_of_the_project_itself_can_be_registered(tmp_path, line):
    project = {"install": [line, "pytest"], "install_fails": [line]}
    assert rc.install_fails_problems(project) == [] and rc.install_fails_registered(project) == 1
    [step] = rc.install_steps(project, tmp_path / "python", tmp_path / "uv-cache")
    assert (step["line"], step["expected_failure"]) == (line, True)


@pytest.mark.parametrize("line,installs_project", [
    ("-r ./requirements.txt", False),  # a requirements list
    ("--find-links . pytest", False),  # a third-party package found in a local folder
    ("--find-links=./wheels pytest", False),
    ("-c ./constraints.txt pytest", False),
    ("-e . -r requirements.txt", True),  # the project, but not only the project
    ("-e ./plugins/extra", True),  # a package in the project's folder, not the project itself
])
def test_only_a_plain_install_of_the_project_itself_can_be_registered(tmp_path, line, installs_project):
    problems = rc.install_fails_problems({"install": [line], "install_fails": [line]})
    assert any("not a plain install of the project itself" in p for p in problems)
    assert rc.installs_project(line) is installs_project
    steps = rc.install_steps({"install": [line]}, tmp_path / "python", tmp_path / "uv-cache")
    assert [s["line"] for s in steps] == ([line] if installs_project else [])


def test_every_install_line_of_the_manifest_is_read_as_before():
    legacy = lambda line: any(w == "." or w.startswith((".[", "./")) for w in shlex.split(line))  # noqa: E731
    manifest = rc.load_manifest(Path(__file__).resolve().parents[1] / "examples" / "real-world" / "projects.toml")
    lines = [line for project in manifest.values() for line in project["install"]]
    assert lines and [rc.installs_project(line) for line in lines] == [legacy(line) for line in lines]
    assert all(rc.install_fails_problems(project) == [] for project in manifest.values())


@pytest.mark.parametrize("code,stopped,problem", [
    (1, False, None),  # ran to completion and failed: the registered start
    (0, False, "succeeded"),
    (None, False, "did not finish"),
    (124, True, "was stopped at its time limit"),
    (-9, False, "was ended by signal 9"),
    (1, None, "has no record that it ran to completion"),
])
def test_a_registered_failure_is_the_start_only_if_it_ran_to_completion(code, stopped, problem):
    assert rc.registered_failure_problem(code, stopped) == problem


def test_a_reference_accepts_only_the_registered_install_failure():
    failed = {"command": "install the project: -e .", "exit_code": 1, "stopped": False, "expected_failure": True}
    reference = {**outcome({"a": "passed"}), "repair": [failed, {"command": "pip install six", "exit_code": 0}]}
    assert rc.validate_reference(reference) == []
    for change, reason in (({"exit_code": 0}, "succeeded"), ({"exit_code": None}, "did not finish"),
                           ({"exit_code": 124, "stopped": True}, "was stopped at its time limit"),
                           ({"exit_code": -9}, "was ended by signal 9")):
        problems = rc.validate_reference({**reference, "repair": [{**failed, **change}]})
        assert any(reason in p and "start is not the registered one" in p for p in problems), change
    unrecorded = {k: v for k, v in failed.items() if k != "stopped"}  # e.g. cached before completion was recorded
    assert any("has no record that it ran to completion" in p
               for p in rc.validate_reference({**reference, "repair": [unrecorded]}))
    unregistered = {**reference, "repair": [{"command": "install the project: -e .", "exit_code": 1}]}
    assert any("exited with 1" in p for p in rc.validate_reference(unregistered))


def test_a_cached_reference_is_reused_unless_its_registered_start_lacks_completion_evidence(tmp_path):
    key = "k" * 64
    base = {"key": key, "commit": "c" * 40, "problems": [], **outcome({"a": "passed"})}
    unregistered = tmp_path / "unregistered.json"  # written before "stopped" was recorded: still usable
    unregistered.write_text(json.dumps({**base, "repair": [{"command": "install the project: -e .", "exit_code": 0}]}))
    assert rc.read_reference_cache(unregistered, key, "t1") == (json.loads(unregistered.read_text()), None)
    registered = tmp_path / "registered.json"
    registered.write_text(json.dumps({**base, "repair": [
        {"command": "install the project: -e .", "exit_code": 1, "expected_failure": True}]}))
    data, note = rc.read_reference_cache(registered, key, "t1")
    assert data is None and "has no record that it ran to completion" in note
    assert (tmp_path / "registered.json.unusable-t1").exists() and not registered.exists()


def test_the_install_step_of_the_project_is_returned_for_the_sandbox(tmp_path):
    python = tmp_path / ".venv" / "bin" / "python"
    commands = rc.install_commands({"install": ["-e .", "pytest pytest-cov", "-r requirements.txt"]}, python,
                                   tmp_path / "uv-cache")
    assert commands == [[str(python), "-m", "pip", "install", "-q", "--no-deps", "-e", "."]]


def test_a_sandbox_profile_denies_the_private_areas_and_allows_only_the_run(tmp_path):
    run, other = tmp_path / "out" / "runs" / "a", tmp_path / "out" / "runs" / "b"
    policy = iso.Policy(writable=(run / "project", run / "tmp"), readable=(tmp_path / "python",), network=False,
                        owner=iso.new_mark())
    text = iso.profile_text(policy, denied=(Path.home(), tmp_path / "out"))
    assert "(deny network*)" in text
    assert f'(deny file-read-data (subpath "{Path.home()}") (subpath "{tmp_path / "out"}"))' in text
    allow = next(line for line in text.splitlines() if line.startswith("(allow file-read-data"))
    assert str(run / "project") in allow and str(tmp_path / "python") in allow and str(other) not in allow
    write = next(line for line in text.splitlines() if line.startswith("(allow file-write*"))
    assert set(re.findall(r'\(subpath "([^"]+)"\)', write)) == {str(run / "project"), str(run / "tmp"), "/dev/fd"}
    assert text.index("(allow file-read-data") < text.index("(deny file-read* (subpath")  # secrets last
    assert "(deny network*)" not in iso.profile_text(iso.Policy((), (), network=True, owner=iso.new_mark()), denied=())


def test_protected_files_are_denied_after_everything_the_policy_allows(tmp_path):
    answers = tmp_path / "readable" / "answers.json"
    answers.parent.mkdir()
    answers.write_text("{}")
    policy = iso.Policy(writable=(), readable=(answers.parent,), owner=iso.new_mark())
    plain = iso.profile_text(policy, denied=(tmp_path,)).splitlines()
    assert not [line for line in plain if "(literal" in line and line.startswith("(deny file-read*")]
    lines = iso.profile_text(policy, denied=(tmp_path,), protected=(answers,)).splitlines()
    rules = [f'(deny {operation} (literal "{os.path.realpath(answers)}"))' for operation in ("file-read-data", "file-read*")]
    allow = next(i for i, line in enumerate(lines) if line.startswith("(allow file-read-data"))
    # the later rule for the same operation wins: the folder around it is allowed, the file is not
    assert allow < lines.index(rules[0]) < lines.index(rules[1])
    assert [line for line in lines if line not in rules] == plain  # nothing else changes


def test_a_protected_folder_is_denied_with_all_below_it_after_everything_the_policy_allows(tmp_path):
    clones, answers = tmp_path / "readable" / "source-clones", tmp_path / "readable" / "answers.json"
    policy = iso.Policy(writable=(), readable=(clones.parent,), owner=iso.new_mark())
    plain = iso.profile_text(policy, denied=(tmp_path,)).splitlines()
    lines = iso.profile_text(policy, denied=(tmp_path,), protected_folders=(clones,)).splitlines()
    rules = [f"(deny {operation} (subpath {iso._quoted(clones)}))" for operation in ("file-read-data", "file-read*")]
    allow = next(i for i, line in enumerate(lines) if line.startswith("(allow file-read-data"))
    assert allow < lines.index(rules[0]) < lines.index(rules[1])  # the folder around it is allowed, it is not
    assert [line for line in lines if line not in rules] == plain  # nothing else changes
    both = iso.profile_text(policy, denied=(tmp_path,), protected=(answers,), protected_folders=(clones,)).splitlines()
    by_name = [f"(deny {operation} (literal {iso._quoted(answers)}))" for operation in ("file-read-data", "file-read*")]
    assert [line for line in both if line not in plain] == by_name + rules  # a file by its name, a folder with all below


@pytest.mark.parametrize("one,other,shared", [
    ("a/b", "a/b", True), ("a/b/c/d", "a/b", True), ("a/b", "a/b/c/d", True), ("a", "a/b", True),
    ("a/b", "a/c", False), ("a/bc", "a/b", False), ("a/b/c", "a/c/b", False)])
def test_two_paths_share_something_when_one_is_the_other_or_lies_inside_it(tmp_path, one, other, shared):
    assert iso.overlap(tmp_path / one, tmp_path / other) is shared
    assert iso.overlap(str(tmp_path / other), tmp_path / one) is shared  # either way round, as text or as a path


def test_shared_paths_are_found_whatever_the_case_or_the_unicode_form(tmp_path):
    """A volume that keeps neither apart opens src/ as SRC/ too, and so do the sandbox's rules on it."""
    assert iso.overlap(tmp_path / "Repo" / "SRC" / "clones", tmp_path / "repo" / "src")
    assert iso.overlap(tmp_path / "repo", tmp_path / "REPO" / "src" / "clones")
    composed, decomposed = "caf\u00e9", "cafe\u0301"  # one name in two Unicode forms
    assert composed != decomposed and iso.overlap(tmp_path / composed / "clones", tmp_path / decomposed)
    assert not iso.overlap(tmp_path / "Repo" / "SRC", tmp_path / "repo" / "srcs")


@pytest.mark.skipif(os.name == "nt", reason="links to folders need a privilege on Windows")
def test_paths_are_compared_as_resolved_so_a_link_shares_what_its_target_shares(tmp_path):
    (tmp_path / "real" / "inner").mkdir(parents=True)
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    assert iso.overlap(tmp_path / "link" / "inner", tmp_path / "real") and iso.overlap(tmp_path / "real", tmp_path / "link")
    assert not iso.overlap(tmp_path / "link", tmp_path / "elsewhere")


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
    text = iso.profile_text(iso.Policy(writable=(link,), readable=(), owner=iso.new_mark()), denied=())
    assert f'(subpath "{os.path.realpath(target)}")' in text and str(link) not in text


def test_the_environment_record_is_read_from_pyvenv_cfg(tmp_path):
    uv = write(tmp_path / "uv" / "pyvenv.cfg", "home = /opt/py/bin\nimplementation = CPython\nversion_info = 3.9.6\n")
    venv = write(tmp_path / "venv" / "pyvenv.cfg", f"home = {tmp_path}/base/bin\nversion = 3.12.14\n")
    assert rc.venv_record(uv.parent)["version"] == "3.9.6"
    record = rc.venv_record(venv.parent)
    assert record["version"] == "3.12.14" and os.path.realpath(tmp_path / "base") in record["interpreters"]


def test_freeze_reads_metadata_and_never_runs_the_environment(tmp_path):
    site = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
    write(site / "Foo_Bar-1.2.dist-info" / "METADATA", "Metadata-Version: 2.1\nName: Foo_Bar\nVersion: 1.2\n\nName: not a header\n")
    write(site / "proj-0.1.dist-info" / "METADATA", "Name: proj\nVersion: 0.1\n")
    write(site / "proj-0.1.dist-info" / "direct_url.json", '{"url": "file:///x/proj", "dir_info": {"editable": true}}')
    write(site / "local-2.0.dist-info" / "METADATA", "Name: local\nVersion: 2.0\n")
    write(site / "local-2.0.dist-info" / "direct_url.json", '{"url": "file:///x/local", "dir_info": {}}')
    write(site / "old-3.0-py3.12.egg-info" / "PKG-INFO", "Name: old\nVersion: 3.0\n")
    sentinel = tmp_path / "hook-ran.txt"
    write(site / "hook.pth", f"import pathlib; pathlib.Path({str(sentinel)!r}).write_text('ran')\n")
    assert rc.freeze(tmp_path / ".venv" / "bin" / "python") == [
        "-e file:///x/proj", "foo-bar==1.2", "local @ file:///x/local", "old==3.0"]
    assert not sentinel.exists()


def test_snapshot_pins_match_whatever_the_name_spelling(tmp_path):
    snapshot = write(tmp_path / "s.txt", "# Python 3.12.14\ntyping_extensions==4.16.0\nPyYAML==6.0.3\n")
    assert rc.snapshot_mismatch(snapshot, ["pyyaml==6.0.3", "typing-extensions==4.16.0"]) == []


def valid_reference(key="k"):
    return {"key": key, "commit": "c", "repair": [{"command": "x", "exit_code": 0}], "exit_code": 0,
            "counts": {"passed": 1}, "outcomes": {"t::a": "passed"}, "problems": []}


@pytest.mark.parametrize("content", ["{", "[1, 2]", '{"key": "k"}',
                                     '{"key": "other", "commit": "c", "repair": [], "exit_code": 0, "counts": {}, "outcomes": {"t::a": "passed"}, "problems": []}',
                                     '{"key": "k", "commit": "c", "repair": [], "exit_code": 1, "counts": {}, "outcomes": {"t::a": "passed"}, "problems": []}',
                                     '{"key": "k", "commit": "c", "repair": [], "exit_code": 0, "counts": {}, "outcomes": [], "problems": []}'])
def test_an_unusable_reference_cache_is_set_aside_and_reported(tmp_path, content):
    cached = write(tmp_path / "ref.json", content)
    data, note = rc.read_reference_cache(cached, "k", "attempt-1")
    assert data is None and "not usable" in note and "built again" in note
    assert not cached.exists() and (tmp_path / "ref.json.unusable-attempt-1").read_text() == content


def test_a_usable_reference_cache_is_read_and_a_missing_one_is_not_an_error(tmp_path):
    assert rc.read_reference_cache(tmp_path / "none.json", "k", "a") == (None, None)
    rc.write_json(tmp_path / "ref.json", valid_reference())
    assert rc.read_reference_cache(tmp_path / "ref.json", "k", "a") == (valid_reference(), None)
    assert [p.name for p in tmp_path.iterdir()] == ["ref.json"]  # no temporary file left behind


def test_every_profile_names_its_owner_and_refuses_starting_processes_outside_the_sandbox():
    owner = iso.new_mark()
    policy = iso.Policy((Path("/private/tmp/run"),), (), owner=owner).extended(readable=(Path("/opt"),))
    lines = iso.profile_text(policy, denied=()).splitlines()
    assert lines[-4:] == [f'(deny mach-lookup (global-name "org.fixfirst.run.{owner}"))',
                          "(deny job-creation lsopen appleevent-send)", "(deny signal)",
                          "(allow signal (target self) (target same-sandbox))"]  # last: no later rule undoes them
    assert iso.new_mark() != owner
    for bad in ("", "abc123", 'a") (allow default', owner.upper()):  # no owner, or not a token of new_mark()
        with pytest.raises(ValueError):
            iso.profile_text(iso.Policy((), (), owner=bad), denied=())


def returns_within(seconds, function, pipes=()):
    """function's result (or error), failing if it is still waiting after `seconds`; the pipes are then
    opened for writing so that the waiting thread can finish."""
    box = {}

    def target():
        try:
            box["value"] = function()
        except Exception as error:
            box["error"] = error
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    waited = thread.is_alive()
    for pipe in pipes if waited else ():
        try:
            os.close(os.open(pipe, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
    thread.join(5)
    assert not waited, "the harness waited on a named pipe"
    return box


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX")
def test_named_pipes_the_agent_leaves_never_make_the_harness_wait(tmp_path):
    project = tmp_path / "project"
    write(project / "tests" / "test_ok.py", "def test_ok():\n    assert True\n")
    site = project / ".venv" / "lib" / "python3.12" / "site-packages"
    write(site / "real-2.0.dist-info" / "METADATA", "Name: real\nVersion: 2.0\n\nbody\n")
    (site / "pipe-1.0.dist-info").mkdir()
    pipes = [project / "tests" / "test_pipe.py", project / "pyproject.toml", project / "notes.txt",
             site / "pipe-1.0.dist-info" / "METADATA", site / "real-2.0.dist-info" / "direct_url.json",
             tmp_path / "junit.xml"]
    for pipe in pipes:
        os.mkfifo(pipe)
    python = project / ".venv" / "bin" / "python"
    state = returns_within(5, lambda: rc.integrity(project), pipes)["value"]
    assert state["tests/test_pipe.py"] == "not a regular file" and "pyproject.toml" in state  # changes count
    assert returns_within(5, lambda: rc.pytest_settings(project), pipes)["value"] == {"pyproject.toml": "unreadable"}
    assert "value" in returns_within(5, lambda: rc.workspace_digest(project, python), pipes)
    assert returns_within(5, lambda: rc.freeze(python), pipes)["value"] == ["real==2.0"]
    assert isinstance(returns_within(5, lambda: rc.junit_outcomes(tmp_path / "junit.xml"), pipes)["error"],
                      ElementTree.ParseError)
    assert returns_within(5, lambda: rc.read_regular(project / "notes.txt"), pipes)["value"] is None
    assert isinstance(returns_within(5, lambda: rc.write_regular(project / "notes.txt", "x"), pipes)["error"],
                      OSError)
    assert rc._grader_ignore(str(project), ["notes.txt", "tests", ".venv"]) == {"notes.txt", ".venv"}


def test_regular_files_hash_and_read_as_before(tmp_path):
    path = write(tmp_path / "tests" / "test_a.py", "def test_a():\n    pass\n")
    assert rc.file_hash(path) == hashlib.sha256(path.read_bytes()).hexdigest()
    assert rc.integrity(tmp_path) == {"tests/test_a.py": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert rc.read_regular(path) == path.read_bytes() and rc.read_regular(path, limit=5) is None
    assert rc.read_regular(tmp_path / "missing.py") is None and rc.read_regular(tmp_path) is None


def test_write_file_replaces_the_contents_and_does_not_follow_a_link(tmp_path):
    target = write(tmp_path / "a.txt", "a much longer text than the new one")
    rc.write_regular(target, "short")
    assert target.read_text(encoding="utf-8") == "short"
    rc.write_regular(tmp_path / "new.txt", "line\nline")
    assert (tmp_path / "new.txt").read_bytes() == b"line\nline"
    outside = write(tmp_path / "outside.txt", "keep")
    try:
        (tmp_path / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("no symlinks here")
    with pytest.raises(OSError):
        rc.write_regular(tmp_path / "link.txt", "changed")
    assert outside.read_text(encoding="utf-8") == "keep"
