"""Failure mix of the real-project field trials (rounds 6-8): each distinct issue title counted once per project.

    python failure_mix.py <git ref> > failure-mix.json
Projects are the first-batch logs (N1..C3, re-runs merged by name) and the retest batch (R-*). Digits in titles
are normalised so that version numbers do not split one issue into many. Coarse keyword classes; first match wins.
"""
import collections
import json
import re
import subprocess
import sys

ref = sys.argv[1]
files = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, "--", "experiments/field_trial/results"],
                       capture_output=True, text=True, check=True).stdout.split()
per_project = collections.defaultdict(set)
for f in files:
    base = f.rsplit("/", 1)[1].rsplit(".", 1)[0]
    if not f.endswith(".jsonl") or not re.fullmatch(r"(R-)?[NSC]\d", base):
        continue
    for line in subprocess.run(["git", "show", f"{ref}:{f}"], capture_output=True, text=True).stdout.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        for issue in entry.get("issues") or []:
            title = (issue.get("title") if isinstance(issue, dict) else str(issue)) or ""
            per_project[base].add(re.sub(r"\d+(\.\d+)*", "#", title)[:120])
RULES = [("install / dependency / build", r"install|wheel|build|declares|dependency|requirement|distribution|pg_config|resolv"),
         ("version / release / removed API", r"version|release|removed|deprecat"),
         ("ImportError / ModuleNotFoundError", r"ImportError|ModuleNotFoundError|No module named|cannot import"),
         ("AttributeError", r"AttributeError"), ("TypeError", r"TypeError"), ("positional-only", r"positional-only")]
titles, projects = collections.Counter(), collections.defaultdict(set)
for project, found in per_project.items():
    for title in found:
        cls = next((name for name, rx in RULES if re.search(rx, title, re.I)), "other (assertion, style, unknown ...)")
        titles[cls] += 1
        projects[cls].add(project)
print(json.dumps({"ref": ref, "projects": sorted(per_project), "distinct_issue_titles": sum(map(len, per_project.values())),
                  "classes": {name: {"titles": titles[name], "projects": len(projects[name])} for name, _ in RULES + [("other (assertion, style, unknown ...)", "")]}},
                 indent=1, ensure_ascii=False))
