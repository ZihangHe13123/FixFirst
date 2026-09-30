"""Versioned records shared by all modules; unknown is never a successful check."""

from datetime import datetime, timezone
import hashlib
import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1


Tool = Literal[
    "environment", "project", "pip_check", "pip_install", "pytest", "pytest_run", "ruff", "version_search",
    "python_run", "unittest_run",
]
Goal = Literal["collect_tests", "check_style", "pass_tests", "run_project", "pass_unittest"]
GOAL_CHECKS = {"collect_tests": "pytest", "check_style": "ruff", "pass_tests": "pytest_run",
               "run_project": "python_run", "pass_unittest": "unittest_run"}
PROJECT_SCOPES = {
    "pytest": "collect:project",
    "ruff": "lint:project",
    "pytest_run": "tests:project",
}


class Execution(Record):
    kind: Literal["script", "module", "notebook", "unittest"] = "script"
    entry: str = Field(min_length=1, max_length=4096)
    args: list[str] = Field(default_factory=list, max_length=200)
    stdin: str = Field(default="", max_length=64_000)
    pattern: str = Field(default="test*.py", max_length=200)


def check_scope(session, tool):
    if tool not in ("python_run", "unittest_run"):
        return PROJECT_SCOPES.get(tool)
    payload = {"project": session.project_root,
               "execution": session.execution.model_dump() if session.execution else None}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
    return f"{tool}:{digest}"


class Run(Record):
    run_id: str = Field(default_factory=lambda: uid("run"))
    tool: Tool
    started_at: str = Field(default_factory=now)
    argv: list[str] = Field(default_factory=list)
    cwd: str = ""
    environment_id: str = "unknown"
    tool_version: str = "unknown"
    scope: str = "unknown"
    status: Literal["completed", "timeout", "cancelled", "launch_failed", "output_limit"] = (
        "completed"
    )
    source: Literal["executed", "imported"] = "executed"
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0
    truncated: bool = False
    # Coverage is earned by parsers and execution, not inferred from absence of errors.
    verified_pass: bool = False
    coverage_complete: bool = False
    notes: list[str] = Field(default_factory=list)
    records: list[dict] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    passed_nodes: list[str] = Field(default_factory=list)
    test_summary: dict[str, int] = Field(default_factory=dict)
    execution_kind: str = ""


class Event(Record):
    event_id: str = Field(default_factory=lambda: uid("event"))
    run_id: str
    tool: Tool
    stage: str
    kind: str
    message: str
    component: str = ""
    location: str = ""
    line: int = 1
    code: str = ""
    source_file: str = ""
    source_line: int | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class Issue(Record):
    issue_id: str
    fingerprint: str
    tool: Tool
    stage: str
    kind: str
    component: str = ""
    title: str
    event_ids: list[str]
    evidence_refs: list[str]
    member_keys: list[str]
    scope: str
    environment_id: str
    category: str = "other_unknown"
    # Root cause: from a diagnosis rule (evidence + knowledge) or, failing that, the model.
    diagnosis: str | None = None
    diagnosis_source: Literal["rule", "heuristic", "model"] | None = None
    diagnosis_rule: str | None = None
    prediction: str | None = None
    prediction_confidence: float | None = None
    prediction_note: str = ""
    group_score: float = 1
    status: Literal["open", "awaiting_verification", "resolved", "not_observed", "unknown"] = "open"
    first_seen: str = Field(default_factory=now)
    last_seen: str = Field(default_factory=now)
    note: str = ""
    targets: list[str] = Field(default_factory=list)
    # Whether a pass verified the original problem against the baseline tests (integrity.py).
    verification: Literal["comparable", "not_comparable"] | None = None


class Fact(Record):
    fact_id: str
    subject: str
    predicate: str
    value: str
    status: Literal["observed", "knowledge", "derived", "hypothesis"] = "observed"
    rule_id: str | None = None
    inputs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class Action(Record):
    action_id: str
    kind: Literal["inspect", "rerun", "manual_fix"]
    title: str
    explanation: str
    verification: str
    check: Tool | None = None
    issue_ids: list[str] = Field(default_factory=list)
    reason_refs: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    goal_impact: int = 0
    evidence_rank: int = 1
    cost: int = 1
    priority: int = 0
    targets: list[str] = Field(default_factory=list)
    cause: str | None = None
    rule_ids: list[str] = Field(default_factory=list)
    # A command the user can run themselves (argv); FixFirst never runs it.
    command: list[str] = Field(default_factory=list)


class Session(Record):
    session_id: str = Field(default_factory=lambda: uid("session"))
    name: str
    project_root: str
    target_python: str
    created_at: str = Field(default_factory=now)
    goal: Goal = "collect_tests"
    execution: Execution | None = None
    grouping: Literal["exact", "tfidf", "sbert"] = "tfidf"
    threshold: float = Field(default=0.82, ge=0, le=1)
    model_path: str | None = None
    use_classifier: bool = True
    sbert_model: str | None = None
    runs: list[Run] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)
    goal_status: Literal["unknown", "blocked", "achieved"] = "unknown"
    stopped: bool = False
    environment: dict = Field(default_factory=dict)
    # The tests and settings a verification is measured against, and the latest comparison (integrity.py).
    verification_baseline: dict = Field(default_factory=dict)
    baseline_check: dict = Field(default_factory=dict)
