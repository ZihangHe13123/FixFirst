"""Would a stronger learner help? (1) single tree vs random forest vs gradient boosting under Codex's round-9
leave-one-family-out design; (2) an oracle classifier (always the true label) replayed through the real a32c195
planner, as the upper bound of what any classifier could change in the first action.

    python structure_check.py <a32 checkout> <ablation2 copy> <collection3 copy> <round-9 replay work dir> <out.json>
"""
import collections, json, re, sys, tempfile
from pathlib import Path

REPO, A, D, RW, OUT = (Path(p).resolve() for p in sys.argv[1:6])
sys.path.insert(0, str(REPO / "experiments/core_diagnosis"))
import numpy as np  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402
from fixfirst.classification import DIAGNOSES, MIN_CONFIDENCE, load_model  # noqa: E402
from fixfirst.evidence import FEATURE_LAYOUTS  # noqa: E402
from fixfirst.storage import Store  # noqa: E402
from round8_ablation import plan  # noqa: E402
import round9_ablation as ab  # noqa: E402

rows = json.loads((A / "feature-rows.json").read_text())
labelled = [r for r in rows if r["label"] is not None]
originals = [r for r in labelled if r["variant"] == 0]
groups = sorted({r["group"] for r in labelled})
report = {"rows": len(labelled), "originals": len(originals), "families": len(groups)}

# provenance, recorded by the run itself: code version, library versions and the sha256 of every input
import hashlib, importlib.metadata, platform, subprocess as _sp
import fixfirst as _ff
_sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
_src = Path(_ff.__file__).resolve().parent
report["provenance"] = {
    "fixfirst_source_commit": _sp.run(["git", "-C", str(_src), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or None,
    "fixfirst_source_dirty_files": len(_sp.run(["git", "-C", str(_src), "status", "--porcelain", "--", "."], capture_output=True, text=True).stdout.splitlines()),
    "python": platform.python_version(), "scikit_learn": importlib.metadata.version("scikit-learn"), "numpy": importlib.metadata.version("numpy"),
    "inputs_sha256": {
        "ablation/feature-rows.json": _sha(A / "feature-rows.json"),
        "collection/development.jsonl": _sha(D / "development.jsonl"),
        "collection/generated/cases.jsonl": _sha(D / "generated" / "cases.jsonl"),
        "candidate-80.json": _sha(REPO / "experiments/core_diagnosis/round9-models/candidate-80.json"),
        "builtin diagnosis_tree.json": _sha(REPO / "src/fixfirst/knowledge/diagnosis_tree.json"),
        "round-9 starting sessions": {p.parents[2].name: _sha(p) for p in sorted(RW.glob("*/store/session-*/session.json"))}},
}

# ---------------------------------------------------------------- 1. learners under the same LOFO design
LEARNERS = {
    "tree (depth 6, leaf 2)": lambda: DecisionTreeClassifier(criterion="gini", max_depth=6, min_samples_leaf=2, random_state=42),
    "random forest (300 trees)": lambda: RandomForestClassifier(n_estimators=300, min_samples_leaf=2, random_state=42, n_jobs=-1),
    "gradient boosting (hist, 200 iters)": lambda: HistGradientBoostingClassifier(max_iter=200, min_samples_leaf=2, random_state=42),
}
learners = {}
for width in ((65, 80) if "--skip-learners" not in sys.argv else ()):
    for name, make in LEARNERS.items():
        preds = {}
        for held in groups:
            train = [r for r in originals if r["group"] != held]
            counts = collections.Counter(r["group"] for r in train)
            X = np.array([r["features"][:width] for r in train]); y = [r["label"] for r in train]
            w = np.array([10 / counts[r["group"]] for r in train])
            model = make(); model.fit(X, y, sample_weight=w)
            test = [r for r in originals if r["group"] == held]
            proba = model.predict_proba(np.array([r["features"][:width] for r in test]))
            for r, p in zip(test, proba):
                best = int(np.argmax(p))
                preds[r["key"]] = (model.classes_[best], float(p[best]))
        right = lambda r: preds[r["key"]][0] == r["label"]
        fused = lambda r: (r["rules_heur"] or (preds[r["key"]][0] if preds[r["key"]][1] >= MIN_CONFIDENCE else None)) == r["label"]
        fam = collections.defaultdict(list)
        for r in originals:
            fam[r["group"]].append(right(r))
        learners[f"{width} / {name}"] = {
            "raw_rows": f"{sum(map(right, originals))}/{len(originals)}",
            "families_all_right": f"{sum(all(v) for v in fam.values())}/{len(fam)}",
            "fused_rows": f"{sum(map(fused, originals))}/{len(originals)}",
            "rule_uncovered_rows_right": f"{sum(right(r) for r in originals if not r['rules_heur'])}/{sum(1 for r in originals if not r['rules_heur'])}",
            "new_dev_families_raw": {r["key"].split(":")[1]: (preds[r["key"]][0][:12], round(preds[r["key"]][1], 2), r["label"][:12])
                                     for r in originals if r["tag"] == "dev"}}
report["learners_leave_one_family_out"] = learners or json.loads(OUT.read_text())["learners_leave_one_family_out"]


# ---------------------------------------------------------------- 2. oracle classifier through the real planner
def oracle_model(label, folder):
    path = folder / f"oracle-{label}.json"
    values = [1.0 if d == label else 0.0 for d in DIAGNOSES]
    path.write_text(json.dumps({"schema_version": 7, "task": "root_cause", "feature_names": FEATURE_LAYOUTS[7], "classes": list(DIAGNOSES),
                                "training_examples": 1, "nodes": [{"left": -1, "right": -1, "feature": -2, "threshold": -2.0, "values": values}]}))
    load_model(path)
    return path


EXEC = re.compile(r"replace `[^`]+` with `|: replace \S+ with \S+\.|fixfirst run session-|Run check")


def executable(action):
    if not action:
        return False
    return bool(action.get("command")) or bool(action.get("check")) or bool(EXEC.search(action.get("explanation") or ""))


tmp = Path(tempfile.mkdtemp())
ORACLE = {label: oracle_model(label, tmp) for label in DIAGNOSES}
CAND = REPO / "experiments/core_diagnosis/round9-models/candidate-80.json"
BUILTIN = REPO / "src/fixfirst/knowledge/diagnosis_tree.json"


def compare(session, label):
    base = plan(session, None)["first_action"]
    out = {"rules_only_executable": executable(base)}
    for name, path in (("oracle", ORACLE[label]), ("builtin44", BUILTIN), ("candidate80", CAND)):
        fa = plan(session, path)["first_action"]
        out[name] = {"changed": fa != base, "executable": executable(fa), "title": (fa or {}).get("title")}
    out["rules_only_title"] = (base or {}).get("title")
    return out


# 2a. Codex's 229 round-9 collection sessions (generated families + public dev tasks), originals with a label
cases, sessions_by_key = {}, {}
for case in ab.read_cases(D):
    sessions_by_key[case["tag"] + ":" + case["case_id"]] = case["session"]
gen = collections.Counter()
for r in originals:
    res = compare(sessions_by_key[r["key"]], r["label"])
    gen["sessions"] += 1
    gen["rules_only_executable"] += res["rules_only_executable"]
    for name in ("oracle", "builtin44", "candidate80"):
        gen[f"{name}_changed"] += res[name]["changed"]
        gen[f"{name}_executable"] += res[name]["executable"]
        gen[f"{name}_newly_executable"] += res[name]["executable"] and not res["rules_only_executable"]
report["oracle_on_collection_originals"] = dict(gen)

# 2b. the 12 round-9 tasks (fresh starting sessions); M -> version_incompatibility, U -> code_defect
TRUE = {"M": "version_incompatibility", "U": "code_defect"}
twelve = {}
for folder in sorted(p for p in RW.iterdir() if (p / "store").exists()):
    meta_class = None
    for root in (REPO / "experiments/field_trial/round9/dev", REPO / "experiments/field_trial/round9/holdout-reveal/tasks"):
        pass
    sid = next(p.name for p in (folder / "store").iterdir() if p.name.startswith("session-"))
    session = Store(folder / "store").load(sid)
    twelve[folder.name] = session
replay = json.loads((Path(sys.argv[5]).parent / "replay-12-PRIVATE.json").read_text()) if (Path(sys.argv[5]).parent / "replay-12-PRIVATE.json").exists() else None
cls = {k: v["class"] for k, v in (replay or {"tasks": {}})["tasks"].items()}
t12 = {}
for name, session in twelve.items():
    c = cls.get(name)
    if c not in TRUE:
        continue
    t12[name] = {"class": c, **compare(session, TRUE[c])}
report["oracle_on_round9_tasks"] = t12
OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
print(json.dumps(report["learners_leave_one_family_out"], indent=1, ensure_ascii=False))
print("oracle on collection originals:", report["oracle_on_collection_originals"])
for k, v in t12.items():
    print(f"  {k:24} {v['class']} rules-only exec={v['rules_only_executable']} | oracle changed={v['oracle']['changed']} exec={v['oracle']['executable']} "
          f"'{v['oracle']['title']}' | cand80 changed={v['candidate80']['changed']}")
