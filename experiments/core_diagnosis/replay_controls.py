"""Replay reserved controls with a chosen source tree and exported classifier.

Set PYTHONPATH to the archived revision's src directory to reproduce old rules.
This reads recorded observations only; it does not run the captured projects.
"""

import argparse
import hashlib
import json
from pathlib import Path

import fixfirst
from fixfirst.classification import load_model
from fixfirst.evaluation import load_rows, predict, score


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--code-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = Path(fixfirst.__file__).parent
    rows = load_rows(args.data)
    model = load_model(args.model)
    predictions = [predict(row, model) for row in rows]
    truth = [row["label"] for row in rows]
    report = {
        "kind": "recorded_control_replay",
        "code_head": args.code_head,
        "source_sha256": {str(p.relative_to(source)): sha(p) for p in sorted(source.rglob("*"))
                          if p.is_file() and "__pycache__" not in p.parts},
        "data_sha256": sha(args.data / "cases.jsonl"),
        "model_sha256": sha(args.model),
        "scores": {name: score(truth, [p[name] for p in predictions]) for name in ("tree", "hybrid")},
        "predictions": [{"case_id": r["case_id"], "truth": r["label"], **p}
                        for r, p in zip(rows, predictions)],
    }
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["scores"], ensure_ascii=False))


if __name__ == "__main__":
    main()
