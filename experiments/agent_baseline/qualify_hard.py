"""Qualify the hard instances and pick each scenario's formal and development instance. No model is involved.

An instance (a template with a hard scenario applied) qualifies when
  - its start is admitted: its tests and pytest settings differ from the healthy template by the check
    registered in hard_cases.toml and by nothing else;
  - its reference (the start with the registered repair; the healthy template for the scenario without
    a check) passes the whole suite with every test actually passing, the registered check included;
  - its start shows the registered fault: the check fails with the registered text and nothing else
    fails (without a check: the template's test module does not load because the renamed helper is
    missing, and nothing else is reported).
Both suites run as the grader runs them: sandboxed, offline, on a copy, in a clean environment.

Selection (the default): each scenario's templates are tried in the fixed order of hard_instances.py; the
first instance that qualifies is the formal one, the next that qualifies the development one, and the
scenario is done. A check that could not be completed (the sandbox or the harness failing, a suite stopped
at its time limit or ended by a signal, pytest's own internal or usage error: not the instance) is tried
once more and then counts as not qualified. Every attempt is recorded with its reason, its instance's
manifest and what the start's failures said in OUT/hard-selection.json, next to the code's and the
environment's identity. That file holds the registered repairs: keep it where no run can read it. It is
what agent_pilot.py --hard-selection takes; it must be made and committed before any model runs a hard
instance, and nothing in it depends on a model.

With --cases only the given instances are checked and OUT/hard-qualification.json is written: the check
to repeat for the selected instances when the harness or the environment has changed.

Usage:
  .venv/bin/python experiments/agent_baseline/qualify_hard.py --out ../agent-runs/hard
  .venv/bin/python experiments/agent_baseline/qualify_hard.py --out ../agent-runs/hard --cases flat-shop:vb_yaml_loader
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
from xml.etree.ElementTree import ParseError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_pilot as ap  # noqa: E402
import hard_instances as hi  # noqa: E402
import isolation as iso  # noqa: E402
import real_cases as rc  # noqa: E402


def qualify(ctx: ap.Context, template: str, scenario_id: str) -> dict:
    """One instance, checked once. `result` is qualified, not_qualified (with the reason) or not_checked
    (the check itself could not be completed)."""
    t, entry = hi.template(template), hi.load_registry()[scenario_id]
    try:
        instance = ap.hard_instance(ctx, t, scenario_id, {}, None)
    except Exception as error:  # building or grading broke: nothing is known about the instance
        return {"result": "not_checked", "reason": f"the instance could not be made: {type(error).__name__}: {error}"[:500]}
    record = {"digest": instance["digest"], "required_node": instance["required"], "manifest": instance.get("manifest")}
    if instance["end"] == "unsupported_case":
        return {**record, "result": "not_qualified", "reason": "not admitted: " + "; ".join(instance["problems"])[:500]}
    reference = instance["reference"] or {}
    if reference:
        record["reference"] = {"exit_code": reference.get("exit_code"), "outcomes": reference.get("outcomes")}
        interrupted = reference.get("not_completed") or hi.not_completed(reference.get("exit_code"), reference.get("stopped"))
        if interrupted:
            return {**record, "result": "not_checked",
                    "reason": f"the reference suite could not be completed: {interrupted}"[:500]}
    if instance["end"]:
        return {**record, "result": "not_qualified", "reason": "the reference: " + "; ".join(instance["problems"])[:500]}
    run = ap.Run(ctx, instance["start"].parent / "start-check", False, False, ap.PYTHON,
                 ap.interpreters(ap.PYTHON.parent.parent))
    try:
        shutil.copytree(instance["start"], run.project)
        suite = run.suite()
        said = hi.failures(run.folder / "grader" / "check-001" / "junit.xml")
    except (RuntimeError, OSError, subprocess.SubprocessError, ParseError) as error:
        return {**record, "result": "not_checked", "reason": f"the start's suite could not be run: {type(error).__name__}: {error}"[:500]}
    finally:
        run.end_processes("after the start's check")
    record["start"] = {"exit_code": suite["exit_code"], "outcomes": suite["outcomes"],
                       "said": {node: text.strip()[-3000:] for node, text in said.items()}}  # its end names the error
    interrupted = "; ".join(run.cleanup_problems) or hi.not_completed(suite["exit_code"], suite["stopped"])
    if interrupted:
        return {**record, "result": "not_checked", "reason": f"the start's suite could not be completed: {interrupted}"[:500]}
    problems = hi.start_problems(suite, said, t, entry)
    if problems:
        return {**record, "result": "not_qualified", "reason": "the start: " + "; ".join(problems)[:500]}
    return {**record, "result": "qualified", "reason": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, help="a folder outside the repository; never overwritten")
    parser.add_argument("--cases", nargs="*", default=[], help="template:scenario: only check these instances, select nothing")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    problem = ap.check_output_folder(out)
    if problem:
        parser.error(problem)
    try:
        registry = hi.load_registry()
        given = [(hi.template(spec.split(":")[0]).name, hi.scenario(spec.split(":")[1]).scenario_id)
                 for spec in args.cases if spec.count(":") == 1]
    except ValueError as error:
        parser.error(str(error))
    if len(given) != len(args.cases):
        parser.error("a case is template:scenario")
    name = "hard-qualification.json" if given else "hard-selection.json"
    if (out / name).exists():
        parser.error(f"{out / name} exists; a record is never overwritten")
    out.mkdir(parents=True, exist_ok=True)
    attempt, calls = iso.new_attempt(), []

    def check(template: str, scenario_id: str) -> dict:
        calls.append(None)  # every check has folders of its own, so that a second try starts clean
        ctx = ap.Context(out, "qualification", f"{attempt}-{len(calls):02d}", False,
                         denied=(Path(ap.HOME), out, ap.FIXFIRST, *iso.SYSTEM_TEMP))
        return qualify(ctx, template, scenario_id)

    git = lambda *command: subprocess.run(["git", *command], cwd=ap.FIXFIRST, capture_output=True, text=True).stdout  # noqa: E731
    record = {"made_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "attempt": attempt,
              "harness_commit": git("rev-parse", "HEAD").strip(),
              "uncommitted_changes": [line for line in git("status", "--porcelain", "--", "src",
                                                           "experiments/agent_baseline").splitlines() if line.strip()],
              "code": hi.code_identity(), "environment": hi.environment(ap.PYTHON), "registry": registry}
    if given:
        record["attempts"] = [{"scenario": scenario_id, "template": template, **check(template, scenario_id)}
                              for template, scenario_id in given]
    else:
        record.update(hi.select(check))
    text = ap.redact(json.dumps(record, indent=1, ensure_ascii=False), out)
    (out / name).write_text(text + "\n", encoding="utf-8")
    print("| Scenario | Candidate | Template | Attempt | Result | Role | Reason |\n|---|---|---|---|---|---|---|")
    for item in record["attempts"]:
        print(f"| {item['scenario']} | {item.get('candidate', '–')} | {item['template']} | {item.get('attempt', 1)} "
              f"| {item['result']} | {item.get('role', '–')} | {item.get('counts_as') or item['reason'] or '–'} |")
    if not given:
        print(f"\nFormal instances per template: {record['formal_templates']}")
        for title, key in (("Cannot run (no template qualified)", "cannot_run"),
                           ("Without a development instance", "without_development_instance")):
            if record[key]:
                print(f"{title}: {', '.join(record[key])}")
    print(f"\nWritten: {name} (sha256 {rc.file_hash(out / name)})")


if __name__ == "__main__":
    main()
