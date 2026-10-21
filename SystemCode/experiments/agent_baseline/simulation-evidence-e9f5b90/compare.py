"""Check, then compare: 7914699 (simulation-evidence-20261002/after/) against e9f5b90 (results/).

    python compare.py

It refuses to write COMPARISON.md unless, for each of the two packages, every output
- has the SHA-256 its package's MANIFEST.json gives, and
- says of itself what that manifest says of it: tasks, runs per arm, baseline, effect model, correlation,
  replicates, bootstrap resamples and seed, and the effects, in order, both in its settings and in its
  result rows (so a wrong file whose digest was updated with it is still refused);
and unless
- both packages have the same settings in the same order with the same parameters, and every effect row
  pairs up with the same true mean gain;
- in e9f5b90's results, every count is a whole number from 0 to the replicates, every displayed share is
  its count over the replicates, the coverage given an interval is its count over the replicates that had
  one, and at no effect the replicates split exactly into false positives, coverage and no interval, for
  the t-interval and for the bootstrap.
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARAMETERS = ("tasks", "runs_per_arm", "baseline", "effect_model", "correlation", "effects", "replicates",
              "bootstrap_resamples", "seed")
IN_OUTPUT = {"bootstrap_resamples": "resamples"}  # an output's own name for a manifest parameter
FIELDS = (("t_interval_excludes_zero", "t excludes 0", "t_excludes"), ("t_interval_covers_truth", "t covers truth", "t_covers"),
          ("bootstrap_excludes_zero", "bootstrap excludes 0", "bootstrap_excludes"),
          ("bootstrap_covers_truth", "bootstrap covers truth", "bootstrap_covers"),
          ("sign_test_p_below_0_05", "sign p < 0.05", "sign"), ("no_interval", "no interval", "no_interval"))
GIVEN = (("t_interval_covers_truth_given_interval", "t_covers", "no_interval"),
         ("bootstrap_covers_truth_given_interval", "bootstrap_covers", "no_bootstrap_interval"))


def refuse(message: str):
    raise SystemExit(message)


def output(root: Path, key: str, setting: dict, entry: dict) -> list[dict]:
    """One output's result rows, refused unless its digest and its own content match its manifest."""
    data = (root / entry["output"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        refuse(f"{entry['output']}: SHA-256 differs from its manifest")
    content = json.loads(data)
    for name in PARAMETERS:
        said = content.get(IN_OUTPUT.get(name, name))
        if (list(said) if name == "effects" and said is not None else said) != setting[name]:
            refuse(f"{entry['output']}: its {name} is {said!r}, its manifest says {setting[name]!r}")
    rows = content.get("simulation")
    if not isinstance(rows, list) or [row.get("effect") for row in rows] != setting["effects"]:
        refuse(f"{entry['output']}: its result rows are not the manifest's effects, in order ({key})")
    return rows


def check_counts(name: str, row: dict, replicates: int):
    """e9f5b90's integer counts against the shares shown from them."""
    counts = row.get("counts") or {}
    if counts.get("replicates") != replicates:
        refuse(f"{name}: counts are not out of {replicates} replicates")
    for _, _, count in (*FIELDS, ("", "", "no_bootstrap_interval")):
        value = counts.get(count)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= replicates:
            refuse(f"{name}: the count {count} is {value!r}, not a whole number from 0 to {replicates}")
    for field, _, count in FIELDS:
        if row[field] != round(counts[count] / replicates, 3):
            refuse(f"{name}: {field} {row[field]} is not {counts[count]} of {replicates}")
    for field, hits, missing in GIVEN:
        with_interval = replicates - counts[missing]
        if row[field] != (round(counts[hits] / with_interval, 3) if with_interval else None):
            refuse(f"{name}: {field} {row[field]} is not {counts[hits]} of the {with_interval} with an interval")
    if row["effect"] == 0:
        for excludes, covers, missing in (("t_excludes", "t_covers", "no_interval"),
                                          ("bootstrap_excludes", "bootstrap_covers", "no_bootstrap_interval")):
            if counts[excludes] + counts[covers] + counts[missing] != replicates:
                refuse(f"{name}: at no effect, {excludes}, {covers} and {missing} do not add up to {replicates}")


def build(here: Path = HERE) -> str:
    """The comparison as Markdown, after every check; `here` is this package, next to the earlier one."""
    root, old_package = here.parents[2], here.parent / "simulation-evidence-20261002"
    old_manifest = json.loads((old_package / "MANIFEST.json").read_text(encoding="utf-8"))
    new_manifest = json.loads((here / "MANIFEST.json").read_text(encoding="utf-8"))
    if list(old_manifest["settings"]) != list(new_manifest["settings"]):
        refuse("the two packages do not have the same settings in the same order")
    header = ["Setting", "Effect", "True mean gain", *(label for _, label, _ in FIELDS), "t covers, given an interval",
              "Counts (t excl., t cov., no interval / replicates)"]
    lines = ["# 7914699 against e9f5b90, setting by setting", "",
             "Generated by `compare.py` after its checks (see its docstring). Shares of 2000 replicates, 7914699 → "
             "e9f5b90. The only change in how they are counted: a replicate whose task differences agree within 1e-9 "
             "(not only exactly) is degenerate and has no interval. The data drawn are the same. Counts and coverage "
             "given an interval are e9f5b90's.", "", "| " + " | ".join(header) + " |", "|---" * len(header) + "|"]
    changed = shown = 0
    for key, old_setting in old_manifest["settings"].items():
        new_setting = new_manifest["settings"][key]
        if any(old_setting[name] != new_setting[name] for name in PARAMETERS):
            refuse(f"{key}: parameters differ between the packages")
        old = output(root, key, old_setting, old_setting["after"])
        new = output(root, key, new_setting, new_setting)
        for before, after in zip(old, new, strict=True):
            if before["true_mean_difference"] != after["true_mean_difference"]:
                refuse(f"{key}: the true mean gain differs, so the data were not drawn the same way")
            check_counts(f"{key} at {after['effect']}", after, new_setting["replicates"])
            counts, cells = after["counts"], []
            for field, _, _ in FIELDS:
                changed += before[field] != after[field]
                shown += 1
                cells.append(f"{before[field]:.3f} → {after[field]:.3f}")
            lines.append(f"| {key} | {after['effect']} | {after['true_mean_difference']} | {' | '.join(cells)} "
                         f"| {after['t_interval_covers_truth_given_interval']} | {counts['t_excludes']}, "
                         f"{counts['t_covers']}, {counts['no_interval']} / {counts['replicates']} |")
    lines += ["", f"{changed} of {shown} displayed shares changed."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    text = build()
    (HERE / "COMPARISON.md").write_text(text, encoding="utf-8")
    print(text.splitlines()[-1])
