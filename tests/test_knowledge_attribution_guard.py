"""A project's own class must not be diagnosed as a library version problem (review of 0785845, items K1 and K2).

Knowledge entries that name a class (`module = "Engine"`) or a bare attribute only apply to an object whose class really is the named library
class (`owners`, checked by the receiver ownership of src/fixfirst/removal_ownership.py). Each case below is a project class that happens to
share a name with such an entry and then calls a method it does not have: the right diagnosis is a code defect in the project. The entries
whose owners cannot be matched yet stay in knowledge/pending_attribution.toml and are not loaded.
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
    # classes of the entries that carry owners since the receiver ownership exists (scripts/knowledge_verify/verify_owners.py)
    "local_dataframe": "class DataFrame:\n    pass\n\nDataFrame().iteritems\n",
    "local_series": "class Series:\n    pass\n\nSeries().append\n",
    "local_flask": "class Flask:\n    pass\n\nFlask().json_encoder\n",
    "local_click_group": "class Group:\n    pass\n\nGroup().resultcallback\n",
    "local_graph": "class Graph:\n    pass\n\nGraph().node\n",
    "local_session": "class Session:\n    pass\n\nSession().transaction\n",
    "local_http_response": "class HTTPResponse:\n    pass\n\nHTTPResponse().strict\n",
    "local_legend": "class Legend:\n    pass\n\nLegend().legendHandles\n",
    "local_openai": "class OpenAI:\n    pass\n\nOpenAI().edits\n",
    "local_ndarray": "class ndarray:\n    pass\n\nndarray().itemset\n",
    "local_testcase": "class TestCase:\n    pass\n\nTestCase().failUnlessAlmostEqual\n",
    "local_field_info": "class FieldInfo:\n    pass\n\nFieldInfo().required\n",
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
    assert len(parked["removed"]) >= 5

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
