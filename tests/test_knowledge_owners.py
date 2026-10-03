"""The owners of the shipped removal knowledge must still match the record of their last execution-based verification
(scripts/knowledge_verify/verify_owners.py).

A removal block with `owners` is applied only to an object whose class is one of the named library classes, so `owners` is a claim about a
real class. The verification builds a real object of each class in the releases that prove the removal, asks the product's own receiver
identity code which classes it has, and lets FixFirst itself diagnose a script that ends in the missing attribute (and a project class with
the same name). The candidates that were merged into an enabled entry are verified the same way with their own receivers.

These tests run offline: they do not repeat that (it needs the network and many interpreters, see the README there). They judge the stored
record AGAIN from the details it holds, with the functions that judged the run, so a record that was emptied or edited does not pass; they fail
when a block with owners is edited, added or dropped without verifying again, when the receiver-identity code or the code and rules that
produce the diagnosis changed, or when the record is not a complete pass.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
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
    assert all(not r["problems"] for r in receipt["results"] + receipt["merged"])
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
    digests = verifier.product_digests(str(ROOT / "src" / "fixfirst"))
    # layer 1: owners are claims about receiver identities as the probe computes them
    assert digests["identity_functions_sha256"] == tool["identity_functions_sha256"]
    # layer 2: the product code and rules that turn those identities into a diagnosis and a plan (the E2E runs of the record)
    assert set(tool["e2e_files_sha256"]) == set(verifier.E2E_FILES) and set(tool["e2e_rules_sha256"]) == set(verifier.E2E_RULES)
    for name, expected in tool["e2e_files_sha256"].items():
        assert digests["e2e_files_sha256"][name] == expected, f"{name} changed after the record was made: verify again"
    for rule, expected in tool["e2e_rules_sha256"].items():
        assert digests["e2e_rules_sha256"][rule] == expected, f"rule {rule} changed after the record was made: verify again"
    assert re.fullmatch(r"[0-9a-f]{64}", tool["package_sha256"])    # informational: the digest of every other file of the package


def test_the_digests_of_the_product_follow_the_code_each_layer_depends_on(verifier, tmp_path):
    package = tmp_path / "fixfirst"
    shutil.copytree(ROOT / "src" / "fixfirst", package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    before = verifier.product_digests(str(package))
    # a file of the E2E layer, but not an identity function
    with open(package / "removal_ownership.py", "a", encoding="utf-8") as stream:
        stream.write("\n# changed\n")
    after = verifier.product_digests(str(package))
    assert after["e2e_files_sha256"]["removal_ownership.py"] != before["e2e_files_sha256"]["removal_ownership.py"]
    assert after["identity_functions_sha256"] == before["identity_functions_sha256"] and after["e2e_rules_sha256"] == before["e2e_rules_sha256"]
    # an identity function of the probe (and so also the file that holds it)
    source = (package / "_runtime_evidence.py").read_text(encoding="utf-8")
    marker = "def receiver_owners(value):"
    assert marker in source
    (package / "_runtime_evidence.py").write_text(source.replace(marker, marker + "  # changed", 1), encoding="utf-8")
    changed = verifier.product_digests(str(package))
    assert changed["identity_functions_sha256"] != before["identity_functions_sha256"]
    assert changed["e2e_files_sha256"]["_runtime_evidence.py"] != before["e2e_files_sha256"]["_runtime_evidence.py"]
    # a rule that makes or renders the diagnosis
    rules = (package / "knowledge" / "rules.toml").read_text(encoding="utf-8")
    assert 'id = "D02"' in rules
    (package / "knowledge" / "rules.toml").write_text(rules.replace('id = "D02"\nphase = "diagnose"\ndescription = "', 'id = "D02"\nphase = "diagnose"\ndescription = "Changed. ', 1), encoding="utf-8")
    assert verifier.product_digests(str(package))["e2e_rules_sha256"]["D02"] != before["e2e_rules_sha256"]["D02"]
    # any other file moves only the informational digest of the whole package
    (package / "report.py").write_text((package / "report.py").read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    other = verifier.product_digests(str(package))
    assert other["package_sha256"] != before["package_sha256"] and other["e2e_files_sha256"].get("report.py") is None


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


def test_verify_owners_py_starts_and_documents_its_options():
    import subprocess
    import sys
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


def move_a_release(receipt):
    first(receipt, lambda r: True)["releases"]["after"]["env"] = "py3.8 not-the-verified-release==1"


def hollow_the_product(receipt):
    for result in receipt["results"]:
        result["product"]["product"]["issues"] = []
        result["product"]["product"]["steps"] = []


def drop_the_action_of_one_key(receipt):
    first(receipt, lambda r: True)["product"]["product"]["steps"] = []


def blank_the_replacement_of_one_key(receipt):
    for step in first(receipt, lambda r: True)["product"]["product"]["steps"]:
        step[1] = "Change the code."


def wrong_rule_for_one_key(receipt):
    for issue in first(receipt, lambda r: r["kind"] == "attribute")["product"]["product"]["issues"]:
        issue[3] = "D02"


def not_a_version_issue(receipt):
    for issue in first(receipt, lambda r: True)["product"]["product"]["issues"]:
        issue[1] = "code_defect"


def hollow_the_twin(receipt):
    for result in receipt["results"]:
        result["product"]["twin"]["issues"] = []
        result["product"]["twin"]["steps"] = []


def twin_without_a_failing_run(receipt):
    first(receipt, lambda r: True)["product"]["twin"]["issues"] = []


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


def edit_a_recipe_without_the_hash(receipt):
    first(receipt, lambda r: True)["recipe"] += "\n# changed\n"


def duplicate_a_record(receipt):
    receipt["results"].append(copy.deepcopy(receipt["results"][0]))


def drop_a_record(receipt):
    receipt["results"].pop()


def forget_the_run_of_the_product(receipt):
    first(receipt, lambda r: True)["product"] = None


def lie_in_the_summary(receipt):
    receipt["summary"]["passed"] -= 1


def release_of_the_product_moved(receipt):
    first(receipt, lambda r: True)["product"]["release"] = "before"


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


MUTATIONS = [hollow_releases, hollow_one_release, hollow_every_release_payload, forget_the_owner_in_one_release, move_a_release,
             hollow_the_product, drop_the_action_of_one_key, blank_the_replacement_of_one_key, wrong_rule_for_one_key, not_a_version_issue,
             hollow_the_twin, twin_without_a_failing_run, twin_shown_the_library_advice, twin_authorized, twin_diagnosed_as_a_version_problem,
             overlapping_authorization, drop_a_further_receiver, hollow_a_further_receiver, edit_a_recipe_without_the_hash,
             duplicate_a_record, drop_a_record, forget_the_run_of_the_product, lie_in_the_summary, release_of_the_product_moved,
             merged_without_releases, merged_dropped, merged_duplicated, merged_points_elsewhere, merged_without_the_product,
             merged_authorizes_another_entry]


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda f: f.__name__)
def test_an_emptied_or_edited_record_is_rejected(receipt, verifier, inputs, mutation):
    changed = copy.deepcopy(receipt)
    mutation(changed)
    assert audit(verifier, inputs, changed), f"{mutation.__name__}: the record still passes"


def test_a_negative_is_not_a_missing_record(verifier):
    item = {"key": "api:Graph.node", "kind": "api", "attribute": "node", "replacement": "G.nodes, the node view that has existed since NetworkX 2.0"}
    assert verifier.judge_twin(item, None) and verifier.judge_twin(item, {}) and verifier.judge_twin(item, {"issues": [], "steps": []})
    failing = {"issues": [["AttributeError: 'Graph' object has no attribute 'node'", "code_defect", "rule", "D43"]], "removal_owner": [], "steps": []}
    assert verifier.judge_twin(item, failing) == []
    assert verifier.judge_twin(item, {**failing, "removal_owner": ["api:Graph.node"]})
    assert verifier.judge_product(item, None) and verifier.judge_product(item, {"error": "boom"})


def test_the_removal_action_and_its_replacement_are_part_of_the_judgement(verifier):
    item = {"key": "api:Graph.node", "kind": "api", "attribute": "node", "replacement": "G.nodes, the node view that has existed since NetworkX 2.0"}
    record = {"issues": [["AttributeError: 'Graph' object has no attribute 'node'", "version_incompatibility", "rule", "D02"]],
              "removal_owner": ["api:Graph.node"],
              "steps": [["Replace Graph.node: removed in networkx 2.4", "Change the code to use G.nodes, the node view that has existed since NetworkX 2.0."]]}
    assert verifier.judge_product(item, record) == []
    assert verifier.judge_product(item, {**record, "steps": []})
    assert verifier.judge_product(item, {**record, "steps": [["Replace Graph.node: removed in networkx 2.4", "Change the code."]]})
    assert verifier.judge_product(item, {**record, "steps": [["Re-run the same program", record["steps"][0][1]]]})
    assert verifier.judge_product(item, {**record, "issues": []})
    assert verifier.judge_product({**item, "kind": "attribute"}, record)       # an attribute entry is decided by D03


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


def test_a_merged_key_is_listed_once_and_is_not_enabled(verifier, inputs):
    groups = copy.deepcopy(inputs.dispositions)
    groups["merged"].append({"keys": [groups["merged"][0]["keys"][0]], "covered_by": groups["merged"][0]["covered_by"], "why": "again"})
    problems = [p for m in verifier.load_merged(groups, inputs.candidates, inputs.index) for p in m["problems"]]
    assert any("is merged twice" in p for p in problems)
    unknown = copy.deepcopy(inputs.dispositions)
    unknown["merged"][0]["keys"].append("api:NotACandidate.node")
    problems = [p for m in verifier.load_merged(unknown, inputs.candidates, inputs.index) for p in m["problems"]]
    assert any("is not a candidate" in p for p in problems)
    # the audit refuses a receipt that lacks the record of a key that became merged
    assert audit(verifier, inputs, json.loads(RECEIPT.read_text(encoding="utf-8")), merged=verifier.load_merged(unknown, inputs.candidates, inputs.index))


def test_every_duplicate_among_the_dispositions_is_visible(verifier):
    """The old check collapsed the merged keys in a dict, so a candidate listed twice looked like one."""
    dispositions = toml(FOLDER / "owners" / "dispositions.toml")
    merged = [k for group in dispositions["merged"] for k in group["keys"]]
    assert len(merged) == len(set(merged)) == 23
    parked = [k for group in dispositions["parked"] for k in group["keys"]]
    assert len(parked) == len(set(parked))
    assert not set(merged) & set(parked)
