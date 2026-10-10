import importlib.util
import os
from pathlib import Path
import sys

import pytest

from fixfirst.behavior import observed_changes
from fixfirst.domain import load
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view


def evidence(**changes):
    values = {"exception": "ModuleNotFoundError", "missing_module": "sqlalchemy.databases",
              "message": "No module named 'sqlalchemy.databases'", "raised_in": "project",
              "source_statement": "from sqlalchemy.databases import sqlite", "exception_module": "",
              "library": "", "source_location": "reader.py:2", "where": "reader.py:2",
              "library_calls": [], "executed_lines": [], "owners": [], "kwargs": [], "signals": []}
    values.update(changes)
    return values


def project():
    return {"imported_names": {"sqlite": "sqlalchemy.databases.sqlite", "xlrd": "xlrd"},
            "own_names": [], "local_modules": [],
            "source_context": {"calls": {"reader.py:2": ["xlrd.open_workbook"]}}}


def test_documented_dialect_move_keeps_aliases_and_requires_the_executed_import():
    assert ("sqlalchemy-sqlite-dialect-import", "sqlalchemy") in observed_changes(evidence(), project())
    assert ("sqlalchemy-sqlite-dialect-import", "sqlalchemy") in observed_changes(
        evidence(source_statement="from sqlalchemy.databases import sqlite as dialect"), project())
    for statement in ("raise ModuleNotFoundError(\"No module named 'sqlalchemy.databases'\")",
                      "from sqlalchemy.databases import made_up", "from local_package import sqlite"):
        assert not observed_changes(evidence(source_statement=statement), project())


def test_a_project_namesake_cannot_borrow_the_dialect_migration():
    local = project()
    local["local_modules"] = [{"name": "sqlalchemy"}]
    assert not observed_changes(evidence(), local)


def xlsx_evidence():
    return evidence(exception="XLRDError", exception_module="xlrd.biffh", library="xlrd",
                    raised_in="third_party", message="Excel xlsx file; not supported",
                    missing_module=None, source_statement="book = xlrd.open_workbook(path)",
                    library_calls=["xlrd.open_workbook"])


def test_xlsx_guidance_requires_the_actual_library_error_and_call():
    assert ("xlrd-xlsx-reading", "xlrd") in observed_changes(xlsx_evidence(), project())
    for field, value in (("exception_module", "my_package"), ("library", "my_package"),
                         ("raised_in", "project"), ("library_calls", []),
                         ("message", "Unsupported format, or corrupt file")):
        item = xlsx_evidence()
        item[field] = value
        assert not observed_changes(item, project())
    local = project()
    local["local_modules"] = [{"name": "xlrd"}]
    assert not observed_changes(xlsx_evidence(), local)


def test_guidance_records_the_migration_without_claiming_identical_reader_semantics():
    kb = load()
    sqlite = kb["behavior_index"]["behavior:sqlalchemy-sqlite-dialect-import"]
    xlsx = kb["behavior_index"]["behavior:xlrd-xlsx-reading"]
    assert sqlite["version"] == xlsx["version"] == "2.0"
    assert "from sqlalchemy.dialects import sqlite" in sqlite["replacement"]
    assert "not interchangeable" in xlsx["replacement"]
    assert "data_only=True" in xlsx["replacement"] and "close" in xlsx["replacement"]
    assert sqlite["source"] in kb["sources"] and xlsx["source"] in kb["sources"]


def test_real_sqlite_import_migration_fixes_the_original_check(tmp_path, monkeypatch):
    if importlib.util.find_spec("sqlalchemy") is None:
        pytest.skip("SQLAlchemy is an optional test dependency")
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    (tmp_path / "requirements.txt").write_text("SQLAlchemy\n")
    (tmp_path / "renderer.py").write_text("from sqlalchemy.databases import sqlite\ndef backend():\n    return sqlite.dialect().name\n")
    (tmp_path / "test_render.py").write_text("from renderer import backend\ndef test_backend():\n    assert backend() == 'sqlite'\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["pytest_run"])
    first = build_view(session)["steps"][0]
    assert first["title"] == "Move the SQLite dialect import to sqlalchemy.dialects"
    assert "from sqlalchemy.dialects import sqlite" in first["instructions"]
    (tmp_path / "renderer.py").write_text("from sqlalchemy.dialects import sqlite\ndef backend():\n    return sqlite.dialect().name\n")
    scan(session, ["pytest_run"])
    assert session.goal_status == "achieved"


def test_real_xlsx_migration_keeps_the_data_and_original_tests(tmp_path, monkeypatch):
    python = os.environ.get("FIXFIRST_TEST_XLSX_PYTHON")
    if not python or not Path(python).is_file():
        pytest.skip("An environment with xlrd, xlsxwriter and openpyxl is optional")
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    (tmp_path / "requirements.txt").write_text("xlrd\n")
    (tmp_path / "reader.py").write_text(
        "import xlrd\ndef rows(path):\n    book = xlrd.open_workbook(path)\n"
        "    sheet = book.sheet_by_name('prices')\n    return [sheet.row_values(i) for i in range(sheet.nrows)]\n")
    tests = ("import xlsxwriter\nfrom reader import rows\ndef test_rows(tmp_path):\n"
             "    path = str(tmp_path / 'prices.xlsx')\n    book = xlsxwriter.Workbook(path)\n"
             "    sheet = book.add_worksheet('prices')\n    sheet.write_row(0, 0, ['sku', 'price'])\n"
             "    sheet.write_row(1, 0, ['bolt', 0.25])\n    book.close()\n"
             "    assert rows(path) == [['sku', 'price'], ['bolt', 0.25]]\n")
    (tmp_path / "test_read.py").write_text(tests)
    session = create_session(tmp_path, python, goal="pass_tests")
    scan(session, ["pytest_run"])
    assert build_view(session)["steps"][0]["title"] == "Migrate XLSX reading to openpyxl"
    (tmp_path / "reader.py").write_text(
        "import openpyxl\ndef rows(path):\n    book = openpyxl.load_workbook(path, read_only=True, data_only=True)\n"
        "    try:\n        sheet = book['prices']\n        return [list(row) for row in sheet.iter_rows(values_only=True)]\n"
        "    finally:\n        book.close()\n")
    scan(session, ["pytest_run"])
    assert session.goal_status == "achieved" and (tmp_path / "test_read.py").read_text() == tests
