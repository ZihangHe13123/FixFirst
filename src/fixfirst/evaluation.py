"""Offline evaluation with explicit project splits and controlled-data caveats."""

import json
from pathlib import Path
from itertools import combinations

from sklearn.metrics import classification_report, f1_score

from .classification import train_tree, predict_tree, rule_classify
from .grouping import group_events
from .models import Session, Issue


def pairwise_metrics(groups, truth):
    predicted = set()
    for group in groups:
        predicted.update(tuple(sorted(pair)) for pair in combinations(group.event_ids, 2))
    correct = {
        tuple(sorted(pair)) for pair in combinations(truth, 2) if truth[pair[0]] == truth[pair[1]]
    }
    hits = len(predicted & correct)
    return {
        "tp": hits,
        "fp": len(predicted - correct),
        "fn": len(correct - predicted),
        "precision": hits / len(predicted) if predicted else None,
        "recall": hits / len(correct) if correct else None,
    }


def evaluate(dataset: Path, output: Path, sbert_model=None):
    dataset, output = dataset.resolve(), output.resolve()
    if output.exists():
        raise ValueError("评价目录已存在，请使用新的输出目录，保留原始结果")
    output.mkdir(parents=True)
    manifest = json.loads((dataset / "manifest.json").read_text())
    rows = json.loads((dataset / "labeled_issues.json").read_text())
    projects = sorted({r["project_id"] for r in rows})
    if len(projects) < 3:
        raise ValueError("至少需要三个项目才能分离训练、验证和测试")
    split = {"train": projects[:-2], "validation": projects[-2:-1], "test": projects[-1:]}
    train = [r for r in rows if r["project_id"] in split["train"]]
    model = train_tree(train, output / "decision_tree.json")
    result = {
        "origin": manifest.get("origin", "controlled_injection"),
        "split": split,
        "classification": {},
        "grouping": {},
        "limitations": [
            manifest["limitations"],
            "分类使用解析后的故障信号，可能仅复现规则，不能据此声称模型带来增益。",
            "未做真人用户试验或付费 AI 基线。没有测量实际修复耗时或用户收益。",
        ],
    }
    for partition in ("validation", "test"):
        subset = [r for r in rows if r["project_id"] in split[partition]]
        truth = [r["label"] for r in subset]
        issues = [Issue.model_validate(r["issue"]) for r in subset]
        result["classification"][partition] = {}
        for name, pred in (
            ("rule", [rule_classify(i) for i in issues]),
            ("gini_tree", [predict_tree(i, model) for i in issues]),
        ):
            result["classification"][partition][name] = {
                "examples": len(subset),
                "macro_f1": f1_score(truth, pred, average="macro", zero_division=0),
                "report": classification_report(truth, pred, output_dict=True, zero_division=0),
            }
    methods = ["exact", "tfidf"] + (["sbert"] if sbert_model else [])
    for method in methods:
        totals = {"tp": 0, "fp": 0, "fn": 0}
        case_results = []
        for case in manifest["cases"]:
            if case["project_id"] not in split["test"]:
                continue
            session = Session.model_validate_json(
                (dataset / case["path"] / "input.json").read_text()
            )
            case_truth = json.loads((dataset / case["path"] / "truth.json").read_text())
            all_groups = []
            truth = {}
            for run in session.runs:
                events = [e for e in session.events if e.run_id == run.run_id]
                all_groups.extend(group_events(events, run, method, 0.82, sbert_model))
                # Execution cases label independent defects within the same tool separately.
                for event in events:
                    truth[event.event_id] = case_truth.get("event_groups", {}).get(
                        event.event_id, event.tool
                    )
            metrics = pairwise_metrics(all_groups, truth)
            for key in totals:
                totals[key] += metrics[key]
            case_results.append({"case_id": case["case_id"], **metrics, "groups": len(all_groups)})
        result["grouping"][method] = {
            **totals,
            "precision": totals["tp"] / (totals["tp"] + totals["fp"])
            if totals["tp"] + totals["fp"]
            else None,
            "recall": totals["tp"] / (totals["tp"] + totals["fn"])
            if totals["tp"] + totals["fn"]
            else None,
            "threshold": 0.82,
            "threshold_tuned": False,
            "cases": case_results,
        }
    (output / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    test = result["classification"]["test"]
    text = f"""# FixFirst 受控案例实验记录

数据：{len(manifest["cases"])} 个实际运行并恢复的受控案例。训练项目 {split["train"]}，验证项目 {split["validation"]}，测试项目 {split["test"]}。

| 方法 | 测试 Macro F1 | 样本数 |
|---|---|---|
| 规则分类 | {test["rule"]["macro_f1"]:.3f} | {test["rule"]["examples"]} |
| Gini 决策树 | {test["gini_tree"]["macro_f1"]:.3f} | {test["gini_tree"]["examples"]} |

这些模板高度相近，特征又包含解析到的故障信号。分数反映受控任务，不代表跨真实项目泛化。决策树作为候选输出，不用于覆盖证据或驱动自动修改。

归并指标与逐案例记录见 metrics.json。阈值 0.82 是明确记录的初始值，本轮没有利用测试集调参。{"SBERT 已使用指定本地模型运行。" if sbert_model else "本轮未运行 SBERT，未下载的模型不计作已实现效果。"}

本轮未进行行动调度收益评价。v0.1 的固定检查次数模拟已从新评测移除，它无法反映实际修复。真实用户与通用 AI 助手对比仍需小组另行执行。

继续研究应补充自然故障、误导性相似日志和不同结构的真实项目，再检验模型是否比规则有额外价值。
"""
    (output / "REPORT.md").write_text(text)
    return output / "REPORT.md"
