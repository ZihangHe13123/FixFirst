"""Regression checks for the study's environment and completion boundary."""

import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "user_study"))

import grade as study_grade  # noqa: E402
from prepare import fingerprint, task_environment, venv_python  # noqa: E402


@pytest.fixture
def task(tmp_path, monkeypatch):
    folder = tmp_path / "task"
    (folder / "tests").mkdir(parents=True)
    (folder / "src").mkdir()
    (folder / "src" / "_study_env_probe.py").write_text("VALUE = 7\n", encoding="utf-8")
    (folder / "tests" / "test_value.py").write_text(
        "from _study_env_probe import VALUE\n\ndef test_value():\n    assert VALUE == 7\n", encoding="utf-8"
    )
    (folder / "pyproject.toml").write_text('[project]\nname = "study-probe"\nversion = "0"\n', encoding="utf-8")
    (tmp_path / ".study").mkdir()
    (tmp_path / ".study" / "manifest.json").write_text(json.dumps({"tasks": {"T2": {
        "folder": "task", "expected_tests": 1, "tests": fingerprint(folder),
    }}}), encoding="utf-8")
    # Use the test runner's installed pytest, without downloading packages for this regression.
    monkeypatch.setattr(study_grade, "venv_python", lambda _: Path(sys.executable))
    return tmp_path, folder


@pytest.mark.parametrize("variable,value", [
    ("PYTEST_ADDOPTS", "-o pythonpath=src"),
    ("PYTHONPATH", "src"),
])
def test_temporary_import_settings_do_not_pass_the_grader(task, monkeypatch, variable, value):
    target, folder = task
    monkeypatch.setenv(variable, str(folder / value) if variable == "PYTHONPATH" else value)
    assert not study_grade.grade(target, "T2")[0]
    # A persistent project configuration is an allowed repair and should pass.
    with (folder / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write('\n[tool.pytest.ini_options]\npythonpath = ["src"]\n')
    assert study_grade.grade(target, "T2")[0]


def test_environment_preserves_windows_runtime_but_not_test_or_application_overrides(tmp_path):
    env = task_environment(tmp_path, {
        "Path": "system-bin", "SystemRoot": r"C:\Windows", "TEMP": r"C:\Temp",
        "PSModulePath": r"C:\Windows\system32\WindowsPowerShell\v1.0\Modules", "USERNAME": "alice",
        "LANG": "en_US.UTF-8", "HTTPS_PROXY": "http://proxy.invalid:8080",
        "PYTEST_PLUGINS": "injected", "pytest_addopts": "-o pythonpath=src",
        "PYTHONHOME": "other-python", "PIP_TARGET": "other-site-packages",
        "APP_CONFIG": "temporary-settings.toml", "BASH_ENV": "profile.sh",
    })
    assert env["SystemRoot"] == r"C:\Windows" and env["TEMP"] == r"C:\Temp"
    assert env["PSModulePath"].endswith("Modules") and env["USERNAME"] == "alice"
    assert env["HTTPS_PROXY"] == "http://proxy.invalid:8080"
    assert env["PATH"].split(os.pathsep)[0] == str(venv_python(tmp_path).parent)
    assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
    assert not {"PYTEST_PLUGINS", "pytest_addopts", "PYTHONHOME", "PIP_TARGET",
                "APP_CONFIG", "BASH_ENV", "Path"} & env.keys()


def test_grader_still_rejects_changed_or_skipped_tests(task):
    target, folder = task
    with (folder / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write('\n[tool.pytest.ini_options]\npythonpath = ["src"]\n')
    test_file = folder / "tests" / "test_value.py"
    original = test_file.read_bytes()
    test_file.write_bytes(original + b"\n# changed\n")
    assert "files under tests/" in study_grade.grade(target, "T2")[1]
    test_file.write_bytes(original)
    (folder / "conftest.py").write_text(
        'import pytest\ndef pytest_collection_modifyitems(items):\n'
        '    items[0].add_marker(pytest.mark.skip(reason="regression"))\n', encoding="utf-8"
    )
    passed, summary = study_grade.grade(target, "T2")
    assert not passed and "skipped" in summary
