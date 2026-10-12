#!/usr/bin/env python3
"""B9: constructed hard pairs for the similarity step of message grouping. No model, nothing executed.

    grouping_hard.py build DATASET [DATASET ...] --out pairs.json
    grouping_hard.py evaluate pairs.json --out results.json

The product must be importable (run with the checkout's own interpreter).

build: takes every distinct message of the events in saved sessions (cases.jsonl files below the given folders)
and makes pairs by rule: the message as it is, and one changed copy that stays in the same block. Changes that a
grouping must merge: one number, one line number, one directory name of a path. Changes that it must keep apart:
one identifier (a quoted name, or a setting or dotted name after a colon) replaced by a near spelling, or by an
unrelated identifier from another message. A number after "file.ext:" or "line " is a line number. The rule takes
the first eligible occurrence; a message without the thing to change gives no pair of that family; a change that
would alter the block key is not made. Nothing is chosen by looking at a grouping method's output.

evaluate: each pair is given to the product's group_events as a block of two events, once with "exact" and once
with "tfidf" (threshold 0.82), and it is recorded whether the two events end in one group.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from fixfirst.grouping import block_key, group_events, normalize, similarity
from fixfirst.models import Event

VERSION = re.compile(r"\b\d+(?:\.\d+)+(?:[\w.+-]*)")  # the block key's own pattern for version-like tokens
PATH = re.compile(r"(?:[A-Za-z]:)?(?:<\w[\w-]*>|\.{1,2}|[\w.+-]+)?(?:/[\w.+@<>-]+){2,}")
LINE = re.compile(r"(?:\bline |[\w-]\.[A-Za-z]{1,5}:|\.py\", line )(\d+)\b")  # "line N", "file.ext:N"
NUMBER = re.compile(r"(?<![\w.<])\d+(?![\w.>])")
QUOTED = re.compile(r"(['\"`])([A-Za-z_][\w.]{3,})\1")
BARE = re.compile(r"(?<=: )([A-Za-z][A-Za-z0-9]*(?:[_.][A-Za-z0-9]+)+)\b")  # a setting or dotted name after a colon
POSITIVE = ("number", "line", "path", "temporary path")
NEGATIVE = ("near identifier", "unrelated identifier")


def spans(pattern, text):
    return [m.span() for m in pattern.finditer(text)]


def inside(position, intervals):
    return any(a <= position < b for a, b in intervals)


def other_number(digits):
    changed = "".join(str((int(d) + 3) % 10) for d in digits)
    return ("7" + changed[1:]) if changed[0] == "0" and len(changed) > 1 else changed


def change_number(text):
    blocked = spans(VERSION, text) + spans(PATH, text) + [m.span(1) for m in LINE.finditer(text)]
    for match in NUMBER.finditer(text):
        if not inside(match.start(), blocked):
            return text[:match.start()] + other_number(match.group()) + text[match.end():]
    return None


def change_line(text):
    match = LINE.search(text)
    if not match:
        return None
    return text[:match.start(1)] + str(int(match.group(1)) + 37) + text[match.end(1):]


def change_path(text, temporary):
    for match in PATH.finditer(text):
        token = match.group()
        if text[max(0, match.start() - 1):match.start() + 2] in ("://", ":/") or text[max(0, match.start() - 2):match.start()] == ":/":
            continue  # part of a URL, not a file path
        is_temporary = token.startswith(("/tmp/", "/private/tmp/"))
        if is_temporary != temporary:
            continue
        parts = token.split("/")
        for index in range(1, len(parts) - 1):  # a directory, never the file name
            if re.fullmatch(r"[A-Za-z_][\w.-]*", parts[index]) and not (temporary and parts[index] in ("tmp", "private")):
                parts[index] = "other_dir" if parts[index] != "other_dir" else "another_dir"
                return text[:match.start()] + "/".join(parts) + text[match.end():]
    return None


def identifier(text):
    match = QUOTED.search(text)
    if match:
        return match.span(2), match.group(2)
    match = BARE.search(text)
    if match:
        return match.span(1), match.group(1)
    return None, None  # an exception class alone is not taken: a misspelt class is not another thing


def near(name):
    return name[:-1] if len(name) >= 5 else name + "x"


def sessions(folders):
    for folder in folders:
        for cases in sorted(Path(folder).rglob("cases.jsonl")):
            for line in cases.read_bytes().splitlines():
                raw = json.loads(line)
                if raw.get("session"):
                    yield f"{cases.parent.name}/{raw.get('case_id', '')}", raw["session"]


def build(folders, out):
    sources, seen = [], set()
    for origin, session in sessions(folders):
        for event in session.get("events", []):
            key = (event["tool"], event["stage"], event["kind"], bool(event.get("component")), normalize(event["message"]))
            if key in seen:
                continue
            seen.add(key)
            sources.append({"origin": origin, "event": {k: event.get(k, "") for k in ("tool", "stage", "kind", "component", "location", "code", "message")}})
    sources.sort(key=lambda s: (s["event"]["kind"], s["event"]["message"], s["origin"]))
    names = [identifier(s["event"]["message"])[1] for s in sources]
    pairs, skipped = [], Counter()
    for index, source in enumerate(sources):
        event = source["event"]
        text = event["message"]
        candidates = [("number", change_number(text)), ("line", change_line(text)),
                      ("path", change_path(text, False)), ("temporary path", change_path(text, True))]
        span, name = identifier(text)
        if name:
            candidates.append(("near identifier", text[:span[0]] + near(name) + text[span[1]:]))
            for offset in range(1, len(sources)):
                other = names[(index + offset) % len(sources)]
                if other and other != name and not other.startswith(name[:3]) and abs(len(other) - len(name)) + sum(a != b for a, b in zip(other, name)) > 2:
                    candidates.append(("unrelated identifier", text[:span[0]] + other + text[span[1]:]))
                    break
        for family, changed in candidates:
            if changed is None:
                skipped[family + ": nothing to change"] += 1
                continue
            first = Event.model_validate({**event, "run_id": "run-pair", "event_id": "event-a"})
            second = Event.model_validate({**event, "run_id": "run-pair", "event_id": "event-b", "message": changed})
            if changed == text or block_key(first) != block_key(second):
                skipped[family + ": would leave the block"] += 1
                continue
            pairs.append({"pair_id": f"{len(pairs) + 1:04d}", "family": family,
                          "expected": "merge" if family in POSITIVE else "apart",
                          "origin": source["origin"], "block": {k: event[k] for k in ("tool", "stage", "kind", "component", "location", "code")},
                          "original": text, "changed": changed})
    Path(out).write_text(json.dumps({"schema_version": 1, "source_messages": len(sources), "skipped": dict(sorted(skipped.items())),
                                     "pairs": pairs}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(sources)} distinct source messages; {len(pairs)} pairs: {dict(Counter(p['family'] for p in pairs))}")
    print("no pair:", dict(sorted(skipped.items())))


def merged(pair, method):
    events = [Event.model_validate({**pair["block"], "run_id": "run-pair", "event_id": name, "message": text})
              for name, text in (("event-a", pair["original"]), ("event-b", pair["changed"]))]
    run = SimpleNamespace(scope="pair", environment_id="pair")
    return any(len(issue.event_ids) == 2 for issue in group_events(events, run, method, 0.82))


def score(rows, method):
    tp = sum(r[method] for r in rows if r["expected"] == "merge")
    fn = sum(not r[method] for r in rows if r["expected"] == "merge")
    fp = sum(r[method] for r in rows if r["expected"] == "apart")
    tn = sum(not r[method] for r in rows if r["expected"] == "apart")
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if precision is not None and recall is not None else None)
    return {"merged_rightly": tp, "missed": fn, "merged_wrongly": fp, "kept_apart_rightly": tn, "precision": precision, "recall": recall, "f1": f1}


def evaluate(pairs_file, out):
    data = json.loads(Path(pairs_file).read_text(encoding="utf-8"))
    rows = []
    for pair in data["pairs"]:
        texts = [normalize(pair["original"]), normalize(pair["changed"])]
        rows.append({"pair_id": pair["pair_id"], "family": pair["family"], "expected": pair["expected"],
                     "exact": merged(pair, "exact"), "tfidf": merged(pair, "tfidf"),
                     "cosine": round(float(similarity(texts, "tfidf")[0][1]), 4), "characters": len(texts[0])})
    result = {"pairs": len(rows), "threshold": 0.82, "overall": {m: score(rows, m) for m in ("exact", "tfidf")}, "by_family": {}}
    result["positives_without_temporary_paths"] = {m: score([r for r in rows if r["family"] != "temporary path"], m) for m in ("exact", "tfidf")}
    for family in POSITIVE + NEGATIVE:
        part = [r for r in rows if r["family"] == family]
        if part:
            cosines = sorted(r["cosine"] for r in part)
            result["by_family"][family] = {"pairs": len(part), "expected": part[0]["expected"],
                                           "merged_by_exact": sum(r["exact"] for r in part), "merged_by_tfidf": sum(r["tfidf"] for r in part),
                                           "cosine_min": cosines[0], "cosine_median": cosines[len(cosines) // 2], "cosine_max": cosines[-1]}
    result["rows"] = rows
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    arguments = sys.argv[1:]
    out = arguments[arguments.index("--out") + 1]
    if arguments[0] == "build":
        build(arguments[1:arguments.index("--out")], out)
    elif arguments[0] == "evaluate":
        evaluate(arguments[1], out)
    else:
        raise SystemExit(__doc__)
