"""The family simulation's evidence is refused when it does not hang together
(experiments/agent_baseline/family-evidence-c464214/check.py), on tampered copies of the package."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

BASELINE = Path(__file__).resolve().parents[1] / "experiments" / "agent_baseline"
PACKAGE = "family-evidence-c464214"
spec = importlib.util.spec_from_file_location("family_check", BASELINE / PACKAGE / "check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.fixture
def copy(tmp_path):
    """The package under tmp/experiments/agent_baseline/, as the manifest's relative paths expect."""
    shutil.copytree(BASELINE / PACKAGE, tmp_path / "experiments" / "agent_baseline" / PACKAGE)
    return tmp_path / "experiments" / "agent_baseline" / PACKAGE


def rewrite(copy, key, change):
    """Change one output and bring its manifest's digest along, as a careless reassembly would."""
    path = copy / "results" / f"{key}.json"
    content = json.loads(path.read_text())
    change(content)
    path.write_text(json.dumps(content, indent=1) + "\n")
    manifest = json.loads((copy / "MANIFEST.json").read_text())
    manifest["settings"][key]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (copy / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")


def test_the_committed_evidence_passes_and_gives_the_committed_summary(copy):
    text = check.build(copy)
    assert text == (BASELINE / PACKAGE / "SUMMARY.md").read_text(encoding="utf-8")
    table = [line for line in text.splitlines() if line.startswith("|")]
    assert len({line.count("|") for line in table}) == 1 and len(table) == 2 + 13  # header, separator, 13 settings


def family(content):
    return content["family_simulation"]


def shares_follow(result, count, share, value):
    result["counts"][count] = value
    result[share] = round(value / result["counts"]["replicates"], 3)


ANY = (("any_rejection", "any_rejection_after_holm"), ("any_false_rejection", "any_false_rejection_after_holm"))
ANY_UNADJUSTED = (("any_p_below_alpha", "any_p_below_alpha_unadjusted"),
                  ("any_false_p_below_alpha", "any_false_p_below_alpha_unadjusted"))


@pytest.mark.parametrize("key,change,reason", [
    ("null", lambda c: c.update(tasks=999), "its tasks is 999"),
    ("null", lambda c: c.update(runs_per_model=[5, 5, 5]), "its runs_per_model is"),
    ("null-own-tasks", lambda c: c.update(shared_tasks=True), "its shared_tasks is True"),
    ("first-0.3", lambda c: family(c)["models"][0].update(effect=0.0), "not the manifest's runs and effects"),
    ("first-0.3", lambda c: family(c)["models"].reverse(), "not the manifest's runs and effects"),
    ("null", lambda c: family(c)["models"][0]["counts"].update(rejected=35), "rejected_after_holm 0.017 is not 35"),
    ("null", lambda c: family(c)["counts"].update(any_false_rejection=2.5), "not a whole number"),
    ("null", lambda c: family(c)["models"][2]["counts"].update(not_estimable=-1), "not a whole number"),
    ("null", lambda c: family(c)["models"][0].update(null_true=False), "null_true does not fit"),
    ("all-0.3", lambda c: family(c)["models"][0].update(null_true=True), "null_true does not fit"),
    ("null", lambda c: family(c).update(every_false_null_rejected_after_holm=0.0), "every_false_null_rejected_after_holm 0.0 does not follow"),
    ("all-0.3", lambda c: family(c).update(any_false_rejection_after_holm=0.0), "any_false_rejection_after_holm 0.0 does not follow"),
    # shares that follow their counts, but counts that contradict each other
    ("null", lambda c: (family(c)["models"][0]["counts"].update(rejected=124),
                        family(c)["models"][0].update(rejected_after_holm=0.062)), "Holm rejects more often"),
    ("first-0.3", lambda c: shares_follow(family(c), "any_false_rejection", "any_false_rejection_after_holm", 1500),
     "family counts contradict"),
    ("first-0.3", lambda c: shares_follow(family(c), "any_rejection", "any_rejection_after_holm", 1999),
     "family counts contradict"),
    ("null", lambda c: shares_follow(family(c), "any_false_rejection", "any_false_rejection_after_holm", 80),
     "every rejection is a false one"),
    ("null", lambda c: c.pop("family_simulation"), "no family simulation in it"),
    # Codex R9-4: the level the family was decided at is part of what the manifest says
    ("null", lambda c: family(c).update(alpha=0.5), "decided at alpha 0.5, its manifest says 0.05"),
    ("all-0.3", lambda c: family(c).pop("alpha"), "decided at alpha None"),
    # Codex R9-5: the family's counts against the models' own (shares kept in step, so only the counts disagree)
    ("null", lambda c: [shares_follow(family(c), name, share, 0) for name, share in ANY], "any_rejection is 0, but its models' own counts"),
    ("null", lambda c: [shares_follow(family(c), name, share, 90) for name, share in ANY], "put it between 36 and 89"),
    ("null", lambda c: [shares_follow(family(c), name, share, 100) for name, share in ANY_UNADJUSTED],
     "any_p_below_alpha is 100, but its models' own counts"),
    ("first-0.3", lambda c: shares_follow(family(c), "any_false_rejection", "any_false_rejection_after_holm", 20),
     "any_false_rejection is 20, but its models' own counts"),
    ("all-0.3", lambda c: shares_follow(family(c), "every_false_null_rejected", "every_false_null_rejected_after_holm", 900),
     "every_false_null_rejected is 900, but its models' own counts"),
    ("null", lambda c: family(c)["counts"].update(every_false_null_rejected=5), "every_false_null_rejected is 5, but its models' own counts .. put it between 0 and 0"),
    ("null", lambda c: (family(c)["models"][0]["counts"].update(not_estimable=1900), family(c)["models"][0].update(not_estimable=0.95)),
     "in replicates where it could not be estimated"),
])
def test_an_output_that_contradicts_its_manifest_or_itself_is_refused_even_with_its_digest_updated(copy, key, change, reason):
    rewrite(copy, key, change)
    with pytest.raises(SystemExit, match=reason):
        check.build(copy)


def test_the_settings_share_the_one_alpha_the_summary_names(copy):
    assert "Holm at 0.05 on the paired t-test's p-values" in check.build(copy) and "Any false p < 0.05, unadjusted" in check.build(copy)
    rewrite(copy, "null", lambda c: family(c).update(alpha=0.5))  # an output and its manifest entry agree on another level
    manifest = json.loads((copy / "MANIFEST.json").read_text())
    manifest["settings"]["null"]["alpha"] = 0.5
    (copy / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
    with pytest.raises(SystemExit, match="do not share one alpha"):
        check.build(copy)
    for key in manifest["settings"]:  # a whole package at another level is summarized at that level, not at 0.05
        rewrite(copy, key, lambda c: family(c).update(alpha=0.1))
    manifest = json.loads((copy / "MANIFEST.json").read_text())
    for setting in manifest["settings"].values():
        setting["alpha"] = 0.1
    (copy / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
    text = check.build(copy)
    assert "Holm at 0.1 on the paired t-test's p-values" in text and "Any false p < 0.1, unadjusted" in text
    assert "Holm at 0.05" not in text and "p < 0.05" not in text


@pytest.mark.parametrize("members,low,high", [([34, 36, 19], 36, 89), ([1500, 1900], 1900, 2000), ([0, 0], 0, 0), ([], 0, 0)])
def test_any_of_several_events_happens_between_the_most_frequent_one_and_all_together(members, low, high):
    for count in (low, high):
        check.union("k", "n", count, members, 2000)
    for count in (low - 1, high + 1):
        with pytest.raises(SystemExit, match="put it between"):
            check.union("k", "n", count, members, 2000)


@pytest.mark.parametrize("members,low,high", [([1175, 1113, 807], 0, 807), ([1900, 1800], 1700, 1800), ([2000, 2000, 5], 5, 5), ([], 0, 0)])
def test_all_of_several_events_happen_together_between_what_their_counts_force_and_the_rarest(members, low, high):
    for count in (low, high):
        check.intersection("k", "n", count, members, 2000)
    for count in (low - 1, high + 1):
        with pytest.raises(SystemExit, match="put it between"):
            check.intersection("k", "n", count, members, 2000)


def test_a_changed_output_with_the_old_digest_is_refused(copy):
    path = copy / "results" / "null.json"
    path.write_text(path.read_text().replace("0.043", "0.042", 1))
    with pytest.raises(SystemExit, match="SHA-256 differs"):
        check.build(copy)


def test_the_readmes_figures_are_the_results_counts():
    """Every figure the README quotes is recomputed from the integer counts and must be in its text as written."""
    package = BASELINE / PACKAGE
    readme = (package / "README.md").read_text(encoding="utf-8")
    manifest = json.loads((package / "MANIFEST.json").read_text())
    results = {key: json.loads((package / "results" / f"{key}.json").read_text())["family_simulation"] for key in manifest["settings"]}
    share = lambda result, count: 100 * count / result["counts"]["replicates"]  # noqa: E731
    family = lambda keys, count: [share(results[key], results[key]["counts"][count]) for key in keys]  # noqa: E731
    span = lambda values: f"{min(values):.2f}–{max(values):.2f}%"  # noqa: E731
    models = lambda key, count: [share(results[key], model["counts"][count]) for model in results[key]["models"]]  # noqa: E731
    nulls, partial = [key for key in results if key.startswith("null")], ["first-0.3", "two-0.3", "last-0.3"]
    assert len(nulls) == 6 and all(all(m["null_true"] for m in results[key]["models"]) for key in nulls)
    single = [value for key in nulls for value in models(key, "p_below_alpha")]
    wide = [value for key in ("null", "null-own-tasks", "null-6-tasks") for value in models(key, "p_below_alpha")]
    quoted = [
        f"| {span(family(nulls, 'any_false_rejection'))} | {span(family(nulls, 'any_false_p_below_alpha'))} |",
        f"| {span(family(partial, 'any_false_rejection'))} | {span(family(partial, 'any_false_p_below_alpha'))} |",
        "| {:.2f}%, {:.2f}% | {:.2f}%, {:.2f}% |".format(*models("all-0.3", "rejected")[:2], *models("all-0.3", "p_below_alpha")[:2]),
        "| {:.2f}% | {:.2f}% |".format(models("all-0.3", "rejected")[2], models("all-0.3", "p_below_alpha")[2]),
        f"every one rejected | {share(results['all-0.3'], results['all-0.3']['counts']['every_false_null_rejected']):.2f}% |",
        "a true gain of 0.194: {:.2f}% / {:.2f}% / {:.2f}%;".format(*models("all-0.2", "rejected")),
        "with chance 0.7: {:.2f}% / {:.2f}% / {:.2f}%;".format(*models("all-0.3-repeats", "rejected")),
        "(true means {}, {} and {}): ".format(*(m["true_mean_difference"] for m in results["all-half"]["models"]))
        + "{:.2f}% / {:.2f}% / {:.2f}%.".format(*models("all-half", "rejected")),
        f"\n{models('first-0.3', 'rejected')[0]:.2f}% of replicates, against {models('first-0.3', 'p_below_alpha')[0]:.2f}% without",
        f"{max(family(nulls, 'any_false_rejection')):.2f}% is not shown to be below 5%",
        f"below 0.05 in {span(single)} of replicates with no effect ({span(wide)} in the",
    ]
    missing = [text for text in quoted if text not in readme]
    assert not missing, missing
    main = " ".join((BASELINE / "README.md").read_text(encoding="utf-8").split())  # the harness README quotes some of them
    rejected, unadjusted = models("all-0.3", "rejected"), models("all-0.3", "p_below_alpha")
    in_main = [f"at least one in {span(family(nulls, 'any_false_rejection'))} of replicates "
               f"({span(family(nulls, 'any_false_p_below_alpha'))} with unadjusted p-values)",
               "a 5-run model in {:.2f}% and {:.2f}% and the 3-run model in {:.2f}%".format(*rejected),
               "({:.2f}%, {:.2f}% and {:.2f}% unadjusted)".format(*unadjusted)]
    missing = [text for text in in_main if text not in main]
    assert not missing, missing
    assert {m["true_mean_difference"] for m in results["all-0.3"]["models"]} == {0.275}
    assert {m["true_mean_difference"] for m in results["all-0.2"]["models"]} == {0.194}
