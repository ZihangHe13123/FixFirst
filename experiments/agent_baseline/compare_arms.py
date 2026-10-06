"""Compare the arms of the agent experiment from agent_pilot.py's results.jsonl files.

Per model, call policy and arm: how many graded runs were fixed (with a Wilson 95% interval), the
turn and agent seconds of the first green check among the fixed runs, tokens, tool calls, FixFirst
calls and scheduled reports with the time and characters they took, wrong first causes (the full
diagnosis arm on generated cases, whose cause is known) and runs that changed tests. Then paired
comparisons between arms on the same case and run: an exact McNemar test for fixed, and for turns to
green (runs fixed in both arms) and tokens the median paired difference with a sign test. Runs that
were not graded (setup, reference, harness or clean-up failures) are counted separately, never as
failures. Nothing here reads a model or runs anything; it only counts rows.

Only comparable runs are pooled or paired: runs of another kind of case (real projects and generated
cases) or under different protocols (model settings, budget, call policy, network, harness version, or
a harness with uncommitted changes) are reported apart, each with its kind and protocol id. One rule
of identity (group_key, then case, arm, run and attempt) serves deduplication, pooling and pairing. The same run read twice is counted once; two different results for one
run are refused. Tokens a model server did not report are missing, not zero.

Usage:
  python experiments/agent_baseline/compare_arms.py RESULTS.jsonl [...] [--attempt A] [--json OUT]
"""

import argparse
import hashlib
from itertools import combinations
import json
from math import comb, sqrt
from pathlib import Path

ARM_ORDER = ("baseline", "facts", "mcp", "fixfirst")
PROTOCOL_SETTINGS = ("max_turns", "run_timeout", "temperature", "max_tokens", "seed")


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


def binomial_two_sided(k: int, n: int) -> float:
    """Exact two-sided p-value of k successes in n fair trials."""
    if n == 0:
        return 1.0
    low = min(k, n - k)
    return min(1.0, 2 * sum(comb(n, i) for i in range(low + 1)) / 2 ** n)


def mcnemar(only_first: int, only_second: int) -> float:
    return binomial_two_sided(min(only_first, only_second), only_first + only_second)


def sign_test(differences) -> float:
    positive = sum(1 for d in differences if d > 0)
    negative = sum(1 for d in differences if d < 0)
    return binomial_two_sided(min(positive, negative), positive + negative)


def median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def tokens(row) -> int | None:
    """None when the model server reported no usage (rows from before usage_reported: when both are absent)."""
    if row.get("usage_reported") is False or (row.get("prompt_tokens") is None and row.get("completion_tokens") is None):
        return None
    return int(row.get("prompt_tokens") or 0) + int(row.get("completion_tokens") or 0)


def changed_tests(row) -> bool:
    return bool(row.get("tests_changed") or row.get("violations"))


def policy(row) -> str:
    return row.get("call_policy") or (row.get("settings") or {}).get("call_policy") or "server"


def protocol(row) -> str:
    """What must match for runs to be pooled or paired, as a short id."""
    settings = row.get("settings") or {}
    data = {key: settings.get(key) for key in PROTOCOL_SETTINGS}
    # Historical rows have no recovery setting: retain their exact protocol id.
    for key in ("max_length_continuations", "max_no_tool_reminders", "file_read_mode", "top_p", "top_k"):
        if key in settings:
            data[key] = settings[key]
    if settings.get("reasoning_effort") is not None:
        data["reasoning_effort"] = settings["reasoning_effort"]
    data.update(call_policy=policy(row), network=row.get("network"), harness=row.get("harness_commit"),
                uncommitted=bool(row.get("uncommitted_changes")))
    if row.get("grading_policy", "legacy") != "legacy":
        data.update(grading_policy=row["grading_policy"], grading_policy_sha256=row.get("grading_policy_sha256"))
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:8]


def kind(row) -> str:
    return row.get("kind") or "generated"


def group_key(row) -> tuple:
    """What runs must share to be pooled or paired: model, call policy, protocol and kind of case."""
    return row.get("model"), policy(row), protocol(row), kind(row)


def identity(row) -> tuple:
    """One run: its attempt, its group, and its case, arm and run number."""
    return (row.get("attempt"), *group_key(row), row.get("case"), row.get("arm"), row.get("run"))


def deduplicate(rows: list[dict]) -> tuple[list[dict], int]:
    """The same run read twice counts once; two different results for one run are refused."""
    seen, kept = {}, []
    for row in rows:
        key = identity(row)
        if key in seen:
            if seen[key] != row:
                raise ValueError(f"two different results for the same run {key}")
            continue
        seen[key] = row
        kept.append(row)
    return kept, len(rows) - len(kept)


def arm_rank(arm: str) -> tuple:
    return (ARM_ORDER.index(arm), arm) if arm in ARM_ORDER else (len(ARM_ORDER), arm)


def summarise(rows: list[dict]) -> list[dict]:
    groups = {}
    for row in deduplicate(rows)[0]:
        groups.setdefault((*group_key(row), row.get("arm")), []).append(row)
    summary = []
    for (model, policy_, protocol_, kind_, arm), members in sorted(
            groups.items(), key=lambda item: (tuple(str(k) for k in item[0][:4]), arm_rank(item[0][4]))):
        graded = [r for r in members if r.get("grading") == "graded"]
        counted = [tokens(r) for r in graded if tokens(r) is not None]
        fixed = [r for r in graded if r.get("fixed") is True]
        known = [r for r in graded if r.get("wrong_first_cause") is not None]
        low, high = wilson(len(fixed), len(graded))
        summary.append({
            "model": model, "call_policy": policy_, "protocol": protocol_, "kind": kind_, "arm": arm,
            "runs": len(members),
            "graded": len(graded),
            "not_graded": len(members) - len(graded), "fixed": len(fixed),
            "fixed_rate": round(len(fixed) / len(graded), 3) if graded else None, "fixed_ci95": [low, high],
            "median_first_green_turn": median(r.get("first_green_turn") for r in fixed),
            "median_first_green_s": median(r.get("first_green_s") for r in fixed),
            "mean_tokens": mean(counted), "tokens_missing": len(graded) - len(counted),
            "mean_tool_calls": mean(r.get("tool_calls") for r in graded),
            "mean_fixfirst_calls": mean(r.get("fixfirst_calls") for r in graded),
            "mean_fixfirst_reports": mean(r.get("fixfirst_reports") for r in graded),
            "mean_fixfirst_s": mean(r.get("fixfirst_s") for r in graded),
            "mean_fixfirst_output_chars": mean(r.get("fixfirst_output_chars") for r in graded),
            "wrong_first_cause": sum(1 for r in known if r["wrong_first_cause"]),
            "first_cause_known": len(known),
            "changed_tests": sum(1 for r in graded if changed_tests(r)),
        })
    return summary


def paired(rows: list[dict]) -> list[dict]:
    """Arm against arm on the same case and run (and attempt), graded in both."""
    groups = {}
    for row in deduplicate(rows)[0]:
        if row.get("grading") == "graded":
            case = (row.get("attempt"), row.get("case"), row.get("run"))
            groups.setdefault(group_key(row), {}).setdefault(row.get("arm"), {})[case] = row
    comparisons = []
    for (model, policy_, protocol_, kind_), arms in sorted(groups.items(), key=lambda item: tuple(str(k) for k in item[0])):
        for first, second in combinations(sorted(arms, key=arm_rank), 2):
            shared = sorted(set(arms[first]) & set(arms[second]), key=str)
            pairs = [(arms[first][c], arms[second][c]) for c in shared]
            only_first = sum(1 for a, b in pairs if a.get("fixed") is True and b.get("fixed") is not True)
            only_second = sum(1 for a, b in pairs if b.get("fixed") is True and a.get("fixed") is not True)
            turns = [b["first_green_turn"] - a["first_green_turn"] for a, b in pairs
                     if a.get("fixed") is True and b.get("fixed") is True
                     and a.get("first_green_turn") is not None and b.get("first_green_turn") is not None]
            token_differences = [tokens(b) - tokens(a) for a, b in pairs
                                 if tokens(a) is not None and tokens(b) is not None]
            comparisons.append({
                "model": model, "call_policy": policy_, "protocol": protocol_, "kind": kind_, "first": first,
                "second": second,
                "pairs": len(pairs),
                "fixed_only_first": only_first, "fixed_only_second": only_second,
                "mcnemar_p": round(mcnemar(only_first, only_second), 4),
                "green_turn_pairs": len(turns), "median_green_turn_difference": median(turns),
                "green_turn_sign_p": round(sign_test(turns), 4),
                "token_pairs": len(token_differences), "median_token_difference": median(token_differences),
                "token_sign_p": round(sign_test(token_differences), 4),
            })
    return comparisons


def read_rows(paths, attempt=None) -> list[dict]:
    rows = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if attempt is None or row.get("attempt") == attempt:
                    rows.append(row)
    return rows


def markdown(summary, comparisons) -> str:
    def cell(value):
        return "–" if value is None else str(value)
    lines = ["| Model | Policy | Protocol | Kind | Arm | Graded | Fixed (95% CI) | Green turn | Green s | Tokens (missing) "
             "| FixFirst calls/reports | FixFirst s | Wrong first cause | Changed tests | Not graded |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in summary:
        low, high = s["fixed_ci95"]
        rate = "–" if s["fixed_rate"] is None else f"{s['fixed']}/{s['graded']} ({cell(low)}–{cell(high)})"
        wrong = f"{s['wrong_first_cause']}/{s['first_cause_known']}" if s["first_cause_known"] else "–"
        lines.append(f"| {s['model']} | {s['call_policy']} | {s['protocol']} | {s['kind']} | {s['arm']} | {s['graded']} | {rate} "
                     f"| {cell(s['median_first_green_turn'])} | {cell(s['median_first_green_s'])} "
                     f"| {cell(s['mean_tokens'])} ({s['tokens_missing']}) "
                     f"| {cell(s['mean_fixfirst_calls'])}/{cell(s['mean_fixfirst_reports'])} | {cell(s['mean_fixfirst_s'])} "
                     f"| {wrong} | {s['changed_tests']} | {s['not_graded']} |")
    lines += ["", "| Model | Policy | Protocol | Kind | Arms | Pairs | Fixed only in first / second (McNemar p) "
              "| Green-turn difference (pairs, sign p) | Token difference (pairs, sign p) |",
              "|---|---|---|---|---|---|---|---|---|"]
    for c in comparisons:
        lines.append(f"| {c['model']} | {c['call_policy']} | {c['protocol']} | {c['kind']} | {c['first']} → {c['second']} | {c['pairs']} "
                     f"| {c['fixed_only_first']} / {c['fixed_only_second']} (p={c['mcnemar_p']}) "
                     f"| {cell(c['median_green_turn_difference'])} ({c['green_turn_pairs']}, p={c['green_turn_sign_p']}) "
                     f"| {cell(c['median_token_difference'])} ({c['token_pairs']}, p={c['token_sign_p']}) |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("results", nargs="+", help="results.jsonl files written by agent_pilot.py")
    parser.add_argument("--attempt", help="only rows of this attempt")
    parser.add_argument("--json", help="also write the numbers to this file")
    args = parser.parse_args(argv)
    rows = read_rows(args.results, args.attempt)
    try:
        unique, duplicates = deduplicate(rows)
    except ValueError as error:
        parser.error(str(error))
    summary, comparisons = summarise(unique), paired(unique)
    print(markdown(summary, comparisons))
    if duplicates:
        print(f"\n{duplicates} duplicate rows (the same run read twice) were counted once.")
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": summary, "paired": comparisons, "duplicates": duplicates},
                                              indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
