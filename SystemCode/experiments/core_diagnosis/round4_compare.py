"""Compare scoped observations and explicit interface-history features.

The history-disabled arm removes both the direct history match and its negation.
All models keep the same fault across old/new observation views in one fold.
Static metadata is refreshed from retained fixture sources; test errors are replayed.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from fixfirst.classification import train_tree
from fixfirst.diagnosis_cases import load_session
from fixfirst.evaluation import load_rows, predict
from fixfirst.evidence import FEATURE_NAMES, V5_FEATURE_NAMES, project_index
from fixfirst.project import MAX_BYTES
from fixfirst.source_context import index_source_context

from round3_compare import result

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refresh(dataset, source_roots, output):
    output.mkdir()
    shutil.copyfile(dataset / "environment.json", output / "environment.json")
    records, changes = [], []
    for line in (dataset / "cases.jsonl").read_text().splitlines():
        row = json.loads(line)
        session = load_session(dataset, row["session"])
        run, project = project_index(session)
        source = next((root / row["case_id"] for root in source_roots if (root / row["case_id"]).is_dir()), None)
        if source and run:
            files = project.get("python_files", [])
            context = index_source_context(source, files, MAX_BYTES)
            old = project.get("source_context", {})
            for key in ("calls", "class_bases"):
                if context[key] != old.get(key, {}):
                    raise ValueError(f"Retained source no longer matches {row['case_id']}: {key}")
            changes.append({"case_id": row["case_id"], "source_context": context,
                            "files_sha256": {name: sha(source / name) for name in files if (source / name).is_file()}})
            project["source_context"] = context
            run.stdout = json.dumps(project)
            row["session"] = session.model_dump()
        records.append(row)
    (output / "cases.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    return load_rows(output), changes


def transform(rows, history, width):
    result_rows = []
    for row in rows:
        vector = list(row["features"][:width])
        if not history and width == len(FEATURE_NAMES):
            vector[FEATURE_NAMES.index("interface_history_match")] = 0.0
            vector[FEATURE_NAMES.index("external_call_without_history")] = float(
                vector[FEATURE_NAMES.index("callee_external")] and vector[FEATURE_NAMES.index("call_signature_mismatch")])
        result_rows.append({**row, "features": vector})
    return result_rows


def fit(rows, names, output=None, balanced=False):
    counts = Counter(r["group"] for r in rows)
    return train_tree([{**r, "weight": 10 / counts[r["group"]] if balanced else 1.0} for r in rows],
                      output, feature_names=names)


def grouped(training, test, names, balanced):
    models, folds = {}, []
    for group in sorted({r["group"] for r in test}):
        model = fit([r for r in training if r["group"] != group], names, balanced=balanced)
        models[group] = model
        folds.append({"held_out": group, "training_groups": model["training_groups"]})
    return {**result(test, [predict(r, models[r["group"]]) for r in test]), "folds": folds}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, help="Replay saved static metadata instead of reading fixture sources")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    base = ROOT / "experiments/core_diagnosis/observation-development-2026-09-30/data"
    scratch = ROOT / "workbench/model-round3"
    mapping = {
        "generated": [scratch / "fresh-generated/projects"],
        "hard": [scratch / "final-hard/projects"],
        "counterexamples": [scratch / "counterexamples", scratch / "extra-controls"],
        "usage-training": [scratch / "usage-training/projects"],
    }
    with tempfile.TemporaryDirectory(prefix="fixfirst-interface-replay-") as directory:
        sets, metadata = {}, {}
        for name, sources in mapping.items():
            if args.metadata:
                destination = Path(directory) / name
                destination.mkdir()
                shutil.copyfile(base / name / "environment.json", destination / "environment.json")
                changes = json.loads(args.metadata.read_text())[name]
                by_id = {r["case_id"]: r for r in changes}
                records = []
                for line in (base / name / "cases.jsonl").read_text().splitlines():
                    row = json.loads(line)
                    if row["case_id"] in by_id:
                        session = load_session(base / name, row["session"])
                        run, project = project_index(session)
                        project["source_context"] = by_id[row["case_id"]]["source_context"]
                        run.stdout = json.dumps(project)
                        row["session"] = session.model_dump()
                    records.append(row)
                (destination / "cases.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
                sets[name] = load_rows(destination)
                metadata[name] = changes
            else:
                sets[name], metadata[name] = refresh(base / name, sources, Path(directory) / name)
        sets["legacy"] = load_rows(ROOT / "examples/diagnosis-dataset")
        sets["previous_hard"] = load_rows(ROOT / "experiments/core_diagnosis/development-2026-09-30/data")
        sets["real"] = load_rows(base / "real")
    (output / "static-metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    report = {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / "src/fixfirst").rglob("*"))
                          if p.is_file() and "__pycache__" not in p.parts},
        "metadata_sha256": sha(output / "static-metadata.json"),
        "inputs_sha256": {name: sha(base / name / "cases.jsonl") for name in (*mapping, "real")},
        "limits": "Development replay. Metadata refreshed from retained fixture sources, not new test execution. History features use the pre-existing cited interface catalog. Controls and hard cases never fit.",
        "models": {},
    }
    report["environment_sha256"] = {name: sha(base / name / "environment.json") for name in (*mapping, "real")}
    for name, path in (("legacy", ROOT / "examples/diagnosis-dataset"),
                       ("previous_hard", ROOT / "experiments/core_diagnosis/development-2026-09-30/data")):
        report["inputs_sha256"][name] = sha(path / "cases.jsonl")
        report["environment_sha256"][name] = sha(path / "environment.json")
    configs = {
        "previous61": (False, False, V5_FEATURE_NAMES),
        "observations65": (False, False, FEATURE_NAMES),
        "history65": (True, False, FEATURE_NAMES),
        "observations_usage65": (False, True, FEATURE_NAMES),
        "history_usage65": (True, True, FEATURE_NAMES),
    }
    for name, (history, usage, names) in configs.items():
        data = {key: transform(rows, history, len(names)) for key, rows in sets.items()}
        training = data["legacy"] + data["generated"] + (data["usage-training"] if usage else [])
        model_path = output / (name + "-tree.json")
        model = fit(training, names, model_path, usage)
        item = {"training_rows": len(training), "history_features": history,
                "model_sha256": sha(model_path), "features": len(names),
                "current_scenario_out": grouped(training, data["generated"], names, usage),
                "legacy_scenario_out": grouped(training, data["legacy"], names, usage)}
        item["inference_contract"] = ("Apply transform(..., history=False) before prediction; this is an ablation export, not a drop-in CLI candidate."
                                      if not history and len(names) == len(FEATURE_NAMES) else "Standard observation features")
        for field, key in (("controls", "counterexamples"), ("fresh_hard", "hard"),
                           ("previous_hard", "previous_hard"), ("real", "real")):
            item[field] = result(data[key], [predict(row, model) for row in data[key]])
        report["models"][name] = item
        print(name, {key: item[key]["scores"] for key in ("current_scenario_out", "controls", "fresh_hard", "previous_hard", "real")}, flush=True)
    baseline = report["models"]["previous61"]
    for name, item in report["models"].items():
        item["acceptance"] = {key: item[key]["scores"]["tree"]["accuracy"] >= baseline[key]["scores"]["tree"]["accuracy"]
                              for key in ("current_scenario_out", "fresh_hard", "previous_hard", "real")}
        item["acceptance"]["controls_recovered"] = item["controls"]["scores"]["tree"]["accuracy"] >= 13 / 14 - 0.0001
        item["acceptance"]["complete_controls_preserved"] = item["controls"]["scores"]["hybrid"]["accuracy"] == 1
    report["selection"] = {"eligible": [name for name, item in report["models"].items() if all(item["acceptance"].values())],
                           "policy": "Require grouped/stress/real preservation and at least 13/14 raw controls before replacing the previous candidate. No automatic production replacement."}
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
