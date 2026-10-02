"""Read-only integrity and exact-node checks; no feature extraction or training."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SHA = "4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--matrix", type=Path)
    args = parser.parse_args()
    result = json.loads((args.result / "results.json").read_text())
    nodes = {}
    for name in ("base-81", "base-93", "augmented-93"):
        path = args.result / "models" / (name + ".json")
        model = json.loads(path.read_text())
        indices = sorted({node["feature"] for node in model["nodes"] if node["left"] != -1})
        nodes[name] = {"file_sha256": sha(path), "internal_feature_indices": indices,
                       "new_feature_indices": [i for i in indices if i >= 81],
                       "new_feature_names": [model["feature_names"][i] for i in indices if i >= 81]}
    assert not nodes["base-93"]["new_feature_indices"]
    assert sha(ROOT / "src/fixfirst/knowledge/diagnosis_tree.json") == result["bundled_model_sha256"] == DEFAULT_SHA
    for name, expected in result["source_sha256"].items():
        assert sha(ROOT / "src/fixfirst" / name) == expected, name
    assert sha(Path(__file__).with_name("compare.py")) == result["script_sha256"]
    for protocol, models in result["comparisons"].items():
        for name, entry in models.items():
            predictions = entry["predictions"]
            assert len({p["row_key"] for p in predictions}) == len(predictions), (protocol, name)
            for method, metrics in entry["metrics"].items():
                assert metrics["rows"] == len(predictions)
                assert metrics["correct"] == sum(p[method] == p["label"] for p in predictions)
            for fold in entry.get("folds", []):
                assert not (set(fold["train_cases"]) & set(fold["test_cases"]))
    if args.matrix:
        for name, expected in result["datasets"]["toolchain"]["files_sha256"].items():
            assert sha(args.matrix / name) == expected, name
    print(json.dumps({"integrity": "passed", "default_model_sha256": DEFAULT_SHA,
                      "results_sha256": sha(args.result / "results.json"),
                      "nodes": nodes}, indent=2))


if __name__ == "__main__":
    main()
