from copy import deepcopy
import json
from pathlib import Path
import platform

import pytest

from fixfirst import toolchain_cases as tc
from fixfirst import toolchain_environments as te
from fixfirst.evaluation import _case_datasets, load_rows


def test_historical_case_and_issue_denominators_are_distinct():
    root = Path(__file__).resolve().parents[1] / "examples/toolchain-dataset"
    manifest = json.loads((root / "manifest.json").read_text())
    rows = load_rows(root)
    assert len(manifest["scenarios"]) == 22
    assert len(manifest["cases"]) == len({r["case_id"] for r in rows}) == 98
    assert len(rows) == sum(c["issues"] for c in manifest["cases"]) == 108
    assert len({c["scenario"] for c in manifest["cases"]}) == 21
    assert len(manifest["unparsed"]) == 5
    assert len(manifest["rejected"]) == 4


@pytest.mark.parametrize("parts", [["../outside"], ["."], ["part", "part"], ["part", "./part"], "part", []])
def test_suite_cannot_escape_repeat_or_cycle(tmp_path, parts):
    root = tmp_path / "suite"
    (root / "part").mkdir(parents=True)
    (root / "part/cases.jsonl").write_text("")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside/cases.jsonl").write_text("")
    (root / "manifest.json").write_text(json.dumps({"datasets": parts}))
    with pytest.raises(ValueError):
        _case_datasets(root)


def lock_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(te, "command", lambda argv: "uv recorded-version")
    definitions = {"case": tc.Env("case", "3.12", ("pytest>=7,<9",))}
    value = {"schema_version": 1, "system": platform.system(), "machine": platform.machine(),
             "uv": "uv recorded-version", "environments": {
                 "case": {"python": "3.12.13", "packages": ["pytest==8.3.5", "pip==26.2.1"]}}}
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(value))
    return path, value, definitions


def test_complete_exact_lock_is_read_without_executing_target(tmp_path, monkeypatch):
    path, value, definitions = lock_fixture(tmp_path, monkeypatch)
    assert te.read_lock(path, definitions, "uv") == value


@pytest.mark.parametrize("kind", ["python_minor", "python_family", "range", "duplicate", "missing", "conflict", "os", "uv"])
def test_lock_rejects_drift_or_underspecified_dependencies(tmp_path, monkeypatch, kind):
    path, original, definitions = lock_fixture(tmp_path, monkeypatch)
    value = deepcopy(original)
    item = value["environments"]["case"]
    if kind == "python_minor":
        item["python"] = "3.12"
    elif kind == "python_family":
        item["python"] = "3.11.15"
    elif kind == "range":
        item["packages"] = ["pytest>=8"]
    elif kind == "duplicate":
        item["packages"] += ["Pytest==8.3.5"]
    elif kind == "missing":
        value["environments"] = {}
    elif kind == "conflict":
        item["packages"] = ["pytest==6.2.5"]
    elif kind == "os":
        value["system"] = "different"
    elif kind == "uv":
        value["uv"] = "uv changed"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        te.read_lock(path, definitions, "uv")


def test_existing_work_directory_is_never_removed(tmp_path):
    work = tmp_path / "keep"
    work.mkdir()
    sentinel = work / "important.txt"
    sentinel.write_text("unchanged")
    with pytest.raises(ValueError, match="must be new"):
        tc.build_dataset(tmp_path / "out", work=work)
    assert sentinel.read_text() == "unchanged"
    assert not (tmp_path / "out").exists()


def test_work_and_output_cannot_overlap(tmp_path):
    with pytest.raises(ValueError, match="overlap"):
        tc.build_dataset(tmp_path / "work/out", work=tmp_path / "work")
    assert not (tmp_path / "work").exists()


def test_manager_refuses_existing_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(te.shutil, "which", lambda name: "uv")
    monkeypatch.setattr(te, "command", lambda argv: "uv recorded-version")
    (tmp_path / "case").mkdir()
    manager = te.Environments(tmp_path, {"case": tc.Env("case", "3.12", ("pytest==8.3.5",))})
    with pytest.raises(ValueError, match="unowned"):
        manager.build("case")


def test_toolchain_wrapper_keeps_suite_validation(tmp_path):
    root = tmp_path / "suite"
    (root / "child").mkdir(parents=True)
    (root / "child/cases.jsonl").write_text("")
    (root / "manifest.json").write_text(json.dumps({
        "scenarios": [], "datasets": ["child", "child"]}))
    with pytest.raises(ValueError, match="duplicate"):
        tc.load_rows(root)


@pytest.mark.parametrize("change", ["incomplete", "missing", "duplicate", "audit"])
def test_new_suite_rejects_partial_or_unreconciled_ledger(tmp_path, change):
    from fixfirst.toolchain_manifest import validate

    value = {"schema_version": 2, "completion": "complete", "templates": ["t"],
             "scenarios": [{"id": "s"}], "cases": [{"case_id": "t--s"}],
             "unparsed": [], "rejected": [], "inapplicable": [],
             "audit_files": ["audit/t--s.json"]}
    validate(value)
    if change == "incomplete":
        value["completion"] = "incomplete"
    elif change == "missing":
        value["cases"] = []
    elif change == "duplicate":
        value["rejected"] = [{"case_id": "t--s"}]
    elif change == "audit":
        value["audit_files"] = []
    with pytest.raises(ValueError):
        validate(value)


def test_dependency_check_failure_prevents_accepting_version_pins(tmp_path, monkeypatch):
    monkeypatch.setattr(te.shutil, "which", lambda name: "uv")
    commands = []

    def command(argv):
        commands.append(argv)
        if argv[1:3] == ["pip", "check"]:
            raise ValueError("missing transitive dependency")
        return "uv recorded-version"

    monkeypatch.setattr(te, "command", command)
    manager = te.Environments(tmp_path, {"case": tc.Env("case", "3.12", ("pytest==8.3.5",))})
    with pytest.raises(ValueError, match="transitive"):
        manager.build("case")
    assert any(argv[1:3] == ["pip", "check"] for argv in commands)
    assert not manager.records
