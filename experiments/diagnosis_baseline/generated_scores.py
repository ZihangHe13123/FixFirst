"""Offline root-cause scoring for sealed B3 generated and hard batches.

Validate every answer, input digest and model/case pair before opening the separately
registered labels. Never call a model, execute a project, infer labels from FixFirst,
or assess the quality of a first-step recommendation. Real-project A2 scores are not
part of either suite reported here.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generated_baseline as baseline  # noqa: E402

PROTOCOL = "b3-generated-scores-v1"
SUITES = ("diagnosis", "hard")
HARD_SUPPORT = ("local_module", "version_incompatibility")


def _labels(data: bytes, case_ids: list[str]) -> dict:
    labels = baseline.read_json(data)
    if (not isinstance(labels, dict) or set(labels) != {
            "schema_version", "protocol", "cases", "supported_labels"}
            or labels.get("schema_version") != 1
            or labels.get("protocol") != "b3-generated-labels-v1"):
        raise ValueError("invalid separated label manifest")
    cases, support = labels["cases"], labels["supported_labels"]
    if (not isinstance(cases, list) or not isinstance(support, dict)
            or set(support) != set(SUITES)):
        raise ValueError("label cases and registered support are required for both suites")
    seen = []
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {"case_id", "suite", "label"}
                or not isinstance(case.get("case_id"), str)
                or case.get("suite") not in SUITES
                or case.get("label") not in baseline.CAUSES):
            raise ValueError("invalid generated label case")
        seen.append(case["case_id"])
    if seen != case_ids or len(set(seen)) != len(seen):
        raise ValueError("label identities/order differ from the sealed input cases")
    for suite in SUITES:
        truths = {case["label"] for case in cases if case["suite"] == suite}
        expected = [label for label in baseline.CAUSES if label in truths]
        if not expected or support[suite] != expected:
            raise ValueError(f"{suite} registered support differs from its injection labels")
    if support["diagnosis"] != list(baseline.CAUSES):
        raise ValueError("diagnosis suite must include the registered five root-cause classes")
    if support["hard"] != list(HARD_SUPPORT):
        raise ValueError("hard suite must use its registered two-class support")
    return labels


def _metrics(rows: list[dict], truths: dict[str, str], support: list[str]) -> dict:
    """Retain every registered row in the denominator, including technical failures."""
    pairs = [(truths[row["case_id"]], row["root_cause"]
              if row["answer_status"] != "request_error" else None) for row in rows]
    per_label = {}
    for label in baseline.CAUSES:
        tp = sum(truth == prediction == label for truth, prediction in pairs)
        fp = sum(truth != label and prediction == label for truth, prediction in pairs)
        fn = sum(truth == label and prediction != label for truth, prediction in pairs)
        per_label[label] = {
            "support": sum(truth == label for truth, _ in pairs),
            "predicted": sum(prediction == label for _, prediction in pairs),
            "correct": tp, "tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
        }
    correct = sum(truth == prediction for truth, prediction in pairs)
    statuses = {status: sum(row["answer_status"] == status for row in rows)
                for status in ("ok", "invalid", "request_error")}
    return {
        "n": len(rows), "correct": correct, "accuracy": correct / len(rows),
        "no_valid_root_cause": sum(prediction is None for _, prediction in pairs),
        "complete_answers": statuses["ok"], "answer_status_counts": statuses,
        "root_cause_without_first_step": sum(
            row["root_cause"] is not None and row["first_step"] is None for row in rows),
        "macro_f1_fixed_five": sum(per_label[label]["f1"] for label in baseline.CAUSES)
        / len(baseline.CAUSES),
        "macro_f1_registered_support": sum(per_label[label]["f1"] for label in support)
        / len(support),
        "registered_support": support,
        "fixed_five_f1_perfect_prediction_ceiling": len(support) / len(baseline.CAUSES),
        "per_label": per_label,
    }


def score(answers: Path, labels_file: Path) -> dict:
    """Labels are read only after a complete checksum seal has been validated.

    These receipts bind file contents; they do not provide a signature or prevent a
    person from rewriting every receipt together. No actual chronology is inferred.
    """
    # Keep this call before even opening the labels file. An interrupted batch must
    # not become scoreable by dropping unanswered cases or a failed model.
    manifest, rows = baseline.load_sealed_answers(answers)
    input_manifest = baseline.read_json((answers / "input-manifest.json").read_bytes())
    expected_hash = input_manifest.get("labels_sha256")
    if not baseline._hash(expected_hash):
        raise ValueError("sealed inputs do not register a valid labels digest")
    label_bytes = labels_file.read_bytes()
    if baseline.digest(label_bytes) != expected_hash:
        raise ValueError("labels digest differs from the pre-answer input registration")
    labels = _labels(label_bytes, manifest["case_ids"])
    result = {
        "schema_version": 1, "protocol": PROTOCOL,
        "scorer_sha256": baseline.digest(Path(__file__).read_bytes()),
        "answers_manifest_sha256": baseline.digest((answers / "manifest.json").read_bytes()),
        "input_batch_sha256": manifest["input_batch_sha256"],
        "labels_sha256": expected_hash,
        "root_cause_policy": (
            "A valid root cause is scored even when first_step is missing. Missing or invalid "
            "root causes and failed requests count as incorrect in the full registered denominator."
        ),
        "first_step_quality": {
            "status": "unscored",
            "reason": "Requires a separately registered human rubric and ratings; text presence is not quality.",
        },
        "suite_policy": "Report diagnosis and hard separately; neither is combined with real-project A2.",
        "suites": {},
    }
    for suite in SUITES:
        suite_cases = [case for case in labels["cases"] if case["suite"] == suite]
        truths = {case["case_id"]: case["label"] for case in suite_cases}
        support = labels["supported_labels"][suite]
        result["suites"][suite] = {
            "case_ids": list(truths), "n_cases": len(truths),
            "primary_metrics": ["accuracy", "macro_f1_fixed_five"] if suite == "diagnosis"
            else ["accuracy", "per_label"],
            "supplementary_metrics": ["macro_f1_registered_support", "macro_f1_fixed_five"]
            if suite == "hard" else [],
            "support_policy": "Support is frozen from injection truth, never selected from predictions.",
            "models": {
                model: _metrics([row for row in rows if row["model"] == model
                                 and row["case_id"] in truths], truths, support)
                for model in manifest["models"]
            },
        }
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("answers", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = score(args.answers, args.labels)
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            # Never replace any pre-existing receipt or sealed answer file.
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(text)
        else:
            print(text, end="")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
