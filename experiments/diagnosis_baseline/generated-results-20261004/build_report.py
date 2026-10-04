"""Assemble the B3 comparison from immutable sealed answers and saved replays.

No inference, project execution, model training, resampling or answer repair.
"""
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "run"
PREP = ROOT / "inputs"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, data):
    (ROOT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main():
    registration = read(RUN / "REGISTRATION.json")
    state = read(RUN / "RUN_STATUS.json")
    assert state["status"] == "complete" and state["completed_requests"] == 750
    assert sha(RUN / "REGISTRATION.json") == read(RUN / "REGISTRATION_SHA256.json")["sha256"]
    seal = read(RUN / "answers/SEALED.json")
    assert sha(RUN / "answers/manifest.json") == seal["manifest_sha256"]
    manifest = read(RUN / "answers/manifest.json")
    assert sha(RUN / "answers/results.jsonl") == manifest["results_sha256"]
    assert sha(RUN / "answers/config.json") == manifest["config_sha256"]
    assert sha(RUN / "answers/input-manifest.json") == registration["files_sha256"]["inputs/manifest.json"]
    assert sha(RUN / "answers/input-cases.jsonl") == registration["files_sha256"]["inputs/cases.jsonl"]
    assert sha(PREP / "labels.json") == registration["files_sha256"]["labels.json"]
    truth = read(PREP / "labels.json")["cases"]
    labels = {r["case_id"]: r for r in truth}
    answers = [json.loads(line) for line in (RUN / "answers/results.jsonl").read_text().splitlines()]
    expected = [(model, row["case_id"]) for model in registration["models"] for row in truth]
    assert [(r["model"], r["case_id"]) for r in answers] == expected
    llm_scores = read(RUN / "SCORES.json")
    ff_scores = read(ROOT / "fixfirst/SCORES.json")
    timings = read(ROOT / "fixfirst/timing/SUMMARY.json")
    systems = []
    matrix = {r["case_id"]: {"case_id": r["case_id"], "suite": r["suite"], "truth": r["label"]} for r in truth}
    for version, title in (("v070", "FixFirst v0.7.0"), ("v08", "FixFirst v0.8 candidate")):
        data = read(ROOT / "fixfirst" / (version + "-replay.json"))
        expected_commit = registration["product_commit" if version == "v070" else "v08_comparison_commit"]
        assert data["commit"] == expected_commit and data["model_features"] == 44
        assert [r["case_id"] for r in data["rows"]] == registration["case_ids"]
        assert all(r["observations_unchanged"] and not r["forbidden_io"] and r["error"] is None for r in data["rows"])
        for row in data["rows"]:
            matrix[row["case_id"]][version] = row["diagnosis"]
            matrix[row["case_id"]][version + "_source"] = row["qualification"]
        metrics = ff_scores["versions"][version]["metrics"]
        for suite, score in metrics.items():
            selected = [r for r in data["rows"] if r["suite"] == suite]
            assert score["correct"] == sum(r["diagnosis"] == labels[r["case_id"]]["label"] for r in selected)
        systems.append({"id": version, "display": title, "kind": "recorded-session replay", "commit": expected_commit,
                        "metrics": metrics, "timing": timings["versions"][version]})
    latencies = {}
    hard_scenarios = {}
    for i, model in enumerate(registration["models"], 1):
        name = "llm" + str(i)
        selected = [r for r in answers if r["model"] == model]
        metrics = {suite: llm_scores["suites"][suite]["models"][model] for suite in ("diagnosis", "hard")}
        for row in selected:
            matrix[row["case_id"]][name] = row["root_cause"]
            matrix[row["case_id"]][name + "_status"] = row["answer_status"]
        latencies[model] = {}
        for suite in ("diagnosis", "hard", "all"):
            rows = [r for r in selected if suite == "all" or labels[r["case_id"]]["suite"] == suite]
            seconds = [r["latency_s"] for r in rows]
            latencies[model][suite] = {"n": len(rows), "sum_s": sum(seconds), "median_s": statistics.median(seconds),
                                      "min_s": min(seconds), "max_s": max(seconds)}
        hard_scenarios[model] = {}
        for scenario in dict.fromkeys(r["case_id"].split("--", 1)[1] for r in selected if labels[r["case_id"]]["suite"] == "hard"):
            rows = [r for r in selected if labels[r["case_id"]]["suite"] == "hard" and r["case_id"].endswith("--" + scenario)]
            assert len(rows) == 5
            hard_scenarios[model][scenario] = {"n": 5, "correct": sum(r["root_cause"] == labels[r["case_id"]]["label"] for r in rows),
                                                "predictions": dict(Counter(r["root_cause"] or "invalid" for r in rows))}
        for suite, score in metrics.items():
            assert score["correct"] == sum(r["root_cause"] == labels[r["case_id"]]["label"] for r in selected if labels[r["case_id"]]["suite"] == suite)
        systems.append({"id": name, "display": model, "kind": "local LLM request", "metrics": metrics,
                        "timing": latencies[model]})
    with (ROOT / "case-matrix.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(next(iter(matrix.values()))))
        writer.writeheader()
        writer.writerows(matrix.values())
    evidence_paths = [RUN / "REGISTRATION.json", RUN / "answers/SEALED.json", RUN / "answers/manifest.json", RUN / "SCORES.json",
                      ROOT / "fixfirst/SCORES.json", ROOT / "fixfirst/v070-replay.json", ROOT / "fixfirst/v08-replay.json",
                      ROOT / "fixfirst/timing/SUMMARY.json", PREP / "labels.json", Path(__file__).resolve()]
    summary = {"scope": "Frozen generated development evidence; category scoring, not repair success or unseen generalization",
               "input_batch_sha256": manifest["input_batch_sha256"], "systems": systems,
               "first_step_quality": "unscored", "hard_scenarios": hard_scenarios,
               "sources_sha256": {str(p.relative_to(ROOT)): sha(p) for p in evidence_paths}}
    save("COMPARISON.json", summary)
    table = ["| 系统 | 普通正确数 / 220 | 普通准确率 | 普通五类 Macro-F1 | 困难正确数 / 30 | 困难准确率 |",
             "|---|---:|---:|---:|---:|---:|"]
    for system in systems:
        a, b = (system["metrics"][s] for s in ("diagnosis", "hard"))
        table.append(f"| {system['display']} | {a['correct']} | {a['accuracy']:.2%} | {a['macro_f1_fixed_five']:.6f} | {b['correct']} | {b['accuracy']:.2%} |")
    hard_table = ["| 系统 | 二类 Macro-F1（补充） | 固定五类 Macro-F1（上限 0.4） |", "|---|---:|---:|"]
    for system in systems:
        m = system["metrics"]["hard"]
        hard_table.append(f"| {system['display']} | {m['macro_f1_registered_support']:.6f} | {m['macro_f1_fixed_five']:.6f} |")
    speed_table = ["| 本地模型 | 普通请求中位秒数 | 困难请求中位秒数 | 250 条请求累计耗时 |", "|---|---:|---:|---:|"]
    for model, t in latencies.items():
        speed_table.append(f"| {model} | {t['diagnosis']['median_s']:.3f} | {t['hard']['median_s']:.3f} | {t['all']['sum_s']/60:.2f} 分钟 |")
    began = datetime.fromisoformat(state["started_at"]).astimezone(ZoneInfo("Asia/Singapore"))
    ended = datetime.fromisoformat(state["completed_at"]).astimezone(ZoneInfo("Asia/Singapore"))
    template = (ROOT / "REPORT.template.md").read_text()
    for token, value in {"{{MAIN_TABLE}}": "\n".join(table), "{{HARD_TABLE}}": "\n".join(hard_table),
                         "{{SPEED_TABLE}}": "\n".join(speed_table), "{{START}}": began.strftime("%Y-%m-%d %H:%M:%S"),
                         "{{END}}": ended.strftime("%Y-%m-%d %H:%M:%S")}.items():
        template = template.replace(token, value)
    assert "{{" not in template
    (ROOT / "REPORT.md").write_text(template)
    print("Verified and assembled 5 systems, 2 suites, 250 paired matrix rows; no new model requests.")


if __name__ == "__main__":
    main()
