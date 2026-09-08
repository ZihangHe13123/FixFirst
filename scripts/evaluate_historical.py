"""Evaluate an existing classifier on small held-out upstream regression replays."""

import argparse
import json
from pathlib import Path

from sklearn.metrics import classification_report

from fixfirst.classification import predict_tree, rule_classify
from fixfirst.models import Session

parser = argparse.ArgumentParser()
parser.add_argument("replay", type=Path)
parser.add_argument("--model", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    raise ValueError("输出已存在，请使用新文件保留旧实验")
manifest = json.loads((args.replay / "results.json").read_text())
model = json.loads(args.model.read_text())
rows = []
for case in manifest["cases"]:
    if case["status"] != "reproduced":
        raise ValueError("含未完成的复现，不能据此报分类分数")
    session = Session.model_validate_json((args.replay / case["id"] / "broken.json").read_text())
    for issue in session.issues:
        if issue.tool == "pytest_run" and issue.status == "open":
            rows.append(
                {
                    "case": case["id"],
                    "truth": case["kind"],
                    "rule": rule_classify(issue),
                    "gini": predict_tree(issue, model),
                }
            )
result = {
    "samples": len(rows),
    "packages": sorted({c["package"] for c in manifest["cases"]}),
    "training": "No retraining; existing controlled execution dataset model",
    "rows": rows,
    "metrics": {
        method: classification_report(
            [r["truth"] for r in rows], [r[method] for r in rows], output_dict=True, zero_division=0
        )
        for method in ("rule", "gini")
    },
    "limitations": "Four minimal historical defect reproductions from two libraries. Too few and selected for feasibility; does not establish model advantage or generalization. Grouping and human repair time are not measured.",
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(args.output)
