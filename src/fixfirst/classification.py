"""Rule baseline and a portable JSON Gini tree. Never unpickle external models."""

import json
from pathlib import Path

from .models import Issue

LABELS = [
    "environment_mismatch",
    "dependency_conflict",
    "import_failure",
    "explicit_config_missing",
    "style_issue",
    "other_unknown",
]
FEATURE_NAMES = ["import", "dependency", "config", "style", "tool", "collect", "lint", "install"]


def features(issue: Issue) -> list[int]:
    return [
        int(issue.kind == "import_failure"),
        int(issue.kind == "dependency_conflict"),
        int(issue.kind == "explicit_config_missing"),
        int(issue.kind == "style_issue"),
        int(issue.kind == "tool_failure"),
        int(issue.stage == "collect"),
        int(issue.stage == "lint"),
        int(issue.stage == "install"),
    ]


def rule_classify(issue: Issue) -> str:
    return issue.kind if issue.kind in LABELS else "other_unknown"


def predict_tree(issue: Issue, model: dict) -> str:
    if model.get("feature_names") != FEATURE_NAMES or model.get("schema_version") != 1:
        raise ValueError("分类模型结构与当前特征不匹配")
    values = features(issue)
    nodes, labels = model["nodes"], model["classes"]
    at = 0
    visited = set()
    while True:
        if at in visited or at < 0 or at >= len(nodes):
            raise ValueError("分类模型包含非法节点或循环")
        visited.add(at)
        node = nodes[at]
        if node["left"] == -1:
            label = labels[max(range(len(node["values"])), key=node["values"].__getitem__)]
            if label not in LABELS:
                raise ValueError("未知分类标签")
            return label
        feature = node["feature"]
        if feature < 0 or feature >= len(values):
            raise ValueError("非法特征索引")
        at = node["left"] if values[feature] <= node["threshold"] else node["right"]


def classify(issues: list[Issue], path: str | None = None):
    model = json.loads(Path(path).read_text()) if path else None
    for issue in issues:
        issue.category = rule_classify(issue)
        # Prediction is separate; it cannot invent evidence or override the observed category.
        issue.prediction = predict_tree(issue, model) if model else None


def train_tree(rows: list[dict], output: Path) -> dict:
    from sklearn.tree import DecisionTreeClassifier, export_text

    if len(rows) < 2:
        raise ValueError("训练数据不足")
    issues = [Issue.model_validate(row["issue"]) for row in rows]
    labels = [row["label"] for row in rows]
    if any(label not in LABELS for label in labels):
        raise ValueError("训练标签不在支持的类别中")
    clf = DecisionTreeClassifier(criterion="gini", max_depth=4, min_samples_leaf=2, random_state=42)
    clf.fit([features(issue) for issue in issues], labels)
    tree = clf.tree_
    model = {
        "schema_version": 1,
        "feature_names": FEATURE_NAMES,
        "classes": list(clf.classes_),
        "training_projects": sorted({r["project_id"] for r in rows}),
        "training_examples": len(rows),
        "nodes": [],
        "description": "小规模受控案例训练；预测仅作候选，不证明跨真实项目泛化。",
    }
    for i in range(tree.node_count):
        model["nodes"].append(
            {
                "left": int(tree.children_left[i]),
                "right": int(tree.children_right[i]),
                "feature": int(tree.feature[i]),
                "threshold": float(tree.threshold[i]),
                "values": tree.value[i][0].tolist(),
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(model, ensure_ascii=False, indent=2))
    output.with_suffix(".txt").write_text(export_text(clf, feature_names=FEATURE_NAMES))
    return model
