"""Package only recorded development observations, excluding project environments."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from fixfirst.diagnosis_cases import PORTABLE_PYTHON
from fixfirst.runner import environment_id


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(source, target, description):
    target.mkdir(parents=True, exist_ok=False)
    for name in ("cases.jsonl", "environment.json"):
        shutil.copy2(source / name, target / name)
    manifest = json.loads((source / "manifest.json").read_text()) if (source / "manifest.json").exists() else {}
    manifest.update(description=description, cases_sha256=sha(target / "cases.jsonl"),
                    environment_sha256=sha(target / "environment.json"))
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def real_records(roots, target):
    target.mkdir(parents=True, exist_ok=False)
    audit, chosen = [], {}
    for root in roots:
        for path in sorted(root.glob("*.json")):
            if path.name == "summary.json":
                continue
            record = json.loads(path.read_text())
            if "id" not in record:
                continue
            entry = {key: record.get(key) for key in (
                "id", "accepted", "verification", "verification_scope", "after_fully_passed",
                "error", "tests_unchanged", "source_commit", "snapshot_sha256", "repair", "source_repair",
            )}
            entry["attempt"] = root.name
            entry["record_sha256"] = sha(path)
            entry["test_runs"] = {}
            for phase in ("before", "after"):
                data = record.get(phase, {})
                runs = [r for r in data.get("session", {}).get("runs", []) if r["tool"] in ("pytest", "pytest_run")]
                if runs:
                    run = runs[-1]
                    entry["test_runs"][phase] = {k: run.get(k) for k in ("tool", "status", "exit_code", "test_summary")}
                    entry["test_runs"][phase]["finish"] = [r for r in run["records"] if r.get("type") == "finish"][-1:]
                    entry["test_runs"][phase]["evidence"] = data.get("evidence", {})
            audit.append(entry)
            if record.get("accepted"):
                chosen[record["id"]] = record
    rows = []
    for name, record in sorted(chosen.items()):
        session = record["before"]["session"]
        # Earlier captures replaced the project root before its nested interpreter
        # path. Their environment IDs already name PORTABLE_PYTHON; align the path.
        if session["target_python"].startswith("/project/.venv/"):
            session["target_python"] = PORTABLE_PYTHON
        if session["environment"].get("_environment_id") != environment_id(session["target_python"]):
            raise ValueError(f"The captured environment does not match {name}'s interpreter")
        ids = record.get("labelled_issue_ids", [])
        if record["label"] != "healthy" and not ids:
            raise ValueError(f"No individually verified issue for {name}")
        rows.append({"case_id": f"real-{name}", "template": "real-project", "scenario": f"real-{name}",
                     "label": record["label"], "knowledge_covered": None,
                     "labelled_issue_ids": ids, "session": session,
                     "label_source": "examples/real-world/LABELS.md with recorded corrections",
                     "human_rereview": "pending", "verification": record["verification"],
                     "verification_scope": record.get("verification_scope", "test_execution"),
                     "repair": record["repair"], "source_commit": record["source_commit"]})
    (target / "cases.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    (target / "environment.json").write_text(json.dumps({"layout": "Each session includes its own environment snapshot"}) + "\n")
    (target / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    (target / "manifest.json").write_text(json.dumps({
        "origin": "verified_public_development", "cases": len(rows),
        "faults": sum(r["label"] != "healthy" for r in rows),
        "limitations": "Existing author labels with automated repair validation, not a newly human-reviewed or independent test set. Only the selected failure layer is labelled; knowledge coverage is unannotated. Healthy controls are excluded from fitting.",
        "cases_sha256": sha(target / "cases.jsonl"), "audit_sha256": sha(target / "audit.json"),
    }, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--hard", type=Path, required=True)
    parser.add_argument("--counterexamples", type=Path, required=True)
    parser.add_argument("--extra-controls", type=Path)
    parser.add_argument("--usage-training", type=Path)
    parser.add_argument("--real-attempt", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    capture(args.generated, args.output / "generated", "Fresh execution of the same 43 development fault families and five templates")
    capture(args.hard, args.output / "hard", "Development stress checks; never used for training")
    capture(args.counterexamples, args.output / "counterexamples", "Actually executed ordinary-error counterexamples; never used for training")
    if args.extra_controls:
        destination = args.output / "counterexamples/cases.jsonl"
        with destination.open("a") as stream:
            stream.write((args.extra_controls / "cases.jsonl").read_text())
        manifest = args.output / "counterexamples/manifest.json"
        data = json.loads(manifest.read_text())
        data.update(cases_sha256=sha(destination), additional_controls=4)
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if args.usage_training:
        capture(args.usage_training, args.output / "usage-training", "Controlled API-usage negatives for training; pass/fail/pass verified")
    real_records(args.real_attempt, args.output / "real")


if __name__ == "__main__":
    main()
