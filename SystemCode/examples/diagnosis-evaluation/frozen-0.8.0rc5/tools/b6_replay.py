#!/usr/bin/env python3
"""B6: what the product displays as the diagnosis for the saved sessions of the B3 snapshots. No model, no execution.

    b6_replay.py TREE SNAPSHOTS OUT.json

TREE is a checkout whose src/ is the product; SNAPSHOTS is .../inputs/data/snapshots of the B3 generated package
(diagnosis and hard: cases.jsonl with the saved session per case, the shared environment.json). As in the package's
replay (fixfirst/PROTOCOL.md): the shared environment is restored into the session, infer_and_plan is called with the
default model, and diagnosis, source and rule are read from the one open pytest issue the session registers.
Without that replay's I/O guard; recorded per case instead: an exception, and whether the saved observations are the
same after the call. Registered before the run in registry addendum 154.
"""
import hashlib
import json
import sys
from pathlib import Path

tree, snapshots, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3])
sys.path.insert(0, str(tree / "src"))
import fixfirst  # noqa: E402
from fixfirst import classification, reasoning  # noqa: E402
from fixfirst.models import Session  # noqa: E402

assert Path(fixfirst.__file__).resolve() == tree / "src/fixfirst/__init__.py"
model_file = tree / "src/fixfirst/knowledge/diagnosis_tree.json"
model_sha = hashlib.sha256(model_file.read_bytes()).hexdigest()
model = classification.default_model()
OBSERVED = ("project_root", "target_python", "runs", "events", "environment", "structured_evidence", "bounded_actions")


def digest(session):
    dumped = session.model_dump()
    return hashlib.sha256(json.dumps({k: dumped.get(k) for k in OBSERVED}, sort_keys=True, default=str).encode()).hexdigest()


rows = []
for suite in ("diagnosis", "hard"):
    folder = snapshots / suite
    shared = json.loads((folder / "environment.json").read_bytes())
    for line in (folder / "cases.jsonl").read_bytes().splitlines():
        raw = json.loads(line)
        data = raw["session"]
        env = data["environment"]
        assert env.get("$shared") == "environment.json"
        data["environment"] = {**shared, **{k: v for k, v in env.items() if k.startswith("_")}}
        registered = [i for i in data["issues"] if i["status"] == "open" and i["tool"] in ("pytest", "pytest_run")]
        assert len(registered) == 1, (raw["case_id"], len(registered))
        old = registered[0]
        session = Session.model_validate(data)
        before, error = digest(session), None
        try:
            reasoning.infer_and_plan(session)
        except Exception as exc:  # recorded, the case then counts as no diagnosis
            error = {"type": type(exc).__name__, "message": str(exc)[:300]}
        unchanged = digest(session) == before
        issue = next((i for i in session.issues if i.issue_id == old["issue_id"]), None)
        good = error is None and unchanged and issue is not None
        first = session.actions[0] if good and session.actions else None
        rows.append({
            "case_id": raw["case_id"], "suite": suite,
            "diagnosis": issue.diagnosis if good else None,
            "diagnosis_source": issue.diagnosis_source if good else None,
            "diagnosis_rule": issue.diagnosis_rule if good else None,
            "prediction": issue.prediction if good else None,
            "prediction_confidence": issue.prediction_confidence if good else None,
            "status": issue.status if good else None,
            "first_step_title": getattr(first, "title", None),
            "recorded_diagnosis": old.get("diagnosis"), "recorded_source": old.get("diagnosis_source"),
            "project_root_exists": Path(str(data.get("project_root"))).exists(),
            "error": error, "observations_unchanged": unchanged, "issue_found": issue is not None,
        })
out.write_text(json.dumps({"version": fixfirst.__version__, "tree_sha256": model_sha, "features": len(model["feature_names"]),
                           "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"product {fixfirst.__version__}; tree {model_sha[:12]} with {len(model['feature_names'])} features; {len(rows)} cases; "
      f"exceptions {sum(1 for r in rows if r['error'])}; observations changed {sum(1 for r in rows if not r['observations_unchanged'])}; "
      f"project folders that exist here {sum(1 for r in rows if r['project_root_exists'])}")
