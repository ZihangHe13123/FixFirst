"""The simulation evidence's comparison script refuses evidence that does not hang together
(experiments/agent_baseline/simulation-evidence-e9f5b90/compare.py), on tampered copies of the packages."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

BASELINE = Path(__file__).resolve().parents[1] / "experiments" / "agent_baseline"
NEW, OLD = "simulation-evidence-e9f5b90", "simulation-evidence-20261002"
spec = importlib.util.spec_from_file_location("evidence_compare", BASELINE / NEW / "compare.py")
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


@pytest.fixture
def copies(tmp_path):
    """Both packages under tmp/experiments/agent_baseline/, as the manifests' relative paths expect."""
    for name in (NEW, OLD):
        shutil.copytree(BASELINE / name, tmp_path / "experiments" / "agent_baseline" / name)
    return tmp_path / "experiments" / "agent_baseline"


def rewrite(copies, package, key, change):
    """Change one output and bring its manifest's digest along, as a careless reassembly would."""
    folder = "after" if package == OLD else "results"
    path = copies / package / folder / f"{key}.json"
    content = json.loads(path.read_text())
    change(content)
    path.write_text(json.dumps(content, indent=1) + "\n")
    manifest_path = copies / package / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    entry = manifest["settings"][key]["after"] if package == OLD else manifest["settings"][key]
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")


def test_the_committed_evidence_passes_and_gives_the_committed_table(copies):
    text = compare.build(copies / NEW)
    assert text == (BASELINE / NEW / "COMPARISON.md").read_text(encoding="utf-8")
    table = [line for line in text.splitlines() if line.startswith("|")]
    assert len({line.count("|") for line in table}) == 1 and len(table) == 2 + 41  # header, separator, 41 rows


def set_tasks(content):
    content["tasks"] = 999


def set_effect(content):
    content["simulation"][1]["effect"] = 0.123


def set_listed_effects(content):
    content["effects"][1] = 0.123


def drop_row(content):
    del content["simulation"][-1]


def raise_count(content):
    content["simulation"][0]["counts"]["t_covers"] += 1


def shift_partition(content):  # shares follow the counts, but the zero-effect split no longer adds up
    row = content["simulation"][0]
    row["counts"]["bootstrap_covers"] += 1
    row["bootstrap_covers_truth"] = round(row["counts"]["bootstrap_covers"] / row["counts"]["replicates"], 3)
    with_interval = row["counts"]["replicates"] - row["counts"]["no_bootstrap_interval"]
    row["bootstrap_covers_truth_given_interval"] = round(row["counts"]["bootstrap_covers"] / with_interval, 3)


@pytest.mark.parametrize("packages,change,reason", [
    ((NEW,), set_tasks, "its tasks is 999"),  # Codex R6-1: a wrong parameter whose digest was updated with it
    ((NEW, OLD), set_effect, "not the manifest's effects"),  # R6-1: the same wrong effect on both sides
    ((OLD,), set_listed_effects, "its effects is"),
    ((NEW,), drop_row, "not the manifest's effects"),
    ((NEW,), raise_count, "t_interval_covers_truth"),
    ((NEW,), shift_partition, "do not add up"),
])
def test_an_output_that_contradicts_its_own_manifest_is_refused_even_with_its_digest_updated(copies, packages,
                                                                                            change, reason):
    for package in packages:
        rewrite(copies, package, "F8x3", change)
    with pytest.raises(SystemExit, match=reason):
        compare.build(copies / NEW)


def test_a_changed_output_with_the_old_digest_is_refused(copies):
    path = copies / NEW / "results" / "A.json"
    path.write_text(path.read_text().replace("0.059", "0.058", 1))
    with pytest.raises(SystemExit, match="SHA-256 differs"):
        compare.build(copies / NEW)
