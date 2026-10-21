"""One-shot diagnosis baseline (task B3): a local model reads the same evidence as FixFirst and
names the root cause and the first step, without tools.

Usage:
  python experiments/diagnosis_baseline/one_shot.py DATASET --models MODEL [MODEL ...] --output DIR
         [--per-label N] [--cases ID ...] [--seed S] [--purpose TEXT]
  python experiments/diagnosis_baseline/one_shot.py --rescore DIR

DATASET is a recorded dataset: examples/diagnosis-dataset, or the output of `fixfirst dataset
--suite diagnosis|hard`. For each case the prompt holds the records FixFirst's diagnosis
reads (see evidence()): pytest's output and the exception records of FixFirst's pytest plugin,
pip check and Ruff output when they ran, the environment snapshot and the project index. FixFirst's
conclusions, its knowledge base and the case definition never enter the prompt; each prompt is
checked for the case name, the scenario and the label before it is sent. The answer must be one
JSON object with root_cause and first_step (see parse()). Failed requests, malformed responses and
invalid answers are recorded and count as wrong. DIR receives results.jsonl (one row per case and
model), config.json (dataset hash, cases, evidence limits, prompt hash, models, decoding settings,
FixFirst commit, seed) and summary.json. --rescore reads the saved answers in DIR again with the
current parser and rewrites summary.json, without asking any model.

Environment: LLM_BASE_URL (default http://127.0.0.1:8123/v1), LLM_API_KEY.
"""

import argparse
from datetime import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fixfirst import domain  # noqa: E402
from fixfirst.classification import DIAGNOSES  # noqa: E402
from fixfirst.diagnosis_cases import load_session  # noqa: E402
from fixfirst.evidence import current_environment, project_index  # noqa: E402

BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8123/v1")
KEY = os.environ.get("LLM_API_KEY", "")
DECODING = {"temperature": 0, "top_p": 1, "max_tokens": 1024}
# How much of each record a prompt keeps. Text keeps its first and last halves; lists and
# mappings keep their first entries. Every cut says how much was left out.
LIMITS = {
    "pytest_output_chars": 20000,
    "tool_output_chars": 6000,
    "exception_records": 50,
    "exception_message_chars": 1000,
    "list_items": 500,
}
# Left out of the snapshots: record identifiers and file hashes (bookkeeping), and the installed
# distributions' own requirements, which the diagnosis does not read (they made a small project's
# prompt four times longer).
OMITTED = {"environment": ["_run_id", "_environment_id", "packages[].requires"],
           "project": ["environment_run_id", "files[].sha256"]}
# The checks whose output FixFirst diagnoses from. Release searches are FixFirst's own follow-up
# (the model has no tools), and FixFirst's issues, facts and actions are its conclusions.
CHECKS = {"pytest": "pytest --collect-only", "pytest_run": "pytest", "pip_check": "pip check", "ruff": "Ruff"}
THINK = re.compile(r"<think>.*?</think>", re.S)
# A line of the snapshot listing: "field_name: <JSON value>".
FIELD_NAME = re.compile(r'^[a-z_]+: (?=[\[{"0-9-]|true\b|false\b|null\b)', re.M)
FENCE = re.compile(r"```(?:json)?[ \t]*\n?(.*?)\n?[ \t]*```", re.S | re.I)


class BadResponse(Exception):
    """The server answered, but not with a chat completion that holds text."""


def system_prompt() -> str:
    classes = "\n".join(f"- {name}: {domain.cause(name)['description']}" for name in DIAGNOSES)
    return (
        "You diagnose why a Python project's tests fail. You get what the project's checks recorded:\n"
        "- pytest's output, and the exception behind each failure as a pytest plugin recorded it "
        "(type, message, the file and line that raised it, warnings the test had recorded);\n"
        "- pip check and Ruff output, when they ran;\n"
        "- the environment: Python version, installed distributions, which distribution provides "
        "each import name, the standard library's module names;\n"
        "- the project index, read from the files without running them: files, Python files, "
        "top-level modules, names defined in the code (defined_names), what each imported name "
        "refers to (imported_names), the distributions the project itself builds (own_names), "
        "declared dependencies with their install status, Python requirements, lint settings, and "
        "versions pinned in lock files (tested_versions).\n"
        "Name the root cause of the failing tests as exactly one of these classes:\n"
        f"{classes}\n"
        "Also give the first thing the user should do. Answer with one JSON object and nothing else:\n"
        '{"root_cause": "<one class name from the list>", "first_step": "<one sentence>"}'
    )


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - 2 * half} characters left out ...]\n{text[-half:]}"


def trimmed(value, items: int = LIMITS["list_items"]):
    """Lists and mappings longer than `items` keep their first entries and say how many are left out."""
    if isinstance(value, list):
        kept = [trimmed(v, items) for v in value[:items]]
        return kept + ([f"[... {len(value) - items} more left out]"] if len(value) > items else [])
    if isinstance(value, dict):
        kept = {k: trimmed(v, items) for k, v in list(value.items())[:items]}
        if len(value) > items:
            kept["[left out]"] = f"{len(value) - items} more entries"
        return kept
    return value


def listing(data: dict) -> str:
    return "\n".join(f"{key}: {json.dumps(trimmed(value), ensure_ascii=False)}" for key, value in data.items())


def ruff_lines(stdout: str) -> str:
    """Ruff's JSON findings as its usual one-line text; anything else as it was printed."""
    try:
        findings = json.loads(stdout)
    except ValueError:
        return stdout
    if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
        return stdout
    lines = []
    for finding in findings:
        location = finding.get("location") or {}
        lines.append(f"{finding.get('filename')}:{location.get('row')}:{location.get('column')}: "
                     f"{finding.get('code')} {finding.get('message')}")
    return "\n".join(lines) or "(no findings)"


def exception_records(run) -> list[str]:
    """What FixFirst's pytest plugin recorded about each exception. Failure records are left out:
    they hold the same tracebacks as pytest's output."""
    records = [r for r in run.records if isinstance(r, dict) and r.get("type") == "exception"]
    lines = []
    for record in records[: LIMITS["exception_records"]]:
        shown = {k: v for k, v in record.items() if k != "type"}
        shown["exception_message"] = clip(str(shown.get("exception_message") or ""),
                                          LIMITS["exception_message_chars"])
        lines.append(json.dumps(shown, ensure_ascii=False))
    if len(records) > LIMITS["exception_records"]:
        lines.append(f"[... {len(records) - LIMITS['exception_records']} more exception records left out]")
    return lines


def evidence(session) -> str:
    """The records FixFirst's diagnosis reads, as it reads them (the latest run of each check,
    the environment and project snapshots only when they are current); nothing it concluded and
    nothing from the case definition."""
    latest = {run.tool: run for run in session.runs if run.tool in CHECKS}
    parts = []
    for tool, title in CHECKS.items():
        run = latest.get(tool)
        if run is None:
            continue
        if tool in ("pytest", "pytest_run"):
            parts.append(f"## {title} (exit code {run.exit_code})\n"
                         f"{clip(run.stdout + run.stderr, LIMITS['pytest_output_chars'])}")
            records = exception_records(run)
            if records:
                parts.append(f"## {title}: exception records\n" + "\n".join(records))
        else:
            output = ruff_lines(run.stdout) + run.stderr if tool == "ruff" else run.stdout + run.stderr
            parts.append(f"## {title} (exit code {run.exit_code})\n{clip(output, LIMITS['tool_output_chars'])}")
    environment = {k: v for k, v in current_environment(session).items() if k not in OMITTED["environment"]}
    if environment:
        environment["packages"] = [f"{p.get('name')}=={p.get('version')}" for p in environment.get("packages", [])]
        parts.append("## Environment\n" + listing(environment))
    _, project = project_index(session)
    if project:
        project = {"root": session.project_root,
                   **{k: v for k, v in project.items() if k not in OMITTED["project"]}}
        project["files"] = [{k: v for k, v in f.items() if k != "sha256"} for f in project.get("files", [])]
        parts.append("## Project index\n" + listing(project))
    return "\n\n".join(parts)


def leaks(text: str, row: dict) -> list[str]:
    """Anything that would give the answer away: the case name, the scenario or the label. The
    listing's own field names are not evidence ("local_modules:" does not give away local_module);
    everything else, values included, is checked."""
    content = FIELD_NAME.sub("", text)
    return [value for value in (row["case_id"], row.get("scenario", ""), row["label"]) if value and value in content]


def ask(model: str, messages: list[dict], seed: int) -> dict:
    body = {"model": model, "messages": messages, **DECODING, "seed": seed,
            "chat_template_kwargs": {"enable_thinking": False}}
    request = urllib.request.Request(f"{BASE}/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {KEY}"} if KEY else {})})
    with urllib.request.urlopen(request, timeout=1200) as response:  # noqa: S310 (local endpoint)
        raw = response.read()
    try:
        return json.loads(raw)
    except ValueError as error:
        raise BadResponse(f"the response is not JSON: {raw[:200]!r}") from error


def reply_text(answer) -> str:
    """The text of the first choice; anything else is a malformed response."""
    if not isinstance(answer, dict):
        raise BadResponse("the response is not a JSON object")
    choices = answer.get("choices")
    if not isinstance(choices, list) or not choices:
        raise BadResponse("the response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise BadResponse("the first choice has no message")
    content = message.get("content")
    if not isinstance(content, str):
        raise BadResponse("the message has no text content")
    return content


def parse(text: str) -> dict:
    """Read an answer. Once any thinking block is removed, it must be one JSON object, bare or in
    one Markdown code fence. root_cause must be one of the five classes (case and outer spaces do
    not matter) and first_step a non-empty string. Parts that break these rules are None and
    listed in `problems`; an answer with a valid root cause but no first step is not complete."""
    body = THINK.sub("", text).strip()
    fenced = FENCE.fullmatch(body)
    if fenced:
        body = fenced[1].strip()
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return {"root_cause": None, "first_step": None, "problems": ["not one JSON object"]}
    problems = []
    cause = data.get("root_cause")
    cause = cause.strip().lower() if isinstance(cause, str) else None
    if cause not in DIAGNOSES:
        cause = None
        problems.append("root_cause missing or not one of the five classes")
    step = data.get("first_step")
    step = step.strip() if isinstance(step, str) else ""
    if not step:
        problems.append("first_step missing, empty or not a string")
    return {"root_cause": cause, "first_step": step or None, "problems": problems}


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
        guess = [r["prediction"] or "no_valid_answer" for r in rows]
        answered = [r["seconds"] for r in rows if r.get("response") is not None]
        summary[model] = {
            "n": len(rows),
            "complete_answers": sum(r["prediction"] is not None and r["first_step"] is not None for r in rows),
            "root_cause_without_first_step": sum(r["prediction"] is not None and r["first_step"] is None
                                                 for r in rows),
            "invalid_answers": sum(r["error_kind"] is None and r["prediction"] is None for r in rows),
            "failed_requests": sum(r["error_kind"] == "request_failed" for r in rows),
            "bad_responses": sum(r["error_kind"] == "bad_response" for r in rows),
            "not_sent": sum(r["error_kind"] == "not_sent" for r in rows),
            "accuracy": round(sum(t == g for t, g in zip(truth, guess)) / len(rows), 3),
            "macro_f1": round(f1_score(truth, guess, labels=DIAGNOSES, average="macro", zero_division=0), 3),
            "per_label": {label: f"{sum(t == g == label for t, g in zip(truth, guess))}/{truth.count(label)}"
                          for label in DIAGNOSES if label in truth},
            "median_seconds": round(statistics.median(answered), 2) if answered else None,
        }
    return summary


def legacy_error_kind(row: dict) -> str | None:
    """Rows written before error kinds were recorded: only unsent prompts and failed requests."""
    if row.get("error") is None:
        return None
    return "not_sent" if row["error"].startswith("not sent") else "request_failed"


def rescore(directory: Path) -> int:
    rows = [json.loads(line) for line in (directory / "results.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    differ = []
    for row in rows:
        if "error_kind" not in row:
            row["error_kind"] = legacy_error_kind(row)
        if row.get("response") is not None:
            answer = parse(row["response"])
            if (answer["root_cause"], answer["first_step"]) != (row["prediction"], row["first_step"]):
                differ.append(f"{row['model']} {row['case_id']}")
            row["prediction"], row["first_step"] = answer["root_cause"], answer["first_step"]
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    summary = {
        "purpose": config.get("purpose"),
        "rescored": {"date": datetime.now().astimezone().isoformat(timespec="seconds"),
                     "note": "answers read again from results.jsonl with the current parser; no model was asked",
                     "answers_read_differently": differ},
        "models": score(rows),
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def run_case(model: str, prompt: str, row: dict, text: str, seed: int) -> dict:
    record = {"case_id": row["case_id"], "model": model, "label": row["label"],
              "evidence_sha256": hashlib.sha256(text.encode()).hexdigest(), "evidence_chars": len(text),
              "prediction": None, "first_step": None, "answer_problems": [], "error_kind": None, "error": None,
              "seconds": None, "prompt_tokens": None, "completion_tokens": None, "response": None}
    leaked = leaks(text, row)
    if leaked:
        record["error_kind"], record["error"] = "not_sent", f"the prompt would contain {leaked}"
        return record
    started = time.monotonic()
    try:
        answer = ask(model, [{"role": "system", "content": prompt}, {"role": "user", "content": text}], seed)
        content = reply_text(answer)
    except (OSError, http.client.HTTPException) as error:  # URLError, HTTPError, timeouts, resets
        record["error_kind"], record["error"] = "request_failed", f"{type(error).__name__}: {error}"[:500]
    except BadResponse as error:
        record["error_kind"], record["error"] = "bad_response", str(error)[:500]
    else:
        parsed = parse(content)
        record.update(response=content, prediction=parsed["root_cause"], first_step=parsed["first_step"],
                      answer_problems=parsed["problems"])
        usage = answer.get("usage") if isinstance(answer.get("usage"), dict) else {}
        record["prompt_tokens"], record["completion_tokens"] = usage.get("prompt_tokens"), usage.get("completion_tokens")
    record["seconds"] = round(time.monotonic() - started, 2)
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dataset", nargs="?")
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--output")
    parser.add_argument("--per-label", type=int, help="sample this many cases per root cause (seeded)")
    parser.add_argument("--cases", nargs="*", default=[])
    parser.add_argument("--seed", type=int, default=20260929)
    parser.add_argument("--purpose", default="development trial")
    parser.add_argument("--rescore", metavar="DIR", help="rewrite DIR's summary from its saved answers")
    args = parser.parse_args(argv)
    if args.rescore:
        return rescore(Path(args.rescore))
    if not (args.dataset and args.models and args.output):
        parser.error("DATASET, --models and --output are required")
    dataset = Path(args.dataset).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit(f"{output} exists; choose a new --output")
    cases_file = dataset / "cases.jsonl"
    rows = [json.loads(line) for line in cases_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    chosen = select(rows, args.per_label, args.cases, args.seed)
    prompt = system_prompt()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    changed = subprocess.run(["git", "status", "--porcelain", "--", "src", Path(__file__).relative_to(ROOT).as_posix()],
                             cwd=ROOT, capture_output=True, text=True).stdout.strip()
    output.mkdir(parents=True)
    config = {
        "purpose": args.purpose, "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": dataset.relative_to(ROOT).as_posix() if dataset.is_relative_to(ROOT) else dataset.name,
        "cases_sha256": hashlib.sha256(cases_file.read_bytes()).hexdigest(),
        "cases": [r["case_id"] for r in chosen], "models": args.models, "decoding": DECODING,
        "thinking": "disabled through chat_template_kwargs; any <think> block is removed before parsing",
        "evidence": {"checks": list(CHECKS), "limits": LIMITS, "omitted": OMITTED},
        "answer_format": "one JSON object, bare or in one code fence; root_cause one of the five classes, "
                         "first_step a non-empty string",
        "seed": args.seed, "system_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "system_prompt": prompt, "fixfirst_commit": commit,
        "uncommitted_changes": changed.splitlines(), "endpoint": BASE,
    }
    (output / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", "utf-8")
    results = []
    for model in args.models:
        for row in chosen:
            record = run_case(model, prompt, row, evidence(load_session(dataset, row["session"])), args.seed)
            results.append(record)
            with (output / "results.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            problem = record["error"] or "; ".join(record["answer_problems"])
            print(f"{model} {row['case_id']}: {record['prediction'] or 'no valid root cause'} "
                  f"(label {row['label']}){' - ' + problem if problem else ''}", flush=True)
    summary = {"purpose": args.purpose, "models": score(results)}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
