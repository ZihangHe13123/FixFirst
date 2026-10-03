"""Static warning configuration evidence, using only invented temporary files."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from fixfirst import pytest_settings
from fixfirst.project import collect_project


@pytest.mark.parametrize("name,section,content", [
    ("pytest.ini", "pytest", "[pytest]\nfilterwarnings =\n    error\n    ignore:100% complete:UserWarning\n"),
    (".pytest.ini", "pytest", "[pytest]\nfilterwarnings = error\n    ignore:100% complete:UserWarning\n"),
    ("tox.ini", "pytest", "[tox]\nenvlist = py312\n[pytest]\nfilterwarnings =\n    error\n    ignore:100% complete:UserWarning\n"),
    ("setup.cfg", "tool:pytest", "[tool:pytest]\nfilterwarnings =\n    error\n    ignore:100% complete:UserWarning\n"),
    ("pyproject.toml", "tool.pytest.ini_options", '[tool.pytest.ini_options]\nfilterwarnings = ["error", "ignore:100% complete:UserWarning"]\n'),
])
def test_records_each_supported_static_configuration(tmp_path, name, section, content):
    (tmp_path / name).write_text(content, encoding="utf-8")
    assert pytest_settings.recorded_warning_filters(tmp_path) == [{
        "source": f"{name} [{section}]", "filters": ["error", "ignore:100% complete:UserWarning"]}]


def test_toml_multiline_linelist_preserves_regex_as_text(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\nfilterwarnings = '''\n"
        "error\nignore:function ham\\(\\) is deprecated:DeprecationWarning\n'''\n", encoding="utf-8")
    assert pytest_settings.recorded_warning_filters(tmp_path)[0]["filters"] == [
        "error", r"ignore:function ham\(\) is deprecated:DeprecationWarning"]


def test_all_sources_are_recorded_without_effective_precedence_or_deduplication(tmp_path):
    for name, section in pytest_settings.CONFIGS:
        content = (f'[{section}]\nfilterwarnings = ["error", "ignore", "error"]\n'
                   if name == "pyproject.toml" else f"[{section}]\nfilterwarnings =\n error\n ignore\n error\n")
        (tmp_path / name).write_text(content, encoding="utf-8")
    rows = pytest_settings.recorded_warning_filters(tmp_path)
    assert [r["source"] for r in rows] == [f"{name} [{section}]" for name, section in pytest_settings.CONFIGS]
    assert all(r["filters"] == ["error", "ignore", "error"] for r in rows)
    assert all(set(r) == {"source", "filters"} for r in rows)


def test_does_not_import_categories_execute_project_code_or_infer_cli_and_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONWARNINGS", "error")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-W error")
    (tmp_path / "conftest.py").write_text("raise AssertionError('must not execute')\n", encoding="utf-8")
    (tmp_path / "malicious.py").write_text("raise AssertionError('must not import')\n", encoding="utf-8")
    assert pytest_settings.recorded_warning_filters(tmp_path) == []
    (tmp_path / "pytest.ini").write_text("[pytest]\nfilterwarnings = error::malicious.Warning\n", encoding="utf-8")
    assert pytest_settings.recorded_warning_filters(tmp_path) == [
        {"source": "pytest.ini [pytest]", "filters": ["error::malicious.Warning"]}]


@pytest.mark.parametrize("name,content", [
    ("pytest.ini", "[pytest\nfilterwarnings=error"),
    ("pytest.ini", "[pytest]\nfilterwarnings=error\nfilterwarnings=ignore"),
    ("pytest.ini", "[DEFAULT]\nfilterwarnings=error\n[pytest]\n"),
    ("pytest.ini", "[pytest]\nFilterWarnings=error\n"),
    ("pytest.ini", "[pytest]\nfilterwarnings=\n"),
    ("setup.cfg", "[pytest]\nfilterwarnings=error\n"),
    ("pyproject.toml", "[tool.pytest.ini_options\nfilterwarnings=['error']"),
    ("pyproject.toml", "[tool.pytest.ini_options]\nfilterwarnings=['error', 2]"),
    ("pyproject.toml", "[tool.pytest.ini_options]\nfilterwarnings=true"),
    ("pyproject.toml", "[tool.pytest.ini_options]\nfilterwarnings=[]"),
    ("pyproject.toml", "tool = 'not a table'"),
])
def test_unrecordable_file_does_not_hide_another_valid_source(tmp_path, name, content):
    (tmp_path / name).write_text(content, encoding="utf-8")
    (tmp_path / "tox.ini").write_text("[pytest]\nfilterwarnings = error\n", encoding="utf-8")
    assert pytest_settings.recorded_warning_filters(tmp_path) == [
        {"source": "tox.ini [pytest]", "filters": ["error"]}]


@pytest.mark.parametrize("kind", ["bytes", "filters", "entry", "total", "encoding"])
def test_read_and_filter_limits_return_unknown_without_partial_filter_order(tmp_path, kind):
    if kind == "bytes":
        raw = b"[pytest]\nfilterwarnings=error\n#" + b"x" * pytest_settings.MAX_BYTES
    elif kind == "filters":
        raw = ("[pytest]\nfilterwarnings=\n" + " error\n" * (pytest_settings.MAX_FILTERS + 1)).encode()
    elif kind == "entry":
        raw = ("[pytest]\nfilterwarnings=\n error\n ignore:" + "x" * pytest_settings.MAX_FILTER_CHARS).encode()
    elif kind == "total":
        long_filter = " ignore:" + "x" * (pytest_settings.MAX_FILTER_CHARS - 10) + "\n"
        raw = ("[pytest]\nfilterwarnings=\n" + long_filter * 10).encode()
    else:
        raw = b"[pytest]\nfilterwarnings=error\n\xff"
    (tmp_path / "pytest.ini").write_bytes(raw)
    assert pytest_settings.recorded_warning_filters(tmp_path) == []


@pytest.mark.parametrize("target_inside", [False, True])
def test_config_symlinks_are_rejected_even_if_their_target_is_inside_root(tmp_path, target_inside):
    project = tmp_path / "project"
    project.mkdir()
    target = (project if target_inside else tmp_path) / "actual.ini"
    target.write_text("[pytest]\nfilterwarnings=error\n", encoding="utf-8")
    (project / "pytest.ini").symlink_to(target)
    assert pytest_settings.recorded_warning_filters(project) == []


def test_symlink_root_and_nonregular_configuration_are_rejected(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pytest.ini").mkdir()
    assert pytest_settings.recorded_warning_filters(project) == []
    alias = tmp_path / "alias"
    alias.symlink_to(project, target_is_directory=True)
    assert pytest_settings.recorded_warning_filters(alias) == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is not available on this platform")
def test_fifo_is_rejected_before_opening(tmp_path, monkeypatch):
    os.mkfifo(tmp_path / "pytest.ini")

    def forbidden(*args, **kwargs):
        raise AssertionError("A nonregular configuration file must not be opened")

    monkeypatch.setattr(pytest_settings.os, "open", forbidden)
    assert pytest_settings.recorded_warning_filters(tmp_path) == []


def test_file_read_errors_do_not_stop_other_configuration_records(tmp_path, monkeypatch):
    for name in ("pytest.ini", "tox.ini"):
        (tmp_path / name).write_text("[pytest]\nfilterwarnings=error\n", encoding="utf-8")
    original = os.open

    def inaccessible(path, *args, **kwargs):
        if Path(path).name == "pytest.ini":
            raise PermissionError("synthetic denied read")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(pytest_settings.os, "open", inaccessible)
    assert pytest_settings.recorded_warning_filters(tmp_path) == [
        {"source": "tox.ini [pytest]", "filters": ["error"]}]


def test_project_snapshot_records_config_presence_without_claiming_it_was_effective(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\nfilterwarnings=error\n", encoding="utf-8")
    session = SimpleNamespace(project_root=str(tmp_path), environment={}, goal="pass_tests")
    run = collect_project(session, "synthetic-environment")
    data = json.loads(run.stdout)
    assert data["pytest_warning_filters"] == [{"source": "pytest.ini [pytest]", "filters": ["error"]}]
    assert run.exit_code == 0
    (tmp_path / "pytest.ini").write_text("not an ini file", encoding="utf-8")
    run = collect_project(session, "synthetic-environment")
    assert json.loads(run.stdout)["pytest_warning_filters"] == []
    assert run.exit_code == 0
