"""User-study analysis (task B13): read the anonymous tables and write the numbers RESULTS.md uses.

Usage (from the repository root):
  python docs/user-study/analysis.py [--sessions CSV] [--questionnaire CSV] [--causes CSV]
         [--output MD] [--json FILE] [--tasks-per-condition N] [--time-limit SECONDS] [--demo]
  python docs/user-study/analysis.py --cause-sheet OUT.csv [--sessions CSV]

The defaults read sessions.csv, questionnaire.csv and cause_scores.csv next to this script and
follow PROTOCOL.md: two tasks per condition, a 12-minute limit. DATA.md defines every column and
rule. In short:

- Records that contradict the rules (a duplicate participant and task, an unknown condition, a
  negative or over-limit time, a success after the limit or with modified tests, ...) stop the
  analysis with every problem listed, so they are corrected in the table, never guessed.
- Records left out on purpose (pilot and example rows, withdrawn tasks, values not recorded) are
  counted and listed with the reason. Nothing missing becomes 0 seconds or a success.
- Every measure uses its own valid records and says how many; the paired comparison uses only
  participants with the configured number of tasks in both conditions.
- A person scores the cause explanations (correct, partly, wrong). --cause-sheet writes the sheet
  for that, without the condition; the analysis only reads the scores.
- --demo marks the output as coming from fictional data. The output records the inputs'
  SHA-256, the protocol version, this script's version and the configuration.
"""

import argparse
import csv
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import random
import re
import statistics
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VERSION = "1.0"
CONDITIONS = ("fixfirst", "baseline")
SETS = {"A": ("T1", "T2"), "B": ("T3", "T4")}
TASKS = {task: name for name, tasks in SETS.items() for task in tasks}
EXCLUDED_PREFIXES = ("PILOT", "P00")
KNOWN_CAUSES = {
    "T1": "Jinja2 3.1 removed jinja2.Markup, which the code imports (Markup now comes from markupsafe).",
    "T2": "src layout: the project package is not installed, so it cannot be imported (the README says "
          "pip install -e .).",
    "T3": "Python 3.12 removed the distutils module, which the code uses for LooseVersion.",
    "T4": "settings.toml was never created: the README says to copy settings.example.toml.",
}
SESSION_COLUMNS = ("participant", "fixfirst_set", "task", "condition", "seconds", "success",
                   "false_done_claims", "tests_modified", "confidence_1to5", "cause_explanation")
SUS_ITEMS = tuple(f"sus_{n}" for n in range(1, 11))
TEXT_ANSWERS = ("easier_condition", "most_helpful", "confusing", "interview_stuck", "interview_would_use")
QUESTIONNAIRE_COLUMNS = ("participant", "python_years", "used_pytest", *SUS_ITEMS, *TEXT_ANSWERS)
CAUSE_COLUMNS = ("participant", "task", "cause_score")
SCORES = ("correct", "partly", "wrong")


class DataError(Exception):
    def __init__(self, problems):
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass
class Config:
    tasks_per_condition: int = 2
    time_limit: int = 720


@dataclass
class Task:
    line: int
    participant: str
    task: str
    condition: str
    fixfirst_set: str
    success: bool
    seconds: int | None
    claims: int | None
    tests_modified: bool | None
    confidence: int | None
    explanation: str
    score: str | None = None


@dataclass
class Data:
    tasks: list = field(default_factory=list)  # usable task records (success yes or no)
    excluded: list = field(default_factory=list)  # (file, line, participant, task, reason)
    rows_read: dict = field(default_factory=dict)
    per_person: dict = field(default_factory=dict)  # participant -> condition -> [rows of any kind]
    fixfirst_sets: dict = field(default_factory=dict)
    questionnaire: dict = field(default_factory=dict)  # participant -> row
    sus: dict = field(default_factory=dict)  # participant -> score
    sus_excluded: dict = field(default_factory=dict)  # participant -> reasons
    notes: list = field(default_factory=list)


def left_out(participant: str) -> str | None:
    if participant.upper().startswith(EXCLUDED_PREFIXES):
        return "pilot or example row (not analysed)"
    return None


def read_table(path: Path, required, problems) -> list[tuple[int, dict]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            problems.append(f"{path.name}: missing columns {', '.join(missing)}")
            return []
        return [(number, {k: (v or "").strip() for k, v in row.items() if k})
                for number, row in enumerate(reader, start=2)]


def whole_number(text: str) -> int | None:
    return int(text) if re.fullmatch(r"-?\d+", text) else None


def load_sessions(path: Path, config: Config, data: Data, problems: list):
    seen = {}
    rows = read_table(path, SESSION_COLUMNS, problems)
    data.rows_read["sessions"] = len(rows)
    for line, row in rows:
        where = f"{path.name} line {line}"
        person, task = row["participant"], row["task"].upper()
        if not person:
            problems.append(f"{where}: participant is empty")
            continue
        reason = left_out(person)
        if reason:
            data.excluded.append((path.name, line, person, task, reason))
            continue
        before = len(problems)
        condition = row["condition"].lower()
        if condition not in CONDITIONS:
            problems.append(f"{where}: condition {row['condition']!r} is not fixfirst or baseline")
        if task not in TASKS:
            problems.append(f"{where}: task {row['task']!r} is not one of {', '.join(TASKS)}")
        chosen = row["fixfirst_set"].upper()
        if chosen not in SETS:
            problems.append(f"{where}: fixfirst_set {row['fixfirst_set']!r} is not A or B")
        if (person, task) in seen:
            problems.append(f"{where}: {person} {task} is also on line {seen[person, task]}")
        seen.setdefault((person, task), line)
        outcome = row["success"].lower()
        if outcome not in ("yes", "no", "withdrawn", ""):
            problems.append(f"{where}: success {row['success']!r} is not yes, no or withdrawn")
        seconds = whole_number(row["seconds"]) if row["seconds"] else None
        if row["seconds"] and seconds is None:
            problems.append(f"{where}: seconds {row['seconds']!r} is not a whole number")
        elif seconds is not None and seconds < 0:
            problems.append(f"{where}: seconds {seconds} is negative")
        elif outcome == "yes" and seconds is not None and seconds > config.time_limit:
            problems.append(f"{where}: success after the time limit ({seconds} s > {config.time_limit} s)")
        elif seconds is not None and seconds > config.time_limit:
            problems.append(f"{where}: seconds {seconds} is above the time limit of {config.time_limit}")
        elif outcome == "yes" and not seconds:
            problems.append(f"{where}: a completed task needs its time (1 to {config.time_limit} seconds)")
        elif outcome == "no" and seconds is not None and seconds != config.time_limit:
            problems.append(f"{where}: a task not completed is recorded as {config.time_limit} s (the time "
                            f"limit), not {seconds}; if the participant left the study, use success=withdrawn")
        modified = row["tests_modified"].lower()
        if modified not in ("yes", "no", ""):
            problems.append(f"{where}: tests_modified {row['tests_modified']!r} is not yes or no")
        if outcome == "yes" and modified == "yes":
            problems.append(f"{where}: success with modified tests (the grader fails when tests change)")
        claims = whole_number(row["false_done_claims"]) if row["false_done_claims"] else None
        if row["false_done_claims"] and (claims is None or claims < 0):
            problems.append(f"{where}: false_done_claims {row['false_done_claims']!r} is not a count")
        confidence = whole_number(row["confidence_1to5"]) if row["confidence_1to5"] else None
        if row["confidence_1to5"] and (confidence is None or not 1 <= confidence <= 5):
            problems.append(f"{where}: confidence_1to5 {row['confidence_1to5']!r} is not 1 to 5")
        if len(problems) > before:
            continue
        data.per_person.setdefault(person, {c: [] for c in CONDITIONS})[condition].append((task, outcome))
        data.fixfirst_sets.setdefault(person, {})[chosen] = line
        if outcome == "withdrawn":
            data.excluded.append((path.name, line, person, task, "withdrawn from the study"))
            continue
        if not outcome:
            data.excluded.append((path.name, line, person, task, "success not recorded"))
            continue
        data.tasks.append(Task(line, person, task, condition, chosen, outcome == "yes",
                               seconds if outcome == "yes" else config.time_limit, claims,
                               {"yes": True, "no": False}.get(modified), confidence, row["cause_explanation"]))
    for person, conditions in data.per_person.items():
        sets = data.fixfirst_sets[person]
        if len(sets) > 1:
            problems.append(f"{person}: fixfirst_set differs between rows ({', '.join(sorted(sets))})")
            continue
        chosen = next(iter(sets))
        other = "B" if chosen == "A" else "A"
        for condition, rows in conditions.items():
            if len(rows) > config.tasks_per_condition:
                problems.append(f"{person}: {len(rows)} {condition} tasks, but the configuration allows "
                                f"{config.tasks_per_condition} per condition")
            expected = chosen if condition == "fixfirst" else other
            wrong = sorted(task for task, _ in rows if TASKS[task] != expected)
            if wrong:
                problems.append(f"{person}: {condition} tasks {', '.join(wrong)} are not in set {expected} "
                                f"(fixfirst_set is {chosen})")


def sus_score(row: dict) -> tuple[float | None, list[str]]:
    values, reasons = [], []
    for number, item in enumerate(SUS_ITEMS, start=1):
        text = row.get(item, "")
        value = whole_number(text) if text else None
        if not text:
            reasons.append(f"{item} missing")
        elif value is None or not 1 <= value <= 5:
            reasons.append(f"{item} = {text!r} is not a whole number from 1 to 5")
        else:
            values.append(value - 1 if number % 2 else 5 - value)
    return (sum(values) * 2.5, []) if not reasons else (None, reasons)


def load_questionnaire(path: Path, data: Data, problems: list):
    seen = {}
    rows = read_table(path, QUESTIONNAIRE_COLUMNS, problems)
    data.rows_read["questionnaire"] = len(rows)
    for line, row in rows:
        person = row["participant"]
        where = f"{path.name} line {line}"
        if not person:
            problems.append(f"{where}: participant is empty")
            continue
        if left_out(person):
            data.excluded.append((path.name, line, person, "", left_out(person)))
            continue
        if person in seen:
            problems.append(f"{where}: {person} is also on line {seen[person]}")
            continue
        seen[person] = line
        if row["python_years"] and not re.fullmatch(r"\d+(\.\d+)?", row["python_years"]):
            problems.append(f"{where}: python_years {row['python_years']!r} is not a number of years")
        if row["used_pytest"].lower() not in ("yes", "no", ""):
            problems.append(f"{where}: used_pytest {row['used_pytest']!r} is not yes or no")
        if person not in data.per_person:
            data.excluded.append((path.name, line, person, "", "no task records for this participant"))
            continue
        data.questionnaire[person] = row
        score, reasons = sus_score(row)
        if reasons:
            data.sus_excluded[person] = reasons
        else:
            data.sus[person] = score


def load_causes(path: Path, data: Data, problems: list):
    usable = {(t.participant, t.task): t for t in data.tasks}
    seen = {}
    rows = read_table(path, CAUSE_COLUMNS, problems)
    data.rows_read["cause_scores"] = len(rows)
    for line, row in rows:
        person, task = row["participant"], row["task"].upper()
        where = f"{path.name} line {line}"
        if left_out(person):
            data.excluded.append((path.name, line, person, task, left_out(person)))
            continue
        score = row["cause_score"].lower()
        if score not in (*SCORES, ""):
            problems.append(f"{where}: cause_score {row['cause_score']!r} is not correct, partly or wrong")
            continue
        if (person, task) in seen:
            problems.append(f"{where}: {person} {task} is also on line {seen[person, task]}")
            continue
        seen[person, task] = line
        if (person, task) not in usable:
            problems.append(f"{where}: {person} {task} has no usable task record in the sessions table")
            continue
        usable[person, task].score = score or None


def median(values):
    return statistics.median(values) if values else None


def reduction(baseline, fixfirst):
    """Relative reduction from the baseline median; None when it cannot be computed."""
    if baseline is None or fixfirst is None or baseline <= 0:
        return None
    return (baseline - fixfirst) / baseline


def paired(data: Data, config: Config):
    pairs, left = [], []
    for person in sorted(data.per_person):
        means, reasons = {}, []
        for condition in CONDITIONS:
            times = [t.seconds for t in data.tasks if t.participant == person and t.condition == condition]
            recorded = data.per_person[person][condition]
            if len(times) == config.tasks_per_condition:
                means[condition] = sum(times) / len(times)
                continue
            withdrawn = sum(1 for _, outcome in recorded if outcome == "withdrawn")
            unrecorded = sum(1 for _, outcome in recorded if not outcome)
            absent = config.tasks_per_condition - len(recorded)
            detail = [f"{n} {what}" for n, what in ((withdrawn, "withdrawn"), (unrecorded, "success not recorded"),
                                                  (absent, "not in the table")) if n > 0]
            reasons.append(f"{condition}: {len(times)} of {config.tasks_per_condition} tasks usable"
                           + (f" ({', '.join(detail)})" if detail else ""))
        if reasons:
            left.append((person, "; ".join(reasons)))
        else:
            pairs.append((person, means["fixfirst"], means["baseline"], means["fixfirst"] - means["baseline"]))
    return pairs, left


def wilcoxon_summary(differences):
    nonzero = [d for d in differences if d != 0]
    if not differences:
        return {"computed": False, "reason": "no participant has both conditions complete"}
    if not nonzero:
        return {"computed": False, "reason": "every difference is zero"}
    from scipy.stats import wilcoxon

    result = wilcoxon(nonzero, alternative="two-sided")
    return {"computed": True, "n_nonzero": len(nonzero), "statistic": float(result.statistic),
            "p_value": float(result.pvalue)}


def condition_summary(tasks, condition):
    rows = [t for t in tasks if t.condition == condition]
    solved = [t.seconds for t in rows if t.success]
    claims = [t.claims for t in rows if t.claims is not None]
    modified = [t.tests_modified for t in rows if t.tests_modified is not None]
    confidence = [t.confidence for t in rows if t.confidence is not None]
    scores = [t.score for t in rows if t.score]
    return {
        "tasks": len(rows),
        "completed": len(solved),
        "completion_rate": len(solved) / len(rows) if rows else None,
        "median_solved_seconds": median(solved),
        "median_seconds_unfinished_as_limit": median([t.seconds for t in rows]),
        "false_done_claims": {"total": sum(claims), "tasks_with_claims": sum(1 for c in claims if c > 0),
                              "n": len(claims), "missing": len(rows) - len(claims)},
        "tests_modified": {"yes": sum(modified), "n": len(modified), "missing": len(rows) - len(modified)},
        "confidence": {"median": median(confidence), "n": len(confidence), "missing": len(rows) - len(confidence)},
        "cause_scores": {**{s: scores.count(s) for s in SCORES}, "n_scored": len(scores),
                         "unscored": len(rows) - len(scores),
                         "share_correct": scores.count("correct") / len(scores) if scores else None},
    }


def analyse(data: Data, config: Config) -> dict:
    conditions = {c: condition_summary(data.tasks, c) for c in CONDITIONS}
    pairs, left = paired(data, config)
    differences = [d for *_, d in pairs]
    sus = list(data.sus.values())
    years = [float(r["python_years"]) for r in data.questionnaire.values() if r["python_years"]]
    pytest_answers = [r["used_pytest"].lower() for r in data.questionnaire.values() if r["used_pytest"]]
    ff, base = conditions["fixfirst"], conditions["baseline"]
    return {
        "participants": sorted(data.per_person),
        "conditions": conditions,
        "completion_target": {"fixfirst_rate": ff["completion_rate"], "target": 0.80,
                              "met": None if ff["completion_rate"] is None else ff["completion_rate"] >= 0.80},
        "time_target": {"reduction": reduction(base["median_solved_seconds"], ff["median_solved_seconds"]),
                        "target": 0.20},
        "unfinished_as_limit_reduction": reduction(base["median_seconds_unfinished_as_limit"],
                                                   ff["median_seconds_unfinished_as_limit"]),
        "paired": {"pairs": pairs, "excluded": left, "n": len(pairs),
                   "median_difference": median(differences),
                   "mean_difference": sum(differences) / len(differences) if differences else None,
                   "faster_with_fixfirst": sum(1 for d in differences if d < 0),
                   "slower_with_fixfirst": sum(1 for d in differences if d > 0),
                   "equal": sum(1 for d in differences if d == 0),
                   "wilcoxon": wilcoxon_summary(differences)},
        "sus": {"scores": dict(sorted(data.sus.items())), "excluded": dict(sorted(data.sus_excluded.items())),
                "n": len(sus), "mean": sum(sus) / len(sus) if sus else None,
                "sd": statistics.stdev(sus) if len(sus) > 1 else None, "median": median(sus),
                "min": min(sus) if sus else None, "max": max(sus) if sus else None},
        "background": {"questionnaires": len(data.questionnaire),
                       "without_questionnaire": sorted(set(data.per_person) - set(data.questionnaire)),
                       "python_years": {"median": median(years), "min": min(years) if years else None,
                                        "max": max(years) if years else None, "n": len(years)},
                       "used_pytest": {"yes": pytest_answers.count("yes"), "no": pytest_answers.count("no"),
                                       "missing": len(data.questionnaire) - len(pytest_answers)}},
        "answers": {column: [(p, r[column]) for p, r in sorted(data.questionnaire.items()) if r[column]]
                    for column in TEXT_ANSWERS},
        "excluded": data.excluded,
        "notes": data.notes,
    }


def shown(value, digits=1):
    if value is None:
        return "n/a"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.{digits}f}"
    return str(int(value)) if isinstance(value, float) else str(value)


def percent(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "not found"


def display(path: Path) -> str:
    path = path.resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name


def protocol_version(path: Path) -> str:
    found = re.search(r"^Version ([\d.]+)", path.read_text(encoding="utf-8"), re.M) if path.exists() else None
    return found[1] if found else "unknown"


def render(results: dict, meta: dict) -> str:
    c, lines = results["conditions"], []
    if meta["demo"]:
        lines += ["# DEMO: fictional data", "",
                  "> These numbers come from the made-up tables in `docs/user-study/fixtures/` and only check "
                  "the analysis script. They are **not** results of the user study.", ""]
    else:
        lines += ["# User study: analysis output", "",
                  "Numbers for RESULTS.md, produced by `analysis.py`; RESULTS.md itself is written by a person.", ""]
    lines += ["## Inputs and configuration", "",
              f"- Script: analysis.py {VERSION} (SHA-256 {meta['script_sha256'][:12]}); protocol version "
              f"{meta['protocol_version']}",
              f"- Tasks per condition: {meta['tasks_per_condition']}; time limit: {meta['time_limit']} s; "
              f"rows whose participant starts with {' or '.join(EXCLUDED_PREFIXES)} are not analysed", ""]
    lines += ["| Input | Rows | SHA-256 |", "|---|---|---|"]
    for name, info in meta["inputs"].items():
        lines.append(f"| {info['path']} | {info['rows']} | `{info['sha256'][:16]}` |")
    lines += ["", "## Records", "",
              f"Participants analysed: {len(results['participants'])} ({', '.join(results['participants']) or 'none'}). "
              f"Usable task records: {c['fixfirst']['tasks'] + c['baseline']['tasks']}.", ""]
    if results["excluded"]:
        lines += ["Left out:", "", "| File | Line | Participant | Task | Reason |", "|---|---|---|---|---|"]
        lines += [f"| {f} | {line} | {p} | {t or '-'} | {r} |" for f, line, p, t, r in results["excluded"]]
        lines.append("")
    for note in results["notes"]:
        lines += [f"Note: {note}", ""]
    ff, base = c["fixfirst"], c["baseline"]
    target = results["completion_target"]
    verdict = "not assessable" if target["met"] is None else ("met" if target["met"] else "not met")
    lines += ["## Completion", "", "| Condition | Completed | Tasks | Rate |", "|---|---|---|---|",
              f"| FixFirst | {ff['completed']} | {ff['tasks']} | {percent(ff['completion_rate'])} |",
              f"| Baseline | {base['completed']} | {base['tasks']} | {percent(base['completion_rate'])} |", "",
              f"Proposal target, at least 80% of FixFirst tasks completed: **{verdict}**.", ""]
    change = results["time_target"]["reduction"]
    if change is None:
        time_verdict = ("not assessable: a condition has no completed task" if None in
                        (ff["median_solved_seconds"], base["median_solved_seconds"])
                        else "not assessable: the baseline median is not above zero")
    else:
        time_verdict = f"{percent(change)} lower with FixFirst; target {'met' if change >= 0.20 else 'not met'}"
        if change < 0:
            time_verdict = f"{percent(-change)} higher with FixFirst; target not met"
    other = results["unfinished_as_limit_reduction"]
    lines += ["## Time", "",
              "| Measure | FixFirst | Baseline |", "|---|---|---|",
              f"| Median seconds of completed tasks (n) | {shown(ff['median_solved_seconds'])} ({ff['completed']}) | "
              f"{shown(base['median_solved_seconds'])} ({base['completed']}) |",
              f"| Median seconds, unfinished tasks counted as {meta['time_limit']} s (n) | "
              f"{shown(ff['median_seconds_unfinished_as_limit'])} ({ff['tasks']}) | "
              f"{shown(base['median_seconds_unfinished_as_limit'])} ({base['tasks']}) |", "",
              f"Proposal target, median time of completed tasks at least 20% lower with FixFirst: **{time_verdict}**.",
              "",
              f"With unfinished tasks counted as {meta['time_limit']} s the median is "
              + ("not comparable" if other is None else
                 f"{percent(abs(other))} {'lower' if other >= 0 else 'higher'} with FixFirst")
              + ". This second measure is reported under its own name and is not used for the target.", ""]
    p = results["paired"]
    lines += ["## Paired comparison (unit: participant)", "",
              f"Each participant's mean time per condition, unfinished tasks counted as {meta['time_limit']} s. "
              "Difference = FixFirst minus baseline; negative means faster with FixFirst.", ""]
    if p["pairs"]:
        lines += ["| Participant | FixFirst mean | Baseline mean | Difference |", "|---|---|---|---|"]
        lines += [f"| {who} | {shown(a)} | {shown(b)} | {shown(d)} |" for who, a, b, d in p["pairs"]]
        lines += ["", f"n = {p['n']} participants. Median difference {shown(p['median_difference'])} s, mean "
                  f"{shown(p['mean_difference'])} s. Faster with FixFirst: {p['faster_with_fixfirst']}; slower: "
                  f"{p['slower_with_fixfirst']}; equal: {p['equal']}.", ""]
    else:
        lines += ["No participant has the configured number of tasks in both conditions.", ""]
    for who, why in p["excluded"]:
        lines.append(f"- Not paired: {who} ({why})")
    if p["excluded"]:
        lines.append("")
    w = p["wilcoxon"]
    if w["computed"]:
        lines += [f"Wilcoxon signed-rank test (supplementary, two-sided, zero differences dropped): W = "
                  f"{shown(w['statistic'])}, p = {w['p_value']:.4f}, n = {w['n_nonzero']} non-zero differences. "
                  "With this few participants it can show a trend, not a general effect.", ""]
    else:
        lines += [f"Wilcoxon signed-rank test: not computed ({w['reason']}).", ""]
    lines += ["## Other task measures", "",
              "| Measure | FixFirst | Baseline |", "|---|---|---|"]
    for label, key, fmt in (
        ("False completion claims: total (tasks with at least one / tasks with a value; missing)", "false_done_claims",
         lambda x: f"{x['total']} ({x['tasks_with_claims']}/{x['n']}; {x['missing']} missing)"),
        ("Tests modified (tasks / tasks with a value; missing)", "tests_modified",
         lambda x: f"{x['yes']}/{x['n']} ({x['missing']} missing)"),
        ("Confidence 1-5: median (n; missing)", "confidence",
         lambda x: f"{shown(x['median'])} ({x['n']}; {x['missing']} missing)"),
        ("Cause explanation scored by a person: correct / partly / wrong (share correct; unscored)", "cause_scores",
         lambda x: f"{x['correct']} / {x['partly']} / {x['wrong']} ({percent(x['share_correct'])} of {x['n_scored']}; "
                   f"{x['unscored']} unscored)"),
    ):
        lines.append(f"| {label} | {fmt(ff[key])} | {fmt(base[key])} |")
    s = results["sus"]
    lines += ["", "## System Usability Scale (after the FixFirst round)", ""]
    if s["n"]:
        lines += [f"n = {s['n']}; mean {shown(s['mean'])}, SD {shown(s['sd'])}, median {shown(s['median'])}, "
                  f"range {shown(s['min'])}-{shown(s['max'])}. About 68 is average (PROTOCOL.md).", "",
                  "| Participant | SUS |", "|---|---|"]
        lines += [f"| {who} | {shown(score)} |" for who, score in s["scores"].items()]
        lines.append("")
    else:
        lines += ["No complete SUS questionnaire.", ""]
    for who, reasons in s["excluded"].items():
        lines.append(f"- SUS not scored for {who}: {'; '.join(reasons)}")
    b = results["background"]
    lines += ["", "## Participants", "",
              f"Questionnaires: {b['questionnaires']}"
              + (f"; none for {', '.join(b['without_questionnaire'])} (their task records are still used)"
                 if b["without_questionnaire"] else "") + ".",
              f"Years of Python: median {shown(b['python_years']['median'])}, range "
              f"{shown(b['python_years']['min'])}-{shown(b['python_years']['max'])} (n = {b['python_years']['n']}).",
              f"Used pytest before: yes {b['used_pytest']['yes']}, no {b['used_pytest']['no']}, missing "
              f"{b['used_pytest']['missing']}.", "",
              "## Open answers (verbatim, not coded)", "",
              "Recurring points are identified by a person when RESULTS.md is written.", ""]
    for column, answers in results["answers"].items():
        lines += [f"**{column}**", ""]
        lines += [f"- {who}: {text}" for who, text in answers] or ["- (no answers)"]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def cause_sheet(data: Data, out: Path, seed: int = 20261013):
    """A sheet for the person who scores the explanations: no condition, rows shuffled per task."""
    rows = sorted(data.tasks, key=lambda t: (t.task, t.participant))
    picker = random.Random(seed)
    ordered = []
    for task in TASKS:
        group = [t for t in rows if t.task == task]
        picker.shuffle(group)
        ordered += group
    with out.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["participant", "task", "known_cause", "explanation", "cause_score", "scorer", "notes"])
        for t in ordered:
            writer.writerow([t.participant, t.task, KNOWN_CAUSES[t.task], t.explanation, "", "", ""])
    return len(ordered)


def load(args, config: Config) -> Data:
    data, problems = Data(), []
    load_sessions(Path(args.sessions), config, data, problems)
    if Path(args.questionnaire).exists():
        load_questionnaire(Path(args.questionnaire), data, problems)
    else:
        data.notes.append(f"{Path(args.questionnaire).name} not found: no questionnaire data")
    if problems:  # the scores are checked against the usable task records, so they wait for a clean table
        raise DataError(problems)
    if Path(args.causes).exists():
        load_causes(Path(args.causes), data, problems)
    else:
        data.notes.append(f"{Path(args.causes).name} not found: no cause explanation has been scored yet")
    if problems:
        raise DataError(problems)
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sessions", default=str(HERE / "sessions.csv"))
    parser.add_argument("--questionnaire", default=str(HERE / "questionnaire.csv"))
    parser.add_argument("--causes", default=str(HERE / "cause_scores.csv"))
    parser.add_argument("--protocol", default=str(HERE / "PROTOCOL.md"))
    parser.add_argument("--tasks-per-condition", type=int, default=2, choices=(1, 2))
    parser.add_argument("--time-limit", type=int, default=720)
    parser.add_argument("--output", help="write the Markdown here instead of printing it")
    parser.add_argument("--json", help="also write the numbers as JSON")
    parser.add_argument("--demo", action="store_true", help="the inputs are fictional: mark the output DEMO")
    parser.add_argument("--cause-sheet", metavar="CSV", help="write the scoring sheet for cause explanations")
    args = parser.parse_args(argv)
    config = Config(args.tasks_per_condition, args.time_limit)
    if args.demo and args.output and Path(args.output).name.upper() == "RESULTS.MD":
        parser.error("DEMO output must not be written to RESULTS.md")
    fixtures = HERE / "fixtures"
    if not args.demo and any(Path(p).resolve().is_relative_to(fixtures)
                             for p in (args.sessions, args.questionnaire, args.causes)):
        parser.error("the fixtures are fictional: run them with --demo")
    try:
        data = load(args, config)
    except (DataError, FileNotFoundError) as error:
        problems = error.problems if isinstance(error, DataError) else [str(error)]
        print("The data break the rules in DATA.md; nothing was analysed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    if args.cause_sheet:
        count = cause_sheet(data, Path(args.cause_sheet))
        print(f"Wrote {count} explanations to {args.cause_sheet}, without the condition.")
        return 0
    results = analyse(data, config)
    meta = {
        "demo": args.demo, "tasks_per_condition": config.tasks_per_condition, "time_limit": config.time_limit,
        "protocol_version": protocol_version(Path(args.protocol)),
        "script_sha256": fingerprint(Path(__file__)),
        "inputs": {name: {"path": display(Path(path)), "rows": data.rows_read.get(name, 0),
                          "sha256": fingerprint(Path(path))}
                   for name, path in (("sessions", args.sessions), ("questionnaire", args.questionnaire),
                                      ("cause_scores", args.causes))},
    }
    text = render(results, meta)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.json:
        Path(args.json).write_text(json.dumps({"meta": meta, "results": results}, indent=2, ensure_ascii=False)
                                   + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
