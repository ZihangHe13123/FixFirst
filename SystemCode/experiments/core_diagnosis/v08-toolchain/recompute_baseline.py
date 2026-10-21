"""Recompute development root-cause accuracy with an explicit feature layout.

Runs local decision-tree fits only. Does not invoke a language model or change
the packaged classifier. Run each source revision in its own Python process.
"""

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--layout", choices=["current", "legacy"], default="current")
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Use a new output path")
    sys.path.insert(0, str(args.src.resolve()))
    from fixfirst.classification import MIN_CONFIDENCE, default_model, predict_tree, train_tree
    from fixfirst.evaluation import load_rows
    from fixfirst.evidence import FEATURE_NAMES

    rows = load_rows(args.dataset)
    names = FEATURE_NAMES[:44] if args.layout == "legacy" else FEATURE_NAMES
    for row in rows:
        row["features"] = row["features"][:len(names)]
    signature = inspect.signature(train_tree)
    kwargs = {"feature_names": names} if "feature_names" in signature.parameters else {}
    if not kwargs and len(names) != len(FEATURE_NAMES):
        raise ValueError("The source revision cannot select this feature layout")

    def accuracy(predictions):
        hits = sum(p == row["label"] for p, row in zip(predictions, rows))
        return {"correct": hits, "n": len(rows), "accuracy": hits / len(rows)}

    predicted = {"tree": [None] * len(rows), "hybrid": [None] * len(rows)}
    for scenario in sorted({r["scenario"] for r in rows}):
        model = train_tree([r for r in rows if r["scenario"] != scenario], **kwargs)
        for i, row in enumerate(rows):
            if row["scenario"] == scenario:
                cause, confidence = predict_tree(row["features"], model)
                predicted["tree"][i] = cause
                predicted["hybrid"][i] = row["rules"] or row["likely"] or (
                    cause if confidence >= MIN_CONFIDENCE else None)
    packaged = default_model()
    packaged_predictions = [predict_tree(r["features"], packaged)[0] for r in rows]
    facts = [{k: row[k] for k in ("case_id", "scenario", "label", "features")} for row in rows]
    package = args.src / "fixfirst"
    result = {
        "protocol": "leave-one-scenario-out; development data; no same-scenario training rows",
        "layout": args.layout, "feature_count": len(names), "feature_names": names,
        "packaged_model_features": len(packaged["feature_names"]),
        "packaged_training_groups": packaged.get("training_groups", []),
        "packaged_accuracy_is_training_replay_not_cv": accuracy(packaged_predictions),
        "cross_validation": {key: accuracy(value) for key, value in predicted.items()},
        "feature_rows_sha256": hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest(),
        "source_files_sha256": {
            str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(package.rglob("*")) if p.is_file() and (
                p.suffix == ".py" or p.parent.name == "knowledge")},
        "dataset_files_sha256": {str(p.relative_to(args.dataset)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(args.dataset.rglob("*")) if p.is_file()},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("layout", "feature_count", "cross_validation")}))


if __name__ == "__main__":
    main()
