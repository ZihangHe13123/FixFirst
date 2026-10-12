#!/usr/bin/env python3
"""The held-out test, judged from the records of heldout_case.py. No model.

    heldout_check.py TARGET SELECTION.json [--json OUT.json]

TARGET is the folder heldout_test.py wrote: TARGET/<arm>/<project>/results/<case>.json. The criteria per bug and
arm are those of registry addendum 86, by the same expressions as b12_phase2_check.py:
  reproduced            the bug's tests exit 1 on the buggy source and 0 after the patch is applied again;
  no environment advice the first check lists no must-fix step that carries a command;
  seen                  the first check has an issue with one of the bug's tests (or an instance of it);
  open until repaired   seen, none of those issues "resolved" before the repair, every one "resolved" after it.
And, as NEXT-VERSION-REQUIREMENTS section 7 adds: the cause the first step names, counted as "Defect in project
code or tests" or as another cause, and whether it is hedged (marked as not confirmed).
The denominator of an arm is the bugs of SELECTION.json; a bug that did not reproduce in an arm or was not checked
there is listed and counted as not passing every criterion.
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
target, selection_path = Path(argv[0]), Path(argv[1])
expected = [e["case"] for e in json.loads(selection_path.read_text(encoding="utf-8"))["selected"]]
ARMS = [arm for arm in ["old-default", "mid-scoped", "new-scoped", "new-default"] if (target / arm).is_dir()]
CODE = "Defect in project code or tests"
table = {}
for arm in ARMS:
    records = {}
    for path in sorted((target / arm).glob("*/results/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        records[record["case"]] = record
    rows = []
    for case in expected:
        r = records.get(case, {})
        before, after = r.get("fixfirst_before"), r.get("fixfirst_after")
        row = {"case": case, "arm": arm, "project": case.rsplit("-", 1)[0], "exit_codes": (r.get("buggy_test_exit_code"), r.get("fixed_test_exit_code")),
               "reproduced": r.get("buggy_test_exit_code") == 1 and r.get("fixed_test_exit_code") == 0, "checked": bool(before and after),
               "patched_tests": [f for f in r.get("patched_files", []) if "test" in f.lower()], "selection_refused": r.get("selection_refused"),
               "product_error": {k: r[k].strip().splitlines()[-1] for k in ("product_error_before", "product_error_after") if k in r}}
        if before and after:
            issues_before, issues_after = before["bug_issues"], after["bug_issues"]
            first = before["steps"][0] if before["steps"] else None
            row.update(
                no_environment_advice=not before["environment_advice"], environment_advice=before["environment_advice"],
                optional_with_command=[s["title"] for s in before.get("optional", []) if s.get("command")],
                seen=bool(issues_before), seen_exact=bool(before.get("bug_issues_exact")),
                status_before=[i["status"] for i in issues_before], status_after=[i["status"] for i in issues_after],
                open_until_repaired=bool(issues_before) and all(i["status"] != "resolved" for i in issues_before)
                and bool(issues_after) and all(i["status"] == "resolved" for i in issues_after),
                first_title=first["title"] if first else None, first_cause=first["cause"] if first else None, hedged=first["hedged"] if first else None,
                first_rules=[x.split(":", 1)[0] for x in first["rules"]] if first else None, steps_before=len(before["steps"]),
                headline_before=before["headline"], headline_after=after["headline"], status_detail_after=after.get("status_detail"),
                saved_selection=before.get("saved_selection"), run_scope=before.get("run_scope"), tests_before=before.get("tests"),
                notes_after=[i.get("note") for i in issues_after if i.get("note")][:2], environment_advice_after=after["environment_advice"])
        rows.append(row)
    table[arm] = rows

for arm in ARMS:
    rows = table[arm]
    counted = [x for x in rows if x["reproduced"] and x["checked"]]
    n = len(rows)
    print(f"\n=== {arm}: {n} bugs selected; reproduced in this arm and checked by the product: {len(counted)}")
    for x in rows:
        if x not in counted:
            print(f"   NOT COUNTED {x['case']}: exit codes {x['exit_codes']}, checked {x['checked']}" + (f", selection refused: {x['selection_refused']}" if x["selection_refused"] else "")
                  + (f", THE PRODUCT RAISED AN EXCEPTION: {x['product_error']}" if x["product_error"] else ""))
    print(f"   {'bug':16}{'no env advice':14}{'seen':6}{'before -> after':40}first step (cause)")
    for x in counted:
        print(f"   {x['case']:16}{str(x['no_environment_advice']):14}{str(x['seen']):6}{(','.join(x['status_before']) or '-') + ' -> ' + (','.join(x['status_after']) or '-'):40}"
              f"{(x['first_title'] or '(no step)')[:64]} ({x['first_cause']}{', hedged' if x['hedged'] else ''}; {','.join(x['first_rules'] or [])})")
    print(f"   no environment advice among the steps to do: {sum(x['no_environment_advice'] for x in counted)} of {n}"
          + "".join(f"\n      with advice: {x['case']} {x['environment_advice']}" for x in counted if not x["no_environment_advice"]))
    print(f"   the product's check has an issue with the bug's test: {sum(x['seen'] for x in counted)} of {n} (by exact names only: {sum(x['seen_exact'] for x in counted)})")
    print(f"   open before the repair and resolved after it: {sum(x['open_until_repaired'] for x in counted)} of {n}")
    for x in counted:
        if x["seen"] and not x["open_until_repaired"]:
            print(f"      not: {x['case']} {x['status_before']} -> {x['status_after']}; patch touches test files: {x['patched_tests'] or 'no'}; {(x['notes_after'] or [''])[0][:150]}")
    stepped = [x for x in counted if x["first_title"]]
    code = [x for x in stepped if x["first_cause"] == CODE]
    other = [x for x in stepped if x["first_cause"] and x["first_cause"] != CODE]
    print(f"   first step names \"{CODE}\": {len(code)} of {n} ({sum(not x['hedged'] for x in code)} by a rule, {sum(bool(x['hedged']) for x in code)} hedged)")
    print(f"   first step names another cause: {len(other)} ({sum(not x['hedged'] for x in other)} NOT hedged, {sum(bool(x['hedged']) for x in other)} hedged)"
          + "".join(f"\n      {x['case']}: {x['first_cause']}{' (hedged)' if x['hedged'] else ' (NOT hedged)'} by {x['first_rules']}: {x['first_title'][:90]}" for x in other))
    print(f"   first step names no cause, or there is no step: {len(counted) - len(code) - len(other)}"
          + f" {dict(collections.Counter((x['first_title'] or '(no step)')[:60] for x in counted if x not in code and x not in other))}")
    print(f"   optional steps with a command: {sum(bool(x['optional_with_command']) for x in counted)} bugs")
    print(f"   by project, open-then-resolved: " + ", ".join(
        f"{p} {sum(x['open_until_repaired'] for x in counted if x['project'] == p)}/{sum(x['project'] == p for x in rows)}" for p in dict.fromkeys(x["project"] for x in rows)))
if out_json:
    out_json.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
