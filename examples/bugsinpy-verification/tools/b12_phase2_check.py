#!/usr/bin/env python3
"""B12 phase 2, judged from the records of scripts/bugsinpy_case.py by the criteria of registry addendum 86.

    b12_phase2_check.py TARGET [--json OUT.json]

TARGET is the folder b12_phase2.py wrote: one sub-folder per stream with results/<case>.json.
Per bug:
  reproduced today      the bug's test exits 1 on the buggy source and 0 after the patch is applied again;
  no environment advice the first check lists no must-fix step that carries a command;
  open until repaired   before the repair at least one issue has the bug's test among its targets and none of
                        those is "resolved"; after the repair every one of them is "resolved";
  not seen              the product's first check has no issue with the bug's test at all.
PySnooper 2 was seen during development and is listed apart. Reported besides: the cause the first step names,
whether it is hedged, the headlines of both checks.
"""
import collections
import json
import sys
from pathlib import Path

argv = sys.argv[1:]
out_json = None
if "--json" in argv:
    at = argv.index("--json")
    out_json = Path(argv[at + 1])
    del argv[at:at + 2]
target = Path(argv[0])
DEV = {"PySnooper-2"}
EXPECTED = ([f"tqdm-{n}" for n in range(1, 10)] + ["cookiecutter-2", "cookiecutter-3", "cookiecutter-4", "PySnooper-2"]
            + [f"tornado-{n}" for n in (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)])
records = {}
for path in sorted(target.glob("*/results/*.json")):
    record = json.loads(path.read_text(encoding="utf-8"))
    records[record["case"]] = record
rows, missing = [], [c for c in EXPECTED if c not in records]
for case in EXPECTED:
    r = records.get(case)
    if not r:
        continue
    before, after = r.get("fixfirst_before"), r.get("fixfirst_after")
    row = {"case": case, "project": case.rsplit("-", 1)[0], "dev": case in DEV, "result": r.get("result"), "python": r.get("python"),
           "reproduced": r.get("buggy_test_exit_code") == 1 and r.get("fixed_test_exit_code") == 0,
           "exit_codes": (r.get("buggy_test_exit_code"), r.get("fixed_test_exit_code")), "checked": bool(before and after)}
    if before and after:
        issues_before, issues_after = before["bug_issues"], after["bug_issues"]
        first = before["steps"][0] if before["steps"] else None
        row.update(
            environment_advice=before["environment_advice"],
            no_environment_advice=not before["environment_advice"],
            optional_with_command=[s["title"] for s in before.get("optional", []) if s.get("command")],
            seen=bool(issues_before),
            status_before=[i["status"] for i in issues_before], status_after=[i["status"] for i in issues_after],
            open_until_repaired=bool(issues_before) and all(i["status"] != "resolved" for i in issues_before)
            and bool(issues_after) and all(i["status"] == "resolved" for i in issues_after),
            first_title=first["title"] if first else None, first_cause=first["cause"] if first else None, hedged=first["hedged"] if first else None,
            first_rules=first["rules"] if first else None, steps_before=len(before["steps"]), headline_before=before["headline"], headline_after=after["headline"],
            status_kind_before=before["status"], status_kind_after=after["status"], diagnosis=[i["diagnosis"] for i in issues_before],
            bug_test_before=before.get("bug_test_outcomes"), bug_test_after=after.get("bug_test_outcomes"), steps_after=len(after["steps"]),
            environment_advice_after=after["environment_advice"])
    rows.append(row)


def summary(group, label):
    counted = [x for x in group if x["reproduced"] and x["checked"]]
    print(f"\n{label}: {len(group)} bugs run; reproduced today and checked by the product: {len(counted)}"
          + (f"; not reproduced today or not checked: {[x['case'] + ' ' + str(x['exit_codes']) for x in group if not (x['reproduced'] and x['checked'])]}" if len(counted) != len(group) else ""))
    if not counted:
        return
    print(f"   no environment advice among the steps to do: {sum(x['no_environment_advice'] for x in counted)} of {len(counted)}"
          + (f"; with advice: {[(x['case'], x['environment_advice']) for x in counted if not x['no_environment_advice']]}" if not all(x['no_environment_advice'] for x in counted) else ""))
    print(f"   the product's check has an issue with the bug's test: {sum(x['seen'] for x in counted)} of {len(counted)}"
          + (f"; not seen: {[x['case'] for x in counted if not x['seen']]}" if not all(x['seen'] for x in counted) else ""))
    print(f"   open until repaired (open before, resolved after): {sum(x['open_until_repaired'] for x in counted)} of {len(counted)}"
          + (f"; not: {[(x['case'], x['status_before'], x['status_after']) for x in counted if not x['open_until_repaired']]}" if not all(x['open_until_repaired'] for x in counted) else ""))
    causes = collections.Counter((x["first_cause"] or "(no step)") + (" [hedged]" if x["hedged"] else "") for x in counted)
    print(f"   cause named by the first step: {dict(causes)}")
    print(f"   optional steps with a command: {sum(bool(x['optional_with_command']) for x in counted)} bugs")
    by_project = collections.Counter(x["project"] for x in counted)
    print(f"   by project: {dict(by_project)}")


print(f"records found: {len(records)} of {len(EXPECTED)} expected" + (f"; missing {missing}" if missing else ""))
print(f"{'bug':16}{'repro':6}{'no env advice':14}{'seen':5}{'before -> after':38}first step (cause)")
for x in rows:
    if not x["checked"]:
        print(f"{x['case']:16}{str(x['reproduced']):6}not checked by the product; exit codes {x['exit_codes']}; result {x['result']}")
        continue
    print(f"{x['case']:16}{str(x['reproduced']):6}{str(x['no_environment_advice']):14}{str(x['seen']):5}{(','.join(x['status_before']) or '-') + ' -> ' + (','.join(x['status_after']) or '-'):38}"
          f"{(x['first_title'] or '(no step)')[:70]} ({x['first_cause']}{', hedged' if x['hedged'] else ''})")
summary([x for x in rows if not x["dev"]], "THE 27 UNSEEN BUGS")
summary([x for x in rows if x["dev"]], "PySnooper 2 (seen during development, apart)")
if out_json:
    out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
