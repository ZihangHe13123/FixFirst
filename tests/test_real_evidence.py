"""B3 preparation contracts, using only invented saved sessions and no execution."""

from copy import deepcopy
import hashlib
import json
import ntpath
import posixpath
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "diagnosis_baseline"))

import real_evidence  # noqa: E402


def digest(data):
    return hashlib.sha256(data).hexdigest()


def saved_session(*, windows=False, healthy=False):
    """Make raw protocol evidence without importing/executing a fixture project."""
    root = r"C:\Users\private-person\private-project" if windows else "/home/private-person/private-project"
    python = root + (r"\.venv\Scripts\python.exe" if windows else "/.venv/bin/python")
    normalized = ntpath.normcase(ntpath.abspath(python)) if windows else posixpath.abspath(python)
    identity = digest(normalized.encode())[:16]
    session_id = "session-private-source"
    env_id, project_id, test_id = "run-private-env", "run-private-project", "run-private-tests"
    node = "test_app.py::test_execute"
    environment = {
        "python_version": "3.12.0",
        "executable": python,
        "packages": [{"name": "SQLAlchemy", "version": "2.0.0", "requires": ["typing-extensions>=4.6"]}],
        "import_distributions": {"sqlalchemy": ["SQLAlchemy"]},
        "stdlib_modules": ["os", "sys"],
        "markers": {"python_version": "3.12"},
    }
    project = {
        "environment_run_id": env_id,
        "python_files": ["app.py", "test_app.py"],
        "files": [{"path": "app.py", "bytes": 44, "sha256": "0" * 64}],
        "local_modules": [{"name": "app", "path": "app.py"}],
        "defined_names": ["execute"],
        "imported_names": {"create_engine": "sqlalchemy.create_engine"},
        "own_names": [],
        "declarations": [{"name": "sqlalchemy", "requirement": "SQLAlchemy>=2.0", "source": "requirements.txt:1"}],
        "tested_versions": [],
    }

    def run(run_id, tool, scope, stdout, *, exit_code=0, records=()):
        return {
            "run_id": run_id, "tool": tool, "scope": scope, "environment_id": identity,
            "source": "executed", "status": "completed", "exit_code": exit_code,
            "stdout": stdout, "stderr": "", "truncated": False, "records": list(records),
            "cwd": root, "argv": [python, "-m", "pytest"],
            "notes": ["CONCLUSION_RUN_NOTE_SENTINEL"],
            "verified_pass": healthy, "coverage_complete": True,
        }

    records = []
    if not healthy:
        records += [
            {"type": "failure", "nodeid": node, "stage": "call",
             "message": f'  File "{root}/app.py", line 3\n    engine.execute(query)\nAttributeError: execute unavailable'},
            {"type": "exception", "nodeid": node, "stage": "call",
             "exception_type": "AttributeError", "exception_message": "execute unavailable",
             "source_file": root + "/app.py", "source_line": 3,
             "symbol_observation": {
                 "source": "failed_instruction_namespace", "kind": "instance", "operation": "LOAD_ATTR",
                 "module": "sqlalchemy.engine.base", "owner": "Engine", "name": "execute",
                 "file": root + "/app.py", "line": 3, "static_namespace_checked": True,
                 "requested_member_present": False, "dynamic": False, "candidates": [],
             }},
        ]
    records += [
        {"type": "outcome", "nodeid": node, "stage": phase,
         "outcome": "failed" if phase == "call" and not healthy else "passed", "wasxfail": False}
        for phase in ("setup", "call", "teardown")
    ]
    records += [{"type": "finish", "nodes": [node], "collected": 1, "collect_only": False,
                 "records_dropped": False, "exit_code": 0 if healthy else 1}]
    return {
        "schema_version": 1, "session_id": session_id, "name": "CONCLUSION_SESSION_NAME_SENTINEL",
        "project_root": root, "target_python": python, "goal": "pass_tests",
        "environment": {**environment, "_run_id": env_id, "_environment_id": identity},
        "runs": [run(env_id, "environment", "environment", json.dumps(environment)),
                 run("run-private-pip", "pip_check", "dependencies:environment", "No broken requirements found."),
                 run(test_id, "pytest_run", "tests:project", f"{root}/test_app.py: one test\n",
                     exit_code=0 if healthy else 1, records=records),
                 run("run-private-ruff", "ruff", "lint:project", "[]"),
                 run(project_id, "project", "declarations:project", json.dumps(project))],
        "issues": [{"diagnosis": "CONCLUSION_ISSUE_SENTINEL"}],
        "events": [{"message": "CONCLUSION_EVENT_SENTINEL"}],
        "facts": [{"value": "CONCLUSION_FACT_SENTINEL"}],
        "actions": [{"title": "CONCLUSION_ACTION_SENTINEL"}],
        "history": [{"note": "CONCLUSION_HISTORY_SENTINEL"}],
        "inference_trace": {"conclusion": "CONCLUSION_TRACE_SENTINEL"},
        "goal_status": "achieved" if healthy else "blocked",
    }


def write_inputs(tmp_path, session=None, *, mapping=None, envelope=False):
    session = saved_session() if session is None else session
    sessions = tmp_path / "sessions"
    source = sessions / session["session_id"] / "session.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if mapping is None:
        mapping = [{"id": "case-private-label", "session_id": session["session_id"],
                    "label": "MAPPING_LABEL_SENTINEL", "first_step": "MAPPING_REFERENCE_SENTINEL",
                    "score": "MAPPING_SCORE_SENTINEL"}]
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps({"results": mapping} if envelope else mapping), encoding="utf-8")
    return mapping_path, sessions, source


def prepared(tmp_path, session=None, **kwargs):
    mapping, sessions, source = write_inputs(tmp_path, session, **kwargs)
    output = tmp_path / "prepared"
    manifest = real_evidence.prepare(mapping, sessions, output)
    rows = [json.loads(line) for line in (output / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    return manifest, rows, output, source


def pytest_evidence(row):
    return next(run for run in row["evidence"]["runs"] if run["tool"] == "pytest_run")


def raw_run(session, tool):
    return next(run for run in session["runs"] if run["tool"] == tool)


@pytest.mark.parametrize("envelope", [False, True])
def test_prepares_unlabelled_cases_from_both_locator_formats(tmp_path, envelope):
    manifest, rows, output, source = prepared(tmp_path, envelope=envelope)
    assert manifest["schema_version"] == 1
    assert manifest["protocol"] == "b3-real-evidence-v1"
    assert manifest["cases_file"] == "cases.jsonl"
    assert manifest["case_ids"] == ["case-private-label"]
    assert manifest["cases_sha256"] == digest((output / "cases.jsonl").read_bytes())
    assert manifest["builder"]["sha256"] == digest(Path(real_evidence.__file__).read_bytes())
    assert manifest["input_provenance"]["mapping_sha256"] == digest((tmp_path / "mapping.json").read_bytes())
    provenance = manifest["input_provenance"]["sessions"][0]
    assert provenance["case_id"] == "case-private-label"
    assert provenance["source_sha256"] == digest(source.read_bytes())
    assert provenance["selected_run_ids"] == ["run-private-env", "run-private-pip", "run-private-tests",
                                               "run-private-ruff", "run-private-project"]
    assert provenance["observation_cutoff_run_id"] == "run-private-project"
    assert manifest["truncation_policy"]
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert len(rows) == 1
    assert rows[0]["source_sha256"] == digest(source.read_bytes())
    assert rows[0]["case_id"] == "case-private-label"
    assert len(rows[0]["evidence_sha256"]) == 64
    assert rows[0]["evidence"]["protocol"] == "b3-real-evidence-v1"
    assert rows[0]["evidence"]["goal"] == "pass_tests"
    assert not ({"label", "score", "first_step", "session_id"} & rows[0].keys())


def test_preserves_requires_failure_trace_and_operation_lineage(tmp_path):
    _, rows, _, _ = prepared(tmp_path)
    evidence = rows[0]["evidence"]
    assert evidence["environment"]["packages"][0]["requires"] == ["typing-extensions>=4.6"]
    assert evidence["project"]["imported_names"]["create_engine"] == "sqlalchemy.create_engine"
    run = pytest_evidence(rows[0])
    assert {key: run[key] for key in ("tool", "scope", "source", "status", "exit_code", "truncated")} == {
        "tool": "pytest_run", "scope": "tests:project", "source": "executed", "status": "completed",
        "exit_code": 1, "truncated": False,
    }
    failure, exception = run["records"][:2]
    assert "engine.execute(query)" in failure["message"]
    assert failure["nodeid"] == exception["nodeid"] == "test_app.py::test_execute"
    assert failure["stage"] == exception["stage"] == "call"
    assert [failure["record_index"], exception["record_index"]] == [0, 1]
    assert exception["symbol_observation"]["operation"] == "LOAD_ATTR"
    assert exception["symbol_observation"]["owner"] == "Engine"
    assert exception["symbol_observation"]["requested_member_present"] is False
    assert [record["type"] for record in run["records"][2:]] == ["outcome", "outcome", "outcome", "finish"]
    assert run["records"][-1]["records_dropped"] is False


def test_preserves_positional_only_keyword_binding_observation(tmp_path):
    session = saved_session()
    observation = raw_run(session, "pytest_run")["records"][1]["symbol_observation"]
    observation.update(operation="CALL", kind="python_binding",
                       binding_errors={"positional_only_as_keyword": ["value"]})
    _, rows, _, _ = prepared(tmp_path, session)
    exception = pytest_evidence(rows[0])["records"][1]
    assert exception["symbol_observation"]["binding_errors"]["positional_only_as_keyword"] == ["value"]


def test_preserves_actual_static_project_producer_shapes(tmp_path):
    """Exercise the frozen producer on invented files; never execute their code."""
    from types import SimpleNamespace

    from fixfirst.project import collect_project

    project_root = tmp_path / "invented-project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text(
        '[project]\nname="sample-lab"\nrequires-python=">=3.10"\n'
        'dependencies=["pydantic>=2"]\n[tool.ruff]\nline-length=88\n'
        '[tool.pylint]\n', encoding="utf-8")
    (project_root / "requirements").mkdir()
    (project_root / "requirements/dev.txt").write_text("pytest>=8\n", encoding="utf-8")
    (project_root / "environment.yml").write_text(
        "dependencies:\n  - python>=3.10\n  - numpy=1.26\n  - unmapped-package=1.0\n"
        "  - pip:\n    - packaging>=24\n", encoding="utf-8")
    (project_root / ".python-version").write_text("3.12\n", encoding="utf-8")
    (project_root / "Pipfile.lock").write_text(
        '{"default":{"numpy":{"version":"==1.26.4"}}}', encoding="utf-8")
    (project_root / "app.py").write_text(
        "from typing import Optional\nfrom pydantic import BaseModel\nimport numpy as np\n"
        "class Model(BaseModel):\n    value: Optional[str]\n"
        "    def convert(self):\n        return str(self.value)\n"
        "def display():\n    return f'{np.float64(1)!r}'\n"
        "def consume(items):\n    values = (x for x in items)\n    return list(values)\n"
        "raise AssertionError('THIS FILE MUST NEVER EXECUTE')\n", encoding="utf-8")
    session = saved_session()
    session["project_root"] = str(project_root)
    for run in session["runs"]:
        run["cwd"] = str(project_root)
    produced = collect_project(SimpleNamespace(project_root=str(project_root), goal="pass_tests",
                                               environment=session["environment"]),
                               session["environment"]["_environment_id"])
    raw_run(session, "project")["stdout"] = produced.stdout
    original = json.loads(produced.stdout)
    assert original["conda_declarations"] and original["conda_mappings"]
    assert any(row.get("selected_from") for row in original["declarations"])
    assert original["source_context"]["calls"] and original["source_context"]["call_bindings"]
    assert original["source_context"]["class_bases"] and original["source_context"]["class_members"]
    assert original["pydantic_optional_models"] and original["generator_consumption"]
    assert original["numpy_repr_functions"] and original["tested_versions"]
    assert original["lint_config"] == {"ruff": "pyproject.toml [tool.ruff]", "other": "pyproject.toml [tool.pylint]"}
    manifest, rows, _, _ = prepared(tmp_path, session)
    rendered = rows[0]["evidence"]["project"]
    omitted = manifest["evidence_field_policy"]["project_omitted"]
    assert set(omitted) == {"conda_mappings"}
    assert set(rendered) == set(original) - set(omitted)
    for key, value in original.items():
        if key not in omitted and key != "environment_run_id":
            assert rendered[key] == value, key
    assert rows[0]["evidence"]["truncation"] == []


@pytest.mark.parametrize("target", ["mapping", "session", "environment", "project"])
@pytest.mark.parametrize("invalid", ['"duplicate":1,"duplicate":2', '"number":NaN',
                                    '"number":Infinity', '"number":-Infinity', '"number":1e999'])
def test_rejects_duplicate_keys_and_nonfinite_json_before_creating_output(tmp_path, target, invalid):
    session = saved_session()
    if target in {"environment", "project"}:
        run = raw_run(session, target)
        run["stdout"] = "{" + invalid + "," + run["stdout"][1:]
    mapping, sessions, source = write_inputs(tmp_path, session)
    if target == "mapping":
        text = mapping.read_text(encoding="utf-8")
        mapping.write_text(text.replace("{", "{" + invalid + ",", 1), encoding="utf-8")
    elif target == "session":
        text = source.read_text(encoding="utf-8")
        source.write_text("{" + invalid + "," + text[1:], encoding="utf-8")
    output = tmp_path / "prepared"
    with pytest.raises(ValueError, match="Duplicate JSON|Non-finite JSON"):
        real_evidence.prepare(mapping, sessions, output)
    assert not output.exists()


def test_healthy_input_retains_completion_evidence_without_derived_conclusions(tmp_path):
    _, rows, _, _ = prepared(tmp_path, saved_session(healthy=True))
    run = pytest_evidence(rows[0])
    assert run["exit_code"] == 0
    assert {r["type"] for r in run["records"]} == {"outcome", "finish"}
    assert all(r["outcome"] == "passed" for r in run["records"] if r["type"] == "outcome")
    finish = run["records"][-1]
    assert finish["nodes"] == ["test_app.py::test_execute"]
    assert finish["collected"] == 1 and finish["collect_only"] is False
    assert "goal_status" not in rows[0]["evidence"]
    assert "verified_pass" not in run and "coverage_complete" not in run


@pytest.mark.parametrize("windows", [False, True])
def test_neutralizes_private_paths_and_ids_consistently(tmp_path, windows):
    session = saved_session(windows=windows)
    _, rows, _, _ = prepared(tmp_path, session)
    evidence = rows[0]["evidence"]
    text = json.dumps(evidence, ensure_ascii=False)
    for private in ("private-person", "private-project", session["session_id"],
                    session["environment"]["_environment_id"], "case-private-label", "run-private-"):
        assert private not in text
    assert "CONCLUSION_" not in text and "MAPPING_" not in text
    run = pytest_evidence(rows[0])
    assert run["run_id"].startswith("run-")
    assert run["environment_id"].startswith("environment-")
    assert run["records"][1]["source_file"] == run["records"][1]["symbol_observation"]["file"]
    assert "app.py" in run["records"][1]["source_file"]


def test_locator_id_cannot_rename_fixed_evidence_fields(tmp_path):
    session = saved_session()
    mapping = [{"id": "source", "session_id": session["session_id"]}]
    _, rows, _, _ = prepared(tmp_path, session, mapping=mapping)
    run = pytest_evidence(rows[0])
    assert run["source"] == "executed"
    assert run["records"][1]["symbol_observation"]["source"] == "failed_instruction_namespace"


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("case_id,name", [(name, name) for name in
                                        ("pytest", "dateparser", "DateParser", "click", "httpx")]
                         + [("dateparser", "DateParser")])
def test_locator_names_do_not_rewrite_packages_imports_commands_or_source(tmp_path, windows, case_id, name):
    session = saved_session(windows=windows)
    session["name"] = name
    environment = json.loads(raw_run(session, "environment")["stdout"])
    packages = [{"name": n, "version": "1.0", "requires": ["pytest>=6.2.5", "dateparser>=1"]}
                for n in ("pytest", "dateparser", "click", "httpx")]
    imports = {"pytest": ["pytest"], "dateparser": ["dateparser"], "DateParser": ["dateparser"],
               "click": ["click"], "httpx": ["httpx"]}
    environment.update(packages=packages, import_distributions=imports)
    raw_run(session, "environment")["stdout"] = json.dumps(environment)
    session["environment"].update(environment)
    project = json.loads(raw_run(session, "project")["stdout"])
    bindings = {"pytest": "pytest", "dateparser": "dateparser", "DateParser": "dateparser.DateParser",
                "click": "click", "httpx": "httpx"}
    declarations = [{"name": n, "requirement": n + ">=1", "source": n + "/requirements.txt:1"}
                    for n in ("pytest", "dateparser", "click", "httpx")]
    context = {"calls": {"dateparser/api.py:5": ["dateparser.parse"],
                         "DateParser/api.py:5": ["DateParser.parse"]}}
    project.update(imported_names=bindings, defined_names=["DateParser"], declarations=declarations,
                   own_names=[name], source_context=context)
    raw_run(session, "project")["stdout"] = json.dumps(project)
    command_and_source = (
        "python -m pytest\npython -m pip install pytest==6.2.5 dateparser==1.0 click==8.0 httpx==0.18\n"
        "import pytest, dateparser, click, httpx\nfrom dateparser import DateParser\n"
        "value = DateParser(dateparser.parse('today'))\n")
    run = raw_run(session, "pytest_run")
    run["stdout"] = command_and_source
    run["records"][0]["message"] += "\n" + command_and_source
    run["records"][1]["symbol_observation"].update(module="dateparser", owner="DateParser", name="parse")
    mapping = [{"id": case_id, "session_id": session["session_id"], "label": "LABEL_SENTINEL"}]
    _, rows, _, _ = prepared(tmp_path, session, mapping=mapping)
    evidence = rows[0]["evidence"]
    assert evidence["environment"]["packages"] == packages
    assert evidence["environment"]["import_distributions"] == imports
    assert evidence["project"]["imported_names"] == bindings
    assert evidence["project"]["declarations"] == declarations
    assert evidence["project"]["source_context"] == context
    assert evidence["project"]["own_names"] == [name]
    assert pytest_evidence(rows[0])["stdout"] == command_and_source
    assert command_and_source in pytest_evidence(rows[0])["records"][0]["message"]
    observed = pytest_evidence(rows[0])["records"][1]["symbol_observation"]
    assert (observed["module"], observed["owner"], observed["name"]) == ("dateparser", "DateParser", "parse")
    assert not ({"case_id", "session_id", "label", "facts", "actions", "issues", "inference_trace"} & evidence.keys())
    assert "LABEL_SENTINEL" not in json.dumps(evidence)
    assert "CONCLUSION_" not in json.dumps(evidence)


def test_nonopaque_identity_words_are_mapped_only_in_explicit_metadata(tmp_path):
    session = saved_session(windows=True)
    session["session_id"] = "dateparser"
    raw_run(session, "environment")["run_id"] = "pytest"
    session["environment"]["_run_id"] = "pytest"
    project = json.loads(raw_run(session, "project")["stdout"])
    project["environment_run_id"] = "pytest"
    project["imported_names"] = {"pytest": "pytest", "DateParser": "dateparser.DateParser"}
    raw_run(session, "project")["stdout"] = json.dumps(project)
    raw_run(session, "pytest_run")["stdout"] = "python -m pytest\nfrom dateparser import DateParser\n"
    _, rows, _, _ = prepared(tmp_path, session)
    evidence = rows[0]["evidence"]
    assert evidence["runs"][0]["run_id"] == evidence["project"]["environment_run_id"] == "run-1"
    assert evidence["project"]["imported_names"] == project["imported_names"]
    assert pytest_evidence(rows[0])["stdout"] == raw_run(session, "pytest_run")["stdout"]


@pytest.mark.parametrize("windows", [False, True])
def test_only_actual_opaque_id_tokens_are_replaced_and_case_is_preserved(tmp_path, windows):
    session = saved_session(windows=windows)
    session["session_id"] = "session-aabbccddeeff"
    for index, run in enumerate(session["runs"]):
        run["run_id"] = f"run-abcdef{index:06x}"
    env_id = raw_run(session, "environment")["run_id"]
    session["environment"]["_run_id"] = env_id
    project = json.loads(raw_run(session, "project")["stdout"])
    project["environment_run_id"] = env_id
    raw_run(session, "project")["stdout"] = json.dumps(project)
    failure = raw_run(session, "pytest_run")
    source_id = failure["run_id"]
    identity = session["environment"]["_environment_id"]
    failure["stdout"] = f"{source_id}:probe:0 {session['session_id']} {identity}\n{source_id.upper()}"
    _, rows, _, _ = prepared(tmp_path, session)
    assert pytest_evidence(rows[0])["stdout"] == f"run-3:probe:0 session-1 environment-1\n{source_id.upper()}"
    assert rows[0]["evidence"]["project"]["environment_run_id"] == "run-1"


@pytest.mark.parametrize("field", ["package", "import", "api"])
def test_opaque_id_collision_with_a_diagnostic_symbol_rejects_instead_of_changing_it(tmp_path, field):
    session = saved_session()
    identity = session["environment"]["_environment_id"]
    if field == "package":
        environment = json.loads(raw_run(session, "environment")["stdout"])
        environment["packages"].append({"name": identity, "version": "1.0", "requires": []})
        raw_run(session, "environment")["stdout"] = json.dumps(environment)
    elif field == "import":
        project = json.loads(raw_run(session, "project")["stdout"])
        project["imported_names"][identity] = "package.symbol"
        raw_run(session, "project")["stdout"] = json.dumps(project)
    else:
        raw_run(session, "pytest_run")["records"][1]["symbol_observation"]["name"] = identity
    mapping, sessions, _ = write_inputs(tmp_path, session)
    output = tmp_path / "prepared"
    with pytest.raises(ValueError, match="opaque source ID collides"):
        real_evidence.prepare(mapping, sessions, output)
    assert not output.exists()


@pytest.mark.parametrize("windows", [False, True])
def test_unknown_home_accounts_are_redacted_without_changing_relative_paths(tmp_path, windows):
    session = saved_session(windows=windows)
    raw = (
        'C:\\Users\\Example Person\\cache.py\nC:/Users/Forward Person/cache.py\n'
        'c:\\uSeRs\\Mixed Person\\cache.py\nC:\\\\Users\\\\Escaped Person\\\\cache.py\n'
        '"C:\\Users\\Quoted Person"\n"/home/Quoted Posix Person"\n'
        '"/Users/Mac Person/cache.py"\n"/home/Linux Person/cache.py"\n'
        '/home/shortname\nC:/Users/shortname\n'
        'pkg/home/person/api.py pkg/Users/person/api.py dateparser.parse DateParser.parse\n')
    expected = (
        'C:\\Users\\<user>\\cache.py\nC:/Users/<user>/cache.py\n'
        'c:\\uSeRs\\<user>\\cache.py\nC:\\\\Users\\\\<user>\\\\cache.py\n'
        '"C:\\Users\\<user>"\n"/home/<user>"\n'
        '"/Users/<user>/cache.py"\n"/home/<user>/cache.py"\n'
        '/home/<user>\nC:/Users/<user>\n'
        'pkg/home/person/api.py pkg/Users/person/api.py dateparser.parse DateParser.parse\n')
    raw_run(session, "pytest_run")["stdout"] = raw
    _, rows, _, _ = prepared(tmp_path, session)
    assert pytest_evidence(rows[0])["stdout"] == expected


def test_home_redaction_does_not_swallow_diagnostic_text_before_a_later_path(tmp_path):
    session = saved_session(windows=True)
    text = (
        "C:\\Users\\Example could not import pytest; inspect /tmp/errors.txt\n"
        "/home/example could not import pytest; inspect /tmp/errors.txt\n"
        "C:/Users/Example could not import pytest; inspect /tmp/errors.txt\n")
    raw_run(session, "pytest_run")["stdout"] = text
    _, rows, _, _ = prepared(tmp_path, session)
    assert pytest_evidence(rows[0])["stdout"] == text.replace(
        "C:\\Users\\Example", "C:\\Users\\<user>").replace(
        "/home/example", "/home/<user>").replace("C:/Users/Example", "C:/Users/<user>")


@pytest.mark.parametrize("windows", [False, True])
def test_path_case_matching_is_scoped_to_windows_paths_only(tmp_path, windows):
    session = saved_session(windows=windows)
    path = session["project_root"].swapcase() + "/DateParser.py"
    raw_run(session, "pytest_run")["stdout"] = path + "\nDateParser dateparser PYTEST pytest"
    _, rows, _, _ = prepared(tmp_path, session)
    expected_path = "/project/DateParser.py" if windows else path
    assert pytest_evidence(rows[0])["stdout"] == expected_path + "\nDateParser dateparser PYTEST pytest"


@pytest.mark.parametrize("windows", [False, True])
def test_distinct_dynamic_keys_that_redact_to_one_path_are_not_merged(tmp_path, windows):
    session = saved_session(windows=windows)
    project = json.loads(raw_run(session, "project")["stdout"])
    prefix = "C:/Users/" if windows else "/home/"
    project["source_context"] = {"calls": {
        prefix + "Alice/api.py:1": ["dateparser.parse"], prefix + "Bob/api.py:1": ["DateParser.parse"]}}
    raw_run(session, "project")["stdout"] = json.dumps(project)
    mapping, sessions, _ = write_inputs(tmp_path, session)
    output = tmp_path / "prepared"
    with pytest.raises(ValueError, match="duplicate mapping keys"):
        real_evidence.prepare(mapping, sessions, output)
    assert not output.exists()


@pytest.mark.parametrize("field", ["packages", "declarations", "local_modules", "tested_versions"])
@pytest.mark.parametrize("bad_row", [None, "not an object"])
def test_identifier_collision_check_keeps_value_errors_for_malformed_rows(tmp_path, field, bad_row):
    session = saved_session()
    run = raw_run(session, "environment" if field == "packages" else "project")
    snapshot = json.loads(run["stdout"])
    snapshot[field] = [bad_row]
    run["stdout"] = json.dumps(snapshot)
    mapping, sessions, _ = write_inputs(tmp_path, session)
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


def test_identifier_collision_check_keeps_value_error_for_a_nonlist_collection(tmp_path):
    session = saved_session()
    run = raw_run(session, "project")
    project = json.loads(run["stdout"])
    project["declarations"] = None
    run["stdout"] = json.dumps(project)
    mapping, sessions, _ = write_inputs(tmp_path, session)
    with pytest.raises(ValueError, match="Expected a list"):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


def test_later_search_resolver_and_install_records_are_not_input_evidence(tmp_path):
    session = saved_session()
    for tool in ("version_search", "dependency_resolve", "pip_install"):
        followup = deepcopy(raw_run(session, "pytest_run"))
        followup.update(run_id=f"later-{tool}", tool=tool, stdout="FOLLOWUP_RESULT_SENTINEL", records=[])
        session["runs"].append(followup)
    _, rows, _, _ = prepared(tmp_path, session)
    assert "FOLLOWUP_RESULT_SENTINEL" not in json.dumps(rows[0]["evidence"])
    assert not ({"version_search", "dependency_resolve", "pip_install"}
                & {r["tool"] for r in rows[0]["evidence"]["runs"]})


def test_unknown_probe_record_cannot_smuggle_a_conclusion(tmp_path):
    session = saved_session()
    raw_run(session, "pytest_run")["records"].insert(0, {"type": "diagnosis", "value": "SMUGGLED_CONCLUSION_SENTINEL"})
    _, rows, _, _ = prepared(tmp_path, session)
    run = pytest_evidence(rows[0])
    assert "SMUGGLED_CONCLUSION_SENTINEL" not in json.dumps(rows[0]["evidence"])
    assert run["records"][0]["record_index"] == 1


@pytest.mark.parametrize("field,value", [
    ("_run_id", "nonexistent-environment-run"),
    ("_environment_id", "different-interpreter"),
])
def test_rejects_environment_snapshot_with_invalid_lineage(tmp_path, field, value):
    session = saved_session()
    session["environment"][field] = value
    mapping, sessions, _ = write_inputs(tmp_path, session)
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


@pytest.mark.parametrize("change", ["wrong_link", "wrong_environment", "imported", "malformed"])
def test_rejects_project_snapshot_with_invalid_lineage(tmp_path, change):
    session = saved_session()
    run = raw_run(session, "project")
    if change == "wrong_link":
        project = json.loads(run["stdout"])
        project["environment_run_id"] = "a-different-snapshot"
        run["stdout"] = json.dumps(project)
    elif change == "wrong_environment":
        run["environment_id"] = "a-different-interpreter"
    elif change == "imported":
        run["source"] = "imported"
    else:
        run["stdout"] = "not a JSON snapshot"
    mapping, sessions, _ = write_inputs(tmp_path, session)
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


@pytest.mark.parametrize("tool", ["environment", "project", "pytest_run"])
def test_rejects_missing_required_raw_check(tmp_path, tool):
    session = saved_session()
    session["runs"] = [run for run in session["runs"] if run["tool"] != tool]
    mapping, sessions, _ = write_inputs(tmp_path, session)
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


def test_rejects_duplicate_run_ids(tmp_path):
    session = saved_session()
    raw_run(session, "pytest_run")["run_id"] = raw_run(session, "environment")["run_id"]
    mapping, sessions, _ = write_inputs(tmp_path, session)
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


@pytest.mark.parametrize("tool,field,value", [
    ("pytest_run", "cwd", "/another-project"),
    ("ruff", "scope", "lint:selected"),
])
def test_rejects_checks_from_a_different_project_or_scope(tmp_path, tool, field, value):
    session = saved_session()
    raw_run(session, tool)[field] = value
    mapping, sessions, _ = write_inputs(tmp_path, session)
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


@pytest.mark.parametrize("duplicate_field", ["id", "session_id"])
def test_rejects_duplicate_locators(tmp_path, duplicate_field):
    session = saved_session()
    mapping = [{"id": "case-one", "session_id": session["session_id"]},
               {"id": "case-two", "session_id": "session-two"}]
    mapping[1][duplicate_field] = mapping[0][duplicate_field]
    mapping_path, sessions, _ = write_inputs(tmp_path, session, mapping=mapping)
    second = deepcopy(session)
    second["session_id"] = "session-two"
    other = sessions / "session-two" / "session.json"
    other.parent.mkdir()
    other.write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping_path, sessions, tmp_path / "prepared")


@pytest.mark.parametrize("missing", ["file", "session_id", "id"])
def test_rejects_missing_raw_session_or_locator(tmp_path, missing):
    session = saved_session()
    row = {"id": "case-one", "session_id": session["session_id"]}
    if missing != "file":
        row.pop(missing)
    mapping, sessions, source = write_inputs(tmp_path, session, mapping=[row])
    if missing == "file":
        source.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


def test_repeated_scan_requires_an_explicit_observation_cutoff(tmp_path):
    session = saved_session()
    rerun = deepcopy(raw_run(session, "pytest_run"))
    rerun.update(run_id="run-second-tests", stdout="LATER_RESCAN_SENTINEL")
    session["runs"].append(rerun)
    mapping, sessions, _ = write_inputs(tmp_path, session)
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


@pytest.mark.parametrize("explicit", [False, True])
def test_custom_check_subset_requires_an_explicit_cutoff(tmp_path, explicit):
    session = saved_session()
    session["runs"] = [raw_run(session, tool) for tool in ("environment", "project", "pytest_run")]
    mapping = [{"id": "case-one", "session_id": session["session_id"]}]
    if explicit:
        mapping[0]["observation_cutoff_run_id"] = "run-private-tests"
    mapping_path, sessions, _ = write_inputs(tmp_path, session, mapping=mapping)
    output = tmp_path / "prepared"
    if explicit:
        manifest = real_evidence.prepare(mapping_path, sessions, output)
        assert manifest["input_provenance"]["sessions"][0]["cutoff_method"] == "explicit"
    else:
        with pytest.raises(ValueError):
            real_evidence.prepare(mapping_path, sessions, output)


def test_explicit_cutoff_selects_original_prefix_and_excludes_later_scan(tmp_path):
    session = saved_session()
    cutoff = raw_run(session, "project")["run_id"]
    rerun = deepcopy(raw_run(session, "pytest_run"))
    rerun.update(run_id="run-second-tests", stdout="LATER_RESCAN_SENTINEL")
    session["runs"].append(rerun)
    mapping = [{"id": "case-one", "session_id": session["session_id"], "observation_cutoff_run_id": cutoff}]
    _, rows, _, _ = prepared(tmp_path, session, mapping=mapping)
    assert "LATER_RESCAN_SENTINEL" not in json.dumps(rows[0]["evidence"])
    assert len([run for run in rows[0]["evidence"]["runs"] if run["tool"] == "pytest_run"]) == 1


def test_cutoff_uses_original_environment_run_not_the_final_session_snapshot(tmp_path):
    session = saved_session()
    cutoff = raw_run(session, "project")["run_id"]
    later = deepcopy(raw_run(session, "environment"))
    snapshot = json.loads(later["stdout"])
    snapshot["packages"] = [{"name": "later-environment", "version": "9.0", "requires": []}]
    later.update(run_id="run-later-environment", stdout=json.dumps(snapshot))
    session["runs"].append(later)
    session["environment"] = {**snapshot, "_run_id": later["run_id"],
                              "_environment_id": later["environment_id"]}
    mapping = [{"id": "case-one", "session_id": session["session_id"], "observation_cutoff_run_id": cutoff}]
    _, rows, _, _ = prepared(tmp_path, session, mapping=mapping)
    assert rows[0]["evidence"]["environment"]["packages"][0]["name"] == "SQLAlchemy"
    assert "later-environment" not in json.dumps(rows[0]["evidence"])


@pytest.mark.parametrize("cutoff", ["missing-run", "run-private-tests", "run-second-tests"])
def test_invalid_or_ambiguous_explicit_cutoffs_are_rejected(tmp_path, cutoff):
    session = saved_session()
    rerun = deepcopy(raw_run(session, "pytest_run"))
    rerun["run_id"] = "run-second-tests"
    session["runs"].append(rerun)
    mapping = [{"id": "case-one", "session_id": session["session_id"], "observation_cutoff_run_id": cutoff}]
    mapping_path, sessions, _ = write_inputs(tmp_path, session, mapping=mapping)
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping_path, sessions, tmp_path / "prepared")


@pytest.mark.parametrize("field,value", [("stdout", None), ("stderr", []), ("records", {}), ("records", None)])
def test_rejects_malformed_raw_check_fields(tmp_path, field, value):
    session = saved_session()
    raw_run(session, "pytest_run")[field] = value
    mapping, sessions, _ = write_inputs(tmp_path, session)
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


def test_rejects_a_summary_without_raw_output_or_records(tmp_path):
    session = saved_session()
    raw_run(session, "pytest_run").update(stdout="", stderr="", records=[], verified_pass=True)
    mapping, sessions, _ = write_inputs(tmp_path, session)
    with pytest.raises(ValueError):
        real_evidence.prepare(mapping, sessions, tmp_path / "prepared")


def test_incomplete_run_is_preserved_as_incomplete_evidence(tmp_path):
    session = saved_session()
    raw_run(session, "pytest_run").update(status="timeout", exit_code=None, truncated=True,
                               stderr="Timed out after partial execution")
    _, rows, _, _ = prepared(tmp_path, session)
    run = pytest_evidence(rows[0])
    assert run["status"] == "timeout" and run["exit_code"] is None and run["truncated"] is True
    assert "Timed out after partial execution" in run["stderr"]


def test_existing_output_is_refused_without_touching_its_contents(tmp_path):
    mapping, sessions, _ = write_inputs(tmp_path)
    output = tmp_path / "prepared"
    output.mkdir()
    marker = output / "do-not-overwrite.txt"
    marker.write_text("original bytes", encoding="utf-8")
    with pytest.raises((ValueError, FileExistsError)):
        real_evidence.prepare(mapping, sessions, output)
    assert marker.read_text(encoding="utf-8") == "original bytes"
    assert list(output.iterdir()) == [marker]


def test_preparation_is_read_only_and_digests_repeat_for_identical_input(tmp_path):
    mapping, sessions, source = write_inputs(tmp_path)
    original_source, original_mapping = source.read_bytes(), mapping.read_bytes()
    first, second = tmp_path / "first", tmp_path / "second"
    manifest_a = real_evidence.prepare(mapping, sessions, first)
    manifest_b = real_evidence.prepare(mapping, sessions, second)
    assert (first / "cases.jsonl").read_bytes() == (second / "cases.jsonl").read_bytes()
    assert manifest_a["cases_sha256"] == manifest_b["cases_sha256"]
    assert source.read_bytes() == original_source and mapping.read_bytes() == original_mapping
    changed = json.loads(original_source)
    raw_run(changed, "pytest_run")["stdout"] += "changed raw observation\n"
    source.write_text(json.dumps(changed), encoding="utf-8")
    third = tmp_path / "third"
    manifest_c = real_evidence.prepare(mapping, sessions, third)
    row_a = json.loads((first / "cases.jsonl").read_text())
    row_c = json.loads((third / "cases.jsonl").read_text())
    assert manifest_c["cases_sha256"] != manifest_a["cases_sha256"]
    assert row_c["evidence_sha256"] != row_a["evidence_sha256"]
    assert row_c["source_sha256"] != row_a["source_sha256"]


def test_mapping_labels_and_reference_answers_cannot_change_model_evidence(tmp_path):
    mapping, sessions, _ = write_inputs(tmp_path)
    first = tmp_path / "first"
    real_evidence.prepare(mapping, sessions, first)
    rows = json.loads(mapping.read_text(encoding="utf-8"))
    rows[0].update(label="ANOTHER_LABEL", first_step="ANOTHER_REFERENCE", score="correct")
    mapping.write_text(json.dumps(rows), encoding="utf-8")
    second = tmp_path / "second"
    real_evidence.prepare(mapping, sessions, second)
    assert (first / "cases.jsonl").read_bytes() == (second / "cases.jsonl").read_bytes()


def test_truncation_is_bounded_and_reported_at_the_affected_field(tmp_path):
    session = saved_session()
    raw_run(session, "pytest_run")["stdout"] = "BEGIN_RAW_OUTPUT\n" + "x" * 100_000 + "\nEND_RAW_OUTPUT"
    _, rows, _, _ = prepared(tmp_path, session)
    evidence = rows[0]["evidence"]
    output = pytest_evidence(rows[0])["stdout"]
    assert len(output) < 100_000
    assert "BEGIN_RAW_OUTPUT" in output and "END_RAW_OUTPUT" in output
    assert evidence["truncation"]
    assert any("stdout" in item["path"] for item in evidence["truncation"])
