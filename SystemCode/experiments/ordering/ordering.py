#!/usr/bin/env python3
"""B17: which problem a method picks first on the multi-fault cases M1 to M5. No model; real runs of generated projects.

    ordering.py OUT.json [--only CASE ...] [--methods NAME ...]

Run with the interpreter of a FixFirst checkout that has the packages the cases use. The replay is the product's
multi_cases.replay (docs/B4_SCENARIOS.md, section 2): check the project, let the method pick one open issue, apply
the reference repair of the fault behind it (nothing if there is none), repeat until every required fault is
repaired, at most ten steps. It is written out again here only to record, for FixFirst, what the plan showed at
each state. Methods:
  fixfirst            the issue of the first step of FixFirst's plan
  fixfirst-exact      the same with the session's grouping set to "exact"
  fixfirst-ungrouped  the same with grouping switched off (a threshold no pair of messages reaches)
  message_order, category_order   the product's two naive baselines
"""
import json
import sys
import tempfile
from pathlib import Path

from fixfirst import multi_cases as mc
from fixfirst import service

argv = sys.argv[1:]
out = Path(argv[0])


def values(name):
    found = []
    if name in argv:
        at = argv.index(name) + 1
        while at < len(argv) and not argv[at].startswith("--"):
            found.append(argv[at])
            at += 1
    return found


ORIGINAL = service.create_session
SETTINGS = {"fixfirst": {}, "fixfirst-exact": {"grouping": "exact"}, "fixfirst-ungrouped": {"threshold": 2.0},
            "message_order": {}, "category_order": {}}


def session_factory(settings):
    def create(project, python, name=None, goal="collect_tests", **more):
        session = ORIGINAL(project, python, name, goal=goal, **{**more, **{k: v for k, v in settings.items() if k == "grouping"}})
        if "threshold" in settings:
            session.threshold = settings["threshold"]
        return session
    return create


def first_step(session, issues):
    """The first action of the plan that is attached to an open issue, and that issue."""
    open_ids = {issue.issue_id: issue for issue in issues}
    for position, action in enumerate(session.actions):
        for issue_id in action.issue_ids:
            if issue_id in open_ids:
                return position, action, open_ids[issue_id]
    return None, None, None


def describe(action):
    if action is None:
        return None
    return {"kind": action.kind, "title": action.title, "cause": action.cause, "rule_ids": action.rule_ids,
            "command": action.command, "targets": action.targets, "instructions": action.instructions[:700],
            "explanation": action.explanation[:400]}


def replay(case, method, limit=10):
    python = sys.executable
    mc.create_session = session_factory(SETTINGS[method])
    required = {fault_id for fault_id, _ in case[2] if fault_id not in mc.OPTIONAL_FAULTS}
    repaired, steps = [], []
    while not required <= set(repaired) and len(steps) < limit:
        session, issues = mc.open_issues(case, repaired, python)
        step = {"repaired_before": list(repaired), "open_issues": len(issues), "open_issue_titles": [i.title for i in issues]}
        if method.startswith("fixfirst"):
            position, action, issue = first_step(session, issues)
            very_first = session.actions[0] if session.actions else None
            step.update({"actions_shown": len(session.actions), "position_of_the_step_taken": position,
                         "very_first_action": describe(very_first),
                         "very_first_action_has_an_open_issue": bool(very_first and set(very_first.issue_ids) & {i.issue_id for i in issues}),
                         "step_taken": describe(action),
                         "issue_cause_shown": getattr(issue, "diagnosis", None) if issue else None,
                         "issue_cause_source": getattr(issue, "diagnosis_source", None) if issue else None})
        else:
            issue = mc.BASELINES[method](session, issues)
        fault = mc.targeted(case, issue.title, repaired, python) if issue else None
        if fault:
            repaired.append(fault)
        step.update({"issue": issue.title if issue else None, "issue_tool": issue.tool if issue else None, "fault": fault})
        steps.append(step)
    with tempfile.TemporaryDirectory() as scratch:
        mc.build(case, Path(scratch) / "project", repaired)
        code, _ = mc.check_output(Path(scratch) / "project", python)
    return {"case": case[0], "template": case[1], "method": method, "steps": steps,
            "first_issue_right": bool(steps) and steps[0]["fault"] is not None,
            "wrong_issue_attempts": sum(step["fault"] is None for step in steps),
            "reached_goal": required <= set(repaired) and code == 0,
            "order": [step["fault"] for step in steps],
            "an_acceptable_order": tuple(step["fault"] for step in steps if step["fault"]) in set(mc.acceptable_orders(case))}


only, methods = values("--only"), values("--methods") or list(SETTINGS)
rows = []
for case in mc.CASES:
    if only and case[0] not in only:
        continue
    for method in methods:
        row = replay(case, method)
        rows.append(row)
        print(f"{row['case']} {method:18} first issue right {row['first_issue_right']!s:5} wrong-issue attempts {row['wrong_issue_attempts']} "
              f"reached goal {row['reached_goal']!s:5} order {row['order']}", flush=True)
        out.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
mc.create_session = ORIGINAL
