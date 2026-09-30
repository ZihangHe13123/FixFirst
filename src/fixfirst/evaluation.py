"""Offline experiments.

Diagnosis datasets (``fixfirst dataset --suite diagnosis``) compare how well each reasoning
component names the root cause of a failing test:

  naive_v03     parser category only (what FixFirst 0.3 effectively did)
  rules_no_kg   rule base without the domain knowledge graph (ablation)
  rules         rule base with the knowledge graph (confirmed diagnoses only)
  rules_heur    rules, then the heuristic phase (likely causes, rules H01/H02)
  tree          Gini decision tree on evidence features only
  hybrid_no_kg  rules and heuristics without knowledge, then the tree (ablation)
  hybrid        rules, heuristics, then the tree (what the product does)

Two cross-validation protocols train the tree without the held-out group: leave one
project template out (unseen project structure) and leave one scenario out (unseen fault
type). With ``--train`` a dataset is instead a held-out test set (for example the hard cases,
``--suite hard``) for a tree trained on another dataset. The rule base and knowledge graph are
fixed and were written by the authors, which the report states. Older controlled datasets are
evaluated for message grouping only.
"""

from collections import Counter
import csv
from itertools import combinations
import json
from pathlib import Path
import random

from .classification import (
    DIAGNOSES,
    MIN_CONFIDENCE,
    naive_diagnosis,
    predict_tree,
    train_tree,
)
from .diagnosis_cases import load_session
from .grouping import group_events
from .models import Session
from .reasoning import diagnose

METHODS = ("naive_v03", "rules_no_kg", "rules", "rules_heur", "tree", "hybrid_no_kg", "hybrid")
LABELS = {
    "naive_v03": "Parser category only (v0.3 baseline)",
    "rules_no_kg": "Rules without knowledge graph",
    "rules": "Rules + knowledge graph",
    "rules_heur": "Rules + KG + heuristics",
    "tree": "Decision tree only",
    "hybrid_no_kg": "Rules + heuristics without KG, then tree",
    "hybrid": "Rules + KG + heuristics, then tree (FixFirst)",
}


def load_rows(dataset: Path, skip=()) -> list[dict]:
    rows = []
    with (dataset / "cases.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            case = json.loads(line)
            session = load_session(dataset, case["session"])
            with_kg, without_kg = diagnose(session, skip=skip), diagnose(session, knowledge=False, skip=skip)
            issues = {i.issue_id: i for i in session.issues}
            for issue_id, item in with_kg.items():
                issue = issues[issue_id]
                if "labelled_issue_ids" in case and issue_id not in case["labelled_issue_ids"]:
                    continue
                if issue.tool != "pytest_run" or issue.status != "open":
                    continue
                evidence = item["evidence"]
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "template": case["template"],
                        "scenario": case["scenario"],
                        "group": case["scenario"],
                        "observation_view": case.get("observation_view", "recorded"),
                        "label": case["label"],
                        "knowledge_covered": case["knowledge_covered"],
                        "kind": issue.kind,
                        "stage": issue.stage,
                        "exception": evidence["exception"],
                        "message": evidence["message"][:160],
                        "features": evidence["features"],
                        "features_no_kg": without_kg[issue_id]["evidence"]["features"],
                        "rules": item["rule"],
                        "rule_id": item["rule_id"],
                        "likely": item["likely"],
                        "likely_rule_id": item["likely_rule_id"],
                        "rules_no_kg": without_kg[issue_id]["rule"],
                        "likely_no_kg": without_kg[issue_id]["likely"],
                    }
                )
    return rows


def score(truth, predicted) -> dict:
    from sklearn.metrics import f1_score

    answered = [(t, p) for t, p in zip(truth, predicted) if p]
    return {
        "n": len(truth),
        "accuracy": round(sum(t == p for t, p in zip(truth, predicted)) / len(truth), 4),
        "macro_f1": round(
            f1_score(
                truth,
                [p or "none" for p in predicted],
                labels=DIAGNOSES,
                average="macro",
                zero_division=0,
            ),
            4,
        ),
        "coverage": round(len(answered) / len(truth), 4),
        "precision_when_answered": round(sum(t == p for t, p in answered) / len(answered), 4)
        if answered
        else None,
    }


def bootstrap(truth, predicted, cases, samples=2000, seed=7) -> list[float]:
    """95% percentile interval for accuracy, resampling whole cases."""
    by_case = {}
    for index, case in enumerate(cases):
        by_case.setdefault(case, []).append(index)
    keys = sorted(by_case)
    generator = random.Random(seed)
    values = []
    for _ in range(samples):
        chosen = [i for _ in keys for i in by_case[generator.choice(keys)]]
        values.append(sum(truth[i] == predicted[i] for i in chosen) / len(chosen))
    values.sort()
    return [round(values[int(0.025 * samples)], 4), round(values[int(0.975 * samples) - 1], 4)]


def predict(row: dict, model: dict) -> dict:
    """Every method's diagnosis for one issue, with the tree `model`."""
    label, confidence = predict_tree(row["features"], model)
    suggestion = label if confidence >= MIN_CONFIDENCE else None
    plain_label, plain_confidence = predict_tree(row.get("features_no_kg", row["features"]), model)
    plain_suggestion = plain_label if plain_confidence >= MIN_CONFIDENCE else None
    return {
        "naive_v03": naive_diagnosis(row["kind"]),
        "rules_no_kg": row["rules_no_kg"],
        "rules": row["rules"],
        "rules_heur": row["rules"] or row["likely"],
        "tree": label,
        "hybrid_no_kg": row["rules_no_kg"] or row["likely_no_kg"] or plain_suggestion,
        "hybrid": row["rules"] or row["likely"] or suggestion,
    }


def cross_validate(rows: list[dict], key: str) -> dict:
    predictions = {method: [None] * len(rows) for method in METHODS}
    for group in sorted({r[key] for r in rows}):
        model = train_tree([r for r in rows if r[key] != group])
        for index, row in enumerate(rows):
            if row[key] == group:
                for method, value in predict(row, model).items():
                    predictions[method][index] = value
    return predictions


def summarise(rows, predictions) -> dict:
    truth = [r["label"] for r in rows]
    cases = [r["case_id"] for r in rows]
    result = {"overall": {}, "knowledge_covered": {}, "knowledge_not_covered": {}}
    for method in METHODS:
        overall = score(truth, predictions[method])
        overall["accuracy_95ci"] = bootstrap(truth, predictions[method], cases)
        result["overall"][method] = overall
        for name, flag in (("knowledge_covered", True), ("knowledge_not_covered", False)):
            index = [i for i, r in enumerate(rows) if r["knowledge_covered"] is flag]
            result[name][method] = score(
                [truth[i] for i in index], [predictions[method][i] for i in index]
            )
    return result


def per_class(rows, predicted) -> dict:
    from sklearn.metrics import classification_report

    report = classification_report(
        [r["label"] for r in rows],
        [p or "none" for p in predicted],
        labels=DIAGNOSES,
        output_dict=True,
        zero_division=0,
    )
    return {label: {k: round(v, 4) for k, v in report[label].items()} for label in DIAGNOSES}


def confusion(rows, predicted) -> dict:
    counts = Counter((r["label"], p or "none") for r, p in zip(rows, predicted))
    columns = [*DIAGNOSES, "none"]
    return {label: {c: counts[(label, c)] for c in columns} for label in DIAGNOSES}


def per_scenario(rows, predictions) -> list[dict]:
    table = []
    for scenario in sorted({r["scenario"] for r in rows}):
        index = [i for i, r in enumerate(rows) if r["scenario"] == scenario]
        entry = {
            "scenario": scenario,
            "label": rows[index[0]]["label"],
            "knowledge_covered": rows[index[0]]["knowledge_covered"],
            "n": len(index),
        }
        for method in METHODS:
            entry[method] = round(
                sum(predictions[method][i] == rows[i]["label"] for i in index) / len(index), 3
            )
        table.append(entry)
    return table


def markdown_table(summary: dict) -> list[str]:
    lines = [
        "| Method | Accuracy (95% CI) | Macro-F1 | Coverage | Precision when answering |",
        "|---|---|---|---|---|",
    ]
    for method in METHODS:
        m = summary[method]
        ci = m.get("accuracy_95ci")
        accuracy = f"{m['accuracy']:.3f}" + (f" ({ci[0]:.3f}–{ci[1]:.3f})" if ci else "")
        precision = "–" if m["precision_when_answered"] is None else f"{m['precision_when_answered']:.3f}"
        lines.append(
            f"| {LABELS[method]} | {accuracy} | {m['macro_f1']:.3f} | {m['coverage']:.3f} | {precision} |"
        )
    return lines


def evaluate_diagnosis(dataset: Path, output: Path) -> Path:
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    rows = load_rows(dataset)
    if len({r["template"] for r in rows}) < 2:
        raise ValueError("Need at least two templates for cross-validation")
    protocols = {
        "leave_one_template_out": cross_validate(rows, "template"),
        "leave_one_scenario_out": cross_validate(rows, "scenario"),
    }
    final = train_tree(rows, output / "decision_tree.json")
    results = {
        "origin": manifest["origin"],
        "cases": len({r["case_id"] for r in rows}),
        "issues": len(rows),
        "rejected_cases": len(manifest.get("rejected", [])),
        "labels": dict(Counter(r["label"] for r in rows)),
        "library_versions": manifest.get("library_versions", {}),
        "python": manifest.get("python"),
        "min_confidence": MIN_CONFIDENCE,
        "tree_hyperparameters": final["hyperparameters"],
        "rule_hits": dict(Counter(r["rule_id"] or "none" for r in rows)),
        "protocols": {},
    }
    for name, predictions in protocols.items():
        results["protocols"][name] = {
            **summarise(rows, predictions),
            "hybrid_per_class": per_class(rows, predictions["hybrid"]),
            "hybrid_confusion": confusion(rows, predictions["hybrid"]),
            "per_scenario": per_scenario(rows, predictions),
        }
    results["final_tree"] = {
        "nodes": len(final["nodes"]),
        "leaves": sum(n["left"] == -1 for n in final["nodes"]),
        "feature_importances": final["feature_importances"],
    }
    (output / "metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with (output / "predictions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case_id", "template", "scenario", "label", "kind", "exception", "rule_id",
                         *(f"{p}:{m}" for p in protocols for m in METHODS), "message"])
        for index, row in enumerate(rows):
            writer.writerow(
                [row["case_id"], row["template"], row["scenario"], row["label"], row["kind"],
                 row["exception"], row["rule_id"] or "",
                 *(protocols[p][m][index] or "" for p in protocols for m in METHODS),
                 row["message"]]
            )
    (output / "REPORT.md").write_text(report(results), encoding="utf-8")
    return output / "REPORT.md"


def report(results: dict) -> str:
    loto = results["protocols"]["leave_one_template_out"]
    loso = results["protocols"]["leave_one_scenario_out"]
    labels = ", ".join(f"{k} {v}" for k, v in sorted(results["labels"].items()))
    versions = ", ".join(f"{k} {v}" for k, v in sorted(results["library_versions"].items()))
    lines = [
        "# Root-cause diagnosis experiment",
        "",
        f"{results['cases']} executed cases ({results['issues']} failing-test issues; "
        f"{results['rejected_cases']} generated cases rejected because the fault was not observed). "
        f"Labels: {labels}. Python {results['python']}; {versions}.",
        "",
        "Each case is a small project with exactly one injected fault, run for real against "
        "the installed libraries. Labels come from the scenario definition. The decision tree "
        "is retrained for every fold without the held-out group; the rule base and knowledge "
        "graph are fixed and were written by the project team, so their scores on scenarios "
        "the team designed are optimistic. Scenarios marked *not covered* use removed APIs, "
        "packages or configuration patterns that the knowledge graph does not list. The "
        "heuristic rules H01/H02 (a name missing from an installed library suggests a version "
        "change) were added after testing on real projects (docs/REAL_PROJECTS.md); rows "
        "without heuristics are kept for comparison.",
        "",
        "## Unseen project structure (leave one template out)",
        "",
        *markdown_table(loto["overall"]),
        "",
        "## Unseen fault type (leave one scenario out)",
        "",
        *markdown_table(loso["overall"]),
        "",
        "## Knowledge-graph coverage (leave one scenario out, accuracy)",
        "",
        "| Method | Faults the KG covers | Faults the KG does not cover |",
        "|---|---|---|",
    ]
    for method in METHODS:
        covered = loso["knowledge_covered"][method]
        missing = loso["knowledge_not_covered"][method]
        lines.append(
            f"| {LABELS[method]} | {covered['accuracy']:.3f} (n={covered['n']}) | "
            f"{missing['accuracy']:.3f} (n={missing['n']}) |"
        )
    lines += [
        "",
        "## Hybrid per class (leave one template out)",
        "",
        "| Cause | Precision | Recall | F1 | Support |",
        "|---|---|---|---|---|",
    ]
    for label, m in loto["hybrid_per_class"].items():
        lines.append(
            f"| {label} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1-score']:.3f} | {int(m['support'])} |"
        )
    columns = [*DIAGNOSES, "none"]
    lines += [
        "",
        "## Hybrid confusion matrix (leave one template out; rows = truth)",
        "",
        "| Truth \\ predicted | " + " | ".join(columns) + " |",
        "|---|" + "---|" * len(columns),
    ]
    for label, row in loto["hybrid_confusion"].items():
        lines.append(f"| {label} | " + " | ".join(str(row[c]) for c in columns) + " |")
    weakest = sorted(loso["per_scenario"], key=lambda e: (e["hybrid"], e["scenario"]))[:8]
    lines += [
        "",
        "## Hardest scenarios for the hybrid (leave one scenario out)",
        "",
        "| Scenario | Cause | KG covers | Naive | Rules | Rules + heuristics | Tree | Hybrid |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in weakest:
        lines.append(
            f"| {e['scenario']} | {e['label']} | {'yes' if e['knowledge_covered'] else 'no'} | "
            f"{e['naive_v03']:.2f} | {e['rules']:.2f} | {e['rules_heur']:.2f} | {e['tree']:.2f} | {e['hybrid']:.2f} |"
        )
    importances = sorted(results["final_tree"]["feature_importances"].items(), key=lambda x: -x[1])
    lines += [
        "",
        "## Final decision tree",
        "",
        f"Trained on all {results['issues']} issues ({results['final_tree']['leaves']} leaves, "
        f"hyperparameters {results['tree_hyperparameters']} fixed in advance). Most important "
        "features: "
        + ", ".join(f"{name} {value:.2f}" for name, value in importances[:8])
        + ". The full tree is in decision_tree.txt; per-issue predictions are in predictions.csv.",
        "",
        "## Limitations",
        "",
        "- Five templates and one fault per case; real projects have several interacting faults.",
        "- The knowledge graph lists removals the team looked up; coverage elsewhere is partial by design.",
        "- A suggestion below the confidence threshold "
        f"({results['min_confidence']}) is not shown, so the hybrid may answer fewer cases than the tree.",
        "- No user study yet: these numbers measure diagnosis, not time saved.",
    ]
    return "\n".join(lines) + "\n"


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


def evaluate_grouping(dataset: Path, output: Path, sbert_model=None) -> Path:
    """Message grouping on the controlled collection/execution datasets."""
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    result = {"origin": manifest.get("origin"), "grouping": {}, "limitations": manifest["limitations"]}
    for method in ["exact", "tfidf"] + (["sbert"] if sbert_model else []):
        totals = {"tp": 0, "fp": 0, "fn": 0}
        for case in manifest["cases"]:
            session = Session.model_validate_json((dataset / case["path"] / "input.json").read_text(encoding="utf-8"))
            case_truth = json.loads((dataset / case["path"] / "truth.json").read_text(encoding="utf-8"))
            groups, truth = [], {}
            for run in session.runs:
                events = [e for e in session.events if e.run_id == run.run_id]
                groups.extend(group_events(events, run, method, 0.82, sbert_model))
                for event in events:
                    truth[event.event_id] = case_truth.get("event_groups", {}).get(
                        event.event_id, event.tool
                    )
            metrics = pairwise_metrics(groups, truth)
            for key in totals:
                totals[key] += metrics[key]
        predicted, actual = totals["tp"] + totals["fp"], totals["tp"] + totals["fn"]
        result["grouping"][method] = {
            **totals,
            "precision": totals["tp"] / predicted if predicted else None,
            "recall": totals["tp"] / actual if actual else None,
            "threshold": 0.82,
        }
    (output / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        "# Message grouping experiment",
        "",
        f"{len(manifest['cases'])} controlled cases. Pairwise precision/recall of grouping error "
        "messages that share a cause (threshold 0.82, set before evaluation).",
        "",
        "| Method | Precision | Recall | TP | FP | FN |",
        "|---|---|---|---|---|---|",
    ]
    for method, m in result["grouping"].items():
        p = "–" if m["precision"] is None else f"{m['precision']:.3f}"
        r = "–" if m["recall"] is None else f"{m['recall']:.3f}"
        lines.append(f"| {method} | {p} | {r} | {m['tp']} | {m['fp']} | {m['fn']} |")
    lines += ["", manifest["limitations"]]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output / "REPORT.md"


def evaluate_transfer(dataset: Path, train: Path, output: Path, skip=()) -> Path:
    """Test on one dataset (for example the hard cases) with a tree trained on another.

    ``skip`` leaves rules out of the test set's reasoning (a before/after comparison).
    """
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    train_rows, rows = load_rows(train), load_rows(dataset, skip)
    if not rows:
        raise ValueError("The dataset has no failing tests to diagnose")
    model = train_tree(train_rows)
    predictions = {method: [] for method in METHODS}
    said = []  # what the product (hybrid) concluded, and from which part
    for row in rows:
        predicted = predict(row, model)
        for method, value in predicted.items():
            predictions[method].append(value)
        source = (row["rule_id"] if row["rules"] else row["likely_rule_id"] if row["likely"]
                  else "tree" if predicted["hybrid"] else "none")
        said.append(f"{predicted['hybrid'] or 'none'} ({source})")
    results = {
        "origin": manifest["origin"],
        "suite": manifest.get("suite"),
        "cases": len({r["case_id"] for r in rows}),
        "issues": len(rows),
        "labels": dict(Counter(r["label"] for r in rows)),
        "trained_on": {"dataset": train.name, "issues": len(train_rows)},
        "skipped_rules": sorted(skip),
        "library_versions": manifest.get("library_versions", {}),
        # Overall only: a held-out set may have no cases the knowledge graph covers.
        "summary": {
            method: {
                **score([r["label"] for r in rows], predictions[method]),
                "accuracy_95ci": bootstrap([r["label"] for r in rows], predictions[method],
                                           [r["case_id"] for r in rows]),
            }
            for method in METHODS
        },
        "per_scenario": per_scenario(rows, predictions),
        "hybrid_said": {
            s: dict(Counter(said[i] for i, r in enumerate(rows) if r["scenario"] == s))
            for s in sorted({r["scenario"] for r in rows})
        },
        "hybrid_confusion": confusion(rows, predictions["hybrid"]),
        "limitations": manifest["limitations"],
    }
    (output / "metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with (output / "predictions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case_id", "scenario", "label", "exception", "rule_id", *METHODS, "message"])
        for index, row in enumerate(rows):
            writer.writerow([row["case_id"], row["scenario"], row["label"], row["exception"],
                             row["rule_id"] or "", *(predictions[m][index] or "" for m in METHODS),
                             row["message"]])
    (output / "REPORT.md").write_text(transfer_report(results), encoding="utf-8")
    return output / "REPORT.md"


def transfer_report(results: dict) -> str:
    labels = ", ".join(f"{k} {v}" for k, v in sorted(results["labels"].items()))
    lines = [
        "# Diagnosis on a held-out set",
        "",
        f"{results['cases']} executed cases ({results['issues']} failing-test issues). Labels: {labels}. "
        f"The decision tree was trained on {results['trained_on']['dataset']} "
        f"({results['trained_on']['issues']} issues); the rule base and knowledge graph were not "
        "changed for these cases."
        + (f" Rules left out: {', '.join(results['skipped_rules'])}." if results["skipped_rules"] else ""),
        "",
        *markdown_table(results["summary"]),
        "",
        "## Per scenario (accuracy)",
        "",
        "| Scenario | Cause | Rules | Rules + heuristics | Tree | FixFirst | FixFirst said (cases) |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in results["per_scenario"]:
        said = "; ".join(f"{k} ×{v}" for k, v in results["hybrid_said"][entry["scenario"]].items())
        lines.append(
            f"| {entry['scenario']} | {entry['label']} | {entry['rules']:.2f} | {entry['rules_heur']:.2f} "
            f"| {entry['tree']:.2f} | {entry['hybrid']:.2f} | {said} |"
        )
    lines += ["", results["limitations"], ""]
    return "\n".join(lines)


def evaluate(dataset: Path, output: Path, sbert_model=None, train: Path | None = None, skip=()) -> Path:
    dataset, output = dataset.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Evaluation directory already exists; use a new output directory")
    if skip and not train:
        raise ValueError("--skip-rules needs --train (a held-out test set)")
    output.mkdir(parents=True)
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    if train:
        return evaluate_transfer(dataset, train.resolve(), output, tuple(skip))
    if manifest.get("origin") == "diagnosis_injection":
        return evaluate_diagnosis(dataset, output)
    return evaluate_grouping(dataset, output, sbert_model)
