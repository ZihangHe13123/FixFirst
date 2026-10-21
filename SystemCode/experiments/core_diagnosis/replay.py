"""Replay development sessions and compare the bundled tree with a retrained candidate.

Run from the repository with its venv. Set PYTHONPATH to a different checkout's
src directory to evaluate that implementation on exactly the same input sessions.
This script neither runs projects nor uses private held-out or user-study data.
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
from fixfirst.classification import default_model, train_tree
from fixfirst.diagnosis_cases import load_session
from fixfirst.evaluation import cross_validate, load_rows, predict, score
from fixfirst.reasoning import infer_and_plan
from fixfirst.workspace import build_view


def run(train: Path, dataset: Path, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    implementation = Path(fixfirst.__file__).resolve().parents[2]
    train_rows, rows = load_rows(train), load_rows(dataset)
    candidate = train_tree(train_rows, output / "candidate-tree.json")
    baseline = default_model()
    truth = [row["label"] for row in rows]
    source_files = sorted((implementation / "src/fixfirst").glob("*.py")) + sorted(
        (implementation / "src/fixfirst/knowledge").glob("*")
    )
    summary = {
        "kind": "development_replay",
        "head": subprocess.check_output(["git", "-C", str(implementation), "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": {str(p.relative_to(implementation)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in source_files if p.is_file()},
        "python": sys.version.split()[0],
        "packages": {name: importlib.metadata.version(name) for name in ("numpy", "pydantic", "scikit-learn", "pytest")},
        "dataset_sha256": hashlib.sha256((dataset / "cases.jsonl").read_bytes()).hexdigest(),
        "environment_sha256": hashlib.sha256((dataset / "environment.json").read_bytes()).hexdigest(),
        "train_sha256": hashlib.sha256((train / "cases.jsonl").read_bytes()).hexdigest(),
        "training_rows": len(train_rows),
        "test_rows": len(rows),
        "fault_families": len({r["scenario"] for r in rows}),
        "scores": {},
        "scenarios": {},
        "first_steps": [],
    }
    for name, model in (("bundled", baseline), ("retrained_same_data", candidate)):
        predictions = [predict(row, model) for row in rows]
        summary["scores"][name] = {method: score(truth, [p[method] for p in predictions])
                                   for method in ("tree", "hybrid", "rules_heur")}
        summary["scenarios"][name] = {
            scenario: dict(Counter(p["hybrid"] for r, p in zip(rows, predictions) if r["scenario"] == scenario))
            for scenario in sorted({r["scenario"] for r in rows})
        }
    predictions = cross_validate(train_rows, "scenario")
    summary["training_loso"] = {m: score([r["label"] for r in train_rows], predictions[m])
                                for m in ("tree", "hybrid")}
    for line in (dataset / "cases.jsonl").read_text().splitlines():
        case = json.loads(line)
        session = load_session(dataset, case["session"])
        infer_and_plan(session)
        view = build_view(session)
        first = view["steps"][0] if view["steps"] else {}
        summary["first_steps"].append({
            "case_id": case["case_id"], "scenario": case["scenario"],
            "title": first.get("title"), "explanation": first.get("explanation"),
            "diagnoses": [i.diagnosis for i in session.issues if i.tool == "pytest_run" and i.status == "open"],
        })
    (output / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("head", "training_rows", "test_rows", "scores", "training_loso")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.train.resolve(), args.dataset.resolve(), args.output.resolve())
