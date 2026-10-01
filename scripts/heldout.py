"""Tools for the held-out check on a new batch of real projects (docs/tasks/A1, A2, C1).

Usage:
  python scripts/heldout.py pytest TARGET --manifest FILE [--only ID ...] [--repeat N] [--output DIR]
  python scripts/heldout.py twin TARGET --manifest FILE --id ID --to DIR
  python scripts/heldout.py check --manifest FILE --labels FILE
  python scripts/heldout.py agree FIRST.csv SECOND.csv [--column NAME]
  python scripts/heldout.py sheet --labels FILE --results FILE --output FILE
  python scripts/heldout.py summary SCORES.csv

pytest   runs plain pytest in each project's environment, as a user who activated it would, and
         saves the output next to the manifest (pytest/<id>.txt). Labels are written from this
         output. It never runs FixFirst.
twin     copies one project and rebuilds the same environment beside it, to try a fix without
         touching the project that will be tested.
check    checks that every project in the manifest has a complete label, a stable pytest output
         and an environment list, and counts the labels by root cause.
agree    compares two people's labels: agreement and Cohen's kappa on the root cause (or on
         --column, e.g. score), and the first steps side by side for the discussion.
sheet    puts each label next to FixFirst's first step (from scripts/run_real_world.py) in a
         CSV with an empty score column.
summary  counts the scores, overall and by root cause.

The label file is a CSV with at least the columns id, root_cause and first_step
(docs/tasks/templates/labels.csv). Home folders are written as <home>.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

CAUSES = [
    "missing_dependency",
    "local_module",
    "version_incompatibility",
    "config_missing",
    "code_defect",
    "healthy",
]
SCORES = ["correct", "partial", "generic", "wrong"]
MAX_CHARS = 2_000_000


def redact(text: str) -> str:
    home = Path.home()
    text = text.replace(home.as_uri(), "file://<home>")
    return text.replace(str(home), "<home>").replace(home.as_posix(), "<home>")


def venv_python(folder: Path) -> Path:
    return folder / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def activated(folder: Path) -> dict:
    """The environment a user gets after activating the project's .venv."""
    scripts = venv_python(folder).parent
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    env["PATH"] = str(scripts) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(scripts.parent)
    # A terminal shows any character; a pipe would use the Windows code page instead.
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# A project whose own config asks for colour (`addopts = --color=yes`) wraps every
# line of the output in escape codes, so `=+ ... =+` never matches the banner and
# the fallback below returns a line that still carries the timing.  Two identical
# runs then look different and the project is dropped as unstable.  Strip the
# codes before looking for the summary line.
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def summary_line(output: str) -> str:
    """pytest's last line without its timing, e.g. '2 failed, 14 errors'."""
    lines = [ANSI_ESCAPE.sub("", line).strip() for line in output.splitlines()]
    lines = [line for line in lines if line]
    for line in reversed(lines):
        match = re.fullmatch(r"=+ (.+?) =+", line)
        if match:
            return re.sub(r" in [\d.]+s\b.*$", "", match.group(1))
    # No banner (a hard crash, or an interrupted collection): the last line is the
    # message itself, and its timing has to go as well.
    return re.sub(r" in [\d.]+s\b.*$", "", lines[-1])[:200] if lines else "(no output)"


def outcome(run: dict) -> tuple:
    """What a run found, ignoring warnings (the first run also warns while compiling)."""
    parts = [p for p in run["summary"].split(", ") if not re.fullmatch(r"\d+ warnings?", p)]
    return run["exit_code"], ", ".join(parts)


def run_pytest(folder: Path, timeout: float) -> dict:
    python = venv_python(folder)
    start = time.monotonic()
    try:
        done = subprocess.run([str(python), "-m", "pytest"], cwd=folder, env=activated(folder),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        output, code = done.stdout, done.returncode
    except subprocess.TimeoutExpired as error:
        output, code = (error.stdout or b"") + b"\n(stopped: timeout)\n", "timeout"
    text = redact(output.decode("utf-8", "replace"))
    if len(text) > MAX_CHARS:
        half = MAX_CHARS // 2
        text = text[:half] + "\n\n[... middle of the output left out ...]\n\n" + text[-half:]
    return {"exit_code": code, "seconds": round(time.monotonic() - start, 1),
            "summary": summary_line(text), "output": text}


def capture(args) -> int:
    manifest = Path(args.manifest).resolve()
    projects = tomllib.loads(manifest.read_text("utf-8"))["project"]
    out = Path(args.output).resolve() if args.output else manifest.parent / "pytest"
    out.mkdir(parents=True, exist_ok=True)
    index_file = out / "index.json"
    index = json.loads(index_file.read_text("utf-8")) if index_file.exists() else {}
    for project in projects:
        if args.only and project["id"] not in args.only:
            continue
        folder = Path(args.target).resolve() / project["id"]
        python = venv_python(folder)
        if not python.exists():
            print(f"== {project['id']}: no .venv, run scripts/setup_real_world.py first", flush=True)
            continue
        print(f"== {project['id']}", flush=True)
        version = subprocess.run([str(python), "-c", "import sys; print(sys.version.split()[0])"],
                                 capture_output=True, text=True, check=False).stdout.strip()
        runs = [run_pytest(folder, args.timeout) for _ in range(args.repeat)]
        same = len({outcome(r) for r in runs}) == 1
        header = [
            "# Plain pytest output for the held-out check (scripts/heldout.py pytest)",
            f"# project: {project['id']} ({project['repo']} {project['ref']})",
            f"# command: python -m pytest, in {redact(str(folder))}, environment activated",
            f"# python: {version}",
            *[f"# run {n}: exit code {r['exit_code']}, {r['seconds']} s, {r['summary']}"
              for n, r in enumerate(runs, 1)],
            f"# date: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        ]
        if not same:
            header.append("# WARNING: the runs differ; do not use this project unless you find out why")
        (out / f"{project['id']}.txt").write_text(
            "\n".join(header) + "\n\n" + runs[0]["output"], encoding="utf-8")
        index[project["id"]] = {"python": version, "same_every_run": same,
                                "runs": [{k: r[k] for k in ("exit_code", "seconds", "summary")} for r in runs]}
        print(f"   {runs[0]['summary']}" + ("" if same else "  (runs differ!)"), flush=True)
    index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"\nSaved in {out}")
    return 0


def twin(args) -> int:
    manifest = Path(args.manifest).resolve()
    projects = {p["id"]: p for p in tomllib.loads(manifest.read_text("utf-8"))["project"]}
    if args.id not in projects:
        raise SystemExit(f"{args.id} is not in {manifest}")
    project = projects[args.id]
    source = Path(args.target).resolve() / args.id
    copy = Path(args.to).resolve() / args.id
    if not venv_python(source).exists():
        raise SystemExit(f"{source} has no .venv; run scripts/setup_real_world.py first")
    if copy.exists():
        raise SystemExit(f"{copy} exists; delete it first (it is only a copy)")
    if not shutil.which("uv"):
        raise SystemExit("uv is needed: https://docs.astral.sh/uv/getting-started/installation/")
    base = subprocess.run([str(venv_python(source)), "-c", "import sys; print(sys._base_executable)"],
                          capture_output=True, text=True, check=True).stdout.strip()
    shutil.copytree(source, copy, symlinks=True, ignore=shutil.ignore_patterns(
        ".venv", ".venv-*", "__pycache__", ".pytest_cache", ".fixfirst"))
    subprocess.run(["uv", "venv", "-q", *(["--seed"] if project.get("pip", True) else []),
                    "-p", base, str(copy / ".venv")], check=True)
    freeze = subprocess.run(["uv", "pip", "freeze", "--python", str(venv_python(source))],
                            capture_output=True, text=True, check=True).stdout.splitlines()
    # The project itself is installed again from the copy, the way the manifest says.
    same = [line for line in freeze if not line.startswith("-e ")
            and source.as_uri() not in line and str(source) not in line]
    with tempfile.TemporaryDirectory() as scratch:
        listing = Path(scratch) / "requirements.txt"
        listing.write_text("\n".join(same) + "\n", encoding="utf-8")
        subprocess.run(["uv", "pip", "install", "-q", "--no-deps", "--python", str(venv_python(copy)),
                        "-r", str(listing)], check=True)
    for line in project["install"]:
        words = shlex.split(line)
        local = [w for w in words if w == "." or w.startswith((".[", "./"))]
        if local:
            editable = ["-e"] if "-e" in words else []
            done = subprocess.run(["uv", "pip", "install", "-q", "--no-deps", "--python",
                                   str(venv_python(copy)), *editable, *local], cwd=copy)
            if done.returncode != 0:
                print("The project does not install here either, as in the original environment.")
    print(f"Twin ready: {copy}\nTry a fix there, then run pytest inside it:\n"
          f"  cd {copy}\n  {venv_python(copy).relative_to(copy)} -m pytest\n"
          "The original project and its environment are untouched; delete the copy when done.")
    return 0


def read_labels(path, column="root_cause") -> dict:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if (r.get("id") or "").strip()]
    labels = {}
    for row in rows:
        row = {k: (v or "").strip() for k, v in row.items() if k}
        if row["id"] in labels:
            raise ValueError(f"{path}: {row['id']} appears twice")
        if column == "root_cause" and row.get("root_cause") not in CAUSES:
            print(f"warning: {path}: {row['id']} has root_cause {row.get('root_cause')!r}, "
                  f"expected one of {', '.join(CAUSES)}", file=sys.stderr)
        labels[row["id"]] = row
    return labels


REQUIRED = ["pytest_shows", "root_cause", "first_step", "checked_by_trying", "labelled_by", "labelled_on"]


def check(args) -> int:
    manifest = Path(args.manifest).resolve()
    ids = [p["id"] for p in tomllib.loads(manifest.read_text("utf-8"))["project"]]
    labels = read_labels(args.labels)
    index_file = manifest.parent / "pytest" / "index.json"
    index = json.loads(index_file.read_text("utf-8")) if index_file.exists() else {}
    problems = [f"{pid}: labelled but not in {manifest.name}" for pid in labels if pid not in ids]
    for pid in ids:
        label = labels.get(pid)
        if label is None:
            problems.append(f"{pid}: no label")
            continue
        problems += [f"{pid}: {column} is empty" for column in REQUIRED if not label.get(column)]
        if label.get("root_cause") and label["root_cause"] not in CAUSES:
            problems.append(f"{pid}: unknown root_cause {label['root_cause']!r}")
        if pid not in index:
            problems.append(f"{pid}: no pytest output (heldout.py pytest ... --repeat 2)")
        elif len(index[pid]["runs"]) < 2:
            problems.append(f"{pid}: pytest ran once; run it with --repeat 2")
        elif not index[pid]["same_every_run"]:
            problems.append(f"{pid}: pytest gave different results in different runs")
        if not (manifest.parent / "environments" / f"{pid}.txt").exists():
            problems.append(f"{pid}: no environments/{pid}.txt (scripts/setup_real_world.py)")
    counts = Counter(labels[pid]["root_cause"] for pid in ids if pid in labels)
    print(f"{len(ids)} projects in {manifest.name}; labels by root cause: "
          + ", ".join(f"{cause} {counts[cause]}" for cause in CAUSES))
    print("\n".join(["Problems:", *[f"- {p}" for p in problems]]) if problems else "Complete.")
    return 1 if problems else 0


def kappa(first: list[str], second: list[str]) -> float | None:
    """Cohen's kappa for two raters; None when chance agreement is already complete."""
    n = len(first)
    observed = sum(a == b for a, b in zip(first, second)) / n
    expected = sum((first.count(c) / n) * (second.count(c) / n) for c in set(first) | set(second))
    return None if expected == 1 else (observed - expected) / (1 - expected)


def cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def agree(args) -> int:
    column = args.column
    first, second = read_labels(args.first, column), read_labels(args.second, column)
    ids = [i for i in first if i in second]
    only = sorted(set(first) ^ set(second))
    if not ids:
        print("No project appears in both files.")
        return 1
    a = [first[i].get(column, "").lower() for i in ids]
    b = [second[i].get(column, "").lower() for i in ids]
    same = sum(x == y for x, y in zip(a, b))
    k = kappa(a, b)
    other = "first_step" if column == "root_cause" else "notes"
    print(f"# Agreement on {column}: {Path(args.first).name} vs {Path(args.second).name}\n")
    print(f"- Projects in both files: {len(ids)}" + (f" (only in one file: {', '.join(only)})" if only else ""))
    print(f"- Same {column}: {same} of {len(ids)} ({same / len(ids):.0%})")
    print(f"- Cohen's kappa: {'undefined (one value only)' if k is None else f'{k:.2f}'}\n")
    print(f"| Project | {column} (first) | {column} (second) | {other} (first) | {other} (second) |")
    print("|---|---|---|---|---|")
    for i, x, y in zip(ids, a, b):
        mark = "" if x == y else " **differs**"
        print(f"| {i}{mark} | {x} | {y} | {cell(first[i].get(other, ''))} | {cell(second[i].get(other, ''))} |")
    if column == "root_cause":
        print("\nThe first steps are compared by reading them: decide together, per project, whether "
              "they would lead to the same fix, and write the outcome in the review notes.")
    return 0


SHEET_FIELDS = [
    "id", "label_root_cause", "label_first_step", "also_acceptable", "partial_if", "wrong_if",
    "fixfirst_headline", "fixfirst_first_step", "fixfirst_cause", "fixfirst_hedged",
    "fixfirst_rules", "fixfirst_command", "search_offered", "score", "scored_by", "notes",
]


def sheet(args) -> int:
    labels = read_labels(args.labels)
    results = {r["id"]: r for r in json.loads(Path(args.results).read_text("utf-8"))}
    output = Path(args.output)
    if output.exists() and not args.force:
        raise SystemExit(f"{output} exists; scores may already be in it (use --force to replace it)")
    rows = []
    for pid, label in labels.items():
        row = {"id": pid, "label_root_cause": label["root_cause"],
               "label_first_step": label.get("first_step", ""),
               "also_acceptable": label.get("also_acceptable", ""),
               "partial_if": label.get("partial_if", ""), "wrong_if": label.get("wrong_if", "")}
        result = results.get(pid)
        if result is None:
            row["fixfirst_headline"] = "(not in the results file)"
        else:
            step = result["steps"][0] if result["steps"] else None
            row["fixfirst_headline"] = result["headline"]
            row["fixfirst_first_step"] = step["title"] if step else "(no must-fix step)"
            if step:
                row["fixfirst_cause"] = step["cause"] or step["possible"] or ""
                row["fixfirst_hedged"] = "yes" if step["possible"] or step["suspected"] else "no"
                row["fixfirst_rules"] = " ".join(step["rules"])
                row["fixfirst_command"] = step["command"] or ""
            if result.get("search"):
                row["search_offered"] = result["search"]["offered"]["title"]
        rows.append(row)
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {output}. Fill in score ({' / '.join(SCORES)}), "
          "scored_by and notes, then run: python scripts/heldout.py summary " + str(output))
    return 0


def summary(args) -> int:
    with open(args.scores, newline="", encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if (r.get("id") or "").strip()]
    scored = [r for r in rows if (r.get("score") or "").strip().lower() in SCORES]
    missing = [r["id"] for r in rows if r not in scored]
    count = {s: sum(r["score"].strip().lower() == s for r in scored) for s in SCORES}
    hedged = sum(r["score"].strip().lower() == "correct" and r.get("fixfirst_hedged") == "yes" for r in scored)
    print(f"# Scores: {Path(args.scores).name}\n")
    print(f"- Scored: {len(scored)} of {len(rows)}" + (f" (not scored: {', '.join(missing)})" if missing else ""))
    print("- " + ", ".join(f"{s.capitalize()} {count[s]}" for s in SCORES)
          + f" (of the correct ones, {hedged} shown as likely rather than confirmed)\n")
    print("| Root cause (label) | Projects | " + " | ".join(s.capitalize() for s in SCORES) + " |")
    print("|---|---|" + "---|" * len(SCORES))
    for cause in CAUSES:
        group = [r for r in scored if r["label_root_cause"] == cause]
        if group:
            print(f"| {cause} | {len(group)} | "
                  + " | ".join(str(sum(r['score'].strip().lower() == s for r in group)) for s in SCORES) + " |")
    return 0 if not missing else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("pytest", help="save plain pytest output for each project")
    one.add_argument("target", help="folder that holds the projects (as for setup_real_world.py)")
    one.add_argument("--manifest", required=True)
    one.add_argument("--only", nargs="*", default=[])
    one.add_argument("--repeat", type=int, default=1, help="run pytest this many times (2 checks it is stable)")
    one.add_argument("--timeout", type=float, default=1200, help="seconds per run (default 1200)")
    one.add_argument("--output", help="folder for the outputs (default: pytest/ next to the manifest)")
    copy = sub.add_parser("twin", help="copy a project with the same environment, to try a fix")
    copy.add_argument("target", help="folder that holds the projects")
    copy.add_argument("--manifest", required=True)
    copy.add_argument("--id", required=True)
    copy.add_argument("--to", required=True, help="folder for the copy")
    complete = sub.add_parser("check", help="check that the labels are complete")
    complete.add_argument("--manifest", required=True)
    complete.add_argument("--labels", required=True)
    two = sub.add_parser("agree", help="compare two label (or score) files")
    two.add_argument("first")
    two.add_argument("second")
    two.add_argument("--column", default="root_cause", help="column to compare (default root_cause)")
    three = sub.add_parser("sheet", help="make a scoring sheet from labels and FixFirst's results")
    three.add_argument("--labels", required=True)
    three.add_argument("--results", required=True)
    three.add_argument("--output", required=True)
    three.add_argument("--force", action="store_true")
    four = sub.add_parser("summary", help="count the scores in a filled-in sheet")
    four.add_argument("scores")
    args = parser.parse_args()
    commands = {"pytest": capture, "twin": twin, "check": check, "agree": agree, "sheet": sheet,
                "summary": summary}
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
