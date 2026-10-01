"""Fixed-model replay on fresh starting sessions of the 12 round-9 tasks (a32c195 code; nothing fitted or tuned).

    python ml_replay9.py <a32 checkout> <ablation2 copy> <dev tasks> <holdout tasks> <work dir> <output.json>
Each task is rebuilt from its frozen inputs (files + env-lock), one init + scan with the default configuration, then
every model is replayed on that same session: raw tree label and leaf share, the fused diagnosis that a32c195 would
assert, and the first action compared with rules only.
"""
import glob
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO, A, DEV, HOLD, WORK, OUT = (Path(p).resolve() for p in sys.argv[1:7])
sys.path.insert(0, str(REPO / "experiments/core_diagnosis"))
import fixfirst  # noqa: E402
assert Path(fixfirst.__file__).resolve().is_relative_to(REPO / "src"), fixfirst.__file__
from fixfirst.classification import load_model, predict_tree  # noqa: E402
from fixfirst.reasoning import diagnose  # noqa: E402
from fixfirst.storage import Store  # noqa: E402
from round8_ablation import plan  # noqa: E402

FF = Path(sys.executable).with_name("fixfirst")
MODELS = {"builtin44": REPO / "src/fixfirst/knowledge/diagnosis_tree.json",
          **{arm: A / "models" / f"full-{arm}.json" for arm in ("T61", "T65", "T80", "T81", "A65", "A80")}}
LOADED = {k: load_model(p) for k, p in MODELS.items()}
EXPECTED = {"M": "version_incompatibility", "U": "code_defect"}
def sh(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=1800)

result = {"models": {k: (str(p.relative_to(A)) if p.is_relative_to(A) else "a32c195:src/fixfirst/knowledge/diagnosis_tree.json") for k, p in MODELS.items()},
          "tasks": {}}
for half, root in (("dev", DEV), ("holdout", HOLD)):
    for n, task in enumerate(sorted(p for p in root.iterdir() if p.is_dir()), 1):
        meta = json.loads((task / "task.json").read_text())
        label = meta["task"] if half == "dev" else f"H{meta['class']}{n}"
        folder = WORK / label
        shutil.rmtree(folder, ignore_errors=True)
        shutil.copytree(task / "project", folder / "project")
        sh(["uv", "venv", "-q", "--seed", "--python", "3.12", str(folder / "venv")])
        sh([str(folder / "venv/bin/python"), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", str(task / "env-lock.txt")])
        store = folder / "store"
        sh([str(FF), "--store", str(store), "init", str(folder / "project"), "--python", str(folder / "venv/bin/python"), "--goal", "pass_tests"])
        sid = Path(glob.glob(str(store / "session-*"))[0]).name
        sh([str(FF), "--store", str(store), "scan", sid])
        session = Store(store).load(sid)
        details = diagnose(session)
        rules_only = plan(session, None)
        rows = []
        for issue in session.issues:
            if issue.tool != "pytest_run" or issue.status != "open" or issue.issue_id not in details:
                continue
            item = details[issue.issue_id]
            row = {"rules_heur": item["rule"] or item["likely"], "rule_id": item["rule_id"] or item["likely_rule_id"],
                   "expected": EXPECTED.get(meta["class"]), "features": len(item["evidence"]["features"]), "models": {}}
            for name, model in LOADED.items():
                raw, share = predict_tree(item["evidence"]["features"], model)
                planned = plan(session, MODELS[name])
                row["models"][name] = {"raw": raw, "share": round(share, 3),
                                       "asserted_diagnosis": planned["diagnoses"].get(issue.issue_id),
                                       "first_action": (planned["first_action"] or {}).get("title"),
                                       "first_action_changed_vs_rules_only": planned["first_action"] != rules_only["first_action"]}
            rows.append(row)
        result["tasks"][label] = {"class": meta["class"], "stratum": meta.get("stratum"), "half": half,
                                  "rules_only_first_action": (rules_only["first_action"] or {}).get("title"), "issues": rows}
        print(label, meta["class"], [(r["rules_heur"], {k: (v["raw"][:4], v["share"], (v["asserted_diagnosis"] or "-")[:4], v["first_action_changed_vs_rules_only"]) for k, v in r["models"].items()}) for r in rows], flush=True)
OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
