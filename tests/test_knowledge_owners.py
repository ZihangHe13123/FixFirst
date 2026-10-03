"""The owners of the shipped removal knowledge must still match the record of their last execution-based verification
(scripts/knowledge_verify/verify_owners.py).

A removal block with `owners` is applied only to an object whose class is one of the named library classes, so `owners` is a claim about a
real class. The verification builds a real object of each class in the releases that prove the removal, asks the product's own receiver
identity code which classes it has, and lets FixFirst itself diagnose a script that ends in the missing attribute (and a project class with
the same name). The candidates that were merged into an enabled entry are verified the same way with their own receivers.

These tests run offline: they do not repeat that (it needs the network and many interpreters, see the README there). They judge the stored
record AGAIN from the details it holds, with the functions that judged the run, so a record that was emptied or edited does not pass; they fail
when a block with owners is edited, added or dropped without verifying again, when the receiver-identity code or any module, data file or rule that
the diagnosis runs on changed, or when the record is not a complete pass. They do not skip when the record is missing: only a checkout without
scripts/knowledge_verify skips them.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
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
pytestmark = pytest.mark.skipif(not FOLDER.is_dir(), reason="scripts/knowledge_verify is not part of this checkout")


def receipt_files(pattern: str) -> list:
    return sorted((FOLDER / "receipts").glob(pattern)) if (FOLDER / "receipts").is_dir() else []


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def key(entry: dict, name: str) -> str:
    return f"api:{entry['module']}.{name}" if entry["kind"] == "api" else f"{entry['kind']}:{name}"


def block_sha256(entry: dict) -> str:
    """The same function as verify_owners.block_sha256 (the order of the names does not matter); test_the_block_hash_is_the_one_of_the_verifier."""
    return hashlib.sha256(json.dumps({**entry, "names": sorted(entry["names"])}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_the_product_that_is_tested_is_the_one_of_this_checkout():
    """The tests read the knowledge base through fixfirst.domain: an editable install of ANOTHER checkout would be tested instead of the files here."""
    assert Path(domain.__file__).resolve().is_relative_to((ROOT / "src").resolve()), domain.__file__


def test_the_owners_record_is_installed():
    files = receipt_files("owners-receipt-*.json")
    assert len(files) == 1, f"expected exactly one owners receipt in {FOLDER / 'receipts'}, found {[f.name for f in files]}"


@pytest.fixture(scope="module")
def receipt():
    files = receipt_files("owners-receipt-*.json")
    assert len(files) == 1, f"expected exactly one owners receipt, found {[f.name for f in files]}"
    return json.loads(files[0].read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def verifier():
    if sys.version_info < (3, 11):
        pytest.skip("the verification programs need Python 3.11 (tomllib)")
    spec = importlib.util.spec_from_file_location("verify_owners_for_tests", FOLDER / "verify_owners.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def inputs(verifier):
    """What the record is judged against: the shipped blocks, the recipes, and the merged keys with the entries that cover them."""
    index = verifier.shipped_entries(str(KNOWLEDGE / "domain.toml"))
    candidates = {i["key"]: i for i in verifier.load_items([str(FOLDER / "candidates" / "candidates-parked.toml")], True)}
    dispositions = toml(FOLDER / "owners" / "dispositions.toml")
    return SimpleNamespace(
        items=verifier.load_items([str(KNOWLEDGE / "domain.toml")], False), index=index, candidates=candidates,
        recipes=verifier.load_recipes(str(FOLDER / "owners" / "recipes.toml")), dispositions=dispositions,
        merged=verifier.load_merged(dispositions, candidates, index))


def audit(verifier, inputs, receipt, **changed) -> list:
    given = {"items": inputs.items, "recipes": inputs.recipes, "index": inputs.index, "merged": inputs.merged, **changed}
    return verifier.audit_receipt(receipt, given["items"], given["recipes"], given["index"], given["merged"])


def shipped_blocks_with_owners() -> list:
    return [e for e in toml(KNOWLEDGE / "domain.toml")["removed"] if e.get("owners")]


def test_the_record_is_a_complete_pass(receipt):
    summary = receipt["summary"]
    assert summary["e2e"] is True and summary["reference"] is True and summary["failed"] == 0
    assert summary["keys"] == summary["passed"] == len(receipt["results"]) >= 150
    assert summary["merged"] == {"keys": len(receipt["merged"]), "passed": len(receipt["merged"])} and len(receipt["merged"]) >= 23
    assert {r["status"] for r in receipt["results"] + receipt["merged"]} == {"pass"}
    assert all(r["problems"] == [] for r in receipt["results"] + receipt["merged"])
    for result in receipt["results"]:
        recipe = "\n@@\n".join([result["recipe"], *result["extra_receivers"]])
        assert result["recipe_sha256"] == hashlib.sha256(recipe.encode("utf-8")).hexdigest()
        assert all(extra["removal_owner"] == [result["key"]] for extra in result["product"]["extra"])   # every further receiver too
        assert result["product"]["product"]["removal_owner"] == [result["key"]]       # exactly this entry, no overlapping one
        assert not result["product"]["twin"]["removal_owner"]                          # a project class of the same name is not authorized


def test_the_record_is_redacted(receipt, verifier):
    text = json.dumps(receipt)
    assert not re.search(r"/Users/|/private/|/var/folders|/home/|/tmp/|[A-Za-z]:\\\\Users", text)
    assert verifier.verify.leaked_paths(text) == []          # the patterns of the verifier itself


def test_the_record_belongs_to_the_tool(receipt, verifier):
    tool = receipt["tool"]
    assert digest(FOLDER / "verify_owners.py") == tool["verify_owners_py_sha256"]
    assert verifier.data_sha256(str(FOLDER / "owners" / "recipes.toml")) == tool["recipes_sha256"]     # by what the recipes parse to


def changed_digests(recorded: dict, current: dict) -> list:
    return sorted(name for name in {*recorded, *current} if recorded.get(name) != current.get(name))


def test_the_record_belongs_to_the_product_it_asked(receipt, verifier):
    """Layer 1: the functions that decide a receiver's identities (owners are claims about those identities). Layer 2: every module of the product
    that the E2E runs loaded and the scripts that run in the target interpreter (code only: comments and layout do not count), the knowledge data
    they read, and every rule. The names of the modules are the ones the record lists; test_every_module_an_e2e_run_loads_is_bound checks that list."""
    tool = receipt["tool"]
    digests = verifier.product_digests(str(ROOT / "src" / "fixfirst"), loaded=list(tool["e2e_files_sha256"]))
    assert digests["identity_functions_sha256"] == tool["identity_functions_sha256"], "the identity functions of the probe changed: verify again"
    for layer in ("e2e_files_sha256", "e2e_data_sha256", "e2e_rules_sha256"):
        assert changed_digests(tool[layer], digests[layer]) == [], f"{layer}: changed after the record was made, verify again"
    assert re.fullmatch(r"[0-9a-f]{64}", tool["package_sha256"])    # informational: the digest of the whole package


def test_every_module_an_e2e_run_loads_is_bound_by_the_record(receipt, verifier, inputs, tmp_path):
    """The record lists the modules that its E2E runs loaded. A run here, of the same runner, must not load a module that the record does not list
    (a new import in the removal chain, or a record whose list was cut down)."""
    workspace = SimpleNamespace(base=str(tmp_path), neutral=str(tmp_path), env_vars=os.environ.copy(), python_for=lambda env: sys.executable)
    item = next(i for i in inputs.items if i["key"] == "attribute:assertEquals")           # unittest.TestCase.assertEquals: removed in Python 3.12
    recipe = verifier.find_recipe(inputs.recipes, item["key"])
    jobs = [{"id": "twin", "python": sys.executable, "code": verifier.twin_code(item)}]
    if sys.version_info >= (3, 12):
        jobs.append({"id": "positive", "python": sys.executable, "code": verifier.e2e_code(item, recipe["setup"])})
    records, loaded = verifier.run_product(workspace, verifier.prepare_source(workspace, str(ROOT / "src"), []), jobs)
    assert all("error" not in record for record in records.values()), records
    platform_only = {"_winprocess.py"}              # the process tree of Windows: the record was made on macOS, where it is not loaded
    unbound = sorted(set(loaded) - platform_only - set(receipt["tool"]["e2e_files_sha256"]))
    assert loaded and not unbound, unbound
    if "positive" in records:                    # the product still diagnoses it here, so the run exercised the removal chain
        assert records["positive"]["removal_owner"] == [item["key"]], records["positive"]


def test_the_digests_of_the_product_follow_what_the_code_says_not_how_it_is_annotated(verifier, tmp_path):
    package = tmp_path / "fixfirst"
    shutil.copytree(ROOT / "src" / "fixfirst", package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    loaded = ["removal_ownership.py", "reasoning.py"]
    before = verifier.product_digests(str(package), loaded)
    assert set(before["e2e_files_sha256"]) == {*loaded, "_runtime_evidence.py", "_native_runner.py", "_unittest_runner.py", "_notebook_runner.py"}
    source = (package / "removal_ownership.py").read_text(encoding="utf-8")
    # comments, blank lines, trailing spaces and line endings: the same digest
    (package / "removal_ownership.py").write_bytes(("# a comment\n\n" + source.replace("\n", "   \r\n") + "\n\n# the end\n").encode("utf-8"))
    assert verifier.product_digests(str(package), loaded)["e2e_files_sha256"] == before["e2e_files_sha256"]
    # a `#` inside a string is not a comment
    (package / "removal_ownership.py").write_text(source + "\nMARK = '# not a comment'\n", encoding="utf-8")
    marked = verifier.product_digests(str(package), loaded)["e2e_files_sha256"]["removal_ownership.py"]
    (package / "removal_ownership.py").write_text(source + "\nMARK = '# another text'\n", encoding="utf-8")
    assert verifier.product_digests(str(package), loaded)["e2e_files_sha256"]["removal_ownership.py"] != marked
    # code: another digest, and only for that file
    (package / "removal_ownership.py").write_text(source + "\nVALUE = 1\n", encoding="utf-8")
    after = verifier.product_digests(str(package), loaded)
    assert changed_digests(before["e2e_files_sha256"], after["e2e_files_sha256"]) == ["removal_ownership.py"]
    assert after["identity_functions_sha256"] == before["identity_functions_sha256"] and after["e2e_rules_sha256"] == before["e2e_rules_sha256"]
    # a module that the runs did not load does not count (the digest of the whole package moves)
    (package / "removal_ownership.py").write_text(source, encoding="utf-8")
    (package / "report.py").write_text((package / "report.py").read_text(encoding="utf-8") + "\nVALUE = 1\n", encoding="utf-8")
    other = verifier.product_digests(str(package), loaded)
    assert other["e2e_files_sha256"] == before["e2e_files_sha256"] and other["package_sha256"] != before["package_sha256"]
    # an identity function of the probe (and so also the file that holds it)
    probe = (package / "_runtime_evidence.py").read_text(encoding="utf-8")
    marker = "def receiver_owners(value):"
    assert marker in probe
    (package / "_runtime_evidence.py").write_text(probe.replace(marker, marker + "  # changed", 1), encoding="utf-8")
    assert verifier.product_digests(str(package), loaded)["identity_functions_sha256"] != before["identity_functions_sha256"]
    (package / "_runtime_evidence.py").write_text(probe, encoding="utf-8")
    # a rule: only that rule changes, whatever the order of the keys of its table; the same text reordered changes nothing
    rules = (package / "knowledge" / "rules.toml").read_text(encoding="utf-8")
    assert 'id = "D02"\n' in rules
    (package / "knowledge" / "rules.toml").write_text(rules.replace('id = "D02"\n', 'note = "changed"\nid = "D02"\n', 1), encoding="utf-8")
    assert changed_digests(before["e2e_rules_sha256"], verifier.product_digests(str(package), loaded)["e2e_rules_sha256"]) == ["D02"]
    (package / "knowledge" / "rules.toml").write_text(rules.replace('id = "D02"\n', 'id = "D02"\n# a comment\n', 1), encoding="utf-8")
    assert verifier.product_digests(str(package), loaded)["e2e_rules_sha256"] == before["e2e_rules_sha256"]
    (package / "knowledge" / "rules.toml").write_text(rules + '\n[[rule]]\nid = "NEW"\nphase = "diagnose"\n', encoding="utf-8")
    assert changed_digests(before["e2e_rules_sha256"], verifier.product_digests(str(package), loaded)["e2e_rules_sha256"]) == ["NEW"]
    (package / "knowledge" / "rules.toml").write_text(rules, encoding="utf-8")
    # data the runs read
    data = sorted(before["e2e_data_sha256"])
    assert "knowledge/package_compatibility.toml" in data and "knowledge/domain.toml" not in data and "knowledge/pending_attribution.toml" not in data
    compatibility = (package / "knowledge" / "package_compatibility.toml").read_text(encoding="utf-8")
    (package / "knowledge" / "package_compatibility.toml").write_text(compatibility + "\n# a comment\n", encoding="utf-8")
    assert verifier.product_digests(str(package), loaded)["e2e_data_sha256"] == before["e2e_data_sha256"]
    (package / "knowledge" / "package_compatibility.toml").write_text(compatibility + '\n[extra]\nvalue = "changed"\n', encoding="utf-8")
    assert changed_digests(before["e2e_data_sha256"], verifier.product_digests(str(package), loaded)["e2e_data_sha256"]) == ["knowledge/package_compatibility.toml"]


def test_the_digest_of_a_data_file_is_what_it_parses_to(verifier, tmp_path):
    first, second = tmp_path / "a.toml", tmp_path / "b.toml"
    first.write_text('# comment\n[x]\nb = 2\na = "one"\n', encoding="utf-8")
    second.write_bytes(b'[x]\r\na = "one"\r\nb = 2\r\n\r\n')
    assert verifier.data_sha256(str(first)) == verifier.data_sha256(str(second))
    second.write_text('[x]\na = "one"\nb = 3\n', encoding="utf-8")
    assert verifier.data_sha256(str(first)) != verifier.data_sha256(str(second))


def test_the_block_hash_is_the_one_of_the_verifier(verifier):
    for entry in toml(KNOWLEDGE / "domain.toml")["removed"]:
        assert verifier.block_sha256(entry) == block_sha256(entry)
    entry = next(e for e in shipped_blocks_with_owners() if len(e["names"]) > 1)
    assert block_sha256({**entry, "names": list(reversed(entry["names"]))}) == block_sha256(entry)        # the order of the names does not matter
    assert block_sha256({**entry, "names": entry["names"][:-1]}) != block_sha256(entry)


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
    assert len({r["key"] for r in receipt["results"]}) == len(receipt["results"])


def test_no_key_of_the_knowledge_base_is_defined_by_two_blocks():
    """The loader of the product keeps the last block of a key without a word, so a second definition would silently replace a verified one."""
    seen = {}
    for entry in toml(KNOWLEDGE / "domain.toml")["removed"]:
        for name in entry["names"]:
            assert key(entry, name) not in seen, f"{key(entry, name)} is defined twice"
            seen[key(entry, name)] = entry
    assert len(seen) == len(domain.load()["removed_index"])


def test_owners_are_qualified_library_paths_of_the_blocks_distribution():
    for entry in shipped_blocks_with_owners():
        assert entry["kind"] in ("api", "attribute")
        assert entry["owners"] == sorted(set(entry["owners"])) or len(entry["owners"]) < 2
        for owner in entry["owners"]:
            assert "." in owner and all(part.isidentifier() for part in owner.split(".")), owner
            assert owner.split(".")[0] not in ("builtins", "__main__"), owner


def test_every_parked_candidate_has_exactly_one_disposition():
    """enabled with owners (domain.toml), still parked (pending_attribution.toml) or merged into an enabled entry (dispositions.toml): once."""
    candidates = toml(FOLDER / "candidates" / "candidates-parked.toml")["removed"]
    keys = [key(e, n) for e in candidates for n in e["names"]]
    assert len(keys) == len(set(keys))
    enabled = set(domain.load()["removed_index"])
    parked = [key(e, n) for e in toml(KNOWLEDGE / "pending_attribution.toml")["removed"] for n in e["names"]]
    dispositions = toml(FOLDER / "owners" / "dispositions.toml")
    merged = [k for group in dispositions.get("merged", []) for k in group["keys"]]
    parked_reasons = [k for group in dispositions.get("parked", []) for k in group["keys"]]
    for group in dispositions.get("merged", []):
        assert group["covered_by"] and len(set(group["covered_by"])) == len(group["covered_by"]) and set(group["covered_by"]) <= enabled, group["covered_by"]
        assert group["why"].strip()
    for k in keys:
        states = [int(k in enabled), parked.count(k), merged.count(k)]
        assert sum(states) == 1, (k, states)                      # a key listed twice counts twice
    assert set(parked) <= set(keys) and set(merged) <= set(keys)
    assert len(parked) == len(set(parked)) and len(parked_reasons) == len(set(parked_reasons))
    assert set(parked) == set(parked_reasons), sorted(set(parked) ^ set(parked_reasons))


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


@pytest.mark.skipif(sys.version_info < (3, 11), reason="the verification programs need Python 3.11 (tomllib)")
def test_verify_owners_py_starts_and_documents_its_options():
    import subprocess
    result = subprocess.run([sys.executable, str(FOLDER / "verify_owners.py"), "--help"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-400:]
    assert "--receipts" in result.stdout and "--fixfirst-src" in result.stdout and "--explore" in result.stdout


# ---------------------------------------------------------------------------------------------------------------------------------------
# the record is judged again from its details (O-R1): what the run judged must follow from what the record stores
# ---------------------------------------------------------------------------------------------------------------------------------------
def test_the_record_is_judged_again_from_its_details(receipt, verifier, inputs):
    assert audit(verifier, inputs, receipt) == []
    assert len(inputs.items) == len(receipt["results"]) and len(inputs.merged) == len(receipt["merged"])


def first(receipt: dict, predicate) -> dict:
    return next(r for r in receipt["results"] if predicate(r))


def hollow_releases(receipt):
    for result in receipt["results"]:
        result["releases"] = {}


def hollow_one_release(receipt):
    first(receipt, lambda r: "later0" in r["releases"])["releases"].pop("later0")


def hollow_every_release_payload(receipt):
    for result in receipt["results"] + receipt["merged"]:
        for release in result["releases"].values():
            release.update(rows=[], authorized_by=[], access="ok")


def forget_the_owner_in_one_release(receipt):
    first(receipt, lambda r: r["owners"])["releases"]["after"]["rows"] = []


def forget_a_declared_owner_everywhere(receipt):
    """One of several declared owners is no identity of the receiver in any release (the others still authorize it)."""
    result = first(receipt, lambda r: len(r["owners"]) >= 2 and not r["extra_receivers"])
    gone = result["owners"][-1]
    for release in result["releases"].values():
        release["rows"] = [row for row in release["rows"] if row.rstrip("*") != gone]
        release["authorized_by"] = [owner for owner in release["authorized_by"] if owner != gone]


def authorized_by_does_not_follow_the_rows(receipt):
    first(receipt, lambda r: True)["releases"]["after"]["authorized_by"] = ["not.a.Owner"]


def move_a_release(receipt):
    first(receipt, lambda r: True)["releases"]["after"]["env"] = "py3.8 not-the-verified-release==1"


def python_of_a_release_changed(receipt):
    first(receipt, lambda r: True)["releases"]["after"]["python"] = "2.7.18"


def installed_versions_forgotten(receipt):
    for result in receipt["results"]:
        for release in result["releases"].values():
            release["dists"] = {}


def a_pinned_version_that_did_not_run(receipt):
    result = first(receipt, lambda r: r["key"] == "api:Graph.node")
    result["releases"]["after"]["dists"] = {"networkx": "2.3"}          # the environment pins networkx==2.4


def the_provider_of_the_module_is_not_recorded(receipt):
    for result in receipt["results"]:
        for role, release in result["releases"].items():
            if role.partition("#")[0] != "before":
                release.pop("stdlib", None)
                release["providers"] = {}


def another_distribution_provides_the_module(receipt):
    result = first(receipt, lambda r: r["key"] == "api:Graph.node")
    for role, release in result["releases"].items():
        if role.partition("#")[0] != "before" and "providers" in release:
            release["providers"] = {top: ["notnetworkx"] for top in release["providers"]}


def the_lookup_before_the_removal_failed(receipt):
    first(receipt, lambda r: True)["releases"]["before"].update(access="AttributeError", message="'x' object has no attribute 'y'")


def a_release_did_not_run(receipt):
    first(receipt, lambda r: True)["releases"]["after"]["crash"] = "boom"


def the_message_is_for_another_attribute(receipt):
    """failUnless is a substring of the message of failUnlessEqual."""
    pasted = first(receipt, lambda r: r["key"] == "attribute:failUnlessEqual")["releases"]
    first(receipt, lambda r: r["key"] == "attribute:failUnless")["releases"] = copy.deepcopy(pasted)


def the_receiver_is_not_plain(receipt):
    first(receipt, lambda r: True)["releases"]["after"]["plain"] = False


def hollow_the_product(receipt):
    for result in receipt["results"]:
        result["product"]["product"]["issues"] = []
        result["product"]["product"]["steps"] = []


def drop_the_action_of_one_key(receipt):
    first(receipt, lambda r: True)["product"]["product"]["steps"] = []


def blank_the_replacement_of_one_key(receipt):
    for step in first(receipt, lambda r: True)["product"]["product"]["steps"]:
        step[1] = "Change the code."


def the_tail_of_the_replacement_is_not_shown(receipt):
    """Only the first 60 characters of the replacement used to be compared."""
    result = first(receipt, lambda r: True)
    replacement = domain.load()["removed_index"][result["key"]]["replacement"]
    step = result["product"]["product"]["steps"][0]
    assert replacement in step[1]
    step[1] = step[1].replace(replacement, replacement[:60])


def the_removal_version_is_not_shown(receipt):
    result = first(receipt, lambda r: True)
    step = result["product"]["product"]["steps"][0]
    step[0] = re.sub(r"removed in (\S+) \S+$", r"removed in \1 999", step[0])
    step[1] = re.sub(r"\(removed in [^)]*\)", "(removed in 999)", step[1])


def the_removal_step_is_not_the_first(receipt):
    steps = first(receipt, lambda r: True)["product"]["product"]["steps"]
    steps.reverse()


def wrong_rule_for_one_key(receipt):
    for issue in first(receipt, lambda r: r["kind"] == "attribute")["product"]["product"]["issues"]:
        issue[3] = "D02"


def not_a_version_issue(receipt):
    for issue in first(receipt, lambda r: True)["product"]["product"]["issues"]:
        issue[1] = "code_defect"


def the_classifier_decided(receipt):
    for result in receipt["results"]:
        for issue in result["product"]["product"]["issues"]:
            issue[2] = "classifier"


def the_record_of_another_job(receipt):
    first(receipt, lambda r: True)["product"]["product"]["id"] = "api:Somebody.else"


def hollow_the_twin(receipt):
    for result in receipt["results"]:
        result["product"]["twin"]["issues"] = []
        result["product"]["twin"]["steps"] = []


def twin_without_a_failing_run(receipt):
    first(receipt, lambda r: True)["product"]["twin"]["issues"] = []


def twin_of_another_class(receipt):
    for result in receipt["results"]:
        for issue in result["product"]["twin"]["issues"]:
            issue[0] = re.sub(r"'[^']*' object", "'Unrelated' object", issue[0])


def twin_shown_the_library_advice(receipt):
    result = first(receipt, lambda r: True)
    result["product"]["twin"]["steps"] = copy.deepcopy(result["product"]["product"]["steps"])


def twin_authorized(receipt):
    result = first(receipt, lambda r: True)
    result["product"]["twin"]["removal_owner"] = [result["key"]]


def twin_diagnosed_as_a_version_problem(receipt):
    for issue in first(receipt, lambda r: True)["product"]["twin"]["issues"]:
        issue[1] = "version_incompatibility"


def overlapping_authorization(receipt):
    result = first(receipt, lambda r: True)
    result["product"]["product"]["removal_owner"] = [result["key"], "api:Graph.node"]


def drop_a_further_receiver(receipt):
    first(receipt, lambda r: r["product"]["extra"])["product"]["extra"].pop()


def hollow_a_further_receiver(receipt):
    first(receipt, lambda r: r["product"]["extra"])["product"]["extra"][0] = {}


def the_product_record_of_the_receiver_and_of_its_further_one_swapped(receipt):
    product = first(receipt, lambda r: r["product"]["extra"])["product"]
    product["product"], product["extra"][0] = product["extra"][0], product["product"]


def edit_a_recipe_without_the_hash(receipt):
    first(receipt, lambda r: True)["recipe"] += "\n# changed\n"


def duplicate_a_record(receipt):
    receipt["results"].append(copy.deepcopy(receipt["results"][0]))


def drop_a_record(receipt):
    receipt["results"].pop()


def a_record_of_a_key_without_owners(receipt):
    stray = copy.deepcopy(receipt["results"][0])
    stray["key"] = "api:NoOwners.anything"
    receipt["results"].append(stray)


def forget_the_run_of_the_product(receipt):
    first(receipt, lambda r: True)["product"] = None


def the_block_hash_changed(receipt):
    first(receipt, lambda r: True)["block_sha256"] = "0" * 64


def the_owners_of_the_record_changed(receipt):
    first(receipt, lambda r: True)["owners"] = ["somebody.Else"]


def the_kind_of_the_record_changed(receipt):
    result = first(receipt, lambda r: True)
    result["kind"] = "attribute" if result["kind"] == "api" else "api"


def the_status_says_fail(receipt):
    first(receipt, lambda r: True)["status"] = "fail"


def problems_are_listed_on_a_pass(receipt):
    first(receipt, lambda r: True)["problems"] = ["something"]


def problems_are_none(receipt):
    first(receipt, lambda r: True)["problems"] = None


def lie_in_the_summary(receipt):
    receipt["summary"]["passed"] -= 1


def the_summary_is_true_by_python_equality(receipt):
    receipt["summary"]["e2e"] = 1
    receipt["summary"]["failed"] = False


def release_of_the_product_moved(receipt):
    first(receipt, lambda r: True)["product"]["release"] = "before"


def a_key_that_is_a_list(receipt):
    receipt["results"][0]["key"] = ["api:Graph.node"]


def merged_without_releases(receipt):
    receipt["merged"][0]["releases"] = {}


def merged_dropped(receipt):
    receipt["merged"].pop()


def merged_duplicated(receipt):
    receipt["merged"].append(copy.deepcopy(receipt["merged"][0]))


def merged_points_elsewhere(receipt):
    receipt["merged"][0]["target"] = "api:Graph.add_path"


def merged_without_the_product(receipt):
    for result in receipt["merged"]:
        result["product"]["product"]["steps"] = []
        result["product"]["twin"]["issues"] = []


def merged_authorizes_another_entry(receipt):
    result = receipt["merged"][0]
    result["product"]["product"]["removal_owner"] = ["api:Graph.add_path"]


def merged_target_hash_changed(receipt):
    receipt["merged"][0]["target_block_sha256"] = "0" * 64


def merged_recipe_changed(receipt):
    receipt["merged"][0]["recipe"] += "\n# changed\n"


def merged_key_key_is_a_dict(receipt):
    receipt["merged"][0]["key"] = {"api": "DiGraph.node"}


def merged_records_swapped(receipt):
    """The receivers of api:DiGraph.node and api:MultiGraph.node exchanged (everything else stays with its key)."""
    by_key = {r["key"]: r for r in receipt["merged"]}
    first_record, second = by_key["api:DiGraph.node"], by_key["api:MultiGraph.node"]
    for field in ("releases", "product"):
        first_record[field], second[field] = second[field], first_record[field]


def merged_receiver_is_of_another_class(receipt):
    """The releases of a plain Graph pasted into every merged record of the Graph family."""
    graph = first(receipt, lambda r: r["key"] == "api:Graph.node")["releases"]
    for result in receipt["merged"]:
        if result["target"].startswith("api:Graph."):
            result["releases"] = {role: copy.deepcopy(graph.get(role, graph["after"])) for role in result["releases"]}


def merged_receiver_without_its_own_class_row(receipt):
    """The identities of the receiver without the rows of its own class (the base class rows still authorize it, so nothing else changes)."""
    for result in receipt["merged"]:
        cls = result["releases"]["after"]["type"][1]
        for release in result["releases"].values():
            release["rows"] = [row for row in release["rows"] if not (row.endswith("*") and row.rstrip("*").rpartition(".")[2] == cls)]


MUTATIONS = [hollow_releases, hollow_one_release, hollow_every_release_payload, forget_the_owner_in_one_release, forget_a_declared_owner_everywhere,
             authorized_by_does_not_follow_the_rows, move_a_release, python_of_a_release_changed, installed_versions_forgotten,
             a_pinned_version_that_did_not_run, the_provider_of_the_module_is_not_recorded, another_distribution_provides_the_module,
             the_lookup_before_the_removal_failed, a_release_did_not_run, the_message_is_for_another_attribute, the_receiver_is_not_plain,
             hollow_the_product, drop_the_action_of_one_key, blank_the_replacement_of_one_key, the_tail_of_the_replacement_is_not_shown,
             the_removal_version_is_not_shown, the_removal_step_is_not_the_first, wrong_rule_for_one_key, not_a_version_issue, the_classifier_decided,
             the_record_of_another_job, hollow_the_twin, twin_without_a_failing_run, twin_of_another_class, twin_shown_the_library_advice,
             twin_authorized, twin_diagnosed_as_a_version_problem, overlapping_authorization, drop_a_further_receiver, hollow_a_further_receiver,
             the_product_record_of_the_receiver_and_of_its_further_one_swapped, edit_a_recipe_without_the_hash, duplicate_a_record, drop_a_record,
             a_record_of_a_key_without_owners, forget_the_run_of_the_product, the_block_hash_changed, the_owners_of_the_record_changed,
             the_kind_of_the_record_changed, the_status_says_fail, problems_are_listed_on_a_pass, problems_are_none, lie_in_the_summary,
             the_summary_is_true_by_python_equality, release_of_the_product_moved, a_key_that_is_a_list,
             merged_without_releases, merged_dropped, merged_duplicated, merged_points_elsewhere, merged_without_the_product,
             merged_authorizes_another_entry, merged_target_hash_changed, merged_recipe_changed, merged_key_key_is_a_dict, merged_records_swapped,
             merged_receiver_is_of_another_class, merged_receiver_without_its_own_class_row]


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda f: f.__name__)
def test_an_emptied_or_edited_record_is_rejected(receipt, verifier, inputs, mutation):
    changed = copy.deepcopy(receipt)
    mutation(changed)
    assert audit(verifier, inputs, changed), f"{mutation.__name__}: the record still passes"


def test_what_the_audit_takes_as_stored_is_the_raw_measurement_only(receipt, verifier, inputs):
    """Documented limits: the identities (rows), the messages and the unpinned installed versions are what the run saw, only a new run can show them
    again; the order of keys and of lists does not matter."""
    changed = copy.deepcopy(receipt)
    changed["results"].reverse()
    changed["merged"].reverse()
    for result in changed["results"]:
        for release in result["releases"].values():
            release["authorized_by"] = list(reversed(release["authorized_by"]))
    changed["summary"]["new_field"] = 1
    changed["tool"]["generated"] = "1999-01-01"
    assert audit(verifier, inputs, changed) == []


def test_a_name_is_a_word_not_a_substring(verifier):
    assert verifier.names_attribute("'T' object has no attribute 'failUnlessEqual'", "failUnlessEqual")
    assert not verifier.names_attribute("'T' object has no attribute 'failUnlessEqual'", "failUnless")
    assert not verifier.names_attribute("'T' object has no attribute 'xassert_'", "assert_")
    assert verifier.names_attribute("'Select' object has no attribute 'c'", "c")
    assert not verifier.names_attribute("'Select' object has no attribute 'columns'", "c")
    assert verifier.names_attribute("`ptp` was removed from the ndarray class in NumPy 2.0", "ptp")
    assert not verifier.names_attribute(None, "ptp") and not verifier.names_attribute(["ptp"], "ptp")


def test_the_rows_of_a_run_are_judged_clause_by_clause(verifier):
    """check_rows: every clause rejects its counterexample (the clauses were once relaxed without a test noticing)."""
    item = {"key": "api:Graph.node", "kind": "api", "attribute": "node", "distribution": "networkx", "owners": ["networkx.Graph", "networkx.classes.Graph"]}
    good = {"python": "3.12.1", "access": "AttributeError", "message": "'Graph' object has no attribute 'node'", "plain": True, "dynamic": False,
            "member_present": False, "stdlib": {"networkx": False}, "providers": {"networkx": ["networkx"]},
            "rows": [["networkx.classes.graph", "Graph", True], ["networkx.classes", "Graph", True], ["networkx", "Graph", True]], "env": "e"}
    before = {"python": "3.12.1", "access": "ok", "plain": True, "rows": [], "env": "e"}
    runs = {"before": before, "after": good}
    assert verifier.check_rows(item, runs) == []
    assert verifier.check_rows(item, {}) and verifier.check_rows(item, {"after": good}) and verifier.check_rows(item, {"before": before})
    assert verifier.check_rows(item, {**runs, "before": {**before, "access": "AttributeError"}})                 # the lookup before must work
    assert verifier.check_rows(item, {**runs, "after": {**good, "access": "ok"}})                                # the lookup after must fail
    assert verifier.check_rows(item, {**runs, "after": {**good, "message": "no such thing"}})                    # about this attribute
    assert verifier.check_rows(item, {**runs, "after": {**good, "message": "'Graph' object has no attribute 'nodes'"}})
    assert verifier.check_rows(item, {**runs, "after": {**good, "crash": "boom"}})                               # a release that did not run
    assert verifier.check_rows(item, {**runs, "after": {**good, "setup_error": "boom"}})
    assert verifier.check_rows(item, {**runs, "after": {**good, "probe_error": "boom"}})
    assert verifier.check_rows(item, {**runs, "after": {**good, "plain": False}})
    assert verifier.check_rows(item, {**runs, "after": {**good, "rows": [["networkx", "Graph", True]]}})        # a declared owner that is no identity (phantom)
    assert verifier.check_rows(item, {**runs, "after": {**good, "rows": [["other", "Graph", True]]}})           # no declared owner is an identity
    assert verifier.check_rows(item, {**runs, "after": {**good, "providers": {"networkx": ["notnetworkx"]}}})   # another distribution provides the module
    assert verifier.check_rows(item, {**runs, "after": {k: v for k, v in good.items() if k != "stdlib"}})       # Python 3.10+ can tell: no evidence is a problem
    assert verifier.check_rows(item, {**runs, "after": {**good, "providers": []}})
    assert verifier.check_rows(item, {**runs, "after": {**good, "dynamic": True, "rows": [[m, o, False] for m, o, _ in good["rows"]]}})  # inherited only
    assert verifier.check_rows({**item, "owners": ["networkx.Graph"]}, {**runs, "after": {**good, "rows": [["networkx", "Graph", True]]}}) == []
    old = {**good, "python": "3.9.9"}
    old.pop("stdlib")
    old["providers"] = {}
    assert verifier.check_rows(item, {**runs, "after": old}) == []             # Python before 3.10 cannot tell the provider: only then is the evidence optional
    assert verifier.check_rows(item, {**runs, "after": good}, phantom_check=False) == []
    phantom = {**item, "owners": [*item["owners"], "networkx.Phantom"]}
    assert verifier.check_rows(phantom, runs) and verifier.check_rows(phantom, runs, phantom_check=False) == []


def test_a_negative_is_not_a_missing_record(verifier):
    item = {"key": "api:Graph.node", "kind": "api", "module": "Graph", "attribute": "node", "version": "2.4",
            "replacement": "G.nodes, the node view that has existed since NetworkX 2.0"}
    assert verifier.judge_twin(item, None) and verifier.judge_twin(item, {}) and verifier.judge_twin(item, {"issues": [], "steps": []})
    failing = {"id": "twin:api:Graph.node", "removal_owner": [], "steps": [],
               "issues": [["AttributeError: 'Graph' object has no attribute 'node'", "code_defect", "rule", "D43"]]}
    assert verifier.judge_twin(item, failing) == []
    assert verifier.judge_twin(item, failing, "twin:api:Graph.node") == [] and verifier.judge_twin(item, failing, "twin:api:Other.node")
    assert verifier.judge_twin(item, {**failing, "removal_owner": ["api:Graph.node"]})
    assert verifier.judge_twin(item, {**failing, "issues": [["AttributeError: 'Unrelated' object has no attribute 'node'", "code_defect", "rule", "D43"]]})
    assert verifier.judge_twin(item, {**failing, "issues": [["AttributeError: 'Graph' object has no attribute 'other'", "code_defect", "rule", "D43"]]})
    assert verifier.judge_twin(item, {**failing, "issues": [["AttributeError: 'Graph' object has no attribute 'node'", "version_incompatibility", "rule", "D02"]]})
    assert verifier.judge_twin(item, {**failing, "steps": [["Replace Graph.node: removed in networkx 2.4", "Use G.nodes, the node view that has existed since NetworkX 2.0."]]})
    assert verifier.judge_product(item, None) and verifier.judge_product(item, {"error": "boom"})
    assert verifier.judge_twin({**item, "attribute": "c"}, {**failing, "issues": [["AttributeError: 'Graph' object has no attribute 'node'", "code_defect", "rule", "D43"]]})


def test_the_removal_action_and_its_replacement_are_part_of_the_judgement(verifier):
    item = {"key": "api:Graph.node", "kind": "api", "attribute": "node", "version": "2.4",
            "replacement": "G.nodes, the node view that has existed since NetworkX 2.0, so G.node[n] becomes G.nodes[n] in every use of the old name"}
    step = ["Replace Graph.node: removed in networkx 2.4",
            f"The target interpreter has networkx 3.7, which no longer provides Graph.node (removed in 2.4). Change the code to use {item['replacement']}. Keeping the old API ..."]
    record = {"id": "api:Graph.node", "issues": [["AttributeError: 'Graph' object has no attribute 'node'", "version_incompatibility", "rule", "D02"]],
              "removal_owner": ["api:Graph.node"], "steps": [step, ["Re-run the same program", "Only the issues ..."]]}
    assert verifier.judge_product(item, record) == [] and verifier.judge_product(item, record, "api:Graph.node") == []
    assert verifier.judge_product(item, record, "api:Other.node")                                          # the record of another job
    assert verifier.judge_product(item, {**record, "steps": []})
    assert verifier.judge_product(item, {**record, "steps": [[step[0], "Change the code."]]})
    tail = {**record, "steps": [[step[0], step[1].replace(item["replacement"], item["replacement"][:60])]]}
    assert verifier.judge_product(item, tail)                                                              # the whole replacement, not its head
    assert verifier.judge_product(item, {**record, "steps": [["Re-run the same program", step[1]]]})
    assert verifier.judge_product(item, {**record, "steps": [record["steps"][1], step]})                    # the first step, the one the user sees
    assert verifier.judge_product(item, {**record, "steps": [[step[0].replace("2.4", "9.9"), step[1]]]})   # the removal version
    assert verifier.judge_product(item, {**record, "steps": [[step[0], step[1].replace("(removed in 2.4)", "(removed in 9.9)")]]})
    assert verifier.judge_product(item, {**record, "issues": []})
    assert verifier.judge_product(item, {**record, "issues": [["AttributeError: 'Graph' object has no attribute 'node'", "version_incompatibility", "classifier", "D02"]]})
    assert verifier.judge_product(item, {**record, "issues": [["AttributeError: 'Graph' object has no attribute 'other'", "version_incompatibility", "rule", "D02"]]})
    assert verifier.judge_product(item, {**record, "removal_owner": ["api:Graph.node", "api:Other.node"]})
    assert verifier.judge_product(item, {**record, "removal_owner": []})
    assert verifier.judge_product({**item, "kind": "attribute"}, record)                                   # an attribute entry is decided by D03


def test_exactly_one_entry_of_the_whole_knowledge_base_authorizes_a_receiver(verifier, inputs, receipt):
    """The record is replayed against EVERY entry of the shipped knowledge base, not only against the key it belongs to."""
    assert audit(verifier, inputs, receipt) == []
    some = inputs.items[0]
    twin = {**inputs.index[some["key"]], "id": "api:Elsewhere." + some["attribute"], "kind": "api", "module": "Elsewhere", "name": some["attribute"]}
    problems = verifier.audit_receipt(receipt, inputs.items, inputs.recipes, {**inputs.index, twin["id"]: twin}, inputs.merged)
    assert any(p.startswith(some["key"]) and "not by exactly" in p for p in problems)    # a second entry with the same owners shows the step twice


# ---------------------------------------------------------------------------------------------------------------------------------------
# merged keys (O-R4): a key that is not enabled because an enabled entry covers it is verified with its own receiver
# ---------------------------------------------------------------------------------------------------------------------------------------
def test_every_merged_key_has_a_passing_record_with_the_entry_that_covers_it(receipt, inputs):
    by_key = {r["key"]: r for r in receipt["merged"]}
    assert len(by_key) == len(receipt["merged"]) == len(inputs.merged)
    for entry in inputs.merged:
        assert entry["problems"] == [], (entry["key"], entry["problems"])
        result = by_key[entry["key"]]
        assert result["status"] == "pass" and result["target"] == entry["target"]
        assert entry["target"] in inputs.index and entry["target"] in inputs.dispositions["merged"][entry["group"] - 1]["covered_by"]
        for role, release in result["releases"].items():
            assert release["type"][1] == entry["source"]["module"], (entry["key"], role)          # the receiver is an object of the merged class
            if role.partition("#")[0] != "before":
                assert release["authorized_by"], (entry["key"], role)           # the covering entry authorizes the receiver
        assert result["product"]["product"]["removal_owner"] == [entry["target"]]   # and no other entry does


def test_merged_keys_must_be_covered_by_the_same_removal(verifier, inputs):
    """O-R4: `covered_by` was only checked to hold some enabled key; a group pointed at an unrelated entry still passed."""
    groups = copy.deepcopy(inputs.dispositions)
    for group in groups["merged"]:
        group["covered_by"] = ["api:Graph.node"]
    problems = [p for m in verifier.load_merged(groups, inputs.candidates, inputs.index) for p in m["problems"]]
    assert any("exactly one entry that ends in" in p for p in problems)
    # two entries of the group end in the same attribute: which one covers?
    groups = copy.deepcopy(inputs.dispositions)
    first_key = groups["merged"][0]["keys"][0]
    attribute = first_key.rsplit(".", 1)[-1]
    covering = next(k for k in groups["merged"][0]["covered_by"] if k.rsplit(".", 1)[-1] == attribute)
    groups["merged"][0]["covered_by"] = [*groups["merged"][0]["covered_by"], f"api:Another.{attribute}"]
    index = {**inputs.index, f"api:Another.{attribute}": {**inputs.index[covering], "id": f"api:Another.{attribute}", "module": "Another"}}
    assert any("exactly one entry that ends in" in p for m in verifier.load_merged(groups, inputs.candidates, index) for p in m["problems"])
    # a covering entry that cannot authorize any receiver (no qualified owner)
    ownerless = {**inputs.index["api:Graph.add_path"], "owners": [], "module": "Graph"}
    ownerless.pop("owners")
    problems = [p for m in verifier.load_merged(inputs.dispositions, inputs.candidates, {**inputs.index, "api:Graph.add_path": ownerless}) for p in m["problems"]]
    assert any("no qualified owner" in p for p in problems)
    # an entry of the same attribute but another removal is not a cover
    other = {**inputs.index["api:Graph.add_path"], "version": "9.9"}
    changed_index = {**inputs.index, "api:Graph.add_path": other}
    problems = [p for m in verifier.load_merged(inputs.dispositions, inputs.candidates, changed_index) for p in m["problems"]]
    assert any("differ in version" in p for p in problems)
    other = {**inputs.index["api:Graph.add_path"], "distribution": "somethingelse"}
    problems = [p for m in verifier.load_merged(inputs.dispositions, inputs.candidates, {**inputs.index, "api:Graph.add_path": other}) for p in m["problems"]]
    assert any("differ in distribution" in p for p in problems)
    other = {**inputs.index["api:Graph.add_path"], "source": "some-other-source"}
    problems = [p for m in verifier.load_merged(inputs.dispositions, inputs.candidates, {**inputs.index, "api:Graph.add_path": other}) for p in m["problems"]]
    assert any("differ in source" in p for p in problems)
    other = {**inputs.index["api:Graph.add_path"], "replacement": "something else entirely"}
    problems = [p for m in verifier.load_merged(inputs.dispositions, inputs.candidates, {**inputs.index, "api:Graph.add_path": other}) for p in m["problems"]]
    assert any("replacement_note" in p for p in problems)
    # a note for identical replacements, and a group that does not say why
    groups = copy.deepcopy(inputs.dispositions)
    groups["merged"][0]["replacement_note"] = "they differ"
    assert any("replacement_note but the replacements are identical" in p for m in verifier.load_merged(groups, inputs.candidates, inputs.index) for p in m["problems"])
    groups = copy.deepcopy(inputs.dispositions)
    groups["merged"][0]["why"] = " "
    assert any("says nothing about why" in p for m in verifier.load_merged(groups, inputs.candidates, inputs.index) for p in m["problems"])


def test_a_merged_key_is_listed_once_and_is_not_enabled(receipt, verifier, inputs):
    groups = copy.deepcopy(inputs.dispositions)
    groups["merged"].append({"keys": [groups["merged"][0]["keys"][0]], "covered_by": groups["merged"][0]["covered_by"], "why": "again"})
    problems = [p for m in verifier.load_merged(groups, inputs.candidates, inputs.index) for p in m["problems"]]
    assert any("is merged twice" in p for p in problems)
    unknown = copy.deepcopy(inputs.dispositions)
    unknown["merged"][0]["keys"].append("api:NotACandidate.node")
    problems = [p for m in verifier.load_merged(unknown, inputs.candidates, inputs.index) for p in m["problems"]]
    assert any("is not a candidate" in p for p in problems)
    # the audit refuses a receipt that lacks the record of a key that became merged
    assert audit(verifier, inputs, copy.deepcopy(receipt), merged=verifier.load_merged(unknown, inputs.candidates, inputs.index))


def test_every_duplicate_among_the_dispositions_is_visible():
    """The old check collapsed the merged keys in a dict, so a candidate listed twice looked like one."""
    dispositions = toml(FOLDER / "owners" / "dispositions.toml")
    merged = [k for group in dispositions["merged"] for k in group["keys"]]
    assert len(merged) == len(set(merged)) == 23
    parked = [k for group in dispositions["parked"] for k in group["keys"]]
    assert len(parked) == len(set(parked))
    assert not set(merged) & set(parked)
