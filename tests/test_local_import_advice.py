"""Local import guidance must work without assuming the project can be installed."""

import os
import subprocess
import sys

import pytest

from fixfirst.service import create_session, scan


@pytest.fixture(autouse=True)
def isolate_test_processes(monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")


@pytest.mark.parametrize("packaged", [False, True], ids=["I02-no-metadata", "packaged-src"])
def test_src_advice_repairs_actual_collection_without_installing(tmp_path, monkeypatch, packaged):
    root = tmp_path / "project with spaces"
    (root / "src" / "local_ledger").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "local_ledger" / "__init__.py").write_text("VALUE = 23\n")
    (root / "tests" / "test_ledger.py").write_text(
        "from local_ledger import VALUE\n"
        "from existing_support import OFFSET\n"
        "def test_value():\n    assert VALUE + OFFSET == 24\n"
    )
    if packaged:
        (root / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["setuptools>=68"]\n'
            'build-backend = "setuptools.build_meta"\n'
            '[project]\nname = "local-ledger"\nversion = "0.0.1"\n'
            '[tool.setuptools.packages.find]\nwhere = ["src"]\n'
        )
    # Keeping this existing entry is part of the promised repair. No shell
    # assignment or pytest-specific pythonpath option is needed on any platform.
    support = tmp_path / "existing support"
    support.mkdir()
    (support / "existing_support.py").write_text("OFFSET = 1\n")
    monkeypatch.setenv("PYTHONPATH", str(support))
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    before = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
    assert before.returncode == 2 and "No module named 'local_ledger'" in before.stdout

    session = create_session(root, sys.executable, goal="pass_tests")
    session.use_classifier = False
    scan(session, ["environment", "project", "pytest_run"])
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    assert (issue.diagnosis, issue.diagnosis_rule) == ("local_module", "D13")
    action = next(a for a in session.actions if "P12" in a.rule_ids)
    assert "absolute path" in action.explanation and "src directory" in action.explanation
    assert "PYTHONPATH" in action.explanation and "same Python interpreter" in action.explanation
    assert "Preserve any existing" in action.explanation and "path separator" in action.explanation
    assert "original test command" in action.verification
    assert "pip install" not in action.explanation and "editable" not in action.explanation
    assert not action.command

    # Apply the stated route and run exactly the same test command/interpreter.
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(root / "src"), str(support)]))
    after = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
    assert after.returncode == 0 and "1 passed" in after.stdout
    assert not (root / "pytest.ini").exists()
    assert (root / "pyproject.toml").exists() is packaged


def test_flat_project_misspelling_still_requests_import_correction(tmp_path):
    (tmp_path / "weather.py").write_text("def celsius():\n    return 23\n")
    (tmp_path / "test_weather.py").write_text(
        "from weahter import celsius\ndef test_temperature():\n    assert celsius() == 23\n"
    )
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    session.use_classifier = False
    scan(session, ["environment", "project", "pytest_run"])
    issue = next(i for i in session.issues if i.tool == "pytest_run" and i.status == "open")
    assert (issue.diagnosis, issue.diagnosis_rule) == ("local_module", "D16")
    action = next(a for a in session.actions if "P13" in a.rule_ids)
    assert "Update imports of weahter" == action.title.split(":", 1)[0]
    assert "weather.py" in action.explanation
    assert not any("P12" in a.rule_ids for a in session.actions)
