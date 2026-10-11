"""Offline bundle verification. Never launches a model, test project, or training."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import generated_scores as scorer  # noqa: E402


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def verify():
    sums = read(HERE / "SHA256SUMS.json")
    actual = {str(p.relative_to(HERE)) for p in HERE.rglob("*") if p.is_file()
              and "__pycache__" not in p.parts and p.name != "SHA256SUMS.json"}
    require(set(sums) == actual, "bundle file inventory differs")
    for name, expected in sums.items():
        require(sha(HERE / name) == expected, "changed bundle file: " + name)
    packaging = read(HERE / "PACKAGING.json")
    for name, source in packaging["files"].items():
        if source["transformation"] == "none":
            require(sha(HERE / name) == source["sha256"], "not an original copy: " + name)
    run, inputs, ff = HERE / "run", HERE / "inputs", HERE / "fixfirst"
    reg = read(run / "REGISTRATION.json")
    require(sha(run / "REGISTRATION.json") == read(run / "REGISTRATION_SHA256.json")["sha256"],
            "registration digest differs")
    computed = scorer.score(run / "answers", inputs / "labels.json")
    require(computed == read(run / "SCORES.json"), "sealed LLM score differs")
    labels = read(inputs / "labels.json")
    truths = {row["case_id"]: row for row in labels["cases"]}
    require(list(truths) == reg["case_ids"] and len(truths) == 250, "registered case order differs")
    require(sha(inputs / "labels.json") == reg["files_sha256"]["labels.json"], "label lock differs")
    manifest = read(run / "answers/input-manifest.json")
    llm_inputs = [json.loads(line) for line in (run / "answers/input-cases.jsonl").read_text().splitlines()]
    projected = {row["case_id"]: row for row in llm_inputs}
    sources = {}
    for provenance in manifest["input_provenance"]:
        suite = provenance["suite"]
        folder = inputs / "data/snapshots" / suite
        env_hash = sha(folder / "environment.json")
        require(env_hash == provenance["environment_sha256"], "snapshot environment differs")
        require(sha(folder / "cases.jsonl") == provenance["cases_sha256"], "snapshot cases differ")
        refs = {r["case_id"]: r for r in provenance["cases"]}
        for line in (folder / "cases.jsonl").read_text().splitlines():
            row = json.loads(line)
            cid = row["case_id"]
            digest = hashlib.sha256(canonical({"row": row, "environment_sha256": env_hash})).hexdigest()
            require(digest == refs[cid]["source_sha256"] == projected[cid]["source_sha256"],
                    "source-to-input binding differs: " + cid)
            require(row["label"] == truths[cid]["label"] and suite == truths[cid]["suite"],
                    "injection label differs: " + cid)
            sources[cid] = row
    identity = read(ff / "SOURCE_INPUT_IDENTITY.json")
    require(identity["replay_sha256"] == packaging["files"]["fixfirst/replay_portable.py"]["original_sha256"],
            "portable replay must identify the originally executed script")
    for name, expected in identity["snapshots"].items():
        require(sha(inputs / name) == expected, "replay snapshot differs: " + name)
    ff_scores = read(ff / "SCORES.json")
    require(ff_scores["label_sha256"] == sha(inputs / "labels.json"), "replay labels differ")
    source_status = {}
    for version, reg_key in (("v070", "product_commit"), ("v08", "v08_comparison_commit")):
        data = read(ff / (version + "-replay.json"))
        src = identity["sources"][version]
        commit = reg[reg_key]
        require(data["commit"] == src["commit"] == commit == ff_scores["versions"][version]["commit"],
                "replay source identity differs")
        require(data["model_features"] == 44 and data["default_model_sha256"] ==
                "4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3", "factory model differs")
        require([r["case_id"] for r in data["rows"]] == reg["case_ids"], "replay case order differs")
        require(all(r["observations_unchanged"] and not r["forbidden_io"] and r["error"] is None
                    for r in data["rows"]), "replay contains invalid observations or I/O")
        require(all(e["case_id"] == "__guard_self_test__" for e in data["guard"]["events"]),
                "replay attempted case I/O")
        for row in data["rows"]:
            original = [i for i in sources[row["case_id"]]["session"]["issues"]
                        if i["status"] == "open" and i["tool"] in ("pytest", "pytest_run")]
            require(len(original) == 1 and original[0]["issue_id"] == row["issue_id"], "original issue differs")
            require(all(original[0].get(k) == value for k, value in row["recorded_v070"].items()),
                    "saved baseline diagnosis differs")
            if version == "v070":
                require(all(row[k] == original[0].get(k) for k in
                            ("diagnosis", "diagnosis_source", "diagnosis_rule")), "v0.7 replay differs")
        for suite in ("diagnosis", "hard"):
            selected = [r for r in data["rows"] if r["suite"] == suite]
            pairs = [(truths[r["case_id"]]["label"], r["diagnosis"]) for r in selected]
            saved = ff_scores["versions"][version]["metrics"][suite]
            require(saved["n"] == len(pairs) and saved["correct"] == sum(t == p for t, p in pairs),
                    "replay integer totals differ")
            require(saved["qualification_counts"] == dict(Counter(r["qualification"] for r in selected)),
                    "replay source counts differ")
            f1s = {}
            for label in scorer.baseline.CAUSES:
                tp = sum(t == p == label for t, p in pairs)
                fp = sum(t != label and p == label for t, p in pairs)
                fn = sum(t == label and p != label for t, p in pairs)
                f1s[label] = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0
                require(all(saved["per_label"][label][k] == v for k, v in
                            {"tp": tp, "fp": fp, "fn": fn, "f1": f1s[label]}.items()), "replay class counts differ")
            require(saved["macro_f1_fixed_five"] == sum(f1s.values()) / 5, "replay five-class F1 differs")
            support = labels["supported_labels"][suite]
            require(saved["macro_f1_registered_support"] == sum(f1s[k] for k in support) / len(support),
                    "replay supported-class F1 differs")
        # Full source verification is possible only when the historical objects exist.
        try:
            found = subprocess.run(["git", "cat-file", "-e", commit + "^{commit}"], cwd=REPO,
                                   capture_output=True, check=False)
        except FileNotFoundError:
            source_status[version] = "NOT CHECKED: git unavailable"
            continue
        if found.returncode:
            source_status[version] = "NOT CHECKED: commit object unavailable (for example a shallow clone)"
            continue
        tree = subprocess.check_output(["git", "rev-parse", commit + "^{tree}"], cwd=REPO, text=True).strip()
        require(tree == src["tree"], "source tree differs")
        for name, expected in src["files_sha256"].items():
            content = subprocess.check_output(["git", "show", commit + ":" + name], cwd=REPO)
            require(hashlib.sha256(content).hexdigest() == expected, "product source differs: " + name)
        source_status[version] = "CHECKED: every recorded product source hash matches the commit"
    with tempfile.TemporaryDirectory(prefix="b3-report-check-") as directory:
        target = Path(directory) / "bundle"
        shutil.copytree(HERE, target, ignore=shutil.ignore_patterns("__pycache__"))
        subprocess.run([sys.executable, str(target / "build_report.py")], check=True, capture_output=True)
        for name in ("REPORT.md", "COMPARISON.json", "case-matrix.csv"):
            require((target / name).read_bytes() == (HERE / name).read_bytes(), "report rebuild differs: " + name)
    # Packaging may change paths/status prose; it may not change scientific values or any matrix row.
    require((HERE / "case-matrix.csv").read_bytes() == (HERE / "original-report/case-matrix.csv").read_bytes(),
            "case matrix changed during publication")
    now, original = read(HERE / "COMPARISON.json"), read(HERE / "original-report/COMPARISON.json")
    require({k: v for k, v in now.items() if k != "sources_sha256"} ==
            {k: v for k, v in original.items() if k != "sources_sha256"}, "scientific comparison changed")
    return {"status": "PASS", "files": len(sums), "llm_answers": 750, "product_replays": 500,
            "case_matrix_rows": 250, "historical_source_objects": source_status,
            "scope": "Contents and recorded counts, not independent proof of chronology or physical execution."}


if __name__ == "__main__":
    try:
        print(json.dumps(verify(), ensure_ascii=False, indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit("Rejected: " + str(error))
