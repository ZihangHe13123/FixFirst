"""Independent synthetic regressions for grouped and stale tool-failure evidence."""

import json

import pytest

from fixfirst.engine import run as infer
from fixfirst.models import Issue, Run, Session
from fixfirst.parsers import parse
from fixfirst.reasoning import base_facts, rule_base
from fixfirst.runner import environment_id
from fixfirst.tool_compatibility import observations


ROOT = "/synthetic/project"
PYTHON = ROOT + "/.venv/bin/python"
IDENTITY = environment_id(PYTHON)
SITE = ROOT + "/.venv/lib/python3.12/site-packages"
STDLIB = "/synthetic/python/lib/python3.12"
REWRITER = SITE + "/_pytest/assertion/rewrite.py"
WARNING = "ast.Str is deprecated and will be removed in Python 3.14; use ast.Constant instead"
ENTITY = "tool-failure:pytest-ast-str"


def raw_failure(node, caller=REWRITER, message=WARNING, *, ast_frame=True):
    """Two actual-shaped probe records; no target code is imported or run."""
    frames = [{"file": caller, "line": 10, "function": "visit_Assert"}]
    if ast_frame:
        frames.append({"file": STDLIB + "/ast.py", "line": 20, "function": "__new__"})
    text = "Traceback (most recent call last):\n" + "".join(
        f'  File "{f["file"]}", line {f["line"]}, in {f["function"]}\n    call()\n' for f in frames
    ) + "DeprecationWarning: " + message
    return [
        {"type": "failure", "nodeid": node, "stage": "collect", "message": text},
        {"type": "exception", "nodeid": node, "stage": "collect",
         "exception_type": "DeprecationWarning", "exception_message": message,
         "source_file": frames[-1]["file"], "source_line": frames[-1]["line"],
         "traceback_frames": frames},
    ]


def saved_case(records, *, environment_after_failure=False, tool_version="6.2.5"):
    environment = {
        "python_version": "3.12.13",
        "packages": [{"name": "pytest", "version": "6.2.5", "requires": []},
                     {"name": "py", "version": "1.11.0", "requires": []}],
        "import_distributions": {"_pytest": ["pytest"], "py": ["py"]},
        "paths": {"purelib": SITE, "platlib": SITE, "stdlib": STDLIB},
        "stdlib_modules": ["ast"], "_run_id": "env", "_environment_id": IDENTITY,
    }
    env_run = Run(run_id="env", tool="environment", environment_id=IDENTITY,
                  scope="environment", cwd=ROOT, exit_code=0,
                  stdout=json.dumps({k: v for k, v in environment.items() if not k.startswith("_")}))
    failed_run = Run(run_id="failure", tool="pytest_run", environment_id=IDENTITY,
                     scope="tests:project", cwd=ROOT, exit_code=2,
                     records=records, tool_version=tool_version)
    project_run = Run(run_id="project", tool="project", environment_id=IDENTITY,
                      scope="declarations:project", cwd=ROOT, exit_code=0,
                      stdout=json.dumps({"environment_run_id": "env", "local_modules": [],
                                         "own_names": [], "declarations": []}))
    runs = ([failed_run, env_run, project_run] if environment_after_failure
            else [env_run, failed_run, project_run])
    session = Session(name="synthetic", project_root=ROOT, target_python=PYTHON,
                      goal="pass_tests", use_classifier=False, environment=environment, runs=runs)
    session.events = parse(failed_run)
    assert session.events and all(event.code == "DeprecationWarning" for event in session.events)
    issue = Issue(issue_id="issue", fingerprint="synthetic", tool="pytest_run", stage="collect",
                  kind="other_unknown", title="synthetic warning failure",
                  event_ids=[event.event_id for event in session.events],
                  evidence_refs=[ref for event in session.events for ref in event.evidence_refs],
                  member_keys=[], scope="tests:project", environment_id=IDENTITY)
    session.issues = [issue]
    return session, issue


def check_observation_and_rule(session, issue, expected):
    tool_facts, _ = observations(session, [issue])
    signatures = [f.value for f in tool_facts if f.predicate == "tool_failure_symptom"]
    facts, _ = base_facts(session, [issue])
    # Rule inference only: do not load or invoke the classifier.
    diagnoses = [f for f in infer(rule_base(), facts).facts
                 if f.subject == issue.issue_id and f.predicate == "diagnosis" and f.rule_id == "D50"]
    assert signatures == ([ENTITY] if expected else [])
    assert bool(diagnoses) is expected


@pytest.mark.parametrize("tool_version", ["6.2.5", "unknown"])
def test_single_matching_member_uses_its_own_failure_context(tool_version):
    session, issue = saved_case(raw_failure("first"), tool_version=tool_version)
    check_observation_and_rule(session, issue, True)


def test_multiple_members_with_the_same_independently_proven_mechanism_still_match():
    session, issue = saved_case(raw_failure("first") + raw_failure("second"))
    assert len(session.events) == 2
    check_observation_and_rule(session, issue, True)


def test_grouped_members_cannot_donate_signature_and_failing_tool_frame_to_each_other():
    project_warning = raw_failure("project", ROOT + "/mod.py")
    other_tool_warning = raw_failure("tool", REWRITER, "An unrelated deprecated helper", ast_frame=False)
    # Neither member proves this mechanism independently.
    for records in (project_warning, other_tool_warning):
        session, issue = saved_case(records)
        check_observation_and_rule(session, issue, False)
    # Combining the project's ast.Str warning with another member's tool frame
    # must not upgrade them into a certain D50 diagnosis.
    session, issue = saved_case(project_warning + other_tool_warning)
    check_observation_and_rule(session, issue, False)


def test_one_event_referencing_multiple_failures_cannot_bypass_member_isolation():
    session, issue = saved_case(
        raw_failure("project", ROOT + "/mod.py")
        + raw_failure("tool", REWRITER, "An unrelated deprecated helper", ast_frame=False))
    first, second = session.events
    first.evidence_refs = [*first.evidence_refs, *second.evidence_refs]
    session.events = [first]
    issue.event_ids = [first.event_id]
    issue.evidence_refs = list(first.evidence_refs)
    check_observation_and_rule(session, issue, False)


@pytest.mark.parametrize("tool_version", ["6.2.5", "8.3.5"])
def test_environment_refreshed_after_failure_cannot_supply_failure_version_context(tool_version):
    session, issue = saved_case(raw_failure("first"), environment_after_failure=True,
                               tool_version=tool_version)
    check_observation_and_rule(session, issue, False)


def test_known_recorded_runner_version_must_match_the_snapshot_even_before_failure():
    session, issue = saved_case(raw_failure("first"), tool_version="8.3.5")
    check_observation_and_rule(session, issue, False)
