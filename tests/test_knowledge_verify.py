"""The shipped knowledge base must still match the record of its last execution-based verification (scripts/knowledge_verify).

These tests run offline. They do not re-run the checks (that needs the network and several interpreters; see the README there): they fail
when a verified block is edited, added or dropped without verifying again, when the record is not a complete pass, or when a local path leaks into it.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest

from fixfirst import domain

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "scripts" / "knowledge_verify"
KNOWLEDGE = ROOT / "src" / "fixfirst" / "knowledge"
RECEIPT = FOLDER / "receipts" / "knowledge-receipt-20261003.json"
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
        for entry in data.get("unmaintained", []):
            assert domain.dist_id(entry["distribution"]) in kb["unmaintained_index"]


def test_every_verified_key_is_covered_by_a_passing_check(receipt):
    covered = {k for c in receipt["checks"] if c["status"] == "pass" for k in c["covers"]}
    for name in ("candidates.toml", "candidates-optional.toml", "candidates-parked.toml"):
        for entry in blocks(FOLDER / "candidates" / name).get("removed", []):
            for n in entry["names"]:
                assert key(entry, n) in covered, (name, key(entry, n))


def test_the_parked_file_in_the_package_is_the_parked_candidate_file():
    shipped = blocks(KNOWLEDGE / "pending_attribution.toml")
    verified = blocks(FOLDER / "candidates" / "candidates-parked.toml")
    assert shipped["removed"] == verified["removed"]
    for sid, source in verified.get("sources", {}).items():
        assert shipped["sources"][sid] == source


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
def test_verify_py_starts_and_documents_its_options():
    result = subprocess.run([sys.executable, str(FOLDER / "verify.py"), "--help"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-400:]
    assert "--receipts" in result.stdout and "--candidates" in result.stdout
