"""Exact finite-data feature collisions; does not train a classifier."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from fixfirst.evaluation import load_rows  # noqa: E402
from fixfirst.evidence import FEATURE_LAYOUTS  # noqa: E402


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def collisions(rows, width):
    buckets = defaultdict(list)
    for row in rows:
        buckets[tuple(row["features"][:width])].append(row)
    conflicts = []
    for vector, members in buckets.items():
        labels = Counter(r["label"] for r in members)
        if len(labels) > 1:
            conflicts.append({"vector_sha256": digest(vector), "labels": dict(sorted(labels.items())),
                              "rows": len(members), "cases": sorted({r["case_id"] for r in members}),
                              "scenarios": sorted({r["scenario"] for r in members})})
    return {"rows": len(rows), "cases": len({r["case_id"] for r in rows}),
            "unique_vectors": len(buckets), "conflicting_vectors": len(conflicts),
            "rows_in_conflicts": sum(r["rows"] for r in conflicts),
            "minimum_errors_from_identical_vectors": sum(r["rows"] - max(r["labels"].values()) for r in conflicts),
            "conflicts": sorted(conflicts, key=lambda row: row["vector_sha256"])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("datasets", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    names = FEATURE_LAYOUTS[8]
    result = {"protocol": "historical-81-collisions-v1", "feature_names": names,
              "interpretation": "Development labels may be provisional; collisions do not prove universal inseparability.",
              "datasets": {}}
    pooled = []
    for dataset in args.datasets:
        rows = load_rows(dataset)
        summary = collisions(rows, len(names))
        summary["data_sha256"] = {str(p.relative_to(dataset)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(dataset.rglob("*")) if p.is_file()}
        summary["feature_rows_sha256"] = digest([{key: r[key] for key in ("case_id", "scenario", "label")}
                                                  | {"features": r["features"][:len(names)]} for r in rows])
        result["datasets"][dataset.name] = summary
        pooled += [{**r, "case_id": dataset.name + "/" + r["case_id"],
                    "scenario": dataset.name + "/" + r["scenario"]} for r in rows]
    result["pooled"] = collisions(pooled, len(names))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({name: {k: value[k] for k in ("rows", "cases", "conflicting_vectors", "rows_in_conflicts",
                                                  "minimum_errors_from_identical_vectors")}
                      for name, value in {**result["datasets"], "pooled": result["pooled"]}.items()}, indent=2))


if __name__ == "__main__":
    main()
