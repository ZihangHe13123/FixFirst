"""Compare captured product diagnoses by case, including unparsed baseline cases.

No inference or training is run: these are the default-model diagnoses captured
by the generator. A correct case requires every open pytest issue to match its
provisional scenario label. First-step quality and actual repairs are not scored.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


MODEL = "4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3"


def read(root):
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("completion") != "complete":
        raise ValueError("Only completed paired replays can be compared")
    if manifest["source_files_sha256"].get("knowledge/diagnosis_tree.json") != MODEL:
        raise ValueError("The captured default model differs from the frozen 44-feature model")
    status = {}
    for kind in ("cases", "unparsed", "rejected", "inapplicable"):
        for item in manifest[kind]:
            if item["case_id"] in status:
                raise ValueError("Repeated case in the ledger")
            status[item["case_id"]] = kind
    roster = {f"{t}--{s['id']}" for t in manifest["templates"] for s in manifest["scenarios"]}
    if set(status) != roster:
        raise ValueError("The ledger does not cover the registered roster")
    families = {s["id"]: s["family"] for s in manifest["scenarios"]}
    cases = {}
    for key, state in status.items():
        if state == "inapplicable":
            continue
        record = json.loads((root / "audit" / f"{key}.json").read_text())
        session = record["session"]
        if not session.get("use_classifier") or session.get("model_path"):
            raise ValueError("Expected the packaged classifier to be enabled")
        project = next(r for r in session["runs"] if r["tool"] == "project")
        files = json.loads(project["stdout"])["files"]
        issues = [i for i in session["issues"] if i["tool"] == "pytest_run" and i["status"] == "open"]
        cases[key] = {"family": families[record["scenario"]], "label": record["label"],
                      "project_files": files, "issue_count": len(issues),
                      "diagnoses": [i.get("diagnosis") for i in issues],
                      "correct": bool(issues) and all(i.get("diagnosis") == record["label"] for i in issues)}
    return manifest, status, cases


def compare(before, after):
    left, ls, lc = read(before)
    right, rs, rc = read(after)
    if left["environments"] != right["environments"] or left["scenarios"] != right["scenarios"]:
        raise ValueError("Environment identities or scenario definitions differ")
    if set(ls) != set(rs):
        raise ValueError("The registered case rosters differ")
    excluded = {key for key in ls if ls[key] in ("inapplicable", "rejected")}
    if excluded != {key for key in rs if rs[key] in ("inapplicable", "rejected")}:
        raise ValueError("Exclusion sets differ; do not silently change the paired denominator")
    rows, totals = [], defaultdict(Counter)
    for key in sorted(set(ls) - excluded):
        a, b = lc[key], rc[key]
        if any(a[k] != b[k] for k in ("project_files", "label", "family")):
            raise ValueError(f"Input files or labels differ for {key}")
        totals[a["family"]].update(cases=1, before_correct=int(a["correct"]), after_correct=int(b["correct"]))
        rows.append({"case_id": key, "family": a["family"], "provisional_label": a["label"],
                     "before": {"status": ls[key], **{k: a[k] for k in ("issue_count", "diagnoses", "correct")}},
                     "after": {"status": rs[key], **{k: b[k] for k in ("issue_count", "diagnoses", "correct")}}})
    return {"metric": "case-level captured root-cause classification, not repair success or first-step quality",
            "scope": "A2-informed development scenarios; labels include unreviewed author judgments",
            "frozen_default_model_sha256": MODEL,
            "n_cases": len(rows), "before_correct": sum(r["before"]["correct"] for r in rows),
            "after_correct": sum(r["after"]["correct"] for r in rows),
            "roster_size": len(ls), "before_ledger": dict(Counter(ls.values())),
            "after_ledger": dict(Counter(rs.values())), "families": dict(totals), "cases": rows,
            "input_file_hashes": {name: {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*")) if p.is_file()}
                for name, root in (("before", before), ("after", after))},
            "source_files_sha256": {"before": left["source_files_sha256"], "after": right["source_files_sha256"]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a new output path")
    result = compare(args.before, args.after)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print({k: result[k] for k in ("n_cases", "before_correct", "after_correct")})


if __name__ == "__main__":
    main()
