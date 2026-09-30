"""Compare classifier representations without using the private final test set.

The fixed comparison isolates features at depth 6 / leaf size 2. Nested validation
selects depth using training scenarios only in each outer fold. Features themselves
were designed using development data, so neither result is independent final testing.
"""

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

import fixfirst
from fixfirst.classification import default_model, predict_tree, train_tree
from fixfirst.diagnosis_cases import load_session
from fixfirst.evaluation import load_rows, predict, score
from fixfirst.evidence import V4_FEATURE_NAMES as FEATURE_NAMES, LEGACY_FEATURE_NAMES
from fixfirst.reasoning import infer_and_plan
from fixfirst.workspace import build_view

DEPTHS = (4, 6, 8)


def fit(rows, names, depth, output=None):
    selected = [{**r, "features": r["features"][:len(names)]} for r in rows]
    return train_tree(selected, output, max_depth=depth, feature_names=names)


def fixed_folds(rows, names, depth, key="scenario"):
    predictions, folds = [None] * len(rows), []
    for group in sorted({r[key] for r in rows}):
        training = [r for r in rows if r[key] != group]
        model = fit(training, names, depth)
        indexes = [i for i, r in enumerate(rows) if r[key] == group]
        for i in indexes:
            predictions[i] = {**predict(rows[i], model), "confidence": predict_tree(rows[i]["features"], model)[1]}
        folds.append({"held_out": group, "training_groups": sorted({r[key] for r in training})})
    return predictions, folds


def choose_depth(rows):
    scores = {}
    truth = [r["label"] for r in rows]
    for depth in DEPTHS:
        predictions, _ = fixed_folds(rows, FEATURE_NAMES, depth)
        scores[depth] = score(truth, [p["tree"] for p in predictions])
    # Prefer the existing depth on a tie, then the simpler alternative.
    depth = max(DEPTHS, key=lambda d: (
        scores[d]["macro_f1"], scores[d]["accuracy"], d == 6, -d,
    ))
    return depth, scores


def nested_folds(rows):
    predictions, folds = [None] * len(rows), []
    for group in sorted({r["scenario"] for r in rows}):
        training = [r for r in rows if r["scenario"] != group]
        depth, inner = choose_depth(training)
        model = fit(training, FEATURE_NAMES, depth)
        for i, row in enumerate(rows):
            if row["scenario"] == group:
                predictions[i] = {**predict(row, model), "confidence": predict_tree(row["features"], model)[1]}
        folds.append({"held_out": group, "training_groups": model["training_groups"],
                      "selected_depth": depth, "inner_scores": inner})
    return predictions, folds


def summary(rows, predictions, folds=None):
    truth = [r["label"] for r in rows]
    return {
        "scores": {m: score(truth, [p[m] for p in predictions]) for m in ("tree", "hybrid", "rules_heur")},
        "tree_per_class": {
            label: score([r["label"] for r in rows if r["label"] == label],
                         [p["tree"] for r, p in zip(rows, predictions) if r["label"] == label])
            for label in sorted(set(truth))
        },
        "errors_by_scenario": dict(Counter(r["scenario"] for r, p in zip(rows, predictions)
                                          if r["label"] != p["tree"])),
        "predictions": [
            {"case_id": r["case_id"], "scenario": r["scenario"], "truth": r["label"], **p}
            for r, p in zip(rows, predictions)
        ],
        "folds": folds,
    }


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(train, transfers, output):
    output.mkdir(parents=True, exist_ok=False)
    implementation = Path(fixfirst.__file__).resolve().parents[2]
    rows = load_rows(train)
    if any(len(r["features"]) < len(FEATURE_NAMES) for r in rows):
        raise ValueError("Current evidence features are required")
    sources = sorted((implementation / "src/fixfirst").glob("*.py")) + sorted(
        (implementation / "src/fixfirst/knowledge").glob("*")
    ) + [Path(__file__).resolve()]
    report = {
        "kind": "classifier_development_comparison",
        "limitations": "Development features and parameters were tuned by the authors; not independent final evaluation. Transfer cases were never used to fit or select depth.",
        "head": subprocess.check_output(["git", "-C", str(implementation), "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": {str(p.relative_to(implementation)): sha(p) for p in sources if p.is_file()},
        "python": sys.version.split()[0],
        "scikit_learn": importlib.metadata.version("scikit-learn"),
        "train_sha256": sha(train / "cases.jsonl"),
        "train_environment_sha256": sha(train / "environment.json"),
        "training_rows": len(rows), "training_scenarios": len({r["scenario"] for r in rows}),
        "feature_names": {"legacy": LEGACY_FEATURE_NAMES, "context": FEATURE_NAMES},
        "depth_candidates": DEPTHS,
        "comparisons": {}, "transfer": {},
    }
    for key in ("scenario", "template"):
        for name, names in (("legacy44", LEGACY_FEATURE_NAMES), ("context49", FEATURE_NAMES)):
            predictions, folds = fixed_folds(rows, names, 6, key)
            report["comparisons"][f"{name}_fixed_{key}"] = summary(rows, predictions, folds)
    predictions, folds = nested_folds(rows)
    nested = summary(rows, predictions, folds)
    report["comparisons"]["context49_nested_scenario"] = nested
    preferred, inner = choose_depth(rows)
    fixed = report["comparisons"]["context49_fixed_scenario"]["scores"]["tree"]
    tuned = nested["scores"]["tree"]
    improves = tuned["accuracy"] > fixed["accuracy"] and tuned["macro_f1"] > fixed["macro_f1"]
    depth = preferred if improves else 6
    candidate = fit(rows, FEATURE_NAMES, depth, output / "candidate-tree.json")
    legacy = fit(rows, LEGACY_FEATURE_NAMES, 6, output / "legacy-retrained-tree.json")
    report["candidate_selection"] = {
        "depth": depth, "development_preferred_depth": preferred,
        "decision": "Nested tuning improved both metrics" if improves else "Keep depth 6: nested tuning did not improve both metrics",
        "grouped_development_scores": inner,
        "candidate_sha256": sha(output / "candidate-tree.json"),
    }
    for dataset in transfers:
        test = load_rows(dataset)
        report["transfer"][dataset.name] = {
            "dataset_sha256": sha(dataset / "cases.jsonl"),
            "environment_sha256": sha(dataset / "environment.json"),
            "case_ids": [r["case_id"] for r in test],
            "models": {
                name: summary(test, [predict(r, model) for r in test])
                for name, model in (("bundled", default_model()), ("legacy_retrained", legacy),
                                    ("context_candidate", candidate))
            },
            "candidate_first_steps": [],
        }
        for line in (dataset / "cases.jsonl").read_text().splitlines():
            case = json.loads(line)
            session = load_session(dataset, case["session"])
            session.model_path = str(output / "candidate-tree.json")
            infer_and_plan(session)
            steps = build_view(session)["steps"]
            first = steps[0] if steps else {}
            report["transfer"][dataset.name]["candidate_first_steps"].append({
                "case_id": case["case_id"], "title": first.get("title"),
                "explanation": first.get("explanation"),
                "issues": [{"diagnosis": i.diagnosis, "source": i.diagnosis_source,
                            "rule": i.diagnosis_rule, "prediction": i.prediction}
                           for i in session.issues if i.tool == "pytest_run" and i.status == "open"],
            })
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"comparisons": {n: r["scores"] for n, r in report["comparisons"].items()},
                      "candidate_depth": depth,
                      "transfer": {n: {m: r["scores"] for m, r in v["models"].items()}
                                   for n, v in report["transfer"].items()}}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--transfer", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.train.resolve(), [p.resolve() for p in args.transfer], args.output.resolve())
