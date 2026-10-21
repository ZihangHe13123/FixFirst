"""The preregistered main analysis of the agent experiment: arms compared task by task.

For each model and protocol, and each kind of case (real projects and generated hard cases are never
pooled), every task gets one fix rate per arm: its fixed runs over its graded runs. The difference
between two arms is taken task by task. The report gives the mean difference with its 95% t-interval
(the tasks as the sample), the 95% percentile interval from resampling the tasks (bootstrap with a fixed
seed) as a sensitivity check, and an exact sign test over the tasks, for mcp - baseline (the main
comparison), mcp - facts and facts - baseline (attribution). The t-interval is the main one because in
the settings simulated so far (--simulate; 6-8 tasks, 3-5 runs, 2000 replicates each) it came closer to
its nominal level than the percentile bootstrap: at 8 tasks x 3 runs with baselines uniform on 0.1-0.9
and no effect, 5.9% false positives against the bootstrap's 9.2% (Monte Carlo standard error about 0.5
and 0.6 points); over the eleven settings tried, 1.5-5.9% against 8.8-11.8%, and coverage 90.6-96.4%
against 82.3-90.7% (the t-interval's 90.6% with baselines on 0.6-1.0 and a true gain of 0.15). Neither has a general guarantee with
so few, bounded and discrete task differences, and the sign test (ties dropped) cannot reach p < 0.05
with fewer than six non-zero differences. When every task has the same difference the result is flagged
degenerate (within 1e-9, as equal rates can differ in a float's last bits) and no interval is given:
agreement among a few tasks is not certainty. With --labels
(keys "kind:case", or "case" when case names are unique across kinds) each comparison is also given per
fault type, from the A1/C1 labels (never from FixFirst's own judgement); those strata are descriptive.

How fast the fix came is compared the same way, task by task: the turns to the first fix (mean per task,
second arm minus first) and the time to the first fix (geometric mean per task, compared as a ratio on the
log scale, as times are skewed). The time is the harness's agent time to the first fix (`first_green_s`):
model requests and tool calls, FixFirst's included, from the start of the episode to the end of the turn
after which the grader's own check first passed; the harness's checks are not counted. It is never the
episode's length (`agent_s`, or `total_s` with the harness's checks), which also counts whatever the agent
did after the fix. As preregistered, only fixed runs count, and a task enters only if both arms fixed it
at least once. That is biased when one arm fixes runs the other cannot (those are often the slow ones), so
both are always shown with a budget-penalized version that keeps every graded run and counts one not
fixed as its whole budget (one turn more than max_turns, and run_timeout, from its settings): a score
that trades fixing against speed, not a time to fix, and not one that always favours the arm fixing more
(three fixes in 1 s and two failures can score better than three fixes in 100 s). Each measure is
checked run by run (whole turns of at least 1, within the episode; finite times above 0, within its agent
time, both episode ends being valid themselves; nothing is clipped or replaced) and a value that fails
is missing for that measure only, listed with its reason. Each comparison gives its own tasks and the runs
that contribute to it (and those usable in the group), next to the tasks of the group and those graded in
both arms. Speed is secondary; neither version replaces the fix rate.

With --family the confirmatory family comes first: mcp - baseline on real projects, one comparison per
model, as registered before the run (each model with its one protocol id and its task set). Its decision
is Holm's step-down procedure at 0.05 on the two-sided p-values of the paired t-test, the test the
t-interval belongs to, at full precision; the intervals shown are the usual 95% ones, not adjusted. Only
the registered tasks enter; a registered task without a graded run in both arms is listed, as is a task
that was not registered. The estimate and the p-value are then over the tasks used: they are not the
mean effect over the whole registered set, and what is missing may differ from what is there. A member
that cannot be estimated (no data, fewer than two tasks, or every task differing by the same amount)
stays in the family and counts as not rejected, so the family never shrinks after the results are seen.
The p-value is computed at full precision from Student's t distribution (it is not an exact test for
discrete task differences). The interval uses a 97.5% point tabulated to three decimals up to 30 degrees
of freedom and expanded beyond, so the two can disagree where the p-value is very close to 0.05: within
0.00006 for the degrees of freedom checked (1 to 60; eight tasks give 7). The decision is the p-value's.
Holm's adjustment does not repair a t-test that is itself off with so few tasks: the family-wise error
rate is not guaranteed (--simulate --family-runs shows it for chosen settings). Everything else in the
report is exploratory.

With --hard-selection the generated hard instances are held to the selection frozen before the runs
(qualify_hard.py's record, given with the SHA-256 registered for its file; the file must have it). The
selection says which cases are hard and which instance of each scenario is the formal one, so nothing is
taken from the rows themselves. The formal instances become a kind of their own, `hard`, apart from other
generated cases; a hard case that is not a formal instance (another template, a development instance, any
row with hard-instance fields) is counted and analysed nowhere here. Every attempt of a formal instance,
failed ones replaced by a retry included, must have run under that selection (`hard_selection`) in the
formal role (`hard_role`), and an instance it recorded (`hard_instance`) must be the selection's for its
case; a graded run must record it. A run with an attempt that says otherwise is left out and listed, and
no later attempt undoes that; an attempt that failed before its instance was built confirms nothing and
contradicts nothing. Formal instances without a run used are listed per group: the selection, not the
rows that passed, says what was to be run. Real projects and other generated cases are untouched. Without
--hard-selection rows with those fields are analysed as generated cases, unchecked, and the report says so.

"Graded" is the harness's word: every episode a model ended (finish, turn_cap, time_cap,
stopped_without_tool, model_error) is graded and counts, fixed or not. Setup, reference, MCP start,
clean-up, grading and harness failures are not graded. A run is identified by its model, call policy,
protocol, kind of case, case, arm and run number (with the attempt, the identity compare_arms.py
deduplicates on). It may be retried once, in a later attempt, and only after a failure the protocol lets
be retried (setup_failed, mcp_start_failed, cleanup_failed, harness_error); the order of its attempts
must be known (the harness's started_utc, or the time in an automatic attempt id). Anything else is a
protocol deviation, left out and listed: an attempt after a graded result, more than one retry (whether
or not the last was graded), a retry after another failure, or attempts in an unknown order. A run never
graded is listed and counts nowhere. Every run used must record its source identity (a real task's
source commit; a generated case's harness commit, as the harness's own code builds it; an empty value is
none), and every attempt of a task that recorded one, failed attempts replaced by a retry included, must
agree on it; otherwise the task is left out of every comparison and listed. A comparison is shown with 0
tasks when both its arms were run but one has no graded runs; arms absent from the input need a plan to
be missed, which these results files do not carry. A ledger gives per group and arm the rows read and
kept and the runs used, never graded, retried (also those still not graded) and left out. A bare-case
label shared by several kinds is listed and not applied. The JSON records the inputs' names, digests and
rows, and the code's digests, with its commit only when both files are that commit's.

Usage:
  python experiments/agent_baseline/task_analysis.py RESULTS.jsonl [...] [--labels LABELS.json]
      [--family FAMILY.json] [--hard-selection SELECTION.json --hard-selection-sha256 HEX]
      [--seed 20261001] [--resamples 10000] [--json OUT]
  python experiments/agent_baseline/task_analysis.py --simulate [--tasks 14] [--runs 3] [--replicates 1000]
      [--effects 0 0.1 0.2 0.3] [--baseline uniform:0.1:0.9] [--effect-model shift] [--correlation 0]
  python experiments/agent_baseline/task_analysis.py --simulate --family-runs 5 5 3 --effects 0 0 0
      [--tasks 8] [--replicates 1000] [--baseline ...] [--effect-model ...] [--correlation 0] [--independent-tasks]

FAMILY.json is {"members": [{"model": ..., "protocol": ..., "tasks": [...]}, ...]} with an optional "note";
the protocol is the id this report prints for the model's runs.

--simulate draws synthetic tasks with known fix probabilities and reports how often the intervals and
the sign test detect each true effect, and how often the intervals cover it. It reads no results. Its
assumptions are options: how the baselines are spread (--baseline), how FixFirst's help is shaped
(--effect-model: the same gain everywhere, a share of the remaining failures, or only half the tasks)
and how alike a task's runs are (--correlation). Uniform baselines must lie in [0, 1], beta parameters
above 0, and the share model's effects in [0, 1], so that the runs and the truth share one model. Each
result keeps its integer counts, and the coverage among replicates that had an interval next to the
coverage among all replicates (a replicate without one neither excludes 0 nor covers the truth).

--simulate --family-runs simulates the family instead: one model per number (its runs per arm), one true
effect per model, every model meeting the same tasks unless --independent-tasks. It reports how often
Holm's procedure rejects each model, any model, and any model whose true mean difference is 0 (a false
rejection; a gain capped away by a baseline of 1 is 0 too), next to the unadjusted p-values.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_arms as ca  # noqa: E402

COMPARISONS = (("baseline", "mcp"), ("facts", "mcp"), ("baseline", "facts"))  # second minus first
SEED = 20261001


RETRYABLE = ("setup_failed", "mcp_start_failed", "cleanup_failed", "harness_error")  # protocol, section 5
ATTEMPT_TIME = re.compile(r"(\d{8}T\d{6})Z?(?:-[0-9A-Za-z]+)?")


def stratum(row) -> tuple:
    """What a task's runs must share to be pooled: model, call policy, protocol and kind of case, the
    same identity that deduplication and the auxiliary comparison use."""
    return ca.group_key(row)


def attempt_time(row):
    """When the run's attempt started, if its row can show it: the harness's started_utc, or the time of
    an automatic attempt id (20261001T122650Z-d98e50). Anything else gives no order (None)."""
    stamp = row.get("started_utc")
    if stamp:
        try:
            moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            return None
        return moment.astimezone(timezone.utc).replace(tzinfo=None) if moment.tzinfo else moment
    found = ATTEMPT_TIME.fullmatch(str(row.get("attempt") or ""))
    return datetime.strptime(found[1], "%Y%m%dT%H%M%S") if found else None


def runs(rows: list[dict]) -> tuple[dict, list, list, list]:
    """One graded result per run, across attempts: (used, retried, deviations, never graded)."""
    by_run = {}
    for row in ca.deduplicate(rows)[0]:
        by_run.setdefault((stratum(row), row.get("case"), row.get("arm"), row.get("run")), []).append(row)
    used, retried, deviations, ungraded = {}, [], [], []
    outcome = lambda row: "graded" if row.get("grading") == "graded" else str(row.get("end"))  # noqa: E731
    for key, members in sorted(by_run.items(), key=lambda item: str(item[0])):
        name = {"model": key[0][0], "protocol": key[0][2], "kind": key[0][3], "case": key[1], "arm": key[2],
                "run": key[3], "_key": key}
        if len(members) == 1:
            if members[0].get("grading") == "graded":
                used[key] = members[0]
            else:
                ungraded.append({**name, "ends": [outcome(members[0])]})
            continue
        times = [attempt_time(row) for row in members]
        if None in times or len(set(times)) < len(times):
            deviations.append({**name, "reason": "attempted more than once, in an order that cannot be established",
                               "attempts": sorted(outcome(row) for row in members)})
            continue
        ordered = [row for _, row in sorted(zip(times, members), key=lambda item: item[0])]
        attempts = [outcome(row) for row in ordered]  # in the order they happened
        if len(ordered) > 2:
            reason = f"{len(ordered)} attempts; one retry is allowed"
        elif ordered[0].get("grading") == "graded":
            reason = "attempted again after a graded result; a graded run is never rerun"
        elif ordered[0].get("end") not in RETRYABLE:
            reason = f"retried after {ordered[0].get('end')}, which the protocol does not let be retried"
        else:
            reason = None
        if reason:
            deviations.append({**name, "reason": reason, "attempts": attempts})
        elif ordered[1].get("grading") == "graded":
            used[key] = ordered[1]
            retried.append({**name, "attempts": attempts})
        else:
            ungraded.append({**name, "ends": attempts, "retried": True})
    return used, retried, deviations, ungraded


def source_identity(row) -> str | None:
    """The frozen source a run started from: a real task's source commit, a generated case's harness commit
    (its generator is the harness's own code). An empty or missing value is no identity."""
    value = row.get("commit") if (row.get("kind") or "generated") == "real" else row.get("harness_commit")
    return value.strip() if isinstance(value, str) and value.strip() else None


def check_versions(used: dict, attempts: list[dict]) -> tuple[dict, list]:
    """Every used run must have a source identity, and every attempt of a task that recorded one (failed
    ones replaced by a retry included) must agree on it: a task with two identities, or with a used run
    that has none, is left out of every comparison of its group and listed. An attempt that failed before
    it recorded one confirms nothing and contradicts nothing."""
    known, unbound = {}, set()
    for row in attempts:
        identity = source_identity(row)
        if identity:
            known.setdefault((stratum(row), row.get("case")), set()).add(identity)
    for (group, case, _, _), row in used.items():
        if source_identity(row) is None:
            unbound.add((group, case))
    bad = {task for task, found in known.items() if len(found) > 1} | unbound
    kept = {key: row for key, row in used.items() if (key[0], key[1]) not in bad}
    field = lambda group: "source commit" if group[3] == "real" else "harness commit"  # noqa: E731
    listed = []
    for group, case in sorted(bad, key=str):
        found = sorted(v[:12] for v in known.get((group, case), ()))
        if len(found) > 1:
            reason = f"its attempts come from {len(found)} {field(group)}s ({', '.join(found)})"
        else:
            reason = f"a used run recorded no {field(group)}" + (f" (others {found[0]})" if found else "")
        dropped = [key for key in used if (key[0], key[1]) == (group, case)]
        listed.append({"model": group[0], "protocol": group[2], "kind": group[3], "case": case,
                       "reason": f"task version: {reason}", "runs_left_out": len(dropped), "_keys": dropped})
    return kept, listed


HARD_KIND = "hard"  # the analysis's own kind: the formal instances of a frozen selection
HARD_FIELDS = ("hard_selection", "hard_role", "hard_instance")  # what agent_pilot.py records for a hard case
SHA256 = re.compile(r"[0-9a-f]{64}")


def read_hard_selection(record, digest: str, name: str) -> dict:
    """The frozen selection of hard instances as qualify_hard.py records it, with its file's name and
    SHA-256: the hard scenarios, and for each its formal instance (the case template:scenario and the
    digest of its content), or none when no template qualified. Read strictly, like the family."""
    if not isinstance(record, dict) or not isinstance(record.get("selection"), dict) or not record["selection"]:
        raise ValueError('the hard selection must be an object with a non-empty "selection"')
    name_ok = lambda value: isinstance(value, str) and value.strip() == value and value != "" and ":" not in value  # noqa: E731
    formal, cannot_run = {}, []
    for scenario, roles in record["selection"].items():
        if not name_ok(scenario) or not isinstance(roles, dict) or "formal" not in roles:
            raise ValueError(f'the hard selection needs a "formal" entry (an instance, or null) for the scenario {scenario!r}')
        instance = roles["formal"]
        if instance is None:
            cannot_run.append(scenario)
            continue
        if not isinstance(instance, dict) or not name_ok(instance.get("template")) \
                or not isinstance(instance.get("digest"), str) or not SHA256.fullmatch(instance["digest"]):
            raise ValueError(f"the formal instance of {scenario} needs a template and the SHA-256 of its content")
        formal[f"{instance['template']}:{scenario}"] = instance["digest"]
    return {"name": name, "sha256": digest, "scenarios": sorted(record["selection"]), "formal": formal,
            "cannot_run": sorted(cannot_run)}


def hard_scope(row, selection: dict) -> str | None:
    """Where a row stands to the frozen selection: "formal" (a run of one of its formal instances),
    "outside" (a hard case that is not one: a scenario of the selection on another template, or any row
    with hard-instance fields) or None (no hard case: real projects and other generated cases keep their
    own path). The case decides, not the row's fields, so a formal instance's row cannot leave the check
    by not carrying them."""
    case = row.get("case")
    if ca.kind(row) == "real" or not isinstance(case, str):
        return None
    if case in selection["formal"]:
        return "formal"
    scenario = case.split(":")[1] if case.count(":") == 1 else None
    return "outside" if scenario in selection["scenarios"] or any(field in row for field in HARD_FIELDS) else None


def hold_to_selection(rows: list[dict], selection: dict) -> tuple[list, list]:
    """(the rows to analyse, the formal instances' rows as the kind `hard`; the hard rows outside the
    selection's formal instances, which are analysed nowhere)."""
    kept, outside = [], []
    for row in rows:
        scope = hard_scope(row, selection)
        if scope == "outside":
            outside.append(row)
        else:
            kept.append({**row, "kind": HARD_KIND} if scope == "formal" else row)
    return kept, outside


def hard_identity(row, selection: dict) -> list[str]:
    """What an attempt's own record says against the frozen selection; nothing when nothing does. An
    instance not recorded is no contradiction here (see check_hard)."""
    short = lambda value: repr(value) if not isinstance(value, str) else value[:12]  # noqa: E731
    problems = []
    if row.get("hard_selection") != selection["sha256"]:
        problems.append("an attempt ran under no selection" if row.get("hard_selection") is None else
                        f"an attempt ran under another selection ({short(row.get('hard_selection'))})")
    if row.get("hard_role") != "formal":
        problems.append(f"an attempt's role is {short(row.get('hard_role'))}, not formal")
    instance = row.get("hard_instance")
    if instance is not None and instance != selection["formal"][row["case"]]:
        problems.append(f"an attempt's instance is {short(instance)}, not the selection's "
                        f"{selection['formal'][row['case']][:12]}")
    return problems


def check_hard(used: dict, attempts: list[dict], selection: dict) -> tuple[dict, list, int]:
    """Every attempt of a formal instance, failed ones replaced by a retry included, is held to the frozen
    selection: it ran under it, in the formal role, and an instance it recorded is the selection's for its
    case. A run with an attempt that says otherwise is left out and listed, whatever a later attempt says.
    An attempt that failed before its instance was built recorded none: that confirms nothing and
    contradicts nothing, but a graded run must record its instance. Returns the runs kept, the list (a
    run that was not used anyway is listed too, and counted once), and the attempts without an instance."""
    problems, unknown = {}, 0
    for row in attempts:
        if ca.kind(row) != HARD_KIND:
            continue
        found = hard_identity(row, selection)
        if not found and row.get("hard_instance") is None:
            if row.get("grading") == "graded":
                found = ["an attempt was graded without recording its instance"]
            else:
                unknown += 1
        for problem in found:
            key = (stratum(row), row.get("case"), row.get("arm"), row.get("run"))
            if problem not in problems.setdefault(key, []):
                problems[key].append(problem)
    kept = {key: row for key, row in used.items() if key not in problems}
    listed = []
    for key, found in sorted(problems.items(), key=lambda item: str(item[0])):
        item = {"model": key[0][0], "protocol": key[0][2], "kind": key[0][3], "case": key[1], "arm": key[2],
                "run": key[3], "reason": "hard instance: " + "; ".join(found)}
        listed.append({**item, "_key": key} if key in used else {**item, "not_used_anyway": True})
    return kept, listed, unknown


def hard_report(selection: dict, rows: list, unique: list, outside: list, used: dict, listed: list, unknown: int) -> dict:
    """What the frozen selection was held against, and what it covers: the formal instances' rows and
    runs, the hard rows outside them, and per group the formal instances without a run used."""
    cases = {}
    for row in outside:
        entry = cases.setdefault(row["case"], {"rows": 0, "roles": set()})
        entry["rows"] += 1
        entry["roles"].add(str(row.get("hard_role")))
    coverage = []
    for group in sorted({stratum(row) for row in unique if ca.kind(row) == HARD_KIND}, key=lambda g: tuple(map(str, g))):
        arms = sorted({row.get("arm") for row in unique if stratum(row) == group}, key=ca.arm_rank)
        counts = {case: {arm: sum(1 for key in used if key[:3] == (group, case, arm)) for arm in arms}
                  for case in sorted(selection["formal"])}
        coverage.append({"model": group[0], "call_policy": group[1], "protocol": group[2], "runs_used": counts,
                         "instances_without_a_run_used": [case for case, per_arm in counts.items() if not any(per_arm.values())]})
    return {"selection": {"name": selection["name"], "sha256": selection["sha256"], "formal_instances": selection["formal"],
                          "scenarios": selection["scenarios"], "cannot_run": selection["cannot_run"]},
            "rows_read": sum(1 for row in rows if ca.kind(row) == HARD_KIND),
            "rows_kept": sum(1 for row in unique if ca.kind(row) == HARD_KIND),
            "runs_used": sum(1 for key in used if key[0][3] == HARD_KIND),
            "runs_left_out": sum(1 for item in listed if "_key" in item),
            "identity_problems_in_runs_not_used": sum(1 for item in listed if "_key" not in item),
            "attempts_without_an_instance": unknown,
            "outside": {"rows_read": len(outside), "rows_kept": len(ca.deduplicate(outside)[0]),
                        "cases": {case: {"rows": entry["rows"], "roles": sorted(entry["roles"])}
                                  for case, entry in sorted(cases.items())}},
            "coverage": coverage}


def task_rates(used: dict) -> dict:
    """{stratum: {case: {arm: [fixed, graded]}}}"""
    rates = {}
    for (group, case, arm, _), row in used.items():
        cell = rates.setdefault(group, {}).setdefault(case, {}).setdefault(arm, [0, 0])
        cell[0] += row.get("fixed") is True
        cell[1] += 1
    return rates


MEASURES = ("turns", "seconds", "turns_penalized", "seconds_penalized")


def whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def finite_positive(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def run_speed(row) -> tuple[dict, dict]:
    """A graded run's speed values, measure by measure, and why any is missing. A run fixed at the end has
    its turns and seconds to the first fix (first_green_turn, first_green_s): a whole number of turns of
    at least 1 and no more than its turns, and a finite positive time no longer than its agent time (both
    episode ends must themselves be valid, or the value cannot be checked and is missing); the penalized
    measures take the same values. A run not fixed has no time to fix; the penalized measures
    count it as its whole budget, one turn more than max_turns and run_timeout, if its settings say them.
    Nothing is clipped or replaced: a value that fails a check is missing, with the reason."""
    values, missing = {}, {}
    if row.get("fixed") is True:
        turn, seconds = row.get("first_green_turn"), row.get("first_green_s")
        last_turn, end = row.get("turns"), row.get("agent_s")
        if not whole(turn) or turn < 1:
            missing["turns"] = f"first_green_turn is {turn!r}, not a whole number of at least 1"
        elif not whole(last_turn) or last_turn < 1:
            missing["turns"] = f"the episode's turns are {last_turn!r}, so first_green_turn cannot be checked"
        elif turn > last_turn:
            missing["turns"] = f"first_green_turn {turn} is after the episode's last turn {last_turn}"
        else:
            values["turns"] = turn
        if not finite_positive(seconds):
            missing["seconds"] = f"first_green_s is {seconds!r}, not a finite time above 0"
        elif not finite_positive(end):
            missing["seconds"] = f"the episode's agent_s is {end!r}, so first_green_s cannot be checked"
        elif seconds > end + 0.01:  # both are rounded to 0.01 s
            missing["seconds"] = f"first_green_s {seconds} is after the episode's end ({end} s)"
        else:
            values["seconds"] = seconds
        for measure in ("turns", "seconds"):
            if measure in values:
                values[f"{measure}_penalized"] = values[measure]
            else:
                missing[f"{measure}_penalized"] = missing[measure]
    else:
        settings = row.get("settings") or {}
        budget_turns, budget_seconds = settings.get("max_turns"), settings.get("run_timeout")
        if whole(budget_turns) and budget_turns >= 1:
            values["turns_penalized"] = budget_turns + 1
        else:
            missing["turns_penalized"] = f"not fixed, and its max_turns is {budget_turns!r}"
        if finite_positive(budget_seconds):
            values["seconds_penalized"] = float(budget_seconds)
        else:
            missing["seconds_penalized"] = f"not fixed, and its run_timeout is {budget_seconds!r}"
    return values, missing


def task_speeds(used: dict) -> tuple[dict, list]:
    """{stratum: {case: {arm: {measure: [values]}}}}, and every missing value with its run and reason."""
    speeds, missing = {}, []
    for (group, case, arm, run), row in used.items():
        cell = speeds.setdefault(group, {}).setdefault(case, {}).setdefault(arm, {m: [] for m in MEASURES})
        values, reasons = run_speed(row)
        for measure, value in values.items():
            cell[measure].append(value)
        for measure, reason in reasons.items():
            missing.append({"model": group[0], "protocol": group[2], "kind": group[3], "case": case, "arm": arm,
                            "run": run, "measure": measure, "reason": reason})
    return speeds, missing


T975 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
        2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042)


def t975(df: int) -> float:
    """The 97.5% point of Student's t: a table to 30 degrees of freedom, then the Cornish-Fisher expansion."""
    if df <= len(T975):
        return T975[df - 1]
    z = 1.959964
    return z + (z ** 3 + z) / (4 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df ** 2)


def t_bounds(values: list[float]) -> tuple | None:
    """95% t-interval of the mean, the values (the tasks) being the sample; None below two values."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    half = t975(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))
    return mean - half, mean + half


def t_interval(values: list[float]) -> list:
    bounds = t_bounds(values)
    return [None, None] if bounds is None else [round(bound, 3) for bound in bounds]


def bootstrap_bounds(values: list[float], resamples: int, seed) -> tuple | None:
    """95% percentile interval of the mean, resampling the values (the tasks) with replacement."""
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(resamples))
    return means[int(0.025 * resamples)], means[-int(0.025 * resamples) - 1]


def bootstrap_interval(values: list[float], resamples: int, seed) -> list:
    bounds = bootstrap_bounds(values, resamples, seed)
    return [None, None] if bounds is None else [round(bound, 3) for bound in bounds]


DEGENERATE_SPREAD = 1e-9


def describe(cases: list, differences: list[float], left_out: list, resamples: int | None, seed, key: str,
             show=lambda value: round(value, 3)) -> dict:
    """One comparison over the tasks `cases` with their differences: the mean, the t-interval (and the
    bootstrap one unless resamples is None), the sign test, and the unrounded numbers under "_raw" for
    the simulation. All differences equal (two tasks or more, within 1e-9: rates like 2/3 - 1/3 and 1/3 - 0
    differ in the last bits of a float) is degenerate: no interval is given."""
    positive = sum(d > 0 for d in differences)
    negative = sum(d < 0 for d in differences)
    degenerate = len(differences) >= 2 and max(differences) - min(differences) <= DEGENERATE_SPREAD
    mean = sum(differences) / len(differences) if differences else None
    t = None if degenerate else t_bounds(differences)
    result = {"tasks": len(cases), key: None if mean is None else show(mean),
              "ci95": [None, None] if t is None else [show(bound) for bound in t], "degenerate": degenerate}
    raw = {"mean": mean, "t": t}
    if resamples is not None:
        bounds = None if degenerate else bootstrap_bounds(differences, resamples, seed)
        result["bootstrap_ci95"] = [None, None] if bounds is None else [show(bound) for bound in bounds]
        raw["bootstrap"] = bounds
    result.update(sign={"positive": positive, "negative": negative, "ties": len(differences) - positive - negative,
                        "p": round(ca.binomial_two_sided(min(positive, negative), positive + negative), 4)},
                  per_task={case: show(d) for case, d in zip(cases, differences)}, left_out=left_out, _raw=raw)
    return result


def difference(tasks: dict, first: str, second: str, resamples: int, seed) -> dict:
    """second minus first, task by task, over the tasks graded in both arms."""
    shared = sorted(case for case, arms in tasks.items() if arms.get(first, [0, 0])[1] and arms.get(second, [0, 0])[1])
    left_out = sorted(case for case, arms in tasks.items() if case not in shared and (first in arms or second in arms))
    rate = lambda case, arm: tasks[case][arm][0] / tasks[case][arm][1]  # noqa: E731
    differences = [rate(case, second) - rate(case, first) for case in shared]
    return {"first": first, "second": second,
            **describe(shared, differences, left_out, resamples, seed, "mean_difference")}


def paired_measure(speeds: dict, first: str, second: str, measure: str, log: bool) -> dict:
    """second minus first, task by task, over the tasks with values of `measure` in both arms: the mean
    turns or, on the log scale, the geometric mean seconds, whose difference is a ratio."""
    def summary(values):
        return sum(math.log(v) for v in values) / len(values) if log else sum(values) / len(values)

    shared = sorted(case for case, arms in speeds.items()
                    if arms.get(first, {}).get(measure) and arms.get(second, {}).get(measure))
    left_out = sorted(case for case, arms in speeds.items() if case not in shared and (first in arms or second in arms))
    differences = [summary(speeds[case][second][measure]) - summary(speeds[case][first][measure]) for case in shared]
    show = (lambda value: round(math.exp(value), 3)) if log else (lambda value: round(value, 3))
    result = describe(shared, differences, left_out, None, None, "ratio" if log else "mean_difference", show)
    result["runs"] = {arm: sum(len(speeds[case][arm][measure]) for case in shared) for arm in (first, second)}
    result["runs_usable"] = {arm: sum(len(speeds[case].get(arm, {}).get(measure, [])) for case in speeds)
                             for arm in (first, second)}
    return result


def speed(speeds: dict, first: str, second: str, tasks_graded_in_both: int) -> dict:
    """Turns and time to the first fix over the tasks fixed in both arms (as preregistered), and the
    budget-penalized scores over the tasks graded in both (a run not fixed counted as its whole budget:
    a score that trades fixing against speed, not a time to fix). Each gives its own tasks and runs, next
    to the tasks of the group and those graded in both arms."""
    return {"tasks_in_group": len(speeds), "tasks_graded_in_both": tasks_graded_in_both,
            "turns_to_first_fix": paired_measure(speeds, first, second, "turns", False),
            "time_to_first_fix": paired_measure(speeds, first, second, "seconds", True),
            "turns_with_failure_penalty": paired_measure(speeds, first, second, "turns_penalized", False),
            "time_with_failure_penalty": paired_measure(speeds, first, second, "seconds_penalized", True)}


CONFIRMATORY = ("baseline", "mcp")  # the registered confirmatory comparison, second minus first, on real projects
ALPHA = 0.05


def incomplete_beta(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function I_x(a, b), by its continued fraction (modified Lentz)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):  # the fraction converges quickly only on this side
        return 1.0 - incomplete_beta(b, a, 1.0 - x)
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)) / a
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    fraction = d
    for m in range(1, 1001):
        for term in (m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
                     -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))):
            d = 1.0 + term * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + term / c
            c = c if abs(c) > tiny else tiny
            fraction *= d * c
        if abs(d * c - 1.0) < 1e-15:
            return front * fraction
    raise ArithmeticError(f"the incomplete beta function did not converge for a={a}, b={b}, x={x}")


def t_test_p(values: list[float]) -> float | None:
    """The two-sided p-value of the paired t-test that the mean of `values` (the tasks' differences) is 0:
    the test the 95% t-interval belongs to, computed at full precision from Student's t distribution. None
    where no interval is given either: fewer than two values, or all of them equal within DEGENERATE_SPREAD."""
    if len(values) < 2 or max(values) - min(values) <= DEGENERATE_SPREAD:
        return None
    df = len(values) - 1
    t = (sum(values) / len(values)) / (statistics.stdev(values) / math.sqrt(len(values)))
    return incomplete_beta(df / 2, 0.5, df / (df + t * t))


def holm(p_values: list, alpha: float = ALPHA) -> list[dict]:
    """Holm's step-down procedure over a family fixed in advance, in the family's own order. The p-values are
    ranked from the smallest; the one of rank i is compared with alpha / (k - i + 1), and the first that
    fails stops the procedure: it and every later one are not rejected. Equivalently, a member is rejected
    when its adjusted p-value, the largest (k - j + 1) * p over the ranks j up to its own (at most 1), is no
    more than alpha. A member without a p-value (None: it could not be estimated) stays in the family: it
    counts as p = 1, so it is never rejected (alpha is below 1), and k is not reduced."""
    k = len(p_values)
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not 0 < alpha < 1:
        raise ValueError(f"alpha must lie strictly between 0 and 1, not {alpha!r}")
    for p in p_values:
        if p is not None and not (isinstance(p, (int, float)) and not isinstance(p, bool) and 0 <= p <= 1):
            raise ValueError(f"a p-value must be a number in [0, 1] or None, not {p!r}")
    order = sorted(range(k), key=lambda index: (1.0 if p_values[index] is None else p_values[index], index))
    results, adjusted = [None] * k, 0.0
    for rank, index in enumerate(order, start=1):
        p = 1.0 if p_values[index] is None else p_values[index]
        adjusted = max(adjusted, min(1.0, (k - rank + 1) * p))
        results[index] = {"rank": rank, "p_holm": adjusted, "rejected": adjusted <= alpha}
    return results


def read_family(spec) -> list[dict]:
    """The confirmatory family as registered before the run: {"members": [{"model": ..., "protocol": ...,
    "tasks": [...]}, ...]} with an optional free-text "note". One member per model, each with its one
    protocol id and its task set. Anything else is refused, so a family cannot be read loosely."""
    if not isinstance(spec, dict) or set(spec) - {"members", "note"} or not isinstance(spec.get("members"), list) \
            or not spec["members"]:
        raise ValueError('the family must be an object with "members" (a non-empty list) and at most a "note"')
    members = []
    for member in spec["members"]:
        if not isinstance(member, dict) or set(member) != {"model", "protocol", "tasks"}:
            raise ValueError('each family member needs exactly "model", "protocol" and "tasks"')
        model, protocol, tasks = member["model"], member["protocol"], member["tasks"]
        text = lambda value: isinstance(value, str) and value.strip() == value and value != ""  # noqa: E731
        if not text(model) or not text(protocol):
            raise ValueError(f"a family member's model and protocol must be non-empty names: {model!r}, {protocol!r}")
        if not isinstance(tasks, list) or not tasks or not all(text(task) for task in tasks) or len(set(tasks)) < len(tasks):
            raise ValueError(f"the tasks of {model} must be a non-empty list of distinct task names")
        if any(model == other["model"] for other in members):
            raise ValueError(f"the model {model} is in the family twice; each model has one comparison")
        members.append({"model": model, "protocol": protocol, "tasks": list(tasks)})
    return members


def confirmatory(family: list[dict], rates: dict, alpha: float = ALPHA) -> dict:
    """The registered confirmatory family: mcp - baseline on real projects, one comparison per model, over
    that model's registered tasks only, decided by Holm's procedure on the paired t-test's p-values. The
    interval of each member is the usual 95% t-interval, not adjusted. A member that cannot be estimated
    (no data, fewer than two registered tasks graded in both arms, or every task differing by the same
    amount) is kept in the family and counts as not rejected. A registered task without a graded run in
    both arms is listed, and the member's estimate is then over the tasks used only; a task in the data
    that was not registered is listed and not used here."""
    first, second = CONFIRMATORY
    members = []
    for member in family:
        found = [group for group in rates if (group[0], group[2], group[3]) == (member["model"], member["protocol"], "real")]
        if len(found) > 1:
            raise ValueError(f"several groups match the family member {member['model']} {member['protocol']}")
        tasks = rates[found[0]] if found else {}
        graded = lambda case, arm: tasks.get(case, {}).get(arm, [0, 0])[1]  # noqa: E731
        used = [case for case in member["tasks"] if graded(case, first) and graded(case, second)]
        missing = [{"case": case, "reason": "no graded run in " + " or ".join(a for a in (first, second) if not graded(case, a))}
                   for case in member["tasks"] if case not in used]
        differences = [tasks[case][second][0] / tasks[case][second][1] - tasks[case][first][0] / tasks[case][first][1]
                       for case in used]
        p = t_test_p(differences)
        degenerate = len(differences) >= 2 and p is None
        bounds = None if p is None else t_bounds(differences)
        if p is not None:
            reason = None
        elif not found:
            reason = "no graded runs of this model under this protocol"
        elif degenerate:
            reason = "every task differs by the same amount, so there is no test"
        else:
            reason = "fewer than two registered tasks were graded in both arms"
        members.append({"model": member["model"], "protocol": member["protocol"], "tasks_registered": len(member["tasks"]),
                        "tasks_used": used, "tasks_missing": missing,
                        "tasks_not_registered": sorted(case for case in tasks if case not in member["tasks"]),
                        "mean_difference": round(sum(differences) / len(differences), 3) if differences else None,
                        "ci95": [None, None] if bounds is None else [round(bound, 3) for bound in bounds],
                        "interval_excludes_zero": None if bounds is None else bool(bounds[0] > 0 or bounds[1] < 0),
                        "p": p, "not_estimable": reason})
    for member, decision in zip(members, holm([member["p"] for member in members], alpha)):
        member.update(decision)
    registered = {(member["model"], member["protocol"]) for member in family}
    outside = sorted({(group[0], group[2]) for group, tasks in rates.items() if group[3] == "real"
                      and (group[0], group[2]) not in registered
                      and any(first in arms for arms in tasks.values()) and any(second in arms for arms in tasks.values())})
    return {"comparison": {"first": first, "second": second}, "kind": "real", "alpha": alpha, "k": len(members),
            "method": "Holm's step-down procedure on the two-sided p-values of the paired t-test, the tasks as the sample",
            "members": members, "rejected": sum(member["rejected"] for member in members),
            "outside_the_family": [{"model": model, "protocol": protocol} for model, protocol in outside]}


def strip_raw(value):
    """The result without the unrounded numbers kept for the simulation, or the bookkeeping keys."""
    if isinstance(value, dict):
        return {k: strip_raw(v) for k, v in value.items() if k not in ("_raw", "_key", "_keys")}
    if isinstance(value, list):
        return [strip_raw(v) for v in value]
    return value


def analyse(rows: list[dict], labels: dict | None = None, resamples: int = 10000, seed=SEED, keep_raw=False,
            family=None, hard=None) -> dict:
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError(f"resamples must be a positive whole number, not {resamples!r}")
    if any(row.get("kind") == HARD_KIND for row in rows):
        raise ValueError(f"a row's kind is {HARD_KIND!r}: that is this report's own name for the formal instances "
                         "of a frozen selection (--hard-selection); the harness writes real or generated")
    members = None if family is None else read_family(family)
    read, duplicates = len(rows), ca.deduplicate(rows)[1]
    marked = sum(1 for row in rows if any(field in row for field in HARD_FIELDS))
    outside = []
    if hard is not None:
        rows, outside = hold_to_selection(rows, hard)
    unique = ca.deduplicate(rows)[0]
    used, retried, deviations, ungraded = runs(rows)
    used, version_deviations = check_versions(used, unique)
    deviations += version_deviations
    if hard is not None:
        used, identity_deviations, without_instance = check_hard(used, unique, hard)
        deviations += identity_deviations
    speeds, speed_missing = task_speeds(used)
    rates = task_rates(used)
    count = Counter()
    for row in rows:
        count[(stratum(row), row.get("arm"), "rows_read")] += 1
    for row in unique:
        count[(stratum(row), row.get("arm"), "rows_kept")] += 1
    for key in used:
        count[(key[0], key[2], "runs_used")] += 1
    for item, field in [(x, "runs_never_graded") for x in ungraded] + [(x, "runs_retried_once") for x in retried] + \
                       [(x, "runs_retried_once") for x in ungraded if x.get("retried")] + \
                       [(x, "runs_left_out") for x in deviations if "_key" in x]:
        count[(item["_key"][0], item["_key"][2], field)] += 1
    for item in version_deviations:
        for key in item["_keys"]:
            count[(key[0], key[2], "runs_left_out")] += 1
    kinds_of_case = {}
    for row in unique:
        kinds_of_case.setdefault(row.get("case"), set()).add(stratum(row)[3])
    # A bare key is one that names a case as it stands, colons or not (generated cases are template:scenario).
    label_problems = sorted(f"the label key {key!r} is a bare case name used by several kinds "
                            f"({', '.join(sorted(kinds_of_case[key]))}); it is not applied, use kind:case"
                            for key in (labels or {}) if len(kinds_of_case.get(key, ())) > 1)
    groups = []
    for group in sorted({key[0] for key in count}, key=lambda g: tuple(str(k) for k in g)):
        tasks = rates.get(group, {})
        arms = {arm for cells in tasks.values() for arm in cells}
        comparisons = []
        for first, second in COMPARISONS:
            missing = [arm for arm in (first, second) if arm not in arms]
            if missing:  # shown when both arms were run (their rows were read), so it was meant to be made
                if all(any(key[0] == group and key[1] == arm for key in count) for arm in (first, second)):
                    comparisons.append({"first": first, "second": second, "tasks": 0, "no_graded_runs_in": missing})
                continue
            name = f"{seed}|{'|'.join(str(k) for k in group)}|{first}|{second}"
            result = difference(tasks, first, second, resamples, name)
            result["speed"] = speed(speeds[group], first, second, result["tasks"])
            if labels is not None:
                strata = {}
                for case in tasks:
                    bare = labels.get(case, "unlabelled") if len(kinds_of_case.get(case, ())) == 1 else "unlabelled"
                    label = labels.get(f"{group[3]}:{case}", bare)
                    strata.setdefault(label, {})[case] = tasks[case]
                result["by_label"] = {}
                for label, subset in sorted(strata.items()):
                    result["by_label"][label] = difference(subset, first, second, resamples, f"{name}|{label}")
                    result["by_label"][label]["speed"] = speed(
                        {case: speeds[group][case] for case in subset}, first, second,
                        result["by_label"][label]["tasks"])
            comparisons.append(result)
        ledger = {arm: {field: count[(group, arm, field)] for field in
                        ("rows_read", "rows_kept", "runs_used", "runs_never_graded", "runs_retried_once", "runs_left_out")}
                  for arm in sorted({key[1] for key in count if key[0] == group}, key=ca.arm_rank)}
        groups.append({"model": group[0], "call_policy": group[1], "protocol": group[2], "kind": group[3],
                       "tasks": {case: tasks[case] for case in sorted(tasks)}, "ledger": ledger,
                       "comparisons": comparisons})
    result = {"seed": seed, "resamples": resamples, "rows_read": read, "duplicates": duplicates,
              "groups": groups, "retried": retried, "deviations": deviations, "never_graded": ungraded,
              "speed_values_missing": speed_missing, "label_problems": label_problems}
    if members is not None:
        result["confirmatory"] = confirmatory(members, rates)
    if hard is not None:
        result["hard"] = hard_report(hard, rows, unique, outside, used, identity_deviations, without_instance)
    elif marked:
        result["hard"] = {"selection": None, "rows_with_hard_fields": marked}
    return result if keep_raw else strip_raw(result)


def markdown(result: dict) -> str:
    def cell(value):
        return "–" if value is None else str(value)

    def interval(item, key="ci95"):
        if item.get("degenerate"):
            return "degenerate: every task differs by the same amount, no interval"
        return f"{cell(item[key][0])} to {cell(item[key][1])}"
    lines = []
    family = result.get("confirmatory")
    if family:
        first, second = family["comparison"]["first"], family["comparison"]["second"]
        lines += [f"Confirmatory family, as registered before the run: {second} − {first} on real projects, one comparison "
                  f"per model, k = {family['k']}. Decision: Holm's step-down procedure at {family['alpha']} on the two-sided "
                  "p-values of the paired t-test (the tasks as the sample). The intervals are the usual 95% t-intervals and "
                  "are not adjusted. Holm's adjustment does not repair a t-test that is itself off with so few tasks, so the "
                  "family-wise error rate is not guaranteed. A member that cannot be estimated stays in the family and "
                  "counts as not rejected. Everything outside this table is exploratory.", "",
                  "| Model | Protocol | Tasks used / registered | Mean difference (unadjusted 95% t-interval) | p (paired t) "
                  f"| Holm rank | Holm-adjusted p | After Holm's adjustment at {family['alpha']} |",
                  "|---|---|---|---|---|---|---|---|"]
        for m in family["members"]:
            if m["not_estimable"]:
                decision = f"not estimable ({m['not_estimable']}); counts as not rejected"
            else:
                decision = "rejects no effect" if m["rejected"] else "does not reject no effect"
            lines.append(f"| {m['model']} | {m['protocol']} | {len(m['tasks_used'])} / {m['tasks_registered']} "
                         f"| {cell(m['mean_difference'])} ({cell(m['ci95'][0])} to {cell(m['ci95'][1])}) "
                         f"| {'–' if m['p'] is None else format(m['p'], '.6g')} | {m['rank']} | {format(m['p_holm'], '.6g')} "
                         f"| {decision} |")
        for m in family["members"]:
            if m["tasks_missing"]:
                lines += ["", f"Registered tasks of {m['model']} not used: "
                          + "; ".join(f"{t['case']} ({t['reason']})" for t in m["tasks_missing"])
                          + ". Its estimate and p-value are over the tasks used, not over its whole registered set."]
            if m["tasks_not_registered"]:
                lines += ["", f"Tasks of {m['model']} in the data but not registered (not used in the family): "
                          + ", ".join(m["tasks_not_registered"])]
        if family["outside_the_family"]:
            lines += ["", "Real-project groups outside the registered family (exploratory only): "
                      + "; ".join(f"{g['model']} {g['protocol']}" for g in family["outside_the_family"])]
        lines.append("")
    hard = result.get("hard")
    if hard and hard["selection"]:
        chosen = hard["selection"]
        lines += [f"Hard instances, held to the frozen selection {chosen['name']} (SHA-256 {chosen['sha256']}): "
                  f"{len(chosen['formal_instances'])} formal instances, the kind `{HARD_KIND}` below"
                  + (f"; no template qualified for {', '.join(chosen['cannot_run'])}" if chosen["cannot_run"] else "")
                  + ". A run counts only if every attempt of it ran under this selection in the formal role and none "
                  "recorded another instance than the selection's; a graded run must record it. Rows of formal instances: "
                  f"{hard['rows_read']} read, {hard['rows_kept']} kept; runs used: {hard['runs_used']}; left out for their "
                  f"identity: {hard['runs_left_out']} (under the protocol deviations, where {hard['identity_problems_in_runs_not_used']} "
                  "more are listed for runs not used anyway); attempts that failed before an instance was built: "
                  f"{hard['attempts_without_an_instance']} (they confirm nothing). Hard rows outside the selection's formal "
                  f"instances, analysed nowhere here: {hard['outside']['rows_read']}"
                  + ("".join(f"; {case} ({entry['rows']}, role {'/'.join(entry['roles'])})"
                             for case, entry in hard["outside"]["cases"].items())) + "."]
        for group in hard["coverage"]:
            if group["instances_without_a_run_used"]:
                lines += ["", f"Formal instances of {group['model']} {group['protocol']} without a run used: "
                          + ", ".join(group["instances_without_a_run_used"])]
        lines.append("")
    elif hard:
        lines += [f"Hard instances: {hard['rows_with_hard_fields']} rows carry hard-instance fields and no frozen selection "
                  "was given (--hard-selection). They are analysed as generated cases; nothing about their instances was "
                  "checked.", ""]
    lines += ["| Model | Protocol | Kind | Comparison | Tasks | Mean difference (95% t-interval) | Bootstrap 95% "
              "| Sign +/−/0 (p) | Left out |",
              "|---|---|---|---|---|---|---|---|---|"]
    for group in result["groups"]:
        for c in group["comparisons"]:
            if "no_graded_runs_in" in c:
                lines.append(f"| {group['model']} | {group['protocol']} | {group['kind']} | {c['second']} − {c['first']} "
                             f"| 0 | no graded runs in: {', '.join(c['no_graded_runs_in'])} | – | – | – |")
                continue
            for label, item in [(None, c), *sorted((c.get("by_label") or {}).items())]:
                name = f"{c['second']} − {c['first']}" + (f" · {label}" if label else "")
                lines.append(f"| {group['model']} | {group['protocol']} | {group['kind']} | {name} | {item['tasks']} "
                             f"| {cell(item['mean_difference'])} ({interval(item)}) "
                             f"| {interval(item, 'bootstrap_ci95')} "
                             f"| {item['sign']['positive']}/{item['sign']['negative']}/{item['sign']['ties']} "
                             f"(p={item['sign']['p']}) | {', '.join(item['left_out']) or '–'} |")
    lines += ["", "Speed is secondary and never replaces the fix rate. Time = agent time to the end of the turn after "
              "which the grader's check first passed (first_green_s), not the episode's length. To first fix: runs "
              "fixed at the end, tasks fixed in both arms. Budget-penalized: every graded run, one not fixed counted as "
              "its whole budget: a score that trades fixing against speed, not a time to fix. Cells: tasks (runs per "
              "arm): estimate (95% t-interval), sign +/−/0.", "",
              "| Model | Protocol | Kind | Comparison | Tasks in group / graded in both | Turns to first fix "
              "| Time to first fix (ratio) | Budget-penalized turns | Budget-penalized time (ratio) |",
              "|---|---|---|---|---|---|---|---|---|"]
    for group in result["groups"]:
        for c in group["comparisons"]:
            if "speed" not in c:
                continue
            for label, item in [(None, c), *sorted((c.get("by_label") or {}).items())]:
                s = item["speed"]

                def show(m, key):
                    runs = "/".join(str(n) for n in m["runs"].values())
                    return (f"{m['tasks']} ({runs}): {cell(m[key])} ({interval(m)}), "
                            f"sign {m['sign']['positive']}/{m['sign']['negative']}/{m['sign']['ties']}")
                name = f"{c['second']} vs {c['first']}" + (f" · {label}" if label else "")
                lines.append(f"| {group['model']} | {group['protocol']} | {group['kind']} | {name} "
                             f"| {s['tasks_in_group']} / {s['tasks_graded_in_both']} "
                             f"| {show(s['turns_to_first_fix'], 'mean_difference')} | {show(s['time_to_first_fix'], 'ratio')} "
                             f"| {show(s['turns_with_failure_penalty'], 'mean_difference')} "
                             f"| {show(s['time_with_failure_penalty'], 'ratio')} |")
    lines += ["", "| Model | Protocol | Kind | Arm | Rows read | Rows kept | Runs used | Never graded | Retried once "
              "| Left out |", "|---|---|---|---|---|---|---|---|---|---|"]
    for group in result["groups"]:
        for arm, n in group["ledger"].items():
            lines.append(f"| {group['model']} | {group['protocol']} | {group['kind']} | {arm} | {n['rows_read']} "
                         f"| {n['rows_kept']} | {n['runs_used']} | {n['runs_never_graded']} | {n['runs_retried_once']} "
                         f"| {n['runs_left_out']} |")
    for title, key in (("Retried once (graded result used)", "retried"), ("Protocol deviations (left out)", "deviations"),
                       ("Never graded", "never_graded"), ("Speed values missing (that measure only)", "speed_values_missing"),
                       ("Label problems", "label_problems")):
        if result[key]:
            lines += ["", f"{title}: {len(result[key])}"] + [f"- {json.dumps(item, ensure_ascii=False)}"
                                                             for item in result[key]]
    return "\n".join(lines)


def baseline_sampler(spec: str):
    """`uniform:LOW:HIGH` (0 <= LOW <= HIGH <= 1) or `beta:A:B` (A, B > 0): how the tasks' baseline fix
    probabilities are spread."""
    try:
        kind, a, b = spec.split(":")
        a, b = float(a), float(b)
    except ValueError:
        raise ValueError(f"unknown baseline {spec!r}: use uniform:LOW:HIGH or beta:A:B") from None
    if kind == "uniform" and math.isfinite(a) and math.isfinite(b) and 0 <= a <= b <= 1:
        return lambda rng: rng.uniform(a, b)
    if kind == "beta" and math.isfinite(a) and math.isfinite(b) and a > 0 and b > 0:
        return lambda rng: rng.betavariate(a, b)
    raise ValueError(f"baseline {spec!r}: uniform needs 0 <= LOW <= HIGH <= 1, beta needs A, B > 0 (finite)")


EFFECT_MODELS = ("shift", "share", "half")


def treated(p: float, effect: float, model: str, rng) -> float:
    """The mcp arm's fix probability for a task whose baseline is p. shift: every task gains `effect`
    (capped at 1); share: FixFirst fixes that share of the remaining failures; half: half the tasks gain
    twice the effect (capped), the others nothing."""
    if model == "shift":
        q = min(1.0, max(0.0, p + effect))
    elif model == "share":
        q = p + effect * (1 - p)
    elif model == "half":
        q = min(1.0, max(0.0, p + 2 * effect)) if rng.random() < 0.5 else p
    else:
        raise ValueError(f"unknown effect model {model!r}")
    if not 0 <= q <= 1:  # the runs are drawn with q and the truth computed with it: one model for both
        raise ValueError(f"the {model} model gives the fix probability {q}, outside [0, 1]")
    return q


def outcomes(rng, probability: float, runs: int, correlation: float) -> list[bool]:
    """One task's runs in one arm: with probability `correlation` all runs share one draw (a model at low
    temperature tends to repeat itself), otherwise each run is drawn on its own."""
    if correlation and rng.random() < correlation:
        return [rng.random() < probability] * runs
    return [rng.random() < probability for _ in range(runs)]


def simulate(tasks=14, runs_per_arm=3, replicates=1000, effects=(0.0, 0.1, 0.2, 0.3), baseline="uniform:0.1:0.9",
             effect_model="shift", correlation=0.0, resamples=1000, seed=SEED) -> list[dict]:
    """How often the preregistered analysis detects a true effect: per effect, the share of replicates whose
    t-interval or bootstrap interval excludes 0 or whose sign test has p < 0.05, and how often each interval
    covers the true mean difference of the task population. Decisions use the unrounded intervals; a
    replicate without an interval (degenerate) neither excludes 0 nor covers the truth, and is counted."""
    for name, value, low in (("tasks", tasks, 2), ("runs_per_arm", runs_per_arm, 1), ("replicates", replicates, 1),
                             ("resamples", resamples, 1)):
        if isinstance(value, bool) or not isinstance(value, int) or value < low:
            raise ValueError(f"{name} must be a whole number of at least {low}, not {value!r}")
    if not 0 <= correlation <= 1 or not all(-1 <= effect <= 1 for effect in effects):
        raise ValueError("correlation must lie in [0, 1] and every effect in [-1, 1]")
    if effect_model not in EFFECT_MODELS:
        raise ValueError(f"unknown effect model {effect_model!r}")
    if effect_model == "share" and not all(0 <= effect <= 1 for effect in effects):
        raise ValueError("the share model needs every effect in [0, 1]")
    draw = baseline_sampler(baseline)
    rng, population, coins = random.Random(seed), random.Random(seed + 1), random.Random(seed + 2)
    draws = [draw(population) for _ in range(200000)]  # the task population, for the true mean difference
    results = []
    for effect in effects:
        truth = sum(treated(p, effect, effect_model, coins) - p for p in draws) / len(draws)
        counts = dict.fromkeys(("t_excludes", "t_covers", "bootstrap_excludes", "bootstrap_covers", "sign",
                                "no_interval", "no_bootstrap_interval"), 0)
        for replicate in range(replicates):
            rows = []
            for task in range(tasks):
                p = draw(rng)
                for arm, probability in (("baseline", p), ("mcp", treated(p, effect, effect_model, rng))):
                    for run, fixed in enumerate(outcomes(rng, probability, runs_per_arm, correlation), start=1):
                        rows.append({"model": "sim", "attempt": "sim", "case": f"t{task}", "arm": arm, "run": run,
                                     "kind": "real", "commit": "simulated", "grading": "graded", "fixed": fixed})
            [group] = analyse(rows, resamples=resamples, seed=f"{seed}|{effect}|{replicate}", keep_raw=True)["groups"]
            main = next(c for c in group["comparisons"] if (c["first"], c["second"]) == ("baseline", "mcp"))
            raw = main["_raw"]
            counts["no_interval"] += raw["t"] is None
            counts["no_bootstrap_interval"] += raw["bootstrap"] is None
            for name, bounds in (("t", raw["t"]), ("bootstrap", raw["bootstrap"])):
                if bounds is not None:
                    counts[f"{name}_excludes"] += bounds[0] > 0 or bounds[1] < 0
                    counts[f"{name}_covers"] += bounds[0] <= truth <= bounds[1]
            counts["sign"] += main["sign"]["p"] < 0.05
        share = lambda key: round(counts[key] / replicates, 3)  # noqa: E731
        given = lambda hits, missing: (round(hits / (replicates - missing), 3)  # noqa: E731
                                       if replicates > missing else None)
        results.append({"effect": effect, "true_mean_difference": round(truth, 3),
                        "t_interval_excludes_zero": share("t_excludes"), "t_interval_covers_truth": share("t_covers"),
                        "bootstrap_excludes_zero": share("bootstrap_excludes"),
                        "bootstrap_covers_truth": share("bootstrap_covers"), "sign_test_p_below_0_05": share("sign"),
                        "no_interval": share("no_interval"), "counts": {"replicates": replicates, **counts},
                        "t_interval_covers_truth_given_interval": given(counts["t_covers"], counts["no_interval"]),
                        "bootstrap_covers_truth_given_interval": given(counts["bootstrap_covers"],
                                                                      counts["no_bootstrap_interval"])})
    return results


def simulate_family(runs_per_model=(5, 5, 3), effects=(0.0, 0.0, 0.0), tasks=8, replicates=1000,
                    baseline="uniform:0.1:0.9", effect_model="shift", correlation=0.0, shared_tasks=True,
                    seed=SEED) -> dict:
    """How the registered family behaves for known true effects, one per model: how often Holm's procedure
    rejects each model's comparison, any of them, and any whose true mean difference is 0 (a false
    rejection), next to how often an unadjusted p-value is below alpha. With shared_tasks every model
    meets the same tasks (one baseline probability per task for all models, as in the experiment);
    otherwise each model draws its own. Every replicate goes through analyse() with the family, so what is
    simulated is the registered path; the bootstrap is no part of the decision and gets one resample."""
    for name, value, low in (("tasks", tasks, 2), ("replicates", replicates, 1)):
        if isinstance(value, bool) or not isinstance(value, int) or value < low:
            raise ValueError(f"{name} must be a whole number of at least {low}, not {value!r}")
    if not runs_per_model or any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in runs_per_model):
        raise ValueError(f"the runs per model must be whole numbers of at least 1, not {runs_per_model!r}")
    if len(effects) != len(runs_per_model):
        raise ValueError(f"give one effect per model: {len(runs_per_model)} models, {len(effects)} effects")
    if not 0 <= correlation <= 1 or not all(-1 <= effect <= 1 for effect in effects):
        raise ValueError("correlation must lie in [0, 1] and every effect in [-1, 1]")
    if effect_model not in EFFECT_MODELS:
        raise ValueError(f"unknown effect model {effect_model!r}")
    if effect_model == "share" and not all(0 <= effect <= 1 for effect in effects):
        raise ValueError("the share model needs every effect in [0, 1]")
    draw = baseline_sampler(baseline)
    rng, population, coins = random.Random(seed + 3), random.Random(seed + 4), random.Random(seed + 5)
    draws = [draw(population) for _ in range(200000)]  # the task population, for each model's true mean difference
    truths = [sum(treated(p, effect, effect_model, coins) - p for p in draws) / len(draws) for effect in effects]
    names = [f"model{index + 1}" for index in range(len(runs_per_model))]
    cases = [f"t{task}" for task in range(tasks)]
    blank = {"attempt": "sim", "kind": "real", "commit": "simulated", "grading": "graded"}
    family = {"members": [{"model": name, "protocol": ca.protocol({**blank, "model": name}), "tasks": cases}
                          for name in names]}
    per_model = [dict.fromkeys(("rejected", "p_below_alpha", "not_estimable"), 0) for _ in names]
    counts = dict.fromkeys(("any_rejection", "any_false_rejection", "every_false_null_rejected",
                            "any_p_below_alpha", "any_false_p_below_alpha"), 0)
    null_true = [truth == 0 for truth in truths]  # by the truth, not the setting: a gain can be capped away
    true_nulls = [index for index, null in enumerate(null_true) if null]
    false_nulls = [index for index, null in enumerate(null_true) if not null]
    for replicate in range(replicates):
        rows = []
        for case in cases:
            shared = draw(rng) if shared_tasks else None
            for name, runs, effect in zip(names, runs_per_model, effects):
                p = shared if shared_tasks else draw(rng)
                for arm, probability in (("baseline", p), ("mcp", treated(p, effect, effect_model, rng))):
                    for run, fixed in enumerate(outcomes(rng, probability, runs, correlation), start=1):
                        rows.append({**blank, "model": name, "case": case, "arm": arm, "run": run, "fixed": fixed})
        members = analyse(rows, resamples=1, seed=f"{seed}|family|{replicate}", family=family)["confirmatory"]["members"]
        rejected = [member["rejected"] for member in members]
        below = [member["p"] is not None and member["p"] < ALPHA for member in members]
        for index, member in enumerate(members):
            per_model[index]["rejected"] += rejected[index]
            per_model[index]["p_below_alpha"] += below[index]
            per_model[index]["not_estimable"] += member["p"] is None
        counts["any_rejection"] += any(rejected)
        counts["any_false_rejection"] += any(rejected[index] for index in true_nulls)
        counts["every_false_null_rejected"] += bool(false_nulls) and all(rejected[index] for index in false_nulls)
        counts["any_p_below_alpha"] += any(below)
        counts["any_false_p_below_alpha"] += any(below[index] for index in true_nulls)
    share = lambda count: round(count / replicates, 3)  # noqa: E731
    return {"models": [{"model": name, "runs_per_arm": runs, "effect": effect, "true_mean_difference": round(truth, 3),
                        "null_true": null, "rejected_after_holm": share(tally["rejected"]),
                        "p_below_alpha_unadjusted": share(tally["p_below_alpha"]),
                        "not_estimable": share(tally["not_estimable"]), "counts": dict(tally)}
                       for name, runs, effect, truth, null, tally
                       in zip(names, runs_per_model, effects, truths, null_true, per_model)],
            "alpha": ALPHA, "any_rejection_after_holm": share(counts["any_rejection"]),
            "any_false_rejection_after_holm": share(counts["any_false_rejection"]) if true_nulls else None,
            "every_false_null_rejected_after_holm": share(counts["every_false_null_rejected"]) if false_nulls else None,
            "any_p_below_alpha_unadjusted": share(counts["any_p_below_alpha"]),
            "any_false_p_below_alpha_unadjusted": share(counts["any_false_p_below_alpha"]) if true_nulls else None,
            "counts": {"replicates": replicates, **counts}}


def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_commit(here: Path) -> dict:
    """The commit the analysis code comes from, given only if both files are tracked by the repository that
    encloses them and equal to their committed version; otherwise none (their digests still identify the
    code). A copy in an ignored folder of another repository is not that repository's commit."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=here, capture_output=True, text=True)
    head = git("rev-parse", "HEAD")
    if head.returncode:
        return {"commit": None, "commit_status": "the code is not in a git repository"}
    for name in ("task_analysis.py", "compare_arms.py"):
        tracked = git("ls-files", "--error-unmatch", "--full-name", name)
        if tracked.returncode:
            return {"commit": None, "commit_status": f"{name} is not tracked by the enclosing repository"}
        committed, working = git("rev-parse", f"HEAD:{tracked.stdout.strip()}"), git("hash-object", name)
        if committed.returncode or committed.stdout.strip() != working.stdout.strip():
            return {"commit": None, "commit_status": f"{name} differs from its committed version"}
    return {"commit": head.stdout.strip(), "commit_status": "both files are this commit's"}


def provenance(results: list[str], labels: str | None, rows: list[dict], family: str | None = None,
               hard_selection: str | None = None) -> dict:
    """What the numbers were computed from: each input's name, digest and rows (no folders), the labels'
    digest (and the family's and the hard selection's, when given), and the analysis code's own digests,
    with its commit when that can be shown."""
    here = Path(__file__).resolve().parent
    return {"inputs": [{"name": Path(path).name, "sha256": file_sha256(path),
                        "rows": len(ca.read_rows([path]))} for path in results],
            "labels": {"name": Path(labels).name, "sha256": file_sha256(labels)} if labels else None,
            **({"family": {"name": Path(family).name, "sha256": file_sha256(family)}} if family else {}),
            **({"hard_selection": {"name": Path(hard_selection).name, "sha256": file_sha256(hard_selection)}}
               if hard_selection else {}),
            "code": {"task_analysis.py": file_sha256(here / "task_analysis.py"),
                     "compare_arms.py": file_sha256(here / "compare_arms.py"), **code_commit(here)},
            "rows_read": len(rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("results", nargs="*", help="results.jsonl files written by agent_pilot.py")
    parser.add_argument("--labels", help='JSON object: "kind:case" (or "case") -> fault type, from the A1/C1 labels')
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--resamples", type=int, help="bootstrap resamples (default 10000; 1000 when simulating)")
    parser.add_argument("--json", help="also write the numbers to this file")
    parser.add_argument("--simulate", action="store_true", help="synthetic tasks instead of results")
    parser.add_argument("--tasks", type=int, default=14)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--replicates", type=int, default=1000)
    parser.add_argument("--effects", type=float, nargs="+", default=[0.0, 0.1, 0.2, 0.3])
    parser.add_argument("--baseline", default="uniform:0.1:0.9", help="uniform:LOW:HIGH or beta:A:B")
    parser.add_argument("--effect-model", choices=EFFECT_MODELS, default="shift")
    parser.add_argument("--correlation", type=float, default=0.0, help="chance that one task's runs in an arm repeat")
    parser.add_argument("--family", help="JSON file: the confirmatory family as registered (models, protocols, tasks)")
    parser.add_argument("--hard-selection", help="the frozen selection of hard instances (qualify_hard.py's record): "
                                                 "the hard rows are held to it")
    parser.add_argument("--hard-selection-sha256", metavar="HEX",
                        help="the SHA-256 registered for that file before the runs; the file must have it")
    parser.add_argument("--family-runs", type=int, nargs="+", metavar="RUNS",
                        help="with --simulate: the family instead, one model per number (its runs per arm); "
                             "--effects then gives one true effect per model")
    parser.add_argument("--independent-tasks", action="store_true",
                        help="with --family-runs: each model draws its own tasks instead of meeting the same ones")
    args = parser.parse_args(argv)
    if args.family_runs and not args.simulate:
        parser.error("--family-runs simulates the family: give it with --simulate")
    if args.independent_tasks and not args.family_runs:
        parser.error("--independent-tasks belongs to --simulate --family-runs")
    if args.family and args.simulate:
        parser.error("--family is the registered family of real results; the simulation takes --family-runs")
    if bool(args.hard_selection) != bool(args.hard_selection_sha256):
        parser.error("--hard-selection and --hard-selection-sha256 go together: the file, and the SHA-256 registered for it")
    if args.hard_selection and args.simulate:
        parser.error("--hard-selection holds results to a frozen selection; the simulation reads no results")
    try:
        if args.simulate and args.family_runs:
            settings = {"runs_per_model": tuple(args.family_runs), "effects": tuple(args.effects), "tasks": args.tasks,
                        "replicates": args.replicates, "baseline": args.baseline, "effect_model": args.effect_model,
                        "correlation": args.correlation, "shared_tasks": not args.independent_tasks, "seed": args.seed}
            result = {**settings, "family_simulation": simulate_family(**settings)}
            print(json.dumps(result, indent=1))
        elif args.simulate:
            settings = {"tasks": args.tasks, "runs_per_arm": args.runs, "replicates": args.replicates,
                        "effects": tuple(args.effects), "baseline": args.baseline, "effect_model": args.effect_model,
                        "correlation": args.correlation,
                        "resamples": 1000 if args.resamples is None else args.resamples, "seed": args.seed}
            result = {**settings, "simulation": simulate(**settings)}
            print(json.dumps(result, indent=1))
        else:
            if not args.results:
                parser.error("give results.jsonl files, or --simulate")
            labels = json.loads(Path(args.labels).read_text(encoding="utf-8")) if args.labels else None
            family = json.loads(Path(args.family).read_text(encoding="utf-8")) if args.family else None
            hard = None
            if args.hard_selection:
                registered, found = args.hard_selection_sha256.strip().lower(), file_sha256(args.hard_selection)
                if not SHA256.fullmatch(registered):
                    parser.error("--hard-selection-sha256 is the file's whole SHA-256: 64 hexadecimal digits")
                if found != registered:
                    parser.error(f"{Path(args.hard_selection).name} has the SHA-256 {found}, not the registered {registered}: "
                                 "it is not the selection frozen before the runs")
                hard = read_hard_selection(json.loads(Path(args.hard_selection).read_text(encoding="utf-8")), found,
                                           Path(args.hard_selection).name)
            rows = ca.read_rows(args.results)
            result = analyse(rows, labels, 10000 if args.resamples is None else args.resamples, args.seed, family=family,
                             hard=hard)
            result["provenance"] = provenance(args.results, args.labels, rows, args.family, args.hard_selection)
            print(markdown(result))
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
