#!/usr/bin/env python3
"""B9 part 1: do exact matching and TF-IDF grouping ever differ on saved event streams? No model, nothing executed.

    survey.py TREE [--datasets DIR ...] [--sessions GLOB ...] [--json OUT]

TREE's src/ is the product. --datasets: folders that hold cases.jsonl files with saved sessions (searched
recursively
a shared environment.json beside a cases.jsonl is restored into its sessions). --sessions: globs of
session.json files of a store. For every run of every session the product's group_events is called with "exact"
and with "tfidf" (threshold 0.82) and the two partitions of the run's events are compared.
"""
import glob
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

argv = sys.argv[1:]
tree = Path(argv[0]).resolve()
sys.path.insert(0, str(tree / "src"))
from fixfirst.grouping import block_key, group_events, normalize  # noqa: E402
from fixfirst.models import Session  # noqa: E402


def option(name):
    values = []
    if name in argv:
        at = argv.index(name) + 1
        while at < len(argv) and not argv[at].startswith("--"):
            values.append(argv[at])
            at += 1
    return values


def sessions():
    for folder in option("--datasets"):
        for cases in sorted(Path(folder).rglob("cases.jsonl")):
            shared_file = cases.with_name("environment.json")
            shared = json.loads(shared_file.read_bytes()) if shared_file.is_file() else None
            for line in cases.read_bytes().splitlines():
                raw = json.loads(line)
                data = raw.get("session")
                if not data:
                    continue
                env = data.get("environment") or {}
                if shared is not None and env.get("$shared") == "environment.json":
                    data["environment"] = {**shared, **{k: v for k, v in env.items() if k.startswith("_")}}
                yield str(cases.parent), data
    for pattern in option("--sessions"):
        for path in sorted(glob.glob(pattern, recursive=True)):
            yield str(Path(path).parents[2]), json.loads(Path(path).read_bytes())


def pairs(issues):
    merged = set()
    for issue in issues:
        merged.update(tuple(sorted(p)) for p in combinations(issue.event_ids, 2))
    return merged


total = Counter()
per_source = {}
examples = []
for source, data in sessions():
    session = Session.model_validate(data)
    row = per_source.setdefault(source, Counter())
    row["sessions"] += 1
    for run in session.runs:
        events = [e for e in session.events if e.run_id == run.run_id]
        if not events:
            continue
        row["runs_with_events"] += 1
        row["events"] += len(events)
        blocks = Counter(block_key(e) for e in events)
        same_block = sum(n * (n - 1) // 2 for n in blocks.values())
        by_block = {}
        for e in events:
            by_block.setdefault(block_key(e), []).append(normalize(e.message))
        differing = sum(1 for texts in by_block.values() for a, b in combinations(texts, 2) if a != b)
        exact, tfidf = pairs(group_events(events, run, "exact")), pairs(group_events(events, run, "tfidf"))
        row["same_block_pairs"] += same_block
        row["same_block_pairs_with_different_text"] += differing
        row["merged_exact"] += len(exact)
        row["merged_tfidf"] += len(tfidf)
        row["merged_by_tfidf_only"] += len(tfidf - exact)
        row["merged_by_exact_only"] += len(exact - tfidf)
        if (tfidf ^ exact) and len(examples) < 10:
            by_id = {e.event_id: e for e in events}
            a, b = sorted(tfidf ^ exact)[0]
            examples.append({"source": source.rsplit("/", 2)[-1], "a": normalize(by_id[a].message)[:160], "b": normalize(by_id[b].message)[:160]})
for row in per_source.values():
    total.update(row)
result = {"total": dict(total), "sources": len(per_source), "examples_of_a_difference": examples}
by_top = {}
for source, row in per_source.items():
    key = "/".join(Path(source).parts[-3:]) if "--sessions" not in argv else Path(source).parts[-1]
    by_top.setdefault(key, Counter()).update(row)
result["by_source"] = {k: dict(v) for k, v in sorted(by_top.items())}
if "--json" in argv:
    Path(argv[argv.index("--json") + 1]).write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"total": result["total"], "sources": result["sources"], "examples_of_a_difference": examples}, indent=1, ensure_ascii=False))
