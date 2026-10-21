"""Keep generated actions and verification evidence without copied environments."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = []
    for folder in args.attempt:
        for path in sorted(folder.glob("*.json")):
            raw = json.loads(path.read_text())
            row = {k: raw.get(k) for k in (
                "id", "source_commit", "snapshot_sha256", "label", "outcome", "error",
                "first_action", "action_after_inspection", "execution_source", "steps", "cleanup",
                "test_changes", "verification_scope", "target_error_remaining", "reached_tests", "after_fully_passed",
            )}
            row.update(attempt=folder.name, raw_record_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            for phase in ("before", "inspection", "after"):
                if phase not in raw:
                    continue
                data = raw[phase]
                row[phase] = {"goal_status": data["session"]["goal_status"], "evidence": data["evidence"], "checks": []}
                for run in data["session"]["runs"]:
                    if run["tool"] not in ("pytest", "pytest_run", "version_search"):
                        continue
                    check = {k: run.get(k) for k in ("tool", "status", "exit_code", "verified_pass", "test_summary")}
                    if run["tool"] == "version_search":
                        check["result"] = json.loads(run["stdout"])
                    else:
                        check["finish"] = [{k: v for k, v in r.items() if k != "nodes"}
                                           for r in run["records"] if r.get("type") == "finish"]
                    row[phase]["checks"].append(check)
            records.append(row)
    text = json.dumps({"kind": "actual_generated_first_step_verification", "records": records,
                       "limits": "Original public development projects only. Generated commands or explicitly offered manual alternatives, with inspections recorded separately. Target-layer progress does not imply all tests pass; new human rereview remains pending."},
                      ensure_ascii=False, indent=2) + "\n"
    if any(needle in text for needle in ("/Users/", "/private/tmp/", "/private/var/folders/")):
        raise ValueError("Machine paths remain; inspect the capture before publication")
    with args.output.open("x") as stream:
        stream.write(text)
    print("Packaged", len(records), "attempt records")


if __name__ == "__main__":
    main()
