"""Fixed-layout development comparison; never writes the bundled model.

Case IDs/scenario families are used only to form/report splits, never as inputs.
The rule/hybrid columns describe this checkout, not an unmerged full system.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from fixfirst.classification import default_model, predict_tree, train_tree, MIN_CONFIDENCE  # noqa: E402
from fixfirst.evaluation import load_rows  # noqa: E402
from fixfirst.evidence import FEATURE_LAYOUTS  # noqa: E402
from fixfirst.toolchain_environments import source_identity  # noqa: E402
from fixfirst.toolchain_manifest import validate  # noqa: E402
from collisions import collisions, digest  # noqa: E402


LAYOUTS = {44: FEATURE_LAYOUTS[3], 81: FEATURE_LAYOUTS[8], 93: FEATURE_LAYOUTS[9]}
METHODS = ("tree", "rules", "rules_heur", "hybrid")


def mechanism(scenario):
    # Predeclared near-neighbor groups; all templates/variants stay together.
    if scenario.startswith("tt_py_spec_"):
        return "tt_py_spec"
    if scenario.startswith("tt_ast_str_"):
        return "tt_ast_str"
    if scenario in {"st_pkg_resources_absent", "st_pkg_resources_runtime", "st_get_distribution"}:
        return "st_pkg_resources_absent"
    if scenario.startswith("dj_unset_"):
        return "dj_settings_unconfigured"
    return scenario


def read_dataset(path, name):
    manifest = json.loads((path / "manifest.json").read_text())
    if name == "toolchain":
        if manifest.get("schema_version") != 2 or manifest.get("lock_mode") != "exact_replay":
            raise ValueError("Candidate experiment requires the fixed schema-2 exact replay matrix")
        validate(manifest)
    families = {s["id"]: s.get("family", "") for s in manifest["scenarios"]}
    rows = load_rows(path)
    for index, row in enumerate(rows):
        row.update(dataset=name, family=families[row["scenario"]], mechanism=mechanism(row["scenario"]),
                   case_key=name + "/" + row["case_id"], row_key=f"{name}/{index}")
    coverage = {"retained_cases": len(manifest["cases"]), "issue_rows": len(rows),
                "unparsed_cases": len(manifest.get("unparsed", [])), "rejected_cases": len(manifest.get("rejected", [])),
                "inapplicable_cases": len(manifest.get("inapplicable", []))}
    coverage["attempted_cases"] = coverage["retained_cases"] + coverage["unparsed_cases"] + coverage["rejected_cases"]
    coverage["parseable_given_observed_and_fix_validated"] = {
        "numerator": coverage["retained_cases"],
        "denominator": coverage["retained_cases"] + coverage["unparsed_cases"]}
    info = {"coverage": coverage, "manifest_sha256": hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest(),
            "files_sha256": {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(path.rglob("*")) if p.is_file()},
            "rows_sha256": digest([{k: r[k] for k in ("case_key", "scenario", "label", "features")} for r in rows]),
            "collisions": {str(width): collisions(rows, width) for width in LAYOUTS},
            "known_new_feature_rows": {feature: sum(r["features"][81 + n] != -1 for r in rows)
                                       for n, feature in enumerate(FEATURE_LAYOUTS[9][81:])}}
    return rows, info


def train(rows, width, output=None):
    clipped = [{**r, "features": r["features"][:width]} for r in rows]
    return train_tree(clipped, output, max_depth=6, min_samples_leaf=2, feature_names=LAYOUTS[width])


def predict(rows, model):
    result = []
    for row in rows:
        label, confidence = predict_tree(row["features"], model)
        heuristic = row["rules"] or row["likely"]
        result.append({k: row[k] for k in ("row_key", "case_key", "scenario", "family", "label")} | {
            "tree": label, "confidence": confidence, "rules": row["rules"], "rules_heur": heuristic,
            "hybrid": heuristic or (label if confidence >= MIN_CONFIDENCE else None)})
    return result


def metrics(predictions):
    result = {}
    for method in METHODS:
        cases = defaultdict(list)
        for row in predictions:
            cases[row["case_key"]].append(row)
        correct = sum(r[method] == r["label"] for r in predictions)
        result[method] = {"correct": correct, "rows": len(predictions),
                          "accuracy": correct / len(predictions) if predictions else None,
                          "answered": sum(r[method] is not None for r in predictions),
                          "all_issues_correct_cases": sum(all(r[method] == r["label"] for r in rows) for rows in cases.values()),
                          "cases": len(cases)}
    return result


def evaluate(rows, model):
    predictions = predict(rows, model)
    return {"metrics": metrics(predictions), "predictions": predictions,
            "model_sha256": digest(model)}


def grouped_cv(rows, width, group_key, additional=()):
    predictions, folds = [], []
    for group in sorted({r[group_key] for r in rows}):
        train_rows = [r for r in rows if r[group_key] != group] + list(additional)
        test_rows = [r for r in rows if r[group_key] == group]
        train_cases, test_cases = {r["case_key"] for r in train_rows}, {r["case_key"] for r in test_rows}
        if train_cases & test_cases:
            raise ValueError("A case crossed a train/test boundary")
        model = train(train_rows, width)
        prediction = predict(test_rows, model)
        predictions += prediction
        folds.append({"held_group": group, "train_cases": sorted(train_cases), "test_cases": sorted(test_cases),
                      "model_sha256": digest(model), "metrics": metrics(prediction)})
    return {"metrics": metrics(predictions), "predictions": predictions, "folds": folds}


def report(result):
    lines = ["# Fixed candidate feature comparison", "", "Development data with provisional toolchain labels. No default promotion.",
             "", "Tree columns are root-cause classifications; hybrid columns use this checkout's rules/heuristics.",
             "Production source is checked against the fixed integrated base; only the candidate feature files differ.", "",
             "Parameters: Gini, depth 6, minimum leaf 2, random_state 42; no hyperparameter search.", "",
             "| Protocol | Model | Tree correct/rows | Hybrid correct/rows |", "|---|---|---:|---:|"]
    for protocol, models in result["comparisons"].items():
        for name, data in models.items():
            tree, hybrid = data["metrics"]["tree"], data["metrics"]["hybrid"]
            lines.append(f"| {protocol} | {name} | {tree['correct']}/{tree['rows']} | {hybrid['correct']}/{hybrid['rows']} |")
    lines += ["", "## Coverage", "", "| Dataset | Retained cases | Issue rows | Unparsed | Rejected | Inapplicable |",
              "|---|---:|---:|---:|---:|---:|"]
    for name, info in result["datasets"].items():
        c = info["coverage"]
        lines.append(f"| {name} | {c['retained_cases']} | {c['issue_rows']} | {c['unparsed_cases']} | {c['rejected_cases']} | {c['inapplicable_cases']} |")
    lines += ["", "Training replays are explicitly labeled and are not out-of-sample scores. Family/mechanism folds retain",
              "all same-case rows and near-neighbor variants together. Inspect fold predictions and feature importances",
              "in results.json before interpreting gains; a version coordinate can correlate with a generated environment.",
              "No test accuracy proves labels, natural-project repair success, or a default-model improvement.", "",
              "## Attribution check", "", "New columns used by the base-93 tree: " +
              (", ".join(k for k in result["candidate_importances"]["base93"] if k.startswith("raw_")) or "none") + ".",
              "If this list is empty, a changed base-93 score is not evidence that the tree used the new raw signals.",
              "Existing-feature split choices can change when the candidate feature set changes, including tied gains."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", type=Path, default=ROOT / "examples/diagnosis-dataset")
    parser.add_argument("--hard", type=Path, default=ROOT / "examples/hard-dataset")
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--production-base", default="c8de5a0")
    args = parser.parse_args()
    base = subprocess.check_output(["git", "rev-parse", args.production_base], cwd=ROOT, text=True).strip()
    differences = subprocess.check_output(["git", "diff", "--name-only", base, "--", "src/fixfirst"], cwd=ROOT, text=True).splitlines()
    allowed = {"src/fixfirst/classification.py", "src/fixfirst/evidence.py", "src/fixfirst/runtime_features.py"}
    if set(differences) - allowed:
        raise ValueError("Unexpected production differences from the integrated comparison base")
    args.output.mkdir(parents=True, exist_ok=False)
    datasets, info = {}, {}
    for name in ("main", "hard", "toolchain"):
        datasets[name], info[name] = read_dataset(getattr(args, name), name)
    import sklearn

    result = {"protocol": "v08-fixed-model-comparison-v1", "provisional_labels": True,
              "runtime": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                          "system": platform.system(), "machine": platform.machine()},
              "parameters": {"criterion": "gini", "max_depth": 6, "min_samples_leaf": 2, "random_state": 42},
              "feature_layouts": LAYOUTS, "source_sha256": source_identity(), "datasets": info,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "production_base": base, "production_differences": differences,
              "hybrid_scope": "Integrated production base with only candidate feature extraction/schema differences.",
              "comparisons": {}, "candidate_importances": {}}
    comparisons = result["comparisons"]
    main_rows, hard, toolchain = (datasets[k] for k in ("main", "hard", "toolchain"))
    bundled = default_model()
    result["bundled_model_sha256"] = hashlib.sha256((ROOT / "src/fixfirst/knowledge/diagnosis_tree.json").read_bytes()).hexdigest()
    for name, rows in (("main_training_replay", main_rows), ("hard_external_regression", hard), ("toolchain_base_transfer", toolchain)):
        comparisons[name] = {"bundled44": evaluate(rows, bundled)}
    for width in LAYOUTS:
        print(f"fixed layout {width}", flush=True)
        base = train(main_rows, width, args.output / "models" / f"base-{width}.json")
        augmented = train(main_rows + toolchain, width, args.output / "models" / f"augmented-{width}.json")
        for name, rows in (("main_training_replay", main_rows), ("hard_external_regression", hard)):
            comparisons[name][f"base{width}"] = evaluate(rows, base)
            comparisons[name][f"augmented{width}"] = evaluate(rows, augmented)
        comparisons["toolchain_base_transfer"][f"base{width}"] = evaluate(toolchain, base)
        comparisons.setdefault("main_leave_scenario_out", {})[f"base{width}"] = grouped_cv(main_rows, width, "scenario")
        comparisons["main_leave_scenario_out"][f"augmented{width}"] = grouped_cv(main_rows, width, "scenario", toolchain)
        for key in ("mechanism", "family"):
            comparisons.setdefault("toolchain_leave_" + key + "_out", {})[f"augmented{width}"] = grouped_cv(toolchain, width, key, main_rows)
        result["candidate_importances"][f"base{width}"] = base["feature_importances"]
        result["candidate_importances"][f"augmented{width}"] = augmented["feature_importances"]
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.output / "REPORT.md").write_text(report(result))
    print(report(result))


if __name__ == "__main__":
    main()
