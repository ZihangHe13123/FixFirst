"""Export separate A/C human scoring sheets after B3 answers have been sealed.

Usage: python experiments/diagnosis_baseline/blind_scores.py ANSWERS LABELS OUTPUT MAPPING

LABELS accepts the heldout.py CSV columns, or equivalent JSON rows (a list, or
{"cases": [...]}). Optional input_batch_sha256 metadata must match the answer batch.
Project IDs are preserved. Model identities are shuffled into aliases and written
only to MAPPING, which must be outside OUTPUT. Human scores are always blank.
"""

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil

from real_baseline import load_sealed_answers


CAUSES = {
    "missing_dependency", "local_module", "version_incompatibility", "config_missing",
    "code_defect", "healthy",
}
LABEL_FIELDS = ("root_cause", "first_step", "also_acceptable", "partial_if", "wrong_if")
SHEET_FIELDS = [
    "id", "label_root_cause", "label_first_step", "also_acceptable", "partial_if", "wrong_if",
    "model_root_cause", "model_first_step", "answer_status", "score", "scored_by", "notes",
]


def read_labels(path: Path, case_ids: list[str], batch_hash: str) -> dict[str, dict]:
    """Read only after the answer loader has validated the complete sealed batch."""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json" or text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        if isinstance(data, dict):
            if "input_batch_sha256" in data and data["input_batch_sha256"] != batch_hash:
                raise ValueError("Label input_batch_sha256 does not match the sealed answers")
            rows = data.get("cases")
        else:
            rows = data
        if not isinstance(rows, list):
            raise ValueError("Labels must be a JSON list or an object containing cases")
    else:
        reader = csv.DictReader(io.StringIO(text))
        fields = reader.fieldnames or []
        if len(set(fields)) != len(fields):
            raise ValueError("Duplicate label CSV columns")
        rows = list(reader)
    labels = {}
    for row in rows:
        if not isinstance(row, dict) or None in row:
            raise ValueError("Each label must be one object with named fields")
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("Every label needs a nonempty id")
        case_id = case_id.strip()
        if case_id in labels:
            raise ValueError(f"Duplicate label id: {case_id}")
        if "input_batch_sha256" in row and row["input_batch_sha256"] != batch_hash:
            raise ValueError("Label input_batch_sha256 does not match the sealed answers")
        clean = {}
        for field in LABEL_FIELDS:
            value = row.get(field, "")
            if not isinstance(value, str):
                raise ValueError(f"Label {case_id}: {field} must be text")
            clean[field] = value.strip()
        if clean["root_cause"] not in CAUSES:
            raise ValueError(f"Label {case_id}: unknown root_cause")
        if not clean["first_step"]:
            raise ValueError(f"Label {case_id}: first_step must not be empty")
        labels[case_id] = clean
    if set(labels) != set(case_ids):
        raise ValueError("Label IDs must exactly match the sealed answer case IDs")
    return labels


def export_scores(answers: Path, labels: Path, output: Path, mapping_output: Path) -> dict:
    """Validate the sealed answers first, then join labels and export unscored sheets."""
    output, mapping_output = Path(output).expanduser(), Path(mapping_output).expanduser()
    if output.exists() or output.is_symlink():
        raise ValueError("Scoring output already exists; choose a new directory")
    if mapping_output.exists() or mapping_output.is_symlink():
        raise ValueError("Model mapping already exists; choose a new file")
    output, mapping_output = output.resolve(), mapping_output.resolve()
    if mapping_output == output or mapping_output.is_relative_to(output):
        raise ValueError("Model mapping must be outside the scoring output directory")

    manifest, rows = load_sealed_answers(Path(answers))
    joined = read_labels(Path(labels), manifest["case_ids"], manifest["input_batch_sha256"])
    by_key = {(row["model"], row["case_id"]): row for row in rows}
    models = list(manifest["models"])
    secrets.SystemRandom().shuffle(models)
    aliases = {f"model-{index}": model for index, model in enumerate(models, 1)}
    files = {}
    for alias, model in aliases.items():
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=SHEET_FIELDS, lineterminator="\n")
        writer.writeheader()
        for case_id in manifest["case_ids"]:
            label, answer = joined[case_id], by_key[model, case_id]
            valid = answer["answer_status"] == "ok"
            writer.writerow({
                "id": case_id,
                "label_root_cause": label["root_cause"],
                "label_first_step": label["first_step"],
                **{field: label[field] for field in LABEL_FIELDS[2:]},
                "model_root_cause": answer["root_cause"] if valid else "",
                "model_first_step": answer["first_step"] if valid else "",
                "answer_status": answer["answer_status"],
                "score": "", "scored_by": "", "notes": "",
            })
        payload = stream.getvalue().encode("utf-8-sig")
        for scorer in ("A", "C"):
            files[f"{alias}-{scorer}.csv"] = payload

    report = {
        "schema_version": 1, "protocol": "b3-blind-scores-v1",
        "input_batch_sha256": manifest["input_batch_sha256"],
        "answers_sha256": manifest["results_sha256"],
        "protocol_sha256": manifest["protocol_sha256"],
        "case_ids": manifest["case_ids"], "model_aliases": list(aliases),
        "sheets": {name: hashlib.sha256(payload).hexdigest() for name, payload in files.items()},
    }
    mapping = {**report, "model_mapping": aliases}
    # Exclusive creation protects previous human scores and the separately kept key.
    output.mkdir(parents=True)
    mapping_created = False
    try:
        mapping_output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(mapping_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        mapping_created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(mapping, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        for name, payload in files.items():
            with (output / name).open("xb") as handle:
                handle.write(payload)
        with (output / "manifest.json").open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except BaseException:
        shutil.rmtree(output)
        if mapping_created:
            mapping_output.unlink(missing_ok=True)
        raise
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("answers", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("mapping_output", type=Path)
    args = parser.parse_args(argv)
    report = export_scores(args.answers, args.labels, args.output, args.mapping_output)
    print(f"Exported {len(report['sheets'])} unscored A/C sheets to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
