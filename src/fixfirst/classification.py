"""Root-cause classifier: a Gini decision tree over evidence features, plus baselines.

The tree only sees ``evidence.FEATURE_NAMES`` (exception type, where it was raised, what
the environment and project index say about the module, textual signals). It never sees
the parser's issue category or anything derived from a label. Models are portable JSON;
nothing is unpickled.
"""

from functools import lru_cache
from importlib import resources
import json
import math
from pathlib import Path

from .evidence import FEATURE_LAYOUTS, FEATURE_NAMES

DIAGNOSES = [
    "missing_dependency",
    "local_module",
    "version_incompatibility",
    "config_missing",
    "code_defect",
]
SCHEMA_VERSION = 8
MIN_CONFIDENCE = 0.6
NAIVE = {
    "import_failure": "missing_dependency",
    "dependency_conflict": "version_incompatibility",
    "environment_mismatch": "version_incompatibility",
    "explicit_config_missing": "config_missing",
}


def naive_diagnosis(kind: str) -> str:
    """Baseline: the parser's category alone decides the cause (FixFirst v0.3 behaviour)."""
    return NAIVE.get(kind, "code_defect")


def validate_model(model: dict) -> dict:
    version = model.get("schema_version")
    if version not in FEATURE_LAYOUTS or model.get("task") != "root_cause":
        raise ValueError(
            "Unsupported classifier model. Models from FixFirst 0.3 predicted parser "
            "categories; retrain with `fixfirst evaluate` on a diagnosis dataset."
        )
    expected = FEATURE_LAYOUTS[version]
    if model.get("feature_names") != expected:
        raise ValueError("Classifier features do not match this FixFirst version")
    if any(label not in DIAGNOSES for label in model["classes"]):
        raise ValueError("Classifier has an unknown label")
    return model


def load_model(path) -> dict:
    return validate_model(json.loads(Path(path).read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def default_model() -> dict | None:
    resource = resources.files("fixfirst").joinpath("knowledge/diagnosis_tree.json")
    if not resource.is_file():
        return None
    return validate_model(json.loads(resource.read_text("utf-8")))


def predict_tree(vector: list[float], model: dict) -> tuple[str, float]:
    """Walk the exported tree; return the leaf's majority label and its share."""
    width = len(model["feature_names"])
    # New observations retain the old prefix. A legacy model ignores only the
    # explicitly versioned extension; arbitrary extra or missing columns fail.
    compatible_extension = (
        model["feature_names"] == FEATURE_LAYOUTS.get(model.get("schema_version"))
        and any(len(vector) == len(names) and len(names) > width for names in FEATURE_LAYOUTS.values())
    )
    if len(vector) != width and not compatible_extension:
        raise ValueError("Feature vector has the wrong length")
    nodes, labels = model["nodes"], model["classes"]
    at, visited = 0, set()
    while True:
        if at in visited or not 0 <= at < len(nodes):
            raise ValueError("Classifier model has an invalid node or a cycle")
        visited.add(at)
        node = nodes[at]
        if node["left"] == -1:
            values = node["values"]
            total = sum(values) or 1
            best = max(range(len(values)), key=values.__getitem__)
            return labels[best], round(values[best] / total, 3)
        feature = node["feature"]
        if not 0 <= feature < width:
            raise ValueError("Classifier model uses an invalid feature index")
        at = node["left"] if vector[feature] <= node["threshold"] else node["right"]


def train_tree(
    rows: list[dict], output: Path | None = None, max_depth=6, min_samples_leaf=2,
    *, feature_names: list[str] | None = None,
):
    """Train on rows of {"features": [...], "label": ..., "group": ...}."""
    from sklearn.tree import DecisionTreeClassifier, export_text

    if len(rows) < 2 or len({r["label"] for r in rows}) < 2:
        raise ValueError("Not enough labelled examples to train")
    if any(r["label"] not in DIAGNOSES for r in rows):
        raise ValueError("Training label outside the supported diagnoses")
    names = FEATURE_NAMES if feature_names is None else list(feature_names)
    if names not in FEATURE_LAYOUTS.values():
        raise ValueError("Unsupported training feature layout")
    if any(len(r["features"]) != len(names) for r in rows):
        raise ValueError("Training feature vector has the wrong length")
    if any(not math.isfinite(value) for r in rows for value in r["features"]):
        raise ValueError("Training features must be finite numbers")
    weights = [r.get("weight", 1.0) for r in rows]
    if any(not math.isfinite(value) or value <= 0 for value in weights):
        raise ValueError("Training weights must be finite and positive")
    clf = DecisionTreeClassifier(
        criterion="gini",
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        random_state=42,
    )
    clf.fit([r["features"] for r in rows], [r["label"] for r in rows], sample_weight=weights)
    tree = clf.tree_
    model = {
        "schema_version": next(version for version, layout in FEATURE_LAYOUTS.items() if names == layout),
        "task": "root_cause",
        "feature_names": names,
        "classes": [str(c) for c in clf.classes_],
        "training_examples": len(rows),
        "training_groups": sorted({r["group"] for r in rows if r.get("group")}),
        "training_weight": sum(weights),
        "hyperparameters": {"max_depth": max_depth, "min_samples_leaf": min_samples_leaf},
        "description": "Gini decision tree over observed evidence features; suggestions only.",
        "feature_importances": {
            name: round(float(value), 4)
            for name, value in zip(names, clf.feature_importances_)
            if value > 0
        },
        "nodes": [
            {
                "left": int(tree.children_left[i]),
                "right": int(tree.children_right[i]),
                "feature": int(tree.feature[i]),
                "threshold": float(tree.threshold[i]),
                "values": [float(v) for v in tree.value[i][0]],
            }
            for i in range(tree.node_count)
        ],
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(model, indent=2), encoding="utf-8")
        output.with_suffix(".txt").write_text(
            export_text(clf, feature_names=names), encoding="utf-8"
        )
    return model


def suggest(details: dict, model: dict | None) -> dict:
    """Classifier suggestions per issue id: (label, confidence)."""
    if not model:
        return {}
    return {
        issue_id: predict_tree(evidence["features"], model)
        for issue_id, evidence in details.items()
        if "features" in evidence
    }
