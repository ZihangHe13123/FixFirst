"""Replay identical public development observations with fixed models and code.

Set PYTHONPATH to a revision's src directory. This never executes the recorded
projects, retrains a model, or reads the private held-out data.
"""

import argparse
import hashlib
import json
from pathlib import Path

import fixfirst
from fixfirst.classification import load_model
from fixfirst.evaluation import load_rows, predict


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="repository containing development snapshots")
    parser.add_argument("--code-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    source = Path(fixfirst.__file__).resolve().parent
    previous = json.loads((repo / "experiments/core_diagnosis/execution-development-2026-09-30/development-replay.json")
                          .read_text(encoding="utf-8"))
    model_paths = {
        "default44": source / "knowledge/diagnosis_tree.json",
        "candidate61": repo / previous["model"],
    }
    models = {name: load_model(path) for name, path in model_paths.items()}
    report = {
        "kind": "round5_recorded_development_replay", "code_head": args.code_head,
        "source_sha256": {str(p.relative_to(source)): sha(p) for p in sorted(source.rglob("*"))
                          if p.is_file() and "__pycache__" not in p.parts},
        "model_sha256": {name: sha(path) for name, path in model_paths.items()},
        "sets": {},
        "limits": "Fixed models on existing development observations, including fitting data. "
                  "Old snapshots lack the new runtime metadata. This is regression replay, "
                  "not independent evaluation, cross-validation, or fresh project execution.",
    }
    for name, recorded in previous["sets"].items():
        dataset = repo / recorded["input"]
        rows = load_rows(dataset)
        record = {"input": recorded["input"], "data_sha256": sha(dataset / "cases.jsonl"), "models": {}}
        for model_name, model in models.items():
            predictions = [{"case_id": row["case_id"], "truth": row["label"],
                            "rule_id": row["rule_id"], "likely_rule_id": row["likely_rule_id"],
                            **predict(row, model)} for row in rows]
            scores = {method: {"correct": sum(p[method] == p["truth"] for p in predictions),
                               "total": len(predictions)} for method in ("tree", "hybrid")}
            record["models"][model_name] = {"scores": scores, "predictions": predictions}
            print(name, model_name, scores, flush=True)
        report["sets"][name] = record
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
