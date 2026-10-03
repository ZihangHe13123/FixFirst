"""A project's own class must not be diagnosed as a library version problem (review of 0785845, items K1 and K2).

Knowledge entries that match a bare attribute name or a class name cannot be bound to the object's real module, so they are kept in
knowledge/pending_attribution.toml and are not loaded. Each case below is a project class that happens to share a name with such an
entry and then calls a method it does not have: the right diagnosis is a code defect in the project.
"""
from pathlib import Path
import sys
import tomllib

import pytest

from fixfirst import domain
from fixfirst.models import Execution
from fixfirst.service import create_session, scan

CASES = {
    "local_entrypoints": "class EntryPoints:\n    def all(self):\n        return []\n\nEntryPoints().items()\n",
    "local_readfp": "class Report:\n    def read(self):\n        return 'ready'\n\nReport().readfp()\n",
    "local_link_to": "class Account:\n    def link(self, user):\n        return user\n\nAccount().link_to('x')\n",
    "local_is_alive": "class Worker:\n    def is_alive(self):\n        return True\n\nWorker().isAlive()\n",
    "local_engine": "class Engine:\n    def run(self):\n        return True\n\nEngine().execute()\n",
    "local_csr_matrix": "class csr_matrix:\n    pass\n\ncsr_matrix().A\n",
    "local_is_ajax": "class Request:\n    def is_json(self):\n        return True\n\nRequest().is_ajax()\n",
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_local_class_with_a_library_name_is_a_code_defect(tmp_path, name):
    (tmp_path / "main.py").write_text(CASES[name], encoding="utf-8")
    session = create_session(tmp_path, sys.executable, goal="run_project", execution=Execution(entry="main.py"))
    session.use_classifier = False
    scan(session, ["environment", "project", "python_run"])
    issues = [i for i in session.issues if i.tool == "python_run" and i.status == "open"]
    assert issues, name
    assert all(i.diagnosis != "version_incompatibility" for i in issues), [(i.title, i.diagnosis, i.diagnosis_rule) for i in issues]


def test_parked_entries_are_verified_data_that_domain_load_does_not_read():
    knowledge = Path(domain.__file__).parent / "knowledge"
    parked = tomllib.loads((knowledge / "pending_attribution.toml").read_text(encoding="utf-8"))
    enabled = tomllib.loads((knowledge / "domain.toml").read_text(encoding="utf-8"))
    assert len(parked["removed"]) >= 100

    def keys(data):
        return {
            f"api:{e['module']}.{n}" if e["kind"] == "api" else f"{e['kind']}:{n}"
            for e in data["removed"] for n in e["names"]
        }

    assert not keys(parked) & keys(enabled)
    assert not set(parked.get("sources", {})) & set(enabled["sources"])
    known = set(parked.get("sources", {})) | set(enabled["sources"])
    assert all(e["source"] in known for e in parked["removed"])
    index = domain.load()["removed_index"]
    assert not keys(parked) & set(index)
    # what is parked is exactly the unscoped kind: a bare attribute name, or a class name (never a dotted module path) used as the module
    for e in parked["removed"]:
        assert e["kind"] == "attribute" or (e["kind"] == "api" and "." not in e["module"])
