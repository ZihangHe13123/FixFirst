"""The owners of the shipped removal knowledge must still match the record of their last execution-based verification
(scripts/knowledge_verify/verify_owners.py).

A removal block with `owners` is applied only to an object whose class is one of the named library classes, so `owners` is a claim about a
real class. The verification builds a real object of each class in the releases that prove the removal, asks the product's own receiver
identity code which classes it has, and lets FixFirst itself diagnose a script that ends in the missing attribute (and a project class with
the same name). These tests run offline: they do not repeat that (it needs the network and many interpreters, see the README there); they
fail when a block with owners is edited, added or dropped without verifying again, when the receiver-identity code of the product changed,
or when the record is not a complete pass.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tomllib

import pytest

from fixfirst import domain

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "scripts" / "knowledge_verify"
KNOWLEDGE = ROOT / "src" / "fixfirst" / "knowledge"
RECEIPT = FOLDER / "receipts" / "owners-receipt-20261003.json"
pytestmark = pytest.mark.skipif(not RECEIPT.exists(), reason="the owners verification record is not installed")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def key(entry: dict, name: str) -> str:
    return f"api:{entry['module']}.{name}" if entry["kind"] == "api" else f"{entry['kind']}:{name}"


def block_sha256(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def receipt():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def verifier():
    spec = importlib.util.spec_from_file_location("verify_owners_for_tests", FOLDER / "verify_owners.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shipped_blocks_with_owners() -> list:
    return [e for e in toml(KNOWLEDGE / "domain.toml")["removed"] if e.get("owners")]


def test_the_record_is_a_complete_pass(receipt):
    summary = receipt["summary"]
    assert summary["e2e"] is True and summary["failed"] == 0
    assert summary["keys"] == summary["passed"] == len(receipt["results"]) >= 100
    assert {r["status"] for r in receipt["results"]} == {"pass"}
    assert all(not r["problems"] for r in receipt["results"])
    for result in receipt["results"]:
        recipe = "\n@@\n".join([result["recipe"], *result["extra_receivers"]])
        assert result["recipe_sha256"] == hashlib.sha256(recipe.encode("utf-8")).hexdigest()
        assert all(extra["removal_owner"] == [result["key"]] for extra in result["product"]["extra"])   # every further receiver too
        assert result["product"]["product"]["removal_owner"] == [result["key"]]       # exactly this entry, no overlapping one
        assert not result["product"]["twin"]["removal_owner"]                          # a project class of the same name is not authorized


def test_the_record_is_redacted():
    assert not re.search(r"/Users/|/private/|/var/folders|/home/|[A-Za-z]:\\\\Users", RECEIPT.read_text(encoding="utf-8"))


def test_the_record_belongs_to_the_tool_and_to_the_product_code_it_asked(receipt, verifier):
    tool = receipt["tool"]
    assert digest(FOLDER / "verify_owners.py") == tool["verify_owners_py_sha256"]
    assert digest(FOLDER / "owners" / "recipes.toml") == tool["recipes_sha256"]
    # owners are claims about receiver identities as the probe computes them: a change of that code needs a new run
    assert verifier.identity_functions_sha256(str(ROOT / "src" / "fixfirst" / "_runtime_evidence.py")) == tool["identity_functions_sha256"]


def test_every_shipped_block_with_owners_has_a_passing_record(receipt):
    by_key = {r["key"]: r for r in receipt["results"]}
    for entry in shipped_blocks_with_owners():
        for name in entry["names"]:
            result = by_key.get(key(entry, name))
            assert result is not None, f"{key(entry, name)} has owners but was not verified"
            assert result["block_sha256"] == block_sha256(entry), f"{key(entry, name)} was edited after it was verified"
            assert result["owners"] == entry["owners"]


def test_every_verified_key_is_still_shipped_with_the_verified_block(receipt):
    shipped = {key(e, n): e for e in shipped_blocks_with_owners() for n in e["names"]}
    assert set(shipped) == {r["key"] for r in receipt["results"]}


def test_owners_are_qualified_library_paths_of_the_blocks_distribution():
    for entry in shipped_blocks_with_owners():
        assert entry["kind"] in ("api", "attribute")
        assert entry["owners"] == sorted(set(entry["owners"])) or len(entry["owners"]) < 2
        for owner in entry["owners"]:
            assert "." in owner and all(part.isidentifier() for part in owner.split(".")), owner
            assert owner.split(".")[0] not in ("builtins", "__main__"), owner


def test_every_parked_candidate_has_exactly_one_disposition():
    """enabled with owners (domain.toml), still parked (pending_attribution.toml) or merged into an enabled entry (dispositions.toml)."""
    candidates = toml(FOLDER / "candidates" / "candidates-parked.toml")["removed"]
    keys = {key(e, n) for e in candidates for n in e["names"]}
    enabled = set(domain.load()["removed_index"])
    parked = {key(e, n) for e in toml(KNOWLEDGE / "pending_attribution.toml")["removed"] for n in e["names"]}
    dispositions = toml(FOLDER / "owners" / "dispositions.toml")
    merged = {k: group["why"] for group in dispositions.get("merged", []) for k in group["keys"]}
    for group in dispositions.get("merged", []):
        assert group["covered_by"] and set(group["covered_by"]) <= enabled, group["covered_by"]
        assert group["why"].strip()
    for k in keys:
        states = [k in enabled, k in parked, k in merged]
        assert sum(states) == 1, (k, states)
    assert parked <= keys and set(merged) <= keys
    reasons = {k: group["why"] for group in dispositions.get("parked", []) for k in group["keys"]}
    assert parked == set(reasons), sorted(parked ^ set(reasons))


def test_enabled_blocks_are_the_verified_candidates_plus_owners():
    """The text of an enabled block is the text that the October verification checked; only `owners` (and fewer names) may differ."""
    candidates = {key(e, n): e for e in toml(FOLDER / "candidates" / "candidates-parked.toml")["removed"] for n in e["names"]}
    for entry in shipped_blocks_with_owners():
        for name in entry["names"]:
            verified = candidates.get(key(entry, name))
            if verified is None:                    # an older block that already had owners
                continue
            assert {k: v for k, v in entry.items() if k not in ("owners", "names")} == {
                k: v for k, v in verified.items() if k not in ("owners", "names")}, key(entry, name)
            if verified.get("owners"):
                assert entry["owners"] == verified["owners"], key(entry, name)


def test_verify_owners_py_starts_and_documents_its_options():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, str(FOLDER / "verify_owners.py"), "--help"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-400:]
    assert "--receipts" in result.stdout and "--fixfirst-src" in result.stdout and "--explore" in result.stdout
