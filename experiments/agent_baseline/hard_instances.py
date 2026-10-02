"""Hard scenarios (src/fixfirst/hard_cases.py) as agent tasks: which tests a scenario may add, what a run
is graded against, what makes an instance the same instance, and which template each scenario uses.

An instance is one template with one hard scenario applied. Five of the six scenarios add a project
function and append one test of its result to the template's test module, so the healthy template cannot
be their reference: it has neither. Their reference is the start plus a repair written beforehand.

Admission. hard_cases.toml is the harness's own whitelist. A scenario may differ from the healthy
template in tests and pytest settings by exactly one thing: its registered check, appended to the
template's test module (the healthy module, a blank line, the check, byte for byte). Any other difference
(another test file, conftest.py, a pytest setting, a changed or extra test) makes the instance
unsupported. The check itself must be one plain test function with a new name, no decorators and no
arguments; that is looked at as well, but the byte comparison is what decides.

Reference. The start with the registered repair applied to a separate copy (code only; a repair that
touches a test or a setting is refused); for the scenario without a check, the healthy template. The
reference must pass cleanly and every one of its tests must actually pass, the registered check included.
During a run the start's tests and settings are the baseline that must not change, as for every case.

Identity. An instance is identified by the digest of its manifest: the registration, the appended check,
every file of the start and of the reference, the tests and settings, the generator's and the harness's
code (by content, so that committing a record does not change it), the interpreter with its installed
distributions, and how the suite is graded. The reference outcome is cached under that digest and a run
copies the start whose files the manifest lists.

Qualification and selection. An instance qualifies when it is admitted, its reference passes as above and
its start shows the registered fault and nothing else (the check failing with the registered text while
every other test passes; without a check, the template's test module failing to load for the renamed
helper, as the only thing reported). A suite that did not run to a verdict (stopped, ended by a signal,
pytest's own error) says nothing about the instance. Each scenario has the five templates in a fixed
order, the templates sorted by name and rotated by the scenario's place among the sorted scenarios. Going
through them, the first that qualifies is the formal instance and the next that qualifies the development
one; then the scenario is done. A check that could not be completed is tried once more and then counts as
not qualified. Nothing here looks at a model's results.
"""

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import tomllib
from xml.etree import ElementTree

from fixfirst import diagnosis_cases as dc
from fixfirst import hard_cases as hc

import real_cases as rc

HERE = Path(__file__).resolve().parent
REGISTRY_FILE = HERE / "hard_cases.toml"
ENTRY_KEYS = {"check", "check_body", "fails_with", "repair"}
CODE_FILES = ("agent_pilot.py", "real_cases.py", "isolation.py", "hard_instances.py", "hard_cases.toml",
              "qualify_hard.py")
GENERATOR_FILES = ("diagnosis_cases.py", "hard_cases.py")
GRADING = "python -m pytest -q -p no:cacheprovider --junitxml=REPORT: the whole suite, offline, on a copy, in a clean environment"
ROLES = ("formal", "development")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_registry(path: Path = REGISTRY_FILE) -> dict:
    """The registered hard scenarios. Every hard scenario of the generator must be registered and nothing
    else may be: a scenario the harness does not know cannot be admitted, and a stale entry is a mistake."""
    registry = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    known = {scenario.scenario_id for scenario in hc.HARD_SCENARIOS}
    if set(registry) != known:
        raise ValueError(f"{Path(path).name} must register exactly the hard scenarios: not registered "
                         f"{sorted(known - set(registry))}, unknown {sorted(set(registry) - known)}")
    for name, entry in registry.items():
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise ValueError(f"{name}: an entry has exactly {', '.join(sorted(ENTRY_KEYS))}")
        check, body, fails, repair = entry["check"], entry["check_body"], entry["fails_with"], entry["repair"]
        if not all(isinstance(value, str) for value in (check, body, fails)) or not fails.strip():
            raise ValueError(f"{name}: check, check_body and fails_with are texts, and fails_with is not empty")
        if check and not check.isidentifier():
            raise ValueError(f"{name}: check must be the name of a function, not {check!r}")
        pairs = isinstance(repair, list) and all(
            isinstance(pair, list) and len(pair) == 2 and all(isinstance(side, str) and side for side in pair)
            and pair[0] != pair[1] for pair in repair)
        if not pairs or bool(check) != bool(body.strip()) or bool(check) != bool(repair):
            raise ValueError(f"{name}: a scenario with a check has its body and a repair of [old, new] pairs; "
                             "one without has neither")
    return registry


def template(name: str) -> dc.Template:
    found = [t for t in dc.TEMPLATES if t.name == name]
    if not found:
        raise ValueError(f"unknown template {name!r}")
    return found[0]


def scenario(name: str) -> dc.Scenario:
    found = [s for s in hc.HARD_SCENARIOS if s.scenario_id == name]
    if not found:
        raise ValueError(f"unknown hard scenario {name!r}")
    return found[0]


def hard_scenarios() -> list[str]:
    return sorted(s.scenario_id for s in hc.HARD_SCENARIOS)


def candidates() -> dict:
    """Each scenario's templates in the order they are tried: the templates sorted by name, starting at
    the scenario's place among the sorted scenarios and going round once."""
    names = sorted(t.name for t in dc.TEMPLATES)
    return {scenario_id: [names[(index + step) % len(names)] for step in range(len(names))]
            for index, scenario_id in enumerate(hard_scenarios())}


def appended_check(t: dc.Template, entry: dict) -> str | None:
    """The one test the scenario may append to the template's test module, as the generator writes it."""
    if not entry["check"]:
        return None
    return f"def test_{entry['check']}():\n    from {t.module} import {entry['check']}\n\n{entry['check_body']}\n"


def required_node(t: dc.Template, entry: dict) -> str | None:
    """The appended check as pytest's JUnit report names it."""
    if not entry["check"]:
        return None
    return f"{t.test.removesuffix('.py').replace('/', '.')}::test_{entry['check']}"


def build(folder: Path, t: dc.Template, s: dc.Scenario) -> dict:
    """The healthy template and the start (the template with the scenario applied), each in its own folder."""
    pristine, start = folder / "pristine", folder / "start"
    dc.build_template(pristine, t)
    shutil.copytree(pristine, start)
    s.apply(dc.Project(start, t, dc.TEMPLATES.index(t)))
    return {"pristine": pristine, "start": start}


def check_shape(healthy: str, addition: str, name: str) -> list[str]:
    """What the byte comparison does not say by itself: the registered check is one plain test function,
    and its name is not one the healthy test module already uses."""
    try:
        new, old = ast.parse(addition), ast.parse(healthy)
    except SyntaxError as error:
        return [f"the test module or the registered check does not parse: {error.msg}"]
    plain = (len(new.body) == 1 and isinstance(new.body[0], ast.FunctionDef) and new.body[0].name == name
             and not new.body[0].decorator_list and ast.dump(new.body[0].args) == ast.dump(ast.parse("def f(): pass").body[0].args))
    problems = [] if plain else [f"the registered check is not one plain function {name}() without decorators or arguments"]
    taken = set()
    for node in ast.walk(old):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            taken.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            taken.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            taken.add(node.id)
    if name in taken:
        problems.append(f"the healthy test module already uses the name {name}")
    return problems


def admit(pristine: Path, start: Path, t: dc.Template, entry: dict) -> list[str]:
    """Why the start may not be used; empty when it may. Against the healthy template its tests and pytest
    settings differ by the registered check and by nothing else."""
    allowed = {t.test} if entry["check"] else set()
    other = [key for key in rc.changed(rc.integrity(pristine), rc.integrity(start)) if key not in allowed]
    problems = [f"the scenario changes tests or pytest settings beyond its registered check: {', '.join(other)}"] if other else []
    if not entry["check"]:
        return problems
    addition = appended_check(t, entry)
    healthy = (pristine / t.test).read_bytes()
    if (start / t.test).read_bytes() != healthy + b"\n\n" + addition.encode("utf-8"):
        problems.append(f"{t.test} is not the healthy test module followed by exactly the registered check")
    return problems + check_shape(healthy.decode("utf-8"), addition, f"test_{entry['check']}")


def make_reference(dest: Path, pristine: Path, start: Path, t: dc.Template, entry: dict) -> list[str]:
    """The reference copy at dest: the start with the registered repair, or the healthy template for a
    scenario without a check. Returns why it could not be made; a repair never touches a test."""
    if not entry["check"]:
        shutil.copytree(pristine, dest)
        return []
    shutil.copytree(start, dest)
    path = dest / t.service
    text = path.read_text(encoding="utf-8")
    for old, new in entry["repair"]:
        if text.count(old) != 1:
            return [f"the registered repair does not apply: {old!r} occurs {text.count(old)} times in {t.service}"]
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    if rc.integrity(dest) != rc.integrity(start):
        return ["the registered repair changes tests or pytest settings"]
    return []


def tree(folder: Path) -> dict:
    """Every file below folder with the digest of its content."""
    return {path.relative_to(folder).as_posix(): rc.file_hash(path) for path in rc._walk(folder)}


def environment(python: Path) -> dict:
    """The interpreter the generated cases run with and its installed distributions, read from their
    metadata (nothing is run). Names and versions only: no path, so that the same environment in another
    folder is the same environment."""
    venv, found = python.parent.parent, set()
    for site in sorted(venv.glob("lib/python*/site-packages")) + sorted(venv.glob("Lib/site-packages")):
        for info in sorted(site.glob("*.dist-info")) + sorted(site.glob("*.egg-info")):
            headers = rc._headers(info / ("METADATA" if info.suffix == ".dist-info" else "PKG-INFO"))
            if headers.get("Name"):
                found.add(f"{rc.canonical(headers['Name'])}=={headers.get('Version', '')}")
    record = rc.venv_record(venv)
    listed = sorted(found)
    return {"python": record["version"], "interpreter": Path(os.path.realpath(record["home"])).parent.name,
            "distributions": listed, "sha256": sha256("\n".join(listed))}


def code_identity() -> dict:
    """The code that makes and grades an instance, by content: the generator and the harness."""
    generator = Path(dc.__file__).resolve().parent
    return {**{f"fixfirst/{name}": rc.file_hash(generator / name) for name in GENERATOR_FILES},
            **{f"agent_baseline/{name}": rc.file_hash(HERE / name) for name in CODE_FILES}}


def manifest(t: dc.Template, scenario_id: str, entry: dict, start: Path, reference: Path, env: dict, code: dict) -> dict:
    """What an instance is. Its digest is the instance's identity: the cache key of its reference outcome,
    and what a frozen selection compares."""
    addition = appended_check(t, entry)
    return {"template": t.name, "scenario": scenario_id, "registration": entry,
            "appended_check": None if addition is None else {"file": t.test, "node": required_node(t, entry),
                                                             "sha256": sha256(addition)},
            "start": tree(start), "reference": tree(reference), "tests_and_settings": rc.integrity(start),
            "code": code, "environment": {"python": env["python"], "interpreter": env["interpreter"],
                                          "distributions_sha256": env["sha256"]},
            "grading": GRADING}


def digest(data: dict) -> str:
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False))


def reference_problems(reference: dict, t: dc.Template, entry: dict) -> list[str]:
    """A hard instance's reference grades only if it passed cleanly and every test actually passed, the
    registered check among them (a skipped or expected-failure check proves nothing)."""
    problems = rc.validate_reference(reference)
    outcomes = reference.get("outcomes") or {}
    node = required_node(t, entry)
    if node and node not in outcomes:
        problems.append(f"the registered check {node} was not run in the reference")
    not_passed = sorted(name for name, outcome in outcomes.items() if outcome != "passed")
    if not_passed:
        problems.append(f"{len(not_passed)} tests did not actually pass in the reference, e.g. {not_passed[0]} "
                        f"({outcomes[not_passed[0]]})")
    return problems


def not_completed(exit_code, stopped) -> str | None:
    """Why a suite's result says nothing about the instance, or None when it ran to a verdict: it was
    stopped at its time limit, ended by a signal, gave no exit code, or pytest itself failed (internal or
    usage error). pytest's other codes are verdicts: 1 for failing tests, 2 also for a test module that
    does not load (the registered start of the scenario without a check), 5 for no tests."""
    if stopped or exit_code == 124:
        return "the suite was stopped at its time limit"
    if type(exit_code) is not int:
        return "the suite gave no exit code"
    if exit_code < 0:
        return f"the suite was ended by signal {-exit_code}"
    if exit_code in (3, 4):
        return f"pytest exited with {exit_code} ({rc.EXIT_CODES[exit_code]})"
    return None


def failures(report: Path) -> dict:
    """What each failed or errored test said, from pytest's JUnit report: its message and its text."""
    found = {}
    data = rc.read_regular(report, 256 << 20) if report.exists() else None
    if data is None:
        return found
    for case in ElementTree.fromstring(data).iter("testcase"):
        for child in case:
            if child.tag in ("failure", "error"):
                node = f"{case.get('classname', '')}::{case.get('name', '')}"
                found[node] = f"{child.get('message') or ''}\n{child.text or ''}"
    return found


def start_problems(suite: dict, said: dict, t: dc.Template, entry: dict) -> list[str]:
    """Why the start does not show the registered fault; empty when it does. With a check: the check fails
    with the registered text and every other test passes, so nothing else is broken. Without one: the
    template's test module fails to load because the renamed helper is missing, and that loading error is
    the only thing the suite reports (a second error, related or not, is not the registered start). A
    start that passes, or fails for another reason (a library that is not installed, say), is not it."""
    outcomes, expected = suite.get("outcomes") or {}, entry["fails_with"]
    node = required_node(t, entry)
    if node:
        if outcomes.get(node) not in ("failed", "error"):
            return [f"the registered check {node} is {outcomes.get(node, 'not run')} at the start, not failing"]
        if expected not in said.get(node, ""):
            return [f"the registered check fails for another reason than {expected!r}: {said.get(node, '').strip()[:200]}"]
        others = sorted(name for name, outcome in outcomes.items() if name != node and outcome != "passed")
        return [f"other tests do not pass at the start, e.g. {others[0]} ({outcomes[others[0]]})"] if others else []
    module = t.test.removesuffix(".py").replace("/", ".")
    loading, wanted = f"::{module}", f"{expected} '{t.helper_module}'"
    if outcomes.get(loading) not in ("failed", "error") or wanted not in said.get(loading, ""):
        shown = (said.get(loading) or next(iter(said.values()), suite.get("summary") or "nothing failed")).strip()[:200]
        return [f"the test module {module} does not fail to load with {wanted!r}: {shown}"]
    others = sorted(name for name in outcomes if name != loading)
    return [f"the start shows more than that loading error, e.g. {others[0]} ({outcomes[others[0]]})"] if others else []


def select(qualify, order: dict | None = None) -> dict:
    """The scan that picks each scenario's instances. `qualify(template, scenario)` checks one instance
    and returns {"result": "qualified" | "not_qualified" | "not_checked", "reason": ..., "digest": ...}.
    In a scenario's candidate order the first qualified instance is the formal one and the next qualified
    the development one, so the two always differ; then the scan of that scenario stops. A check that could
    not be completed is tried once more, then counts as not qualified. Every attempt is recorded."""
    order = candidates() if order is None else order
    attempts, selection = [], {}
    for scenario_id, names in order.items():
        chosen = dict.fromkeys(ROLES)
        for number, name in enumerate(names, start=1):
            for attempt in (1, 2):
                outcome = dict(qualify(name, scenario_id))
                if outcome.get("result") not in ("qualified", "not_qualified", "not_checked"):
                    raise ValueError(f"a qualification result must be qualified, not_qualified or not_checked: {outcome!r}")
                record = {"scenario": scenario_id, "template": name, "candidate": number, "attempt": attempt, **outcome}
                attempts.append(record)
                if outcome["result"] != "not_checked":
                    break
            if outcome["result"] == "not_checked":
                record["counts_as"] = "not_qualified: the check could not be completed in two attempts"
            if outcome["result"] == "qualified":
                role = ROLES[0] if chosen[ROLES[0]] is None else ROLES[1]
                chosen[role] = {"template": name, "candidate": number, "digest": outcome.get("digest")}
                record["role"] = role
                if role == ROLES[1]:
                    break
        selection[scenario_id] = chosen
    formal = [chosen["formal"]["template"] for chosen in selection.values() if chosen["formal"]]
    return {"candidates": order, "attempts": attempts, "selection": selection,
            "formal_templates": {name: formal.count(name) for name in sorted(set(formal))},
            "cannot_run": sorted(name for name, chosen in selection.items() if chosen["formal"] is None),
            "without_development_instance": sorted(name for name, chosen in selection.items()
                                                   if chosen["formal"] and chosen["development"] is None)}


def selected(selection: dict, role: str) -> dict:
    """{template:scenario: digest} of a frozen selection's instances for one role."""
    if role not in ROLES:
        raise ValueError(f"the role is one of {', '.join(ROLES)}, not {role!r}")
    chosen = {}
    for scenario_id, roles in (selection.get("selection") or {}).items():
        instance = (roles or {}).get(role)
        if instance:
            chosen[f"{instance['template']}:{scenario_id}"] = instance["digest"]
    return chosen
