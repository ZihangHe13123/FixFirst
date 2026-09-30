"""Claude's cross-review probes for Codex's round 5 changes (2026-09-30).

Each probe is a small project run with the fixed round 5 environments (built by round5_cases.py):
the current environment and the older one decide the true label (a version change passes on the
older release; an ordinary error fails there too). "expect" was written before any probe ran.
Development material only; not held out, not a gold standard.

  python experiments/core_diagnosis/round5_review_probes.py --runs RUNS --tag TAG [--only NAME ...]

The packaging probes need RUNS/packaging-old/venv (packaging 21.3 and pytest).
"""

import argparse
import json
from pathlib import Path
import shutil

import round5_cases as rc

NUMPY = ("numpy_copy_false/venv", "numpy_copy_false/venv-old")  # numpy 2.2.6, 1.26.4
PYDANTIC = ("pydantic_optional_required/venv", "pydantic_optional_required/venv-old")  # 2.11.9, 1.10.22
DECLARE_NUMPY = {"requirements.txt": "numpy>=1.21\n"}
DECLARE_PYDANTIC = {"requirements.txt": "pydantic>=1.8\n"}
PACKAGING = ("numpy_copy_false/venv", "packaging-old/venv")  # packaging 26.3 (with pytest), 21.3
UV_LOCK = 'version = 1\nrequires-python = ">=3.9"\n\n[[package]]\nname = "numpy"\nversion = "1.26.4"\n' \
          'source = { registry = "https://pypi.org/simple" }\n'

COPY_FALSE = rc.CASES[0]["files"]
OPTIONAL = rc.CASES[1]["files"]
RESHAPE = rc.CASES[5]["files"]
SOLVE_APP = rc.CASES[2]["files"]["app.py"]

PROBES = [
    {"name": "undeclared_copy_false", "focus": "real positive", "env": NUMPY,
     "files": {k: v for k, v in COPY_FALSE.items() if k != "requirements.txt"},
     "expect": "Ideal: the copy=False migration step. Risk: without a declared minimum no documented "
               "behavior is derived (G14/G15), so a beginner project gets the generic step."},
    {"name": "undeclared_optional_required", "focus": "real positive", "env": PYDANTIC,
     "files": {k: v for k, v in OPTIONAL.items() if k != "requirements.txt"},
     "expect": "Same question for Pydantic's Optional field without requirements.txt."},
    {"name": "solve_batch_equals_order", "focus": "solve sizes", "env": NUMPY,
     "files": {**DECLARE_NUMPY, "app.py": SOLVE_APP,
               "test_app.py": "from app import solve_all\n\n\ndef test_solve_all():\n"
                              "    matrices = [[[2, 0], [0, 2]], [[4, 0], [0, 4]]]\n"
                              "    assert solve_all(matrices, [[2, 4], [8, 4]]) == [[1.0, 2.0], [2.0, 1.0]]\n"},
     "expect": "Version change without an exception: with 2 systems of order 2, NumPy 2 broadcasts b as one "
               "matrix and returns another shape, so the test fails on its assertion. The ValueError-based "
               "rule cannot see it; expected a generic assertion step (a known limit, not a false claim)."},
    {"name": "solve_true_mismatch", "focus": "solve sizes", "env": NUMPY,
     "files": {**DECLARE_NUMPY, "app.py": SOLVE_APP,
               "test_app.py": "from app import solve_all\n\n\ndef test_solve_all():\n"
                              "    matrices = [[[2, 0], [0, 2]], [[4, 0], [0, 4]], [[1, 0], [0, 1]]]\n"
                              "    assert solve_all(matrices, [[2, 4, 6], [8, 4, 0], [3, 5, 7]])\n"},
     "expect": "Vectors of length 3 for 2x2 systems fail on NumPy 1.x too: must not be called a version change."},
    {"name": "optional_swapped_valid_key", "focus": "pydantic dynamic input", "env": PYDANTIC,
     "files": {**DECLARE_PYDANTIC,
               "app.py": "from typing import Optional\n\nfrom pydantic import BaseModel\n\n\n"
                         "class Contact(BaseModel):\n    name: str\n    email: Optional[str]\n"
                         "    backup_email: Optional[str] = None\n\n\ndef from_form(form):\n"
                         "    return Contact(name=form[\"name\"], backup_email=form[\"email\"])\n",
               "test_app.py": "from app import from_form\n\n\ndef test_from_form():\n"
                              "    form = {\"name\": \"Ada\", \"email\": \"ada@example.org\"}\n"
                              "    assert from_form(form).email == \"ada@example.org\"\n"},
     "expect": "The value goes to another valid field; Pydantic 1 fails the assertion too, so not a version "
               "change. Risk: every supplied key is a model field, so the Optional rule may fire and advise "
               "= None, which would not make the test pass."},
    {"name": "optional_explicit_required", "focus": "pydantic custom declaration", "env": PYDANTIC,
     "files": {**DECLARE_PYDANTIC,
               "app.py": "from typing import Optional\n\nfrom pydantic import BaseModel, Field\n\n\n"
                         "class Contact(BaseModel):\n    name: str\n    email: Optional[str] = Field(...)\n\n\n"
                         "def load(record):\n    return Contact(**record)\n",
               "test_app.py": OPTIONAL["test_app.py"]},
     "expect": "Field(...) is required in Pydantic 1 too: must not be called a version change."},
    {"name": "optional_alias_input", "focus": "pydantic alias", "env": PYDANTIC,
     "files": {**DECLARE_PYDANTIC,
               "app.py": "from typing import Optional\n\nfrom pydantic import BaseModel, Field\n\n\n"
                         "class Contact(BaseModel):\n    full_name: str = Field(alias=\"name\")\n"
                         "    email: Optional[str]\n\n\ndef load(record):\n    return Contact(**record)\n",
               "test_app.py": "from app import load\n\n\ndef test_load():\n    contact = load({\"name\": \"Ada\"})\n"
                              "    assert contact.full_name == \"Ada\" and contact.email is None\n"},
     "expect": "A real version change, but the supplied key is an alias, not a field name: expected the rule "
               "to stay silent (a missed positive, not a false claim)."},
    {"name": "optional_with_unrelated_validator", "focus": "pydantic custom validation", "env": PYDANTIC,
     "files": {**DECLARE_PYDANTIC,
               "app.py": "from typing import Optional\n\nfrom pydantic import BaseModel, validator\n\n\n"
                         "class Contact(BaseModel):\n    name: str\n    email: Optional[str]\n\n"
                         "    @validator(\"name\")\n    def strip_name(cls, value):\n        return value.strip()\n\n\n"
                         "def load(record):\n    return Contact(**record)\n",
               "test_app.py": OPTIONAL["test_app.py"]},
     "expect": "A real version change; a validator on another field marks the project customized, so the "
               "rule is expected to stay silent (missed positive)."},
    {"name": "lockfile_reshape", "focus": "lock priority", "env": NUMPY,
     "files": {**RESHAPE, "uv.lock": UV_LOCK},
     "expect": "The reshape input error must come first; no step toward the locked 1.26 series."},
    {"name": "lockfile_singular_matrix", "focus": "lock priority", "env": NUMPY,
     "files": {**DECLARE_NUMPY, "uv.lock": UV_LOCK,
               "app.py": "import numpy as np\n\n\ndef scale_matrix(sx, sy):\n    return [[sx, sy], [sx, sy]]\n\n\n"
                         "def inverse_scale(sx, sy):\n"
                         "    return np.linalg.inv(np.asarray(scale_matrix(sx, sy), dtype=float)).tolist()\n",
               "test_app.py": "from app import inverse_scale\n\n\ndef test_inverse_scale():\n"
                              "    assert inverse_scale(2, 4) == [[0.5, 0.0], [0.0, 0.25]]\n"},
     "expect": "A singular matrix built by the project fails on 1.26 too. Risk: an input error outside the "
               "known list plus an older lock still leads H06 to the locked series."},
    {"name": "singular_matrix_no_lock", "focus": "lock priority (control)", "env": NUMPY,
     "files": {**DECLARE_NUMPY,
               "app.py": "import numpy as np\n\n\ndef scale_matrix(sx, sy):\n    return [[sx, sy], [sx, sy]]\n\n\n"
                         "def inverse_scale(sx, sy):\n"
                         "    return np.linalg.inv(np.asarray(scale_matrix(sx, sy), dtype=float)).tolist()\n",
               "test_app.py": "from app import inverse_scale\n\n\ndef test_inverse_scale():\n"
                              "    assert inverse_scale(2, 4) == [[0.5, 0.0], [0.0, 0.25]]\n"},
     "expect": "Same failure without a lock file: nothing should claim a version change."},
    {"name": "requirements_pin_reshape", "focus": "pin priority", "env": NUMPY,
     "files": {**{k: v for k, v in RESHAPE.items() if k != "requirements.txt"},
               "requirements.txt": "numpy==1.26.4\n"},
     "expect": "The environment violates the pin (a true fact), but the reshape failure is still an input "
               "error: record which comes first and whether the failure is called a version change."},
    {"name": "local_class_named_ndarray", "focus": "type provenance", "env": NUMPY,
     "files": {**DECLARE_NUMPY,
               "app.py": "import numpy as np\n\n\nclass ndarray:\n    \"\"\"A project container named like NumPy's.\"\"\"\n\n"
                         "    def __init__(self, values):\n        self.values = np.asarray(values)\n\n\n"
                         "def spread(values):\n    return int(ndarray(values).ptp())\n",
               "test_app.py": "from app import spread\n\n\ndef test_spread():\n    assert spread([1, 5, 3]) == 4\n"},
     "expect": "The project's own class lacks ptp (fails on 1.26 too): the text 'ndarray' object must not "
               "borrow NumPy's ptp removal."},
    {"name": "ndarray_subclass_ptp", "focus": "type provenance", "env": NUMPY,
     "files": {**DECLARE_NUMPY,
               "app.py": "import numpy as np\n\n\nclass Signal(np.ndarray):\n    pass\n\n\n"
                         "def spread(values):\n    return float(np.asarray(values).view(Signal).ptp())\n",
               "test_app.py": "from app import spread\n\n\ndef test_spread():\n    assert spread([1, 5, 3]) == 4.0\n"},
     "expect": "A real version change through an inherited method; the registered type is the project's "
               "subclass, so a missed positive is expected (not a false claim)."},
    {"name": "newbyteorder_real", "focus": "real positive", "env": NUMPY,
     "files": {**DECLARE_NUMPY,
               "app.py": "import numpy as np\n\n\ndef big_endian_view(values):\n"
                         "    array = np.asarray(values, dtype=\"<u2\")\n"
                         "    return array.newbyteorder(\">\").tolist()\n",
               "test_app.py": "from app import big_endian_view\n\n\ndef test_view():\n"
                              "    assert big_endian_view([1, 2]) == [256, 512]\n"},
     "expect": "A real NumPy 2 removal with a documented replacement: expected the view(dtype.newbyteorder) step."},
    {"name": "packaging_parse_legacy_label", "focus": "real positive", "env": PACKAGING,
     "files": {"requirements.txt": "packaging>=20\n",
               "app.py": "from packaging.version import parse\n\n\ndef newest(labels):\n"
                         "    return str(max(parse(label) for label in labels))\n",
               "test_app.py": "from app import newest\n\n\ndef test_newest():\n"
                              "    assert newest([\"1.0\", \"nightly\", \"2.0\"]) == \"2.0\"\n"},
     "expect": "packaging 22 removed LegacyVersion: expected the documented change (H10), not an input error."},
    {"name": "packaging_version_strict", "focus": "real positive (counterexample)", "env": PACKAGING,
     "files": {"requirements.txt": "packaging>=20\n",
               "app.py": "from packaging.version import Version\n\n\ndef newest(labels):\n"
                         "    return str(max(Version(label) for label in labels))\n",
               "test_app.py": "from app import newest\n\n\ndef test_newest():\n"
                              "    assert newest([\"1.0\", \"nightly\", \"2.0\"]) == \"2.0\"\n"},
     "expect": "Version was always strict (fails on 21.3 too): expected the input contract (H12), not a version change."},
]


# D1 review (4bded78): which receiver loads each Python compiles `receiver.ptp()` to. Predicted from
# dis before running: 3.13 fuses a store and the next load (STORE_FAST_LOAD_FAST) and two loads
# (LOAD_FAST_LOAD_FAST); 3.14 also reads locals with LOAD_FAST_BORROW. NumPy 2.3.5 (for 3.14) still
# raises the removal message without AttributeError.name/obj, like 2.2.6.
D1_ENVS = {"3.12": ("numpy_copy_false/venv", "numpy_copy_false/venv-old"),
           "3.13": ("d1-py313/venv", "numpy_copy_false/venv-old"),   # numpy 2.2.6
           "3.14": ("d1-py314/venv", "numpy_copy_false/venv-old")}   # numpy 2.3.5
D1_PATTERNS = {
    "param": ("def spread(values):\n    return int(values.ptp())\n",
              "np.array([1, 5, 3])", {"3.12": "found", "3.13": "found", "3.14": "missed (LOAD_FAST_BORROW)"}),
    "store_then_load": ("def spread(values):\n    array = np.asarray(values)\n    return int(array.ptp())\n",
                        "[1, 5, 3]", {"3.12": "found", "3.13": "missed (STORE_FAST_LOAD_FAST)",
                                      "3.14": "missed (STORE_FAST_LOAD_FAST)"}),
    "global": ("DATA = np.array([1, 5, 3])\n\n\ndef spread(values):\n    return int(DATA.ptp())\n",
               "None", {"3.12": "found", "3.13": "found", "3.14": "found"}),
    "closure": ("def spread(values):\n    data = np.asarray(values)\n\n    def inner():\n"
                "        return int(data.ptp())\n    return inner()\n",
                "[1, 5, 3]", {"3.12": "found", "3.13": "found", "3.14": "found"}),
    "second_of_two_locals": ("def spread(values, floor=0):\n    return max(floor, int(values.ptp()))\n",
                             "np.array([1, 5, 3])", {"3.12": "found", "3.13": "missed (LOAD_FAST_LOAD_FAST)",
                                                     "3.14": "missed (LOAD_FAST_BORROW_LOAD_FAST_BORROW)"}),
    # Added after the first D1 run showed that wrapping in int(...) keeps the loads apart: these two
    # put the receiver load right after a store or another local load, which 3.13 fuses.
    "fused_store_load": ("def spread(values):\n    array = np.asarray(values)\n    return array.ptp()\n",
                         "[1, 5, 3]", {"3.12": "found", "3.13": "missed (STORE_FAST_LOAD_FAST)",
                                       "3.14": "missed (STORE_FAST_LOAD_FAST)"}),
    "fused_two_locals": ("def spread(values, floor=0):\n    return max(floor, values.ptp())\n",
                         "np.array([1, 5, 3])", {"3.12": "found", "3.13": "missed (LOAD_FAST_LOAD_FAST)",
                                                 "3.14": "missed (LOAD_FAST_BORROW_LOAD_FAST_BORROW)"}),
    "attribute_chain": ("class Holder:\n    def __init__(self, values):\n        self.data = np.asarray(values)\n\n\n"
                        "def spread(values):\n    return int(Holder(values).data.ptp())\n",
                        "[1, 5, 3]", {"3.12": "not inferred (by design)", "3.13": "not inferred (by design)",
                                      "3.14": "not inferred (by design)"}),
}
for _version, _env in D1_ENVS.items():
    for _pattern, (_source, _argument, _expected) in D1_PATTERNS.items():
        PROBES.append({
            "name": f"d1_{_pattern}_py{_version.replace('.', '')}", "focus": "D1 receiver", "env": _env,
            "files": {**DECLARE_NUMPY, "app.py": "import numpy as np\n\n\n" + _source,
                      "test_app.py": "import numpy as np\n\nfrom app import spread\n\n\ndef test_spread():\n"
                                     f"    assert spread({_argument}) == 4\n"},
            "expect": f"Python {_version}: removed ndarray.ptp through this receiver is {_expected[_version]}."})

# SQLAlchemy review (ba52e22): the eager result iterator of 1.4. Expectations written before running.
SQLA = ("sqla20/venv", "sqla13/venv")  # SQLAlchemy 2.0.44 and 1.3.24, with pytest
SQLA_TEST = ("from sqlalchemy import create_engine\n\nfrom app import {name}\n\n\ndef test_{name}():\n"
             "    with create_engine(\"sqlite://\").connect() as connection:\n{body}")
SQLA_PROBES = {
    "sqla_lazy_generator": (
        "def query(connection, sql):\n    cursor = connection.execute(text(sql))\n"
        "    rows = (tuple(row) for row in cursor)\n    return rows\n",
        "query", "        query(connection, \"CREATE TABLE t (x INTEGER)\")\n"
                 "        assert list(query(connection, \"SELECT 1\")) == [(1,)]\n",
        "Real 1.4 change (1.3 builds the generator lazily and never consumes it): expected the eager "
        "iterator history and the returns_rows step."),
    "sqla_generator_then_consumed": (
        "def query_all(connection, sql):\n    cursor = connection.execute(text(sql))\n"
        "    rows = (tuple(row) for row in cursor)\n    return list(rows)\n",
        "query_all", "        assert query_all(connection, \"CREATE TABLE t (x INTEGER)\") == []\n",
        "The generator is consumed in the same function, so 1.3 fails too (at list): not a version change. "
        "Risk: the error line is the generator construction, so the history may still be borrowed."),
    "sqla_list_consumption": (
        "def query_all(connection, sql):\n    cursor = connection.execute(text(sql))\n    return list(cursor)\n",
        "query_all", "        assert query_all(connection, \"CREATE TABLE t (x INTEGER)\") == []\n",
        "Consumption fails on 1.3 too: must not be called the 1.4 change."),
    "sqla_fetchall": (
        "def query_all(connection, sql):\n    cursor = connection.execute(text(sql))\n    return cursor.fetchall()\n",
        "query_all", "        assert query_all(connection, \"CREATE TABLE t (x INTEGER)\") == []\n",
        "fetchall fails on 1.3 too: must not be called the 1.4 change."),
    "sqla_closed_then_generator": (
        "def query(connection, sql):\n    cursor = connection.execute(text(sql))\n    cursor.close()\n"
        "    rows = (tuple(row) for row in cursor)\n    return rows\n",
        "query", "        assert list(query(connection, \"SELECT 1\")) == [(1,)]\n",
        "A result closed on purpose fails on 1.3 too (at consumption): must not be called the 1.4 change."),
}
for _name, (_source, _function, _body, _expect) in SQLA_PROBES.items():
    PROBES.append({"name": _name, "focus": "sqlalchemy history", "env": SQLA,
                   "files": {"requirements.txt": "SQLAlchemy>=1.3\n",
                             "app.py": "from sqlalchemy import text\n\n\n" + _source,
                             "test_app.py": SQLA_TEST.format(name=_function, body=_body)},
                   "expect": _expect})

# a56a621 review: consumption forms around generator_consumption. Expectations written before running.
GENERATOR = "    cursor = connection.execute(text(sql))\n    rows = (tuple(row) for row in cursor)\n"
DDL_EMPTY = "        assert {name}(connection, \"CREATE TABLE t (x INTEGER)\") == {empty}\n"
SQLA_CONSUMERS = {
    "sqla_alias_then_list": ("    batch = rows\n    return list(batch)\n", "[]",
                             "Alias then list: 1.3 fails too; the alias is recorded, so no version change expected."),
    "sqla_for_loop_consumption": ("    found = []\n    for row in rows:\n        found.append(row)\n    return found\n", "[]",
                                  "A for loop consumes it: 1.3 fails too; no version change expected."),
    "sqla_star_unpacking": ("    return [*rows]\n", "[]",
                            "[*rows] consumes it (1.3 fails too). Predicted: not a listed consumer, so the "
                            "1.4 history may still be borrowed."),
    "sqla_join_consumption": ("    return \"\\n\".join(\",\".join(map(str, row)) for row in rows)\n", "\"\"",
                              "join over a generator of rows consumes it (1.3 fails too). Predicted: not recognised."),
    "sqla_nested_consumer": ("    def materialise():\n        return list(rows)\n    return materialise()\n", "[]",
                             "Consumed in a nested function (1.3 fails too). Predicted: nested bodies are not "
                             "searched, so not recognised."),
}
for _name, (_tail, _empty, _expect) in SQLA_CONSUMERS.items():
    PROBES.append({"name": _name, "focus": "generator consumption", "env": SQLA,
                   "files": {"requirements.txt": "SQLAlchemy>=1.3\n",
                             "app.py": "from sqlalchemy import text\n\n\ndef query_all(connection, sql):\n"
                                       + GENERATOR + _tail,
                             "test_app.py": SQLA_TEST.format(name="query_all",
                                                             body=DDL_EMPTY.format(name="query_all", empty=_empty))},
                   "expect": _expect})
PROBES.append({"name": "sqla_generator_in_lambda", "focus": "generator consumption", "env": SQLA,
               "files": {"requirements.txt": "SQLAlchemy>=1.3\n",
                         "app.py": "from sqlalchemy import text\n\nrows_of = lambda cursor: (tuple(row) for row in cursor)\n\n\n"
                                   "def query(connection, sql):\n    return rows_of(connection.execute(text(sql)))\n",
                         "test_app.py": SQLA_TEST.format(name="query", body=
                             "        query(connection, \"CREATE TABLE t (x INTEGER)\")\n"
                             "        assert list(query(connection, \"SELECT 1\")) == [(1,)]\n")},
               "expect": "A real 1.4 change, but the generator is built in a lambda (no recorded context): "
                         "expected no version inference (a missed positive, not a false claim)."})
PROBES.append({"name": "sqla_wrapped_not_consumed", "focus": "generator consumption", "env": SQLA,
               "files": {"requirements.txt": "SQLAlchemy>=1.3\n",
                         "app.py": "from sqlalchemy import text\n\n\nclass Rows:\n    def __init__(self, source):\n"
                                   "        self._source = source\n\n    def all(self):\n        return list(self._source)\n\n\n"
                                   "def query(connection, sql):\n" + GENERATOR + "    return Rows(rows)\n",
                         "test_app.py": SQLA_TEST.format(name="query", body=
                             "        query(connection, \"CREATE TABLE t (x INTEGER)\")\n"
                             "        assert query(connection, \"SELECT 1\").all() == [(1,)]\n")},
               "expect": "records-like: the generator is handed to a wrapper and not consumed here (1.3 passes): "
                         "expected the 1.4 history and the returns_rows step."})

def run(runs: Path, tag: str, only=()) -> None:
    from fixfirst.evidence import issue_evidence
    from fixfirst.service import create_session, scan
    from fixfirst.workspace import build_view

    base = runs / f"review-{tag}"
    base.mkdir()
    record = {"implementation": rc.implementation(), "probes": []}
    for probe in PROBES:
        if only and probe["name"] not in only:
            continue
        folder = base / probe["name"]
        rc.write_project({"files": probe["files"]}, folder / "project")
        current, old = (runs / p for p in probe["env"])
        results = {}
        for which, venv in (("current", current), ("old", old)):
            work = folder / f"pytest-{which}"
            shutil.copytree(folder / "project", work)
            results[which] = rc.pytest(work, venv)
        truth = ("no failure" if results["current"]["exit_code"] == 0 else
                 "version change" if results["old"]["exit_code"] == 0 else "fails on the older release too")
        work = folder / "diagnose"
        shutil.copytree(folder / "project", work)
        session = create_session(work, current / "bin/python", goal="pass_tests")
        scan(session)
        view = build_view(session)
        issues = [i for i in session.issues if i.status in ("open", "awaiting_verification") and i.tool != "ruff"]
        row = {"name": probe["name"], "focus": probe["focus"], "expect": probe["expect"], "truth": truth,
               "old_tail": results["old"]["output"][-300:], "current_tail": results["current"]["output"][-500:],
               "status": view["status"].get("kind"),
               "issues": [{"tool": i.tool, "diagnosis": i.diagnosis, "rule": i.diagnosis_rule,
                           "source": i.diagnosis_source, "tree": i.prediction,
                           "evidence": {k: v for k, v in issue_evidence(session, i).items()
                                        if k in ("exception", "raised_in", "where", "library", "attributes",
                                                 "library_calls", "validation_errors")}}
                          for i in issues],
               "steps": [{k: s.get(k) for k in ("title", "explanation", "command", "where", "rules")}
                         for s in view["steps"][:2]]}
        record["probes"].append(row)
        first = row["issues"][0] if row["issues"] else {}
        print(json.dumps({"name": row["name"], "truth": truth, "diagnosis": first.get("diagnosis"),
                          "rule": first.get("rule"), "step": row["steps"][0]["title"] if row["steps"] else None}),
              flush=True)
    (runs / f"review-{tag}.json").write_text(
        json.dumps(record, indent=1, ensure_ascii=False).replace(str(runs), "<runs>") + "\n")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=Path, required=True, help="the RUNS folder of round5_cases.py build")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--only", nargs="+", default=(), help="run these probes only")
    args = parser.parse_args(argv)
    run(args.runs.resolve(), args.tag, args.only)


if __name__ == "__main__":
    main()
