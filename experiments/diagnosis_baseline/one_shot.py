"""One-shot diagnosis baseline (task B3): a local model reads the same evidence as FixFirst and
names the root cause and the first step, without tools.

Usage:
  python experiments/diagnosis_baseline/one_shot.py DATASET --models MODEL [MODEL ...] --output DIR
         [--per-label N] [--cases ID ...] [--seed S] [--purpose TEXT]

DATASET is a recorded dataset: examples/diagnosis-dataset, or the output of `fixfirst dataset
--suite diagnosis|hard`. For each case the prompt holds only what FixFirst's checks recorded:
the pytest output, a summary of the environment snapshot, and the project's files and declared
dependencies. The label, the scenario and the case name never enter the prompt; each prompt is
checked for them before it is sent. The answer must be JSON with root_cause and first_step;
anything else is recorded as unparseable and counted as wrong. Requests that fail are recorded
too. DIR receives results.jsonl (one row per case and model), config.json (dataset hash, cases,
prompt hash, models, decoding settings, FixFirst commit, seed) and summary.json.

Environment: LLM_BASE_URL (default http://127.0.0.1:8123/v1), LLM_API_KEY.
"""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fixfirst import domain  # noqa: E402
from fixfirst.classification import DIAGNOSES  # noqa: E402
from fixfirst.diagnosis_cases import load_session  # noqa: E402

BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8123/v1")
KEY = os.environ.get("LLM_API_KEY", "")
DECODING = {"temperature": 0, "top_p": 1, "max_tokens": 1024}
MAX_OUTPUT_CHARS = 12000


def system_prompt() -> str:
    classes = "\n".join(f"- {name}: {domain.cause(name)['description']}" for name in DIAGNOSES)
    return (
        "You diagnose why a Python project's tests fail. You get the output of the project's own "
        "checks: the pytest run, the installed packages, and the project's files and declared "
        "dependencies. Name the root cause of the failing tests as exactly one of these classes:\n"
        f"{classes}\n"
        "Also give the first thing the user should do. Answer with one JSON object and nothing else:\n"
        '{"root_cause": "<one class name from the list>", "first_step": "<one sentence>"}'
    )


def clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n[... middle of the output left out ...]\n" + text[-limit // 2:]


def evidence(session) -> str:
    """The recorded check results, as FixFirst received them; nothing from the case definition."""
    parts = []
    for run in session.runs:
        if run.tool in ("pytest", "pytest_run"):
            parts.append(f"## pytest ({run.tool}, exit code {run.exit_code})\n{clip(run.stdout + run.stderr)}")
    environment = session.environment
    packages = sorted(f"{p.get('name')}=={p.get('version')}" for p in environment.get("packages", []))
    parts.append(f"## Environment\nPython {environment.get('python_version', 'unknown')}; installed: "
                 + ", ".join(packages))
    project_run = next((r for r in reversed(session.runs) if r.tool == "project"), None)
    if project_run:
        project = json.loads(project_run.stdout)
        declared = [f"{d['requirement']} ({d['source']})" for d in project.get("declarations", [])]
        parts.append("## Project\nPython files: " + ", ".join(project.get("python_files", [])) + "\n"
                     + "Declared dependencies: " + (", ".join(declared) or "none"))
    return "\n\n".join(parts)


def leaks(text: str, row: dict) -> list[str]:
    """Anything that would give the answer away: the case name, the scenario or the label."""
    return [value for value in (row["case_id"], row.get("scenario", ""), row["label"]) if value and value in text]


def ask(model: str, messages: list[dict], seed: int) -> dict:
    body = {"model": model, "messages": messages, **DECODING, "seed": seed,
            "chat_template_kwargs": {"enable_thinking": False}}
    request = urllib.request.Request(f"{BASE}/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {KEY}"} if KEY else {})})
    with urllib.request.urlopen(request, timeout=1200) as response:  # noqa: S310 (local endpoint)
        return json.loads(response.read())


def parse(text: str) -> tuple[str | None, str | None]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    for candidate in reversed(re.findall(r"\{[^{}]*\}", text, flags=re.S)):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        cause = str(data.get("root_cause", "")).strip().lower()
        if cause in DIAGNOSES:
            return cause, str(data.get("first_step", "")).strip()
    return None, None


def select(rows: list[dict], per_label: int | None, ids: list[str], seed: int) -> list[dict]:
    if ids:
        chosen = [r for r in rows if r["case_id"] in ids]
        missing = set(ids) - {r["case_id"] for r in chosen}
        if missing:
            raise SystemExit(f"Not in the dataset: {', '.join(sorted(missing))}")
        return chosen
    if per_label is None:
        return rows
    picker, chosen = random.Random(seed), []
    for label in DIAGNOSES:
        group = sorted((r for r in rows if r["label"] == label), key=lambda r: r["case_id"])
        chosen += picker.sample(group, min(per_label, len(group)))
    return chosen


def score(results: list[dict]) -> dict:
    from sklearn.metrics import f1_score

    summary = {}
    for model in dict.fromkeys(r["model"] for r in results):
        rows = [r for r in results if r["model"] == model]
        truth = [r["label"] for r in rows]
        guess = [r["prediction"] or "unparseable" for r in rows]
        summary[model] = {
            "n": len(rows),
            "answered": sum(r["prediction"] is not None for r in rows),
            "failed_requests": sum(r["error"] is not None for r in rows),
            "accuracy": round(sum(t == g for t, g in zip(truth, guess)) / len(rows), 3),
            "macro_f1": round(f1_score(truth, guess, labels=DIAGNOSES, average="macro", zero_division=0), 3),
            "per_label": {label: f"{sum(t == g == label for t, g in zip(truth, guess))}/{truth.count(label)}"
                          for label in DIAGNOSES if label in truth},
            "median_seconds": sorted(r["seconds"] for r in rows)[len(rows) // 2],
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dataset")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--per-label", type=int, help="sample this many cases per root cause (seeded)")
    parser.add_argument("--cases", nargs="*", default=[])
    parser.add_argument("--seed", type=int, default=20260929)
    parser.add_argument("--purpose", default="development trial")
    args = parser.parse_args()
    dataset = Path(args.dataset).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit(f"{output} exists; choose a new --output")
    cases_file = dataset / "cases.jsonl"
    rows = [json.loads(line) for line in cases_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    chosen = select(rows, args.per_label, args.cases, args.seed)
    prompt = system_prompt()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    output.mkdir(parents=True)
    config = {
        "purpose": args.purpose, "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": dataset.relative_to(ROOT).as_posix() if dataset.is_relative_to(ROOT) else dataset.name,
        "cases_sha256": hashlib.sha256(cases_file.read_bytes()).hexdigest(),
        "cases": [r["case_id"] for r in chosen], "models": args.models, "decoding": DECODING,
        "thinking": "disabled through chat_template_kwargs; any <think> block is removed before parsing",
        "seed": args.seed, "system_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "system_prompt": prompt, "fixfirst_commit": commit, "endpoint": BASE,
    }
    (output / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", "utf-8")
    results = []
    for model in args.models:
        for row in chosen:
            session = load_session(dataset, row["session"])
            text = evidence(session)
            leaked = leaks(text, row)
            record = {"case_id": row["case_id"], "model": model, "label": row["label"],
                      "evidence_sha256": hashlib.sha256(text.encode()).hexdigest(),
                      "prediction": None, "first_step": None, "error": None, "seconds": 0.0,
                      "prompt_tokens": None, "completion_tokens": None, "response": None}
            if leaked:
                record["error"] = f"not sent: the prompt would contain {leaked}"
            else:
                started = time.monotonic()
                try:
                    answer = ask(model, [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
                                 args.seed)
                    content = answer["choices"][0]["message"].get("content") or ""
                    record["response"] = content[:4000]
                    record["prediction"], record["first_step"] = parse(content)
                    usage = answer.get("usage") or {}
                    record["prompt_tokens"] = usage.get("prompt_tokens")
                    record["completion_tokens"] = usage.get("completion_tokens")
                except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as error:
                    record["error"] = f"{type(error).__name__}: {error}"[:500]
                record["seconds"] = round(time.monotonic() - started, 2)
            results.append(record)
            with (output / "results.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"{model} {row['case_id']}: {record['prediction'] or 'unparseable'} "
                  f"(label {row['label']}){' ERROR ' + record['error'] if record['error'] else ''}", flush=True)
    summary = {"purpose": args.purpose, "models": score(results)}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
