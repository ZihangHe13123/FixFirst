"""Removal names require the receiver of this actual failure, not a namesake."""

from copy import deepcopy
import json
import sys

import pytest

from fixfirst import domain
from fixfirst._runtime_evidence import exception_metadata
from fixfirst.evidence import observations
from fixfirst.reasoning import infer_and_plan
from fixfirst.service import create_session, scan


@pytest.fixture
def proposal(monkeypatch):
    """Only representative proposed entries, never the unmerged bulk knowledge."""
    kb = deepcopy(domain.load())
    rows = [
        {"kind": "attribute", "owners": ["configparser.ConfigParser", "configparser.RawConfigParser"],
         "names": ["readfp"], "distribution": "python", "version": "3.12",
         "replacement": "read_file()", "source": "python-3.12"},
        {"kind": "api", "module": "EntryPoints", "owners": ["importlib.metadata.EntryPoints"],
         "names": ["items"], "distribution": "python", "version": "3.12",
         "replacement": "entry_points(group='your.group')", "source": "python-3.12"},
    ]
    for row in rows:
        kb["removed"].append(row)
        for name in row["names"]:
            key = (f"api:{row['module']}.{name}" if row["kind"] == "api" else f"attribute:{name}")
            kb["removed_index"][key] = {**row, "id": key, "name": name}
    monkeypatch.setattr(domain, "load", lambda: kb)
    return kb


def run_case(root, source, *, unit=False):
    (root / "app.py").write_text(source)
    (root / "test_app.py").write_text(
        "from app import fail\n" + ("import unittest\nclass TestCase(unittest.TestCase):\n"
                                   "    def test_fail(self):\n        fail()\n" if unit else
                                   "def test_fail():\n    fail()\n"))
    check = "unittest_run" if unit else "pytest_run"
    session = create_session(root, sys.executable, goal="pass_unittest" if unit else "pass_tests",
                             execution={"kind": "unittest", "entry": "."} if unit else None)
    session.use_classifier = False
    scan(session, ["environment", "project", check])
    issue = next(issue for issue in session.issues if issue.tool == check)
    return session, issue, check


@pytest.mark.parametrize("source", [
    "class Report:\n    def read(self): pass\ndef fail():\n    item = Report()\n    item.readfp()\n",
    "class EntryPoints: pass\ndef fail():\n    item = EntryPoints()\n    item.items()\n",
    "class OtherParser: pass\ndef fail():\n    item = OtherParser()\n    item.readfp()\n",
    "class EntryPoints: pass\ndef fail():\n    EntryPoints.items()\n",
    "from configparser import ConfigParser\ndef fail():\n"
    "    raise AttributeError(\"'ConfigParser' object has no attribute 'readfp'\", name='readfp', obj=ConfigParser())\n",
])
def test_local_types_and_fabricated_exception_fields_never_borrow_removal_knowledge(tmp_path, proposal, source):
    session, issue, _ = run_case(tmp_path, source)
    assert issue.diagnosis_rule not in {"D02", "D03"}
    assert not any(f.subject == issue.issue_id and f.predicate == "removal_owner" for f in session.facts)
    assert not any("Replace " in action.title for action in session.actions)


PARSER = ("from configparser import ConfigParser\nfrom io import StringIO\n"
          "def fail():\n    parser = ConfigParser()\n    parser.readfp(StringIO('[section]\\nkey = value'))\n")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="readfp was removed in Python 3.12")
@pytest.mark.parametrize("unit", [False, True])
def test_real_parser_bare_method_has_bound_ownership_and_repaired_run_passes(tmp_path, proposal, unit):
    session, issue, check = run_case(tmp_path, PARSER, unit=unit)
    assert issue.diagnosis_rule == "D03"
    owner = next(f for f in session.facts if f.subject == issue.issue_id and f.predicate == "removal_owner")
    assert owner.value == "attribute:readfp" and len(owner.evidence_refs) >= 4
    assert not session.structured_evidence  # Ownership is a safety gate, not an experimental factor.
    assert any("read_file()" in action.explanation for action in session.actions)
    (tmp_path / "app.py").write_text(PARSER.replace("readfp", "read_file"))
    scan(session, [check])
    assert session.goal_status == "achieved"


@pytest.mark.skipif(sys.version_info < (3, 12), reason="class API removed in Python 3.12")
@pytest.mark.parametrize("class_form", [False, True])
def test_real_entrypoints_class_and_instance_require_qualified_owner(tmp_path, proposal, class_form):
    source = "from importlib.metadata import EntryPoints\ndef fail():\n"
    source += "    EntryPoints.items()\n" if class_form else "    item = EntryPoints()\n    item.items()\n"
    session, issue, _ = run_case(tmp_path, source)
    assert issue.diagnosis_rule == "D02"
    proposal["removed_index"]["api:EntryPoints.items"].pop("owners")
    infer_and_plan(session)
    assert issue.diagnosis_rule not in {"D02", "D03"}  # Short module text never proves importlib.


@pytest.mark.skipif(sys.version_info < (3, 12), reason="class API removed in Python 3.12")
def test_a_fully_qualified_class_api_already_encodes_its_owner(tmp_path, proposal):
    entry = proposal["removed_index"].pop("api:EntryPoints.items")
    entry.pop("owners")
    entry.update(module="importlib.metadata.EntryPoints", id="api:importlib.metadata.EntryPoints.items")
    proposal["removed_index"][entry["id"]] = entry
    session, issue, _ = run_case(tmp_path,
        "from importlib.metadata import EntryPoints\ndef fail():\n    EntryPoints.items()\n")
    assert issue.diagnosis_rule == "D02"
    assert any(f.predicate == "removal_owner" and f.value == entry["id"] for f in session.facts)


@pytest.mark.skipif(sys.version_info < (3, 12), reason="unittest aliases removed in Python 3.12")
def test_real_inherited_unittest_alias_uses_registered_public_base(tmp_path):
    source = ("import unittest\nclass Local(unittest.TestCase): pass\n"
              "def fail():\n    item = Local()\n    item.assertEquals(1, 1)\n")
    session, issue, check = run_case(tmp_path, source)
    assert issue.diagnosis_rule == "D03"
    (tmp_path / "app.py").write_text(source.replace("assertEquals", "assertEqual"))
    scan(session, [check])
    assert session.goal_status == "achieved"


@pytest.mark.parametrize("subclass", [False, True])
def test_pandas_public_alias_keeps_real_dynamic_type_but_not_local_dynamic_subclass(tmp_path, subclass):
    pandas = pytest.importorskip("pandas")
    if int(pandas.__version__.split(".")[0]) < 2:
        pytest.skip("DataFrame.append was removed in pandas 2")
    source = "import pandas as pd\n"
    if subclass:
        source += "class Local(pd.DataFrame):\n    def __getattr__(self, name):\n        raise AttributeError(name)\n"
    source += "def fail():\n    data = " + ("Local" if subclass else "pd.DataFrame") + "({'x': [1]})\n    data.append(data)\n"
    session, issue, check = run_case(tmp_path, source)
    assert (issue.diagnosis_rule == "D02") is not subclass
    if not subclass:
        (tmp_path / "app.py").write_text(source.replace("data.append(data)", "pd.concat([data, data])"))
        scan(session, [check])
        assert session.goal_status == "achieved"


@pytest.mark.skipif(sys.version_info < (3, 12), reason="readfp was removed in Python 3.12")
@pytest.mark.parametrize("change", ["imported", "wrong_environment", "missing_owner", "dynamic_subclass",
                                   "conflicting_provider", "shadowing", "own_distribution", "wrong_origin",
                                   "fresh_environment", "wrong_statement", "extra_event"])
def test_owned_method_rejects_unverifiable_or_stale_context(tmp_path, proposal, change):
    session, issue, _ = run_case(tmp_path, PARSER)
    assert issue.diagnosis_rule == "D03"
    run = next(run for run in session.runs if run.tool == "pytest_run")
    record = next(row for row in run.records if row.get("type") == "exception")
    project = next(run for run in session.runs if run.tool == "project")
    if change == "imported":
        run.source = "imported"
    elif change == "wrong_environment":
        run.environment_id = "other-environment"
    elif change == "missing_owner":
        record["symbol_observation"].pop("receiver_owners")
    elif change == "dynamic_subclass":
        record["symbol_observation"]["dynamic"] = True
        for owner in record["symbol_observation"]["receiver_owners"]:
            owner["direct"] = False
    elif change == "conflicting_provider":
        session.environment["import_distributions"]["configparser"] = ["another-provider"]
    elif change in {"shadowing", "own_distribution"}:
        data = json.loads(project.stdout)
        if change == "shadowing":
            data["local_modules"].append({"name": "configparser", "path": "configparser.py"})
        else:
            data["own_names"].append("python")
        project.stdout = json.dumps(data)
    elif change == "wrong_origin":
        for owner in record["symbol_observation"]["receiver_owners"]:
            owner["file"] = str(tmp_path / "configparser.py")
    elif change == "fresh_environment":
        scan(session, ["environment", "project"])
    elif change == "wrong_statement":
        for row in run.records:
            if row.get("type") == "failure":
                row["message"] = row["message"].replace("parser.readfp", "other.read_file")
    else:
        event = next(event for event in session.events if event.event_id in issue.event_ids)
        other = event.model_copy(deep=True, update={"event_id": "other-event", "evidence_refs": [f"{run.run_id}:stderr:1"]})
        session.events.append(other)
        issue.event_ids.append(other.event_id)
    infer_and_plan(session)
    issue = next(current for current in session.issues if current.issue_id == issue.issue_id)
    assert issue.diagnosis_rule not in {"D02", "D03"}
    assert not any(f.subject == issue.issue_id and f.predicate == "removal_owner" for f in session.facts)


def test_runtime_introspection_never_reads_user_class_descriptor():
    seen = []
    class Tricky:
        @property
        def __class__(self):
            seen.append("class")
            return type
    value = Tricky()
    with pytest.raises(AttributeError) as caught:
        value.readfp()
    exception_metadata(caught.value, caught.value.__traceback__)
    assert seen == []


def test_runtime_owner_mro_has_a_fixed_bound():
    cls = type("Base", (), {})
    for n in range(16):
        cls = type(f"Level{n}", (cls,), {})
    item = cls()
    with pytest.raises(AttributeError) as caught:
        item.readfp()
    assert exception_metadata(caught.value, caught.value.__traceback__)["symbol_observation"] == {}


def test_removal_owner_is_issue_scoped(tmp_path, proposal):
    (tmp_path / "app.py").write_text(
        "from configparser import ConfigParser\nclass Report: pass\n"
        "def fail(item):\n    item.readfp(None)\n")
    (tmp_path / "test_app.py").write_text(
        "from app import ConfigParser, Report, fail\n"
        "def test_real():\n    fail(ConfigParser())\n"
        "def test_local():\n    fail(Report())\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    _, details = observations(session, session.issues)
    assert len(details) == 2
    for issue in session.issues:
        item = details[issue.issue_id]
        assert (issue.diagnosis_rule == "D03") == (item["symbol_observation"]["owner"] == "ConfigParser")
    # Coalescing these separate failures must not preserve the external claim.
    first, second = session.issues
    first.event_ids.extend(second.event_ids)
    first.evidence_refs.extend(second.evidence_refs)
    infer_and_plan(session)
    assert first.diagnosis_rule not in {"D02", "D03"}


@pytest.mark.skipif(sys.version_info < (3, 12), reason="readfp was removed in Python 3.12")
def test_default_scan_can_use_the_later_same_environment_project_snapshot(tmp_path, proposal):
    (tmp_path / "app.py").write_text(PARSER)
    (tmp_path / "test_app.py").write_text("from app import fail\ndef test_fail():\n    fail()\n")
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session)
    issue = next(issue for issue in session.issues if issue.tool == "pytest_run")
    assert issue.diagnosis_rule == "D03"


@pytest.mark.skipif(sys.version_info < (3, 12), reason="readfp was removed in Python 3.12")
@pytest.mark.parametrize("kind", ["script", "module"])
@pytest.mark.parametrize("source,rule,repair", [
    (PARSER, "D03", ("readfp", "read_file")),
    ("from importlib.metadata import EntryPoints, entry_points\ndef fail():\n    EntryPoints.items()\n",
     "D02", ("EntryPoints.items()", "entry_points(group='fixfirst.nonexistent')")),
    ("class Report: pass\ndef fail():\n    item = Report()\n    item.readfp()\n", None, None),
    ("class EntryPoints: pass\ndef fail():\n    item = EntryPoints()\n    item.items()\n", None, None),
])
def test_native_script_and_module_preserve_owned_positives_and_namesake_negatives(
        tmp_path, proposal, kind, source, rule, repair):
    program = source + "fail()\n"
    (tmp_path / "main.py").write_text(program)
    session = create_session(tmp_path, sys.executable, goal="run_project",
                             execution={"kind": kind, "entry": "main.py" if kind == "script" else "main"})
    scan(session, ["environment", "project", "python_run"])
    issue = next(issue for issue in session.issues if issue.tool == "python_run")
    run = next(run for run in session.runs if run.tool == "python_run")
    assert any(row.get("symbol_observation") for row in run.records)
    if rule:
        assert issue.diagnosis_rule == rule
        (tmp_path / "main.py").write_text(program.replace(*repair))
        scan(session, ["python_run"])
        assert session.goal_status == "achieved"
    else:
        assert issue.diagnosis_rule not in {"D02", "D03"}


def test_a_local_descriptor_cannot_borrow_its_library_base_removal(tmp_path):
    pytest.importorskip("numpy")
    source = ("import numpy as np\nclass Local(np.ndarray):\n"
              "    @property\n    def ptp(self):\n        raise AttributeError('unavailable')\n"
              "def fail():\n    item = np.array([1, 2]).view(Local)\n    item.ptp\n")
    session, issue, _ = run_case(tmp_path, source)
    assert issue.diagnosis_rule not in {"D02", "D03"}
    assert not any(f.subject == issue.issue_id and f.predicate == "removal_owner" for f in session.facts)
