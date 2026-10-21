"""The interpreter identity the published datasets carry and the algorithm that reproduces it.

A dataset records its interpreter as the POSIX placeholder "/venv/bin/python" and stores that
identity in the case itself; loading a dataset must keep the recorded identity as it is, and
environment_id must hash every path in that path's own style: the placeholder keeps its saved
value on a Windows host too, a drive path follows ntpath, a POSIX path follows posixpath.
A rewrite that sent every path through os.path (the old algorithm) answered
C:\\venv\\bin\\python on Windows and silently invalidated 34 recorded-session tests.
"""
import hashlib
import json
import ntpath
import os
from pathlib import Path
import posixpath

from fixfirst import diagnosis_cases as cases
from fixfirst.runner import environment_id

DATASET = Path(__file__).resolve().parents[1] / "examples/diagnosis-dataset"


def saved_case():
    return json.loads((DATASET / "cases.jsonl").read_text(encoding="utf-8").splitlines()[0])["session"]


def test_loading_a_saved_dataset_keeps_the_recorded_identity():
    data = saved_case()
    original = json.loads(json.dumps(data))
    session = cases.load_session(DATASET, data)
    assert data == original                                        # loading never rewrites the record
    assert session.target_python == cases.PORTABLE_PYTHON
    assert session.environment["_environment_id"] == data["environment"]["_environment_id"]
    assert {r.environment_id for r in session.runs} == {data["environment"]["_environment_id"]}


def test_the_placeholder_keeps_the_saved_id_on_a_windows_like_host(monkeypatch):
    saved = saved_case()["environment"]["_environment_id"]
    assert environment_id(cases.PORTABLE_PYTHON) == saved
    monkeypatch.setattr(os, "path", ntpath)                        # a rewrite through os.path answers C:\\venv\\...
    assert environment_id(cases.PORTABLE_PYTHON) == saved


def test_windows_drive_paths_hash_in_their_own_normalised_style():
    path = r"C:\Venv\Scripts\python.exe"
    expected = hashlib.sha256(ntpath.normcase(ntpath.normpath(path)).encode()).hexdigest()[:16]
    assert environment_id(path) == expected


def test_posix_absolute_paths_hash_as_posix_paths_on_any_host(monkeypatch):
    path = "/opt/venvs/demo/bin/python"
    expected = hashlib.sha256(posixpath.normpath(path).encode()).hexdigest()[:16]
    assert environment_id(path) == expected
    monkeypatch.setattr(os, "path", ntpath)
    assert environment_id(path) == expected                        # its style follows the path, not the host
