"""Compare richer observations, paired old/new snapshots, and verified real data.

Fault families stay together across both snapshot versions. Real-data effects are
measured with each real project left out. Hard cases and ordinary-error controls
never enter fitting. All of these sets are development material, not final testing.
"""

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

from fixfirst.classification import train_tree
from fixfirst.diagnosis_cases import load_session
from fixfirst.evaluation import load_rows, predict, score
from fixfirst.evidence import V5_FEATURE_NAMES as FEATURE_NAMES, V4_FEATURE_NAMES
from fixfirst.reasoning import infer_and_plan
from fixfirst.workspace import build_view


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fit(rows, names, output=None, balance=False):
    counts = Counter(r["group"] for r in rows)
    selected = [{**r, "features": r["features"][:len(names)],
                 "weight": 10 / counts[r["group"]] if balance else 1.0} for r in rows]
    return train_tree(selected, output, feature_names=names)


def result(rows, predictions):
    truth = [r["label"] for r in rows]
    return {
        "scores": {name: score(truth, [p[name] for p in predictions]) for name in ("tree", "hybrid")},
        "errors": dict(Counter(r["scenario"] for r, p in zip(rows, predictions) if r["label"] != p["tree"])),
        "predictions": [{"case_id": r["case_id"], "truth": r["label"], "tree": p["tree"], "hybrid": p["hybrid"]}
                        for r, p in zip(rows, predictions)],
    }


def grouped(training, test, names, balance=False):
    predictions, folds = [], []
    models = {}
    for group in sorted({r["group"] for r in test}):
        subset = [r for r in training if r["group"] != group]
        model = fit(subset, names, balance=balance)
        models[group] = model
        folds.append({"held_out": group, "training_groups": model["training_groups"],
                      "training_rows": model["training_examples"]})
    for row in test:
        predictions.append(predict(row, models[row["group"]]))
    return {**result(test, predictions), "folds": folds}


def first_steps(dataset, model_path):
    results = []
    for line in (dataset / "cases.jsonl").read_text().splitlines():
        case = json.loads(line)
        session = load_session(dataset, case["session"])
        session.model_path = str(model_path)
        infer_and_plan(session)
        view = build_view(session)
        results.append({"case_id": case["case_id"], "label": case["label"],
                        "goal_status": session.goal_status, "must_fix_steps": len(view["steps"]),
                        "first_step": (view["steps"] or [{}])[0].get("title"),
                        "labelled_diagnoses": [i.diagnosis for i in session.issues
                                                if i.issue_id in case.get("labelled_issue_ids", [])]})
    return results


def run(legacy, previous_hard, data, output):
    output.mkdir(parents=True, exist_ok=False)
    old = load_rows(legacy)
    current = load_rows(data / "generated")
    real = load_rows(data / "real")
    hard = load_rows(data / "hard")
    old_hard = load_rows(previous_hard)
    controls = load_rows(data / "counterexamples")
    usages = load_rows(data / "usage-training")
    if not real or not controls or {r["case_id"] for r in old} != {r["case_id"] for r in current}:
        raise ValueError("Missing real cases/controls or unpaired generated observations")
    root = Path(__file__).resolve().parents[2]
    sources = [*sorted((root / "src/fixfirst").glob("*.py")),
               *sorted((root / "src/fixfirst/knowledge").glob("*")), Path(__file__).resolve()]
    report = {
        "kind": "observation_and_real_data_development_comparison",
        "head": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": {str(p.relative_to(root)): sha(p) for p in sources if p.is_file()},
        "python": sys.version.split()[0], "sklearn": importlib.metadata.version("scikit-learn"),
        "inputs_sha256": {name: sha(path / "cases.jsonl") for name, path in (
            ("legacy_generated", legacy), ("current_generated", data / "generated"),
            ("previous_hard", previous_hard), ("current_hard", data / "hard"),
            ("real", data / "real"), ("controls", data / "counterexamples"),
            ("usage_training", data / "usage-training"))},
        "units": {"synthetic_fault_families": len({r["group"] for r in old}),
                  "synthetic_template_cases": len(old), "snapshot_records_when_paired": len(old) + len(current),
                  "real_fault_projects": len(real), "controls": len(controls),
                  "usage_training_cases": len(usages), "usage_training_families": len({r["group"] for r in usages})},
        "limitations": "Development data guided feature design. Paired snapshots are the same faults, not extra independent faults. Real labels have automated repair validation and await human rereview. No final A1/C1 data was accessed.",
        "models": {},
    }
    configs = {
        "previous49": (old, V4_FEATURE_NAMES, False),
        "fresh61": (current, FEATURE_NAMES, False),
        "paired61": (old + current, FEATURE_NAMES, False),
        "with_real61": (old + current + real, FEATURE_NAMES, True),
        "with_usage61": (old + current + usages, FEATURE_NAMES, True),
        "with_real_usage61": (old + current + real + usages, FEATURE_NAMES, True),
    }
    for name, (training, names, balance) in configs.items():
        path = output / (name + "-tree.json")
        model = fit(training, names, path, balance)
        item = {"model_sha256": sha(path), "training_rows": len(training),
                "features": len(names), "balance_fault_groups": balance,
                "fresh_hard": result(hard, [predict(r, model) for r in hard]),
                "previous_hard": result(old_hard, [predict(r, model) for r in old_hard]),
                "controls": result(controls, [predict(r, model) for r in controls]),
                "real_project_out": grouped(training, real, names, balance),
                "first_steps": first_steps(data / "real", path)}
        if name not in ("with_real61", "with_real_usage61"):
            item["current_scenario_out"] = grouped(training, current, names, balance)
            item["legacy_scenario_out"] = grouped(training, old, names, balance)
        else:
            item["synthetic_cv_note"] = "Not scored with real augmentation: similar fault mechanisms may overlap the synthetic families. Use the real-project-out comparison and controls."
        report["models"][name] = item
    baseline, selected = report["models"]["previous49"], report["models"]["paired61"]
    gates = {
        "current_scenario_accuracy_improved": selected["current_scenario_out"]["scores"]["tree"]["accuracy"] > baseline["current_scenario_out"]["scores"]["tree"]["accuracy"],
        "previous_hard_preserved": selected["previous_hard"]["scores"]["tree"]["accuracy"] >= baseline["previous_hard"]["scores"]["tree"]["accuracy"],
        "complete_system_controls_preserved": selected["controls"]["scores"]["hybrid"]["accuracy"] >= baseline["controls"]["scores"]["hybrid"]["accuracy"],
        "complete_system_hard_preserved": selected["fresh_hard"]["scores"]["hybrid"]["accuracy"] >= baseline["fresh_hard"]["scores"]["hybrid"]["accuracy"],
    }
    report["selection"] = {
        "candidate": "paired61-tree.json" if all(gates.values()) else None,
        "gates": gates,
        "reason": "Prefer the paired-observation model for grouped accuracy, old-record compatibility and complete-system controls. Other models are exploratory. Raw-tree control errors remain visible and are not erased by rule corrections.",
    }
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({name: {key: value[key]["scores"] for key in (
        "fresh_hard", "previous_hard", "controls", "real_project_out")}
        for name, value in report["models"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--previous-hard", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.legacy.resolve(), args.previous_hard.resolve(), args.data.resolve(), args.output.resolve())
