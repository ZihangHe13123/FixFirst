"""The shipped knowledge base must still match the record of its last execution-based verification (scripts/knowledge_verify).

These tests run offline. They do not re-run the checks (that needs the network and several interpreters; see the README there): they fail
when a verified block is edited, added or dropped without verifying again, when the record is not a complete pass, or when a local path leaks into it.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 (the verification programs themselves need 3.11)
    import tomli as tomllib

import pytest

from fixfirst import domain

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "scripts" / "knowledge_verify"
KNOWLEDGE = ROOT / "src" / "fixfirst" / "knowledge"
RECEIPT = FOLDER / "receipts" / "knowledge-receipt-20261003.json"
# the knowledge base of the product right before the verified candidates were merged into it (git show c0bd25e:src/fixfirst/knowledge/domain.toml):
# the explicit base of the loader smoke test of the record, and the reference of everything that the candidates do not define
BASELINE = FOLDER / "baseline" / "domain-c0bd25e.toml"
CANDIDATE_FILES = ("candidates.toml", "candidates-optional.toml", "candidates-parked.toml")
pytestmark = pytest.mark.skipif(not RECEIPT.exists(), reason="the verification record is not installed")

# older entries that the audit could not confirm: four modules that cannot be built on the machine that ran it, and one contradicted claim
AUDIT_EXCEPTIONS = {
    "audit-module-msilib", "audit-module-nis", "audit-module-ossaudiodev", "audit-module-spwd",
    "audit-flask-sqlalchemy-Model-claim-3.0",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def key(entry: dict, name: str) -> str:
    return f"api:{entry['module']}.{name}" if entry["kind"] == "api" else f"{entry['kind']}:{name}"


@pytest.fixture(scope="module")
def receipt():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_record_is_a_complete_pass(receipt):
    summary = receipt["summary"]
    assert summary["total_failures"] == 0 and summary["probes_not_checked"] == 0
    assert summary["candidate_checks"] == summary["candidate_checks_passed"] == len(receipt["checks"]) >= 1200
    assert summary["supporting_probes"] == summary["supporting_probes_passed"] == len(receipt["supports"]) >= 290
    assert {c["status"] for c in receipt["checks"]} == {"pass"}
    assert {s["status"] for s in receipt["supports"]} == {"pass"}
    assert not receipt["cross_check_problems"]
    failed_audit = {c["id"] for c in receipt["audit_checks"] if c["status"] != "pass"}
    assert failed_audit == AUDIT_EXCEPTIONS
    for item in receipt["checks"] + receipt["supports"]:
        assert item["code_sha256"] == hashlib.sha256(item["code"].encode("utf-8")).hexdigest()


def test_the_record_is_redacted(receipt):
    text = RECEIPT.read_text(encoding="utf-8")
    assert not re.search(r"/Users/|/private/|/var/folders|/home/|[A-Za-z]:\\\\Users", text)


def test_the_record_belongs_to_the_files_in_this_repository(receipt):
    for name, expected in receipt["files"].items():
        assert digest(FOLDER / "candidates" / name) == expected, name
    assert digest(FOLDER / "verify.py") == receipt["tool"]["verify_py_sha256"]


def blocks(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_every_enabled_block_is_a_verified_block():
    kb = domain.load()
    for name in ("candidates.toml", "candidates-optional.toml"):
        data = blocks(FOLDER / "candidates" / name)
        for entry in data.get("removed", []):
            for n in entry["names"]:
                shipped = kb["removed_index"].get(key(entry, n))
                assert shipped is not None, (name, key(entry, n))
                assert {k: v for k, v in shipped.items() if k not in ("name", "id")} == entry, key(entry, n)
        for entry in data.get("deprecated", []):
            for n in entry["names"]:
                shipped = kb["deprecated_index"].get(f"api:{entry['module']}.{n}")
                assert shipped is not None and {k: v for k, v in shipped.items() if k not in ("name", "id")} == entry


def test_every_verified_key_is_covered_by_a_passing_check(receipt):
    covered = {k for c in receipt["checks"] if c["status"] == "pass" for k in c["covers"]}
    for name in ("candidates.toml", "candidates-optional.toml", "candidates-parked.toml"):
        for entry in blocks(FOLDER / "candidates" / name).get("removed", []):
            for n in entry["names"]:
                assert key(entry, n) in covered, (name, key(entry, n))


def test_the_parked_file_in_the_package_holds_verified_candidate_blocks_only():
    """What is still parked is a subset of the verified candidates, unchanged; the rest was enabled or merged (test_knowledge_owners.py)."""
    shipped = blocks(KNOWLEDGE / "pending_attribution.toml")
    verified = blocks(FOLDER / "candidates" / "candidates-parked.toml")
    candidates = {key(e, n): e for e in verified["removed"] for n in e["names"]}
    for entry in shipped["removed"]:
        for n in entry["names"]:
            assert candidates[key(entry, n)] == entry, key(entry, n)
    for sid, source in shipped.get("sources", {}).items():
        assert verified["sources"][sid] == source


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
def test_verify_py_starts_and_documents_its_options():
    result = subprocess.run([sys.executable, str(FOLDER / "verify.py"), "--help"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-400:]
    assert "--receipts" in result.stdout and "--candidates" in result.stdout


# ---------------------------------------------------------------------------------------------------------------------------------------
# what the candidates and the baseline define must still be what is shipped (O-R3): unmaintained entries field by field, and the title/url
# of the sources the entries cite
# ---------------------------------------------------------------------------------------------------------------------------------------
def candidate_data() -> list:
    return [blocks(FOLDER / "candidates" / name) for name in CANDIDATE_FILES]


def compare_unmaintained(shipped: list, candidates: list, baseline: list) -> list:
    """An entry that a candidate file or the baseline defines must be shipped exactly as defined (every field); what neither defines is free."""
    shipped_by = {domain.dist_id(e["distribution"]): e for e in shipped}
    problems = []
    for origin, entries in (("baseline", baseline), ("candidates", candidates)):          # a candidate overrides the baseline
        for entry in entries:
            dist = domain.dist_id(entry["distribution"])
            if shipped_by.get(dist) != entry:
                problems.append(f"unmaintained {dist} differs from its {origin} definition: shipped {shipped_by.get(dist)} != {entry}")
    return problems


def compare_sources(shipped: dict, candidates: dict, baseline: dict, cited: set) -> list:
    """The sources that the enabled candidate entries cite are shipped, and every shipped source that a candidate file or the baseline defines
    is the same title and url (all fields); sources that neither defines were added and reviewed elsewhere and are not governed here."""
    problems = [f"source {sid} is cited by an enabled verified entry but is not shipped" for sid in sorted(cited) if sid not in shipped]
    for sid, source in shipped.items():
        verified = candidates.get(sid, baseline.get(sid))
        if verified is not None and verified != source:
            problems.append(f"source {sid} differs from its {'candidate' if sid in candidates else 'baseline'} definition: {source} != {verified}")
    return problems


def merged_sources(files: list) -> dict:
    sources = {}
    for data in files:
        for sid, source in data.get("sources", {}).items():
            assert sources.setdefault(sid, source) == source, f"{sid} is defined differently by two candidate files"
    return sources


def enabled_citations(kb: dict) -> tuple:
    """(sources, unmaintained entries) that the ENABLED entries of the candidate files cite, as the product serves them."""
    cited = set()
    for data in candidate_data():
        for entry in data.get("removed", []):
            if any(key(entry, n) in kb["removed_index"] for n in entry["names"]):
                cited.add(entry["source"])
        for entry in data.get("deprecated", []):
            if any(f"api:{entry['module']}.{n}" in kb["deprecated_index"] for n in entry["names"]):
                cited.add(entry["source"])
        for entry in data.get("unmaintained", []):
            cited.add(entry["source"])
    return cited


def test_enabled_unmaintained_entries_are_the_verified_ones():
    kb = domain.load()
    candidates = [e for data in candidate_data() for e in data.get("unmaintained", [])]
    baseline = blocks(BASELINE).get("unmaintained", [])
    assert candidates and baseline
    assert compare_unmaintained(list(kb["unmaintained_index"].values()), candidates, baseline) == []
    # every entry the candidates verified is shipped (a dropped entry would not be seen by the comparison of the fields)
    assert {domain.dist_id(e["distribution"]) for e in candidates} <= set(kb["unmaintained_index"])


def test_the_title_and_url_of_enabled_sources_are_the_verified_ones():
    kb = domain.load()
    candidates = merged_sources(candidate_data())
    baseline = blocks(BASELINE).get("sources", {})
    assert not set(candidates) & set(baseline)      # the baseline plus the candidates is a valid knowledge base (no source is defined twice)
    cited = enabled_citations(kb)
    assert len(cited) > 100
    assert compare_sources(kb["sources"], candidates, baseline, cited) == []


def test_changing_an_unmaintained_field_or_a_source_is_detected():
    """The mutations of the independent review of 13e30e0: both used to leave every test of this file green."""
    kb = domain.load()
    candidates = [e for data in candidate_data() for e in data.get("unmaintained", [])]
    baseline = blocks(BASELINE).get("unmaintained", [])
    shipped = copy.deepcopy(list(kb["unmaintained_index"].values()))
    for index in range(len(shipped)):
        for field, value in (("last", "999.0"), ("replacement", "REVIEW MUTATION: wrong advice"), ("source", "somewhere-else")):
            changed = copy.deepcopy(shipped)
            changed[index][field] = value
            assert compare_unmaintained(changed, candidates, baseline), (shipped[index]["distribution"], field)
    assert compare_unmaintained(shipped[:-1], candidates, baseline)              # an entry that was dropped
    sources = merged_sources(candidate_data())
    old = blocks(BASELINE).get("sources", {})
    cited = enabled_citations(kb)
    for label, pool in (("candidate", sources), ("baseline", old)):
        sid = sorted(pool)[0]
        for field in ("url", "title"):
            changed = copy.deepcopy(kb["sources"])
            changed[sid][field] = "https://example.invalid/review-mutation"
            assert compare_sources(changed, sources, old, cited), (label, sid, field)
    changed = {k: v for k, v in kb["sources"].items() if k != sorted(cited)[0]}
    assert compare_sources(changed, sources, old, cited)                        # a cited source that is no longer shipped


def test_the_baseline_is_the_one_the_record_was_made_with(receipt):
    """The record says which knowledge base the candidates were merged into for the loader smoke test, and what that run found."""
    assert digest(BASELINE) == receipt["domain_toml_sha256"]
    smoke = receipt["smoke"]
    assert smoke["mode"] == "baseline" and smoke["problems"] == []
    assert smoke["engine_ok"] == smoke["engine_total"] >= 1700
    baseline = blocks(BASELINE)
    verified = {key(e, n) for data in candidate_data() for e in data.get("removed", []) for n in e["names"]}
    assert smoke["removed_index"] == len({key(e, n) for e in baseline.get("removed", []) for n in e["names"]} | verified)


# ---------------------------------------------------------------------------------------------------------------------------------------
# the loader smoke test of verify.py builds its knowledge base from the explicit baseline (O-R2)
# ---------------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def verify_module():
    if sys.version_info < (3, 11):
        pytest.skip("verify.py needs Python 3.11 (tomllib)")
    spec = importlib.util.spec_from_file_location("verify_py_for_tests", FOLDER / "verify.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def candidate_text() -> str:
    return "\n".join((FOLDER / "candidates" / name).read_text(encoding="utf-8") for name in CANDIDATE_FILES)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
def test_the_loader_smoke_builds_its_copy_from_the_explicit_baseline(verify_module, tmp_path):
    """The copy of the product's knowledge base already holds the candidates. Appending them to it again defined every source twice (TOMLDecodeError)
    and the run stopped only after the checks; with --domain the copy is the baseline plus the candidates."""
    text = candidate_text()
    cand = tomllib.loads(text)
    kb = tmp_path / "domain.toml"
    shutil.copyfile(KNOWLEDGE / "domain.toml", kb)
    assert verify_module.merge_candidates_into_copy(str(kb), str(BASELINE), text, cand) == "baseline"
    made = kb.read_text(encoding="utf-8")
    assert made == BASELINE.read_text(encoding="utf-8") + "\n\n" + text
    assert set(verify_module.candidate_keys(cand)) <= set(verify_module.candidate_keys(tomllib.loads(made)))      # it parses, every candidate is in it
    # the shape that the review reproduced: the shipped copy plus candidates is not a TOML document
    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads((KNOWLEDGE / "domain.toml").read_text(encoding="utf-8") + "\n\n" + text)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
def test_without_a_baseline_the_loader_smoke_never_defines_a_source_twice(verify_module, tmp_path):
    text = candidate_text()
    cand = tomllib.loads(text)
    baseline = BASELINE.read_text(encoding="utf-8")
    full = tmp_path / "full.toml"                    # a knowledge base that holds every candidate: nothing is appended again
    full.write_text(baseline + "\n\n" + text, encoding="utf-8")
    assert verify_module.merge_candidates_into_copy(str(full), None, text, cand) == "shipped"
    assert full.read_text(encoding="utf-8") == baseline + "\n\n" + text
    plain = tmp_path / "plain.toml"                  # one that holds none of them: they are appended
    plain.write_text(baseline, encoding="utf-8")
    assert verify_module.merge_candidates_into_copy(str(plain), None, text, cand) == "shipped+candidates"
    tomllib.loads(plain.read_text(encoding="utf-8"))
    for name, content in (("first-file", baseline + "\n\n" + (FOLDER / "candidates" / CANDIDATE_FILES[0]).read_text(encoding="utf-8")),
                          ("product", (KNOWLEDGE / "domain.toml").read_text(encoding="utf-8"))):
        partial = tmp_path / (name + ".toml")        # one that holds some of them (the product holds the enabled ones): an error that names the remedy
        partial.write_text(content, encoding="utf-8")
        with pytest.raises(RuntimeError, match="only some of the candidates.*--domain"):
            verify_module.merge_candidates_into_copy(str(partial), None, text, cand)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
def test_the_loader_smoke_runs_the_real_loader_and_engine_on_the_baseline_plus_the_candidates(verify_module, tmp_path):
    text = candidate_text()
    cand = tomllib.loads(text)
    workspace = SimpleNamespace(base=str(tmp_path), neutral=str(tmp_path), env_vars=os.environ.copy(), python_for=lambda env: sys.executable)
    result = verify_module.loader_smoke(workspace, str(ROOT / "src"), str(BASELINE), text, cand)
    assert result["problems"] == [], result["problems"][:3]
    assert result["mode"] == "baseline"
    assert result["engine_ok"] == result["engine_total"] >= 1700
    assert result["removed_index"] >= 1800 and result["unmaintained_index"] == 3
