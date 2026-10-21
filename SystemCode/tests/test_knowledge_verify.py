"""The shipped knowledge base must still match the record of its last execution-based verification (scripts/knowledge_verify).

These tests run offline. They do not re-run the checks (that needs the network and several interpreters; see the README there): they fail
when a verified block is edited, added or dropped without verifying again, when the record is not a complete pass, when the details of the record
(the exceptions each release raised, the snippets, the environments with the interpreter and the package versions each role ran with, the verdicts)
no longer give its verdicts, or when a local path leaks into it.
They do not skip when the record is missing: only a checkout without scripts/knowledge_verify skips them.
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
from packaging.requirements import Requirement      # pytest itself needs packaging
from packaging.version import InvalidVersion, Version

from fixfirst import domain

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "scripts" / "knowledge_verify"
KNOWLEDGE = ROOT / "src" / "fixfirst" / "knowledge"
# the knowledge base of the product right before the verified candidates were merged into it (git show c0bd25e:src/fixfirst/knowledge/domain.toml):
# the explicit base of the loader smoke test of the record, and the reference of everything that the candidates do not define
BASELINE = FOLDER / "baseline" / "domain-c0bd25e.toml"
CANDIDATE_FILES = ("candidates.toml", "candidates-optional.toml", "candidates-parked.toml")
pytestmark = pytest.mark.skipif(not FOLDER.is_dir(), reason="scripts/knowledge_verify is not part of this checkout")

# older entries that the audit could not confirm: four modules that cannot be built on the machine that ran it, and one contradicted claim
AUDIT_EXCEPTIONS = {
    "audit-module-msilib", "audit-module-nis", "audit-module-ossaudiodev", "audit-module-spwd",
    "audit-flask-sqlalchemy-Model-claim-3.0",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def key(entry: dict, name: str) -> str:
    return f"api:{entry['module']}.{name}" if entry["kind"] == "api" else f"{entry['kind']}:{name}"


def receipt_files(pattern: str) -> list:
    return sorted((FOLDER / "receipts").glob(pattern)) if (FOLDER / "receipts").is_dir() else []


def test_the_product_that_is_tested_is_the_one_of_this_checkout():
    """The tests read the knowledge base through fixfirst.domain: an editable install of ANOTHER checkout would be tested instead of the files here."""
    assert Path(domain.__file__).resolve().is_relative_to((ROOT / "src").resolve()), domain.__file__


def test_the_knowledge_record_is_installed():
    files = receipt_files("knowledge-receipt-*.json")
    assert len(files) == 1, f"expected exactly one knowledge receipt in {FOLDER / 'receipts'}, found {[f.name for f in files]}"


@pytest.fixture(scope="module")
def receipt():
    files = receipt_files("knowledge-receipt-*.json")
    assert len(files) == 1, f"expected exactly one knowledge receipt, found {[f.name for f in files]}"
    return json.loads(files[0].read_text(encoding="utf-8"))


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
    text = json.dumps(receipt)
    assert not re.search(r"/Users/|/private/|/var/folders|/home/|/tmp/|[A-Za-z]:\\\\Users", text)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
def test_the_record_is_redacted_by_the_patterns_of_the_verifier(receipt, verify_module):
    assert verify_module.leaked_paths(json.dumps(receipt)) == []


def test_the_record_belongs_to_the_files_in_this_repository(receipt):
    assert set(receipt["files"]) == set(CANDIDATE_FILES)          # an emptied list would compare nothing
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
    governed = {domain.dist_id(e["distribution"]) for e in [*candidates, *baseline]}
    for index in range(len(shipped)):
        if domain.dist_id(shipped[index]["distribution"]) not in governed:
            continue                                                             # a reviewed entry that neither defines is free
        for field, value in (("last", "999.0"), ("replacement", "REVIEW MUTATION: wrong advice"), ("source", "somewhere-else")):
            changed = copy.deepcopy(shipped)
            changed[index][field] = value
            assert compare_unmaintained(changed, candidates, baseline), (shipped[index]["distribution"], field)
    assert compare_unmaintained(shipped[:-1] if domain.dist_id(shipped[-1]["distribution"]) in governed else shipped[1:], candidates, baseline)   # an entry dropped
    # a new entry (neither defines it) is not a problem
    assert compare_unmaintained([*shipped, {"distribution": "newtool", "last": "1.0", "replacement": "other", "source": "x"}], candidates, baseline) == []
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


def test_every_unmaintained_entry_cites_a_shipped_source():
    """The loader of the product does not check the source of an unmaintained entry: a deleted source would be a dangling citation."""
    kb = domain.load()
    for entry in kb["unmaintained_index"].values():
        assert entry["source"] in kb["sources"], entry


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


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
def test_the_loader_smoke_is_strict_about_what_the_engine_does_with_an_entry(verify_module, tmp_path):
    """The smoke test must reject an entry whose advice lacks the replacement text, an entry that the engine does not diagnose as a version
    incompatibility, and a source that does not resolve (each clause was once relaxed without a test noticing)."""
    text = candidate_text()
    cand = tomllib.loads(text)
    workspace = SimpleNamespace(base=str(tmp_path), neutral=str(tmp_path), env_vars=os.environ.copy(), python_for=lambda env: sys.executable)
    kind_module = next(i for i, e in enumerate(cand["removed"]) if e["kind"] == "module")

    def smoke(changed):
        return verify_module.loader_smoke(workspace, str(ROOT / "src"), str(BASELINE), text, changed)["problems"]

    assert smoke(cand) == []
    changed = copy.deepcopy(cand)
    changed["removed"][kind_module]["replacement"] = "NOT IN THE KNOWLEDGE BASE: " + changed["removed"][kind_module]["replacement"]
    assert any("does not contain the replacement text" in p for p in smoke(changed))
    changed = copy.deepcopy(cand)
    changed["removed"][kind_module]["version"] = "0.0.1"          # the engine is told this release is installed, which is older than the removal
    assert any("did not diagnose version_incompatibility" in p for p in smoke(changed))
    changed = copy.deepcopy(cand)
    changed["sources"]["a-source-that-is-not-in-the-text"] = {"title": "x", "url": "https://example.invalid/"}
    assert any("does not resolve" in p for p in smoke(changed))


# ---------------------------------------------------------------------------------------------------------------------------------------
# the record is judged again from its details (the same class of gap as O-R1 for the knowledge record): what each check concluded must follow
# from the exceptions that each release raised, and each snippet, environment and expectation must be the ones of verify.py
# ---------------------------------------------------------------------------------------------------------------------------------------
def describe(v, rec: dict) -> str:
    """verify.fmt_rec of a stored record (a hollowed record has no message: that is a problem of the record, not a crash)."""
    try:
        return v.fmt_rec(rec)
    except Exception:
        return "an unusable record"


def role_names(check) -> list:
    return ["before", "after", *[f"later{i}" for i in range(len(check.later))]]


def role_envs(check) -> dict:
    return {"before": check.before, "after": check.after, **{f"later{i}": env for i, env in enumerate(check.later)}}


def rejudge_check(v, check, entry: dict) -> tuple:
    """(problems, info) that verify.run_checks would conclude from the stored records of one check; the lookup of PyPI (adjacency) is not repeated."""
    problems, info = [], {}
    stored_info = entry.get("info") if isinstance(entry.get("info"), dict) else {}
    roles = entry.get("roles") if isinstance(entry.get("roles"), dict) else {}
    recs = {role: roles.get(role) for role in role_names(check)}
    if set(roles) != set(recs):
        return [f"the record holds the roles {sorted(roles)}, expected {sorted(recs)}"], info
    for role, rec in recs.items():
        if not isinstance(rec, dict) or not isinstance(rec.get("ok"), bool):
            problems.append(f"{role}: no verdict")
    if problems:
        return problems, info
    if check.kind == "removed":
        if not recs["before"]["ok"]:
            problems.append(f"before: expected the snippet to succeed, got {describe(v, recs['before'])}")
        expect = check.expect.split("|")
        for role in [r for r in recs if r != "before"]:
            rec = recs[role]
            if rec["ok"]:
                problems.append(f"{role}: expected {check.expect}, but the snippet succeeded")
            elif rec.get("exc_type") not in expect:
                problems.append(f"{role}: expected {check.expect}, got {rec.get('exc_type')}: {str(rec.get('exc_msg', ''))[:120]}")
            elif check.match and check.match not in str(rec.get("exc_msg", "")):
                problems.append(f"{role}: message lacks {check.match!r}: {str(rec.get('exc_msg', ''))[:120]}")
        after = recs[check.shape_role]
        if check.shape and not after["ok"] and not problems:
            last_line = [line for line in check.code.splitlines() if line.strip()][-1]
            derived = v.derive_keys(str(after.get("exc_msg", "")), last_line, str(after.get("exc_type", "")))
            if len(str(after.get("exc_msg", ""))) >= 4000:       # the record keeps 4000 characters of a longer message: the rest was derived by the run
                derived |= set(stored_info.get("derived", []))
            missing = [k for k in check.covers if not k.startswith("usage:") and k not in derived]
            info["derived"], info["derived_from"] = sorted(derived), check.shape_role
            if missing:
                problems.append(f"keys {missing} cannot be derived from the message (FixFirst would derive {sorted(derived)})")
    else:
        pattern = re.compile(check.warn)
        for role, rec in recs.items():
            if not rec["ok"]:
                problems.append(f"{role}: deprecated name must still work, got {describe(v, rec)}")
                continue
            hits = [w for w in rec.get("warnings", []) if isinstance(w, list) and len(w) == 2 and w[0] == check.warn_category and pattern.search(str(w[1]))]
            if role == "before" and hits:
                problems.append(f"before: already warns: {hits[0][1][:120]}")
            if role != "before" and not hits:
                problems.append(f"{role}: no {check.warn_category} matching /{check.warn}/")
            if role == "after" and hits and check.shape:
                got = v.deprecated_key(hits[0][1])
                info["derived"] = [got]
                if got not in check.covers:
                    problems.append(f"warning text yields key {got!r}, not {list(check.covers)}")
    return problems, info


def judge_environment(v, env, rec: dict, reported: tuple = ()) -> list:
    """What a role really ran with (the interpreter and the distributions its probe reported) against what verify.py plans for it: the Python
    release, every planned package at a version its requirement allows, and the versions of the distributions that the check asks to report."""
    problems = []
    python = rec.get("python")
    if not isinstance(python, str) or not python.startswith(env.python + "."):
        problems.append(f"ran on Python {python!r}, verify.py plans {env.python}")
    dists = rec.get("dists")
    if not isinstance(dists, dict):
        return problems + ["has no record of the installed distributions"]
    installed = {v.canon(name): version for name, version in dists.items() if isinstance(name, str)}
    for requirement in env.pkgs:
        wanted = Requirement(requirement)
        have = installed.get(v.canon(wanted.name))
        if not isinstance(have, str) or not have:
            problems.append(f"{wanted.name} is not recorded as installed (verify.py plans {requirement})")
            continue
        try:
            version = Version(have)
        except InvalidVersion:
            problems.append(f"{wanted.name} is recorded as version {have!r}")
            continue
        if not wanted.specifier.contains(version, prereleases=True):
            problems.append(f"{wanted.name} {have} was installed, verify.py plans {requirement}")
    problems += [f"the version of {name} is not recorded" for name in reported if v.canon(name) not in installed]
    return problems


def audit_check_records(v, entries: list, expected: dict, label: str) -> list:
    problems, by_id = [], {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            problems.append(f"{label}: a record without an id")
            continue
        by_id.setdefault(entry["id"], []).append(entry)
    for check_id, found in sorted(by_id.items()):
        if check_id not in expected:
            problems.append(f"{label} {check_id}: not a check of verify.py")
        elif len(found) > 1:
            problems.append(f"{label} {check_id}: recorded {len(found)} times")
    for check_id, check in expected.items():
        if check_id not in by_id:
            problems.append(f"{label} {check_id}: has no record")
            continue
        entry = by_id[check_id][0]
        for field, wanted in (("group", check.group), ("dist", check.dist), ("first_gone", check.first_gone), ("kind", check.kind), ("covers", list(check.covers)),
                              ("expect", check.expect), ("match", check.match), ("code", check.code), ("code_sha256", v._digest(check.code))):
            if entry.get(field) != wanted:
                problems.append(f"{label} {check_id}: {field} is not what verify.py says")
        roles = entry.get("roles") if isinstance(entry.get("roles"), dict) else {}
        for role, env in role_envs(check).items():
            if not isinstance(roles.get(role), dict):
                continue        # the roles that are missing or hollow are reported by the verdicts below
            if roles[role].get("env") != env.label():
                problems.append(f"{label} {check_id}: {role} ran in {roles[role].get('env')!r}, verify.py says {env.label()!r}")
            problems += [f"{label} {check_id}: {role} {problem}" for problem in judge_environment(v, env, roles[role], check.dists)]
        try:
            found_problems, info = rejudge_check(v, check, entry)
        except Exception as error:      # a malformed record is a problem of the record, not a crash of the audit
            found_problems, info = [f"the record cannot be judged ({type(error).__name__}: {error})"], {}
        status = "pass" if not found_problems else "fail"
        if entry.get("status") != status:
            problems.append(f"{label} {check_id}: the record says {entry.get('status')!r}, its details say {status!r}")
        if entry.get("problems") != v._clean(found_problems):
            problems.append(f"{label} {check_id}: the stored problems are not the ones the details give")
        stored_info = entry.get("info") if isinstance(entry.get("info"), dict) else {}
        for field, wanted in info.items():
            if stored_info.get(field) != wanted:
                problems.append(f"{label} {check_id}: info.{field} is {stored_info.get(field)!r}, the details give {wanted!r}")
        if (check.adjacent and check.dist != "python" and status == "pass" and v.pinned_version(check.before, check.dist)
                and v.pinned_version(check.after, check.dist)):
            if not isinstance(stored_info.get("adjacent"), str) or not stored_info["adjacent"]:
                problems.append(f"{label} {check_id}: no evidence that the pinned releases are neighbours")
    return problems


def rejudge_support(v, support, entry: dict) -> list:
    if not isinstance(entry.get("ok"), bool):
        return ["no verdict"]
    problems = []
    if support.pypi_latest and f"PyPI newest release of {support.pypi_latest[0]}: {support.pypi_latest[1]}" not in str(entry.get("stdout", "")):
        problems.append(f"newest PyPI release of {support.pypi_latest[0]} is not recorded as {support.pypi_latest[1]}")
    if support.expect:
        if entry["ok"] or entry.get("exc_type") != support.expect or (support.match and support.match not in str(entry.get("exc_msg", ""))):
            problems.append(f"expected {support.expect} {support.match!r}, got {describe(v, entry)}")
    elif not entry["ok"]:
        problems.append(f"assertion failed: {describe(v, entry)}")
    return problems


def audit_support_records(v, entries: list, expected: dict, label: str) -> list:
    problems, by_id = [], {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            problems.append(f"{label}: a record without an id")
            continue
        by_id.setdefault(entry["id"], []).append(entry)
    for support_id, found in sorted(by_id.items()):
        if support_id not in expected:
            problems.append(f"{label} {support_id}: not a probe of verify.py")
        elif len(found) > 1:
            problems.append(f"{label} {support_id}: recorded {len(found)} times")
    for support_id, support in expected.items():
        if support_id not in by_id:
            problems.append(f"{label} {support_id}: has no record")
            continue
        entry = by_id[support_id][0]
        for field, wanted in (("claim", support.claim), ("covers", list(support.covers)), ("env", support.env.label()), ("expect", support.expect),
                              ("match", support.match), ("code", support.code), ("code_sha256", v._digest(support.code))):
            if entry.get(field) != wanted:
                problems.append(f"{label} {support_id}: {field} is not what verify.py says")
        python = entry.get("python")        # a probe records the interpreter it ran on, not the versions of its packages
        if not isinstance(python, str) or not python.startswith(support.env.python + "."):
            problems.append(f"{label} {support_id}: ran on Python {python!r}, verify.py plans {support.env.python}")
        try:
            found_problems = rejudge_support(v, support, entry)
        except Exception as error:
            found_problems = [f"the record cannot be judged ({type(error).__name__}: {error})"]
        status = "pass" if not found_problems else "fail"
        if entry.get("status") != status:
            problems.append(f"{label} {support_id}: the record says {entry.get('status')!r}, its details say {status!r}")
        if entry.get("problems") != v._clean(found_problems):
            problems.append(f"{label} {support_id}: the stored problems are not the ones the details give")
    return problems


def audit_knowledge_record(v, receipt: dict) -> list:
    """Every problem the knowledge record has when it is judged again from its details. Needs verify.py (its checks, probes and key derivation)
    and the baseline that the audit of the older entries was generated from; nothing else, no network."""
    if not isinstance(receipt, dict) or not all(isinstance(receipt.get(name), list) for name in ("checks", "supports", "audit_checks", "audit_supports")):
        return ["the record holds no lists of checks, probes, audit checks and audit probes"]
    baseline = tomllib.loads(BASELINE.read_text(encoding="utf-8"))
    expected_audit = {c.id: c for c in [*v.audit_checks(baseline), *v.audit_deprecated_checks(baseline), *v.AUDIT]}
    problems = audit_check_records(v, receipt["checks"], {c.id: c for c in v.CHECKS}, "check")
    problems += audit_check_records(v, receipt["audit_checks"], expected_audit, "audit")
    problems += audit_support_records(v, receipt["supports"], {s.id: s for s in v.SUPPORTS}, "probe")
    problems += audit_support_records(v, receipt["audit_supports"], {s.id: s for s in v.AUDIT_SUPPORTS}, "audit probe")
    summary = receipt.get("summary") if isinstance(receipt.get("summary"), dict) else {}
    passed = sum(1 for c in receipt["checks"] if isinstance(c, dict) and c.get("status") == "pass")
    passed_probes = sum(1 for s in receipt["supports"] if isinstance(s, dict) and s.get("status") == "pass")
    for field, wanted in (("candidate_checks", len(receipt["checks"])), ("candidate_checks_passed", passed), ("supporting_probes", len(receipt["supports"])),
                          ("supporting_probes_passed", passed_probes), ("probes_not_checked", 0), ("total_failures", 0)):
        if type(summary.get(field)) is not int or summary[field] != wanted:
            problems.append(f"summary.{field} is {summary.get(field)!r}, the records say {wanted!r}")
    if receipt.get("cross_check_problems") != []:
        problems.append("the cross checks found problems")
    smoke = receipt.get("smoke") if isinstance(receipt.get("smoke"), dict) else {}
    if smoke.get("mode") != "baseline" or smoke.get("problems") != [] or smoke.get("engine_ok") != smoke.get("engine_total") or not smoke.get("engine_total"):
        problems.append("the loader smoke test of the record is not a pass on the explicit baseline")
    return problems


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
def test_the_record_is_judged_again_from_its_details(receipt, verify_module):
    assert audit_knowledge_record(verify_module, receipt) == []


def a_check(receipt, predicate=lambda c: True, key="checks") -> dict:
    return next(c for c in receipt[key] if predicate(c))


def every_role_emptied(receipt):
    for entry in receipt["checks"]:
        entry["roles"] = {}


def one_role_dropped(receipt):
    a_check(receipt, lambda c: "later0" in c["roles"])["roles"].pop("later0")


def the_exception_of_every_after_changed(receipt):
    for entry in receipt["checks"]:
        entry["roles"]["after"].update(exc_type="Nothing", exc_msg="Nothing")


def the_snippet_failed_before_the_removal(receipt):
    a_check(receipt, lambda c: c["kind"] == "removed")["roles"]["before"]["ok"] = False


def the_snippet_worked_after_the_removal(receipt):
    entry = a_check(receipt, lambda c: c["kind"] == "removed")
    entry["roles"]["later0"].update(ok=True)
    entry["roles"]["later0"].pop("exc_type", None)


def the_message_lacks_the_expected_text(receipt):
    entry = a_check(receipt, lambda c: c["kind"] == "removed" and c["match"])
    entry["roles"]["after"]["exc_msg"] = "something else"


def another_environment_ran(receipt):
    a_check(receipt)["roles"]["after"]["env"] = "py3.8 not-the-verified-release==1"


def the_expectation_blanked(receipt):
    for entry in receipt["checks"]:
        entry["expect"], entry["match"] = "", ""


def covers_swapped(receipt):
    first, second = receipt["checks"][0], receipt["checks"][1]
    first["covers"], second["covers"] = second["covers"], first["covers"]


def the_snippet_edited_with_its_hash(receipt):
    entry = a_check(receipt)
    entry["code"] += "\n# edited"
    entry["code_sha256"] = hashlib.sha256(entry["code"].encode("utf-8")).hexdigest()


def the_hash_of_the_snippet_changed(receipt):
    a_check(receipt)["code_sha256"] = "0" * 64


def the_status_flipped(receipt):
    a_check(receipt)["status"] = "fail"


def problems_listed_on_a_pass(receipt):
    a_check(receipt)["problems"] = ["x"]


def the_derived_key_forgotten(receipt):
    for entry in receipt["checks"]:
        entry["info"].pop("derived", None)


def the_adjacency_forgotten(receipt):
    for entry in receipt["checks"]:
        entry["info"].pop("adjacent", None)


def a_check_dropped_with_the_summary(receipt):
    receipt["checks"].pop()
    receipt["summary"]["candidate_checks"] -= 1
    receipt["summary"]["candidate_checks_passed"] -= 1


def a_check_recorded_twice(receipt):
    receipt["checks"].append(copy.deepcopy(receipt["checks"][0]))


def a_check_that_verify_py_does_not_have(receipt):
    stray = copy.deepcopy(receipt["checks"][0])
    stray["id"] = "a-check-that-does-not-exist"
    receipt["checks"].append(stray)


def the_details_of_every_probe_emptied(receipt):
    for entry in receipt["supports"]:
        for field in ("ok", "stdout", "exc_type", "exc_msg", "warnings"):
            entry.pop(field, None)


def a_probe_failed(receipt):
    a_check(receipt, key="supports")["ok"] = False


def a_probe_claim_changed(receipt):
    a_check(receipt, key="supports")["claim"] = "something else is claimed"


def the_audit_roles_emptied(receipt):
    for entry in receipt["audit_checks"]:
        entry["roles"] = {}


def an_audit_check_that_must_fail_passes(receipt):
    a_check(receipt, lambda c: c["status"] == "fail", key="audit_checks")["status"] = "pass"


def the_audit_probes_failed(receipt):
    for entry in receipt["audit_supports"]:
        entry["ok"] = False


def the_smoke_ran_on_another_base(receipt):
    receipt["smoke"]["mode"] = "shipped+candidates"


def the_summary_is_not_the_records(receipt):
    receipt["summary"]["supporting_probes_passed"] -= 1


def a_leak_of_a_temp_path(receipt):
    a_check(receipt)["roles"]["after"]["exc_msg"] = "No module named 'x' (/tmp/ffk-verify-abc/py/bin/python)"


def a_role_planned_with(receipt, predicate, key="checks"):
    """(record, requirement) of the first stored role whose planned requirements (the words behind the interpreter in its label) include one that
    the predicate accepts."""
    for entry in receipt[key]:
        for rec in entry["roles"].values():
            for requirement in rec["env"].split()[1:]:
                if predicate(requirement):
                    return rec, requirement
    raise AssertionError("the record holds no such role")


def name_of(requirement: str) -> str:
    return re.split(r"[<>=!~]", requirement)[0]


def a_role_on_the_wrong_python(receipt):
    """Python 3.12 is planned; the record says 3.1.0 (the reproduction of the review of 4c8fd80)."""
    a_check(receipt, lambda c: c["id"] == "st82-module-pkg_resources")["roles"]["after"]["python"] = "3.1.0"


def a_pinned_package_at_another_version(receipt):
    """setuptools==82.0.0 is planned; the record says that 0.0.1 was installed (the same review)."""
    a_check(receipt, lambda c: c["id"] == "st82-module-pkg_resources")["roles"]["after"]["dists"]["setuptools"] = "0.0.1"


def the_versions_of_a_role_removed(receipt):
    """Deleting the fields is not allowed to be a way out either (the same review)."""
    rec = a_check(receipt, lambda c: c["id"] == "st82-module-pkg_resources")["roles"]["after"]
    del rec["python"], rec["dists"]


def a_range_that_the_installed_version_is_outside_of(receipt):
    rec, requirement = a_role_planned_with(receipt, lambda r: "<" in r)
    rec["dists"][name_of(requirement)] = "99.0.0"


def a_package_that_was_not_installed(receipt):
    rec, requirement = a_role_planned_with(receipt, lambda r: re.fullmatch(r"[A-Za-z0-9_.\-]+", r))
    rec["dists"][name_of(requirement)] = None


def a_version_that_is_not_a_version(receipt):
    rec, requirement = a_role_planned_with(receipt, lambda r: "==" in r)
    rec["dists"][name_of(requirement)] = "not-a-version"


def the_distributions_of_a_role_forgotten(receipt):
    a_check(receipt, lambda c: c["id"] == "st82-module-pkg_resources")["roles"]["after"]["dists"] = {}


def a_role_of_the_audit_on_the_wrong_python(receipt):
    a_check(receipt, key="audit_checks")["roles"]["after"]["python"] = "2.7.18"


def a_probe_on_the_wrong_python(receipt):
    a_check(receipt, key="supports")["python"] = "3.1.0"


def a_probe_without_its_python(receipt):
    a_check(receipt, key="audit_supports").pop("python")


KNOWLEDGE_MUTATIONS = [every_role_emptied, one_role_dropped, the_exception_of_every_after_changed, the_snippet_failed_before_the_removal,
                       the_snippet_worked_after_the_removal, the_message_lacks_the_expected_text, another_environment_ran, the_expectation_blanked,
                       covers_swapped, the_snippet_edited_with_its_hash, the_hash_of_the_snippet_changed, the_status_flipped, problems_listed_on_a_pass,
                       the_derived_key_forgotten, the_adjacency_forgotten, a_check_dropped_with_the_summary, a_check_recorded_twice,
                       a_check_that_verify_py_does_not_have, the_details_of_every_probe_emptied, a_probe_failed, a_probe_claim_changed,
                       the_audit_roles_emptied, an_audit_check_that_must_fail_passes, the_audit_probes_failed, the_smoke_ran_on_another_base,
                       the_summary_is_not_the_records, a_role_on_the_wrong_python, a_pinned_package_at_another_version,
                       the_versions_of_a_role_removed, a_range_that_the_installed_version_is_outside_of, a_package_that_was_not_installed,
                       a_version_that_is_not_a_version, the_distributions_of_a_role_forgotten, a_role_of_the_audit_on_the_wrong_python,
                       a_probe_on_the_wrong_python, a_probe_without_its_python]


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
@pytest.mark.parametrize("mutation", KNOWLEDGE_MUTATIONS, ids=lambda f: f.__name__)
def test_an_emptied_or_edited_knowledge_record_is_rejected(receipt, verify_module, mutation):
    changed = copy.deepcopy(receipt)
    mutation(changed)
    assert audit_knowledge_record(verify_module, changed), f"{mutation.__name__}: the record still passes"


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
def test_a_leaked_path_in_the_details_is_found(receipt, verify_module):
    changed = copy.deepcopy(receipt)
    a_leak_of_a_temp_path(changed)
    assert verify_module.leaked_paths(json.dumps(changed)) and re.search(r"/tmp/", json.dumps(changed))


@pytest.mark.skipif(sys.version_info < (3, 11), reason="verify.py needs tomllib")
def test_the_environment_of_a_role_is_judged_clause_by_clause(verify_module):
    """What a role ran with is judged against the plan: each clause has a counterexample, and the plan itself passes."""
    env = verify_module.E("3.12", "setuptools==82.0.0", "httpx<0.28", "pydantic")
    right = {"python": "3.12.13", "dists": {"setuptools": "82.0.0", "httpx": "0.27.2", "pydantic": "2.9.2", "cryptography": None}}

    def judged(**changes):
        rec = copy.deepcopy(right)
        rec.update(changes)
        return judge_environment(verify_module, env, rec, reported=("cryptography",))

    assert judged() == []
    assert judged(python="3.1.0") and judged(python="3.13.1") and judged(python="3.12") and judged(python=None) and judged(python=312)
    assert judged(python="3.12.0rc1") == []                                                  # a release candidate is still 3.12
    assert judged(dists=None) and judged(dists=[]) and judged(dists={})
    assert judged(dists={**right["dists"], "setuptools": "0.0.1"}) and judged(dists={**right["dists"], "setuptools": "82.0.1"})
    assert judged(dists={**right["dists"], "httpx": "0.28.0"}) and judged(dists={**right["dists"], "httpx": "1.0"})
    assert judged(dists={**right["dists"], "pydantic": None}) and judged(dists={**right["dists"], "pydantic": ""})
    assert judged(dists={**right["dists"], "pydantic": "not-a-version"}) and judged(dists={**right["dists"], "httpx": 0.27})
    assert judged(dists={k: v for k, v in right["dists"].items() if k != "pydantic"})
    assert judged(dists={k: v for k, v in right["dists"].items() if k != "cryptography"})      # the check asked to report it
    assert judged(dists={**right["dists"], "Setuptools": "82.0.0"}) == []                       # names are compared canonically
    assert judge_environment(verify_module, verify_module.E("3.12"), {"python": "3.12.1", "dists": {}}) == []
