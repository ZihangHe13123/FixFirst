"""Check the family simulation's evidence, then write SUMMARY.md.

    python check.py

It refuses to write the summary unless every output
- has the SHA-256 its MANIFEST.json entry gives, and
- says of itself what that entry says of it: runs per model, effects, tasks, baseline, effect model,
  correlation, whether the models share their tasks, replicates and seed, and the level alpha its family
  was decided at (so a wrong file whose digest was updated with it is still refused);
and unless, in every output,
- each model's runs and effect are the setting's, in order; a model whose null is true shows a true mean
  difference of 0, and a model without an effect has a true null;
- every count is a whole number from 0 to the replicates and every displayed share is its count over the
  replicates; a model is never rejected in a replicate where it could not be estimated;
- Holm never rejects where the unadjusted p-value is not below alpha, per model and for "any model" (Holm
  rejects at an adjusted p-value of at most alpha, the unadjusted count is of p below alpha: a p-value
  exactly at alpha would be refused here), and a false rejection is a rejection;
- the family's counts fit the models' own: "any model" happened at least as often as its most frequent
  model and at most as often as all of them together; "every helped model" at most as often as its
  rarest and at least as often as their counts force; and an event over no model at all never happened;
- a share that needs a true null (or a false one) is given exactly when the setting has one.
Every setting must have the same alpha, which is the one the summary names. These are conditions the
counts must meet; they do not rebuild what happened replicate by replicate.
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARAMETERS = ("runs_per_model", "effects", "tasks", "baseline", "effect_model", "correlation", "shared_tasks",
              "replicates", "seed")
MODEL = (("rejected_after_holm", "rejected"), ("p_below_alpha_unadjusted", "p_below_alpha"), ("not_estimable", "not_estimable"))
FAMILY = (("any_rejection_after_holm", "any_rejection", None), ("any_false_rejection_after_holm", "any_false_rejection", True),
          ("every_false_null_rejected_after_holm", "every_false_null_rejected", False),
          ("any_p_below_alpha_unadjusted", "any_p_below_alpha", None),
          ("any_false_p_below_alpha_unadjusted", "any_false_p_below_alpha", True))


def refuse(message: str):
    raise SystemExit(message)


def whole(name: str, value, replicates: int):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= replicates:
        refuse(f"{name} is {value!r}, not a whole number from 0 to {replicates}")


def union(key: str, name: str, count: int, members: list[int], replicates: int):
    """How often at least one of the members' events happened, against the members' own counts."""
    low, high = (max(members), min(replicates, sum(members))) if members else (0, 0)
    if not low <= count <= high:
        refuse(f"{key}: {name} is {count}, but its models' own counts {members} put it between {low} and {high}")


def intersection(key: str, name: str, count: int, members: list[int], replicates: int):
    """How often all of the members' events happened together, against the members' own counts."""
    low, high = (max(0, sum(members) - (len(members) - 1) * replicates), min(members)) if members else (0, 0)
    if not low <= count <= high:
        refuse(f"{key}: {name} is {count}, but its models' own counts {members} put it between {low} and {high}")


def output(root: Path, key: str, setting: dict) -> dict:
    """One output's family simulation, refused unless its digest and its own content match its manifest entry."""
    data = (root / setting["output"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != setting["sha256"]:
        refuse(f"{setting['output']}: SHA-256 differs from its manifest")
    content = json.loads(data)
    for name in PARAMETERS:
        if content.get(name) != setting[name]:
            refuse(f"{setting['output']}: its {name} is {content.get(name)!r}, its manifest says {setting[name]!r}")
    result, replicates = content.get("family_simulation"), setting["replicates"]
    if not isinstance(result, dict) or not isinstance(result.get("models"), list) or not isinstance(result.get("counts"), dict):
        refuse(f"{setting['output']}: no family simulation in it")
    if result.get("alpha") != setting["alpha"] or isinstance(result.get("alpha"), bool):
        refuse(f"{key}: its family was decided at alpha {result.get('alpha')!r}, its manifest says {setting['alpha']!r}")
    models, counts = result["models"], result["counts"]
    if [(m.get("runs_per_arm"), m.get("effect")) for m in models] != list(zip(setting["runs_per_model"], setting["effects"])):
        refuse(f"{key}: its models are not the manifest's runs and effects, in order")
    if counts.get("replicates") != replicates:
        refuse(f"{key}: its counts are not out of {replicates} replicates")
    for index, model in enumerate(models, start=1):
        tally = model.get("counts") or {}
        for share, count in MODEL:
            whole(f"{key} model {index} {count}", tally.get(count), replicates)
            if model[share] != round(tally[count] / replicates, 3):
                refuse(f"{key} model {index}: {share} {model[share]} is not {tally[count]} of {replicates}")
        if tally["rejected"] > tally["p_below_alpha"]:
            refuse(f"{key} model {index}: Holm rejects more often than the unadjusted p-value is below alpha")
        if tally["p_below_alpha"] + tally["not_estimable"] > replicates:
            refuse(f"{key} model {index}: it has a p-value below alpha in replicates where it could not be estimated")
        if not isinstance(model["null_true"], bool) or model["null_true"] and model["true_mean_difference"] != 0 \
                or not model["null_true"] and model["effect"] == 0:
            refuse(f"{key} model {index}: null_true does not fit its effect and true mean difference")
    nulls = [m["null_true"] for m in models]
    for share, count, needs_true_null in FAMILY:
        whole(f"{key} {count}", counts.get(count), replicates)
        there = True if needs_true_null is None else any(nulls) if needs_true_null else not all(nulls)
        if result[share] != (round(counts[count] / replicates, 3) if there else None):
            refuse(f"{key}: {share} {result[share]} does not follow from {counts[count]} of {replicates}")
    if not (counts["any_false_rejection"] <= counts["any_rejection"] <= counts["any_p_below_alpha"]
            and counts["any_false_rejection"] <= counts["any_false_p_below_alpha"] <= counts["any_p_below_alpha"]
            and counts["every_false_null_rejected"] <= counts["any_rejection"]):
        refuse(f"{key}: its family counts contradict each other")
    if all(nulls) and counts["any_false_rejection"] != counts["any_rejection"]:
        refuse(f"{key}: with every null true, every rejection is a false one")
    tallies = [model["counts"] for model in models]
    true_nulls = [tally for tally, null in zip(tallies, nulls) if null]
    helped = [tally for tally, null in zip(tallies, nulls) if not null]
    for name, members, count in (("any_rejection", tallies, "rejected"), ("any_false_rejection", true_nulls, "rejected"),
                                 ("any_p_below_alpha", tallies, "p_below_alpha"),
                                 ("any_false_p_below_alpha", true_nulls, "p_below_alpha")):
        union(key, name, counts[name], [tally[count] for tally in members], replicates)
    intersection(key, "every_false_null_rejected", counts["every_false_null_rejected"],
                 [tally["rejected"] for tally in helped], replicates)
    return result


def build(here: Path = HERE) -> str:
    """The summary as Markdown, after every check."""
    manifest = json.loads((here / "MANIFEST.json").read_text(encoding="utf-8"))
    show = lambda value: "–" if value is None else f"{value:.3f}"  # noqa: E731
    levels = {setting.get("alpha") for setting in manifest["settings"].values()}
    if len(levels) != 1 or not all(isinstance(level, float) and 0 < level < 1 for level in levels):
        refuse(f"the settings do not share one alpha between 0 and 1: {sorted(map(repr, levels))}")
    [alpha] = levels  # every output is held to it below, so this is the level the results were decided at
    lines = ["# The confirmatory family under known effects", "",
             f"Generated by `check.py` after its checks (see its docstring). Shares of {manifest['settings']['null']['replicates']} "
             "replicates, code " + manifest["code"]["commit"][:7] + f". Three models with 5, 5 and 3 runs per arm; Holm at {alpha} on the "
             "paired t-test's p-values. A false rejection is the rejection of a model whose true mean difference is 0.", "",
             f"| Setting | True effects | Any false rejection after Holm | Any false p < {alpha}, unadjusted | Rejected after Holm, per model "
             f"| p < {alpha} unadjusted, per model | Every helped model rejected | Not estimable, per model |",
             "|---|---|---|---|---|---|---|---|"]
    for key, setting in manifest["settings"].items():
        result = output(here.parents[2], key, setting)
        models = result["models"]
        per = lambda name: " / ".join(show(m[name]) for m in models)  # noqa: E731
        lines.append(f"| {key}: {setting['description']} | {' / '.join(str(m['true_mean_difference']) for m in models)} "
                     f"| {show(result['any_false_rejection_after_holm'])} | {show(result['any_false_p_below_alpha_unadjusted'])} "
                     f"| {per('rejected_after_holm')} | {per('p_below_alpha_unadjusted')} "
                     f"| {show(result['every_false_null_rejected_after_holm'])} | {per('not_estimable')} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    text = build()
    (HERE / "SUMMARY.md").write_text(text, encoding="utf-8")
    print(f"{len(text.splitlines()) - 6} settings checked and summarized")
