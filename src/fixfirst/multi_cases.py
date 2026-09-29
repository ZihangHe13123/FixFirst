"""Multi-fault cases for the next-step ordering evaluation (task B17, docs/B4_SCENARIOS.md).

Each case applies several faults to one diagnosis template. Some faults hide others: a
collection error stops the tests that would show a run-time fault, and an earlier failing import
stops a later one. A case records, for every fault, its root cause, which faults hide it, its
allowed repair and the text that shows it is observable. Acceptable repair orders are all orders
consistent with "hidden by"; there is no single right answer.

Building the suite checks every case by real runs: the faults that should be observable are,
the hidden ones are not, repairing each layer reveals exactly the next one, and repairing every
required fault makes the tests pass. A case that behaves otherwise is rejected.
"""

from dataclasses import dataclass
from itertools import permutations
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from . import diagnosis_cases as dc
from .models import now
from .service import create_session, scan

CHECKS = [*dc.CHECKS, "ruff"]
OPTIONAL = "optional"
OPTIONAL_FAULTS = {"lint_unused"}


@dataclass(frozen=True)
class Fault:
    fault_id: str
    label: str  # root cause, or "optional" for a style finding the goal does not need
    stage: str  # collection, run or lint
    shows: str  # regular expression found in the check output while the fault is observable
    repair: str  # the allowed repair, in words


def replace(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise ValueError(f"{path.name} does not contain {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Each maker takes a dc.Project and returns (fault, inject, repair).

def renamed_helper(p):
    fault = Fault("renamed_helper", "local_module", "collection",
                  f"No module named '{re.escape(p.t.helper_module)}'", "move the helper module back, or import its new name")
    return (fault, lambda: (p.root / p.t.helper).rename(p.root / p.t.renamed),
            lambda: (p.root / p.t.renamed).rename(p.root / p.t.helper))


def stdlib_removed(p):
    fault = Fault("stdlib_removed", "version_incompatibility", "collection", r"No module named 'imp'",
                  "remove the import of imp (importlib replaces it)")
    return fault, lambda: p.imports("import imp"), lambda: replace(p.root / p.t.service, "import imp\n", "")


def private_moved(p):
    old, new = "from sklearn.utils import _print_elapsed_time", "from sklearn.utils._user_interface import _print_elapsed_time"
    fault = Fault("private_moved", "version_incompatibility", "collection", r"cannot import name '_print_elapsed_time'",
                  "import _print_elapsed_time from sklearn.utils._user_interface")
    return fault, lambda: p.imports(old), lambda: replace(p.root / p.t.service, old, new)


def numpy_alias(p):
    fault = Fault("numpy_alias", "version_incompatibility", "run", r"has no attribute 'float'", "use the builtin float")
    return (fault, lambda: p.body("    import numpy as np\n    np.float(1)"),
            lambda: replace(p.root / p.t.service, "np.float(1)", "float(1)"))


def env_missing(p):
    variable = p.t.env
    fault = Fault("env_missing", "config_missing", "run", f"KeyError: '{variable}'",
                  "provide a default for the environment variable")
    return (fault, lambda: p.body(f'    import os\n    os.environ["{variable}"]'),
            lambda: replace(p.root / p.t.service, f'os.environ["{variable}"]', f'os.environ.get("{variable}", "demo")'))


def total_off_by_one(p):
    right, wrong = "        return sum(self.values)\n", "        return sum(self.values) + 1\n"
    fault = Fault("total_off_by_one", "code_defect", "run", r"4 (==|!=) 3", "restore sum(self.values)")
    return (fault, lambda: replace(p.root / p.t.service, right, wrong),
            lambda: replace(p.root / p.t.service, wrong, right))


def lint_unused(p):
    fault = Fault("lint_unused", OPTIONAL, "lint", r"`json` imported but unused",
                  "remove the unused import (not needed for the goal)")
    return fault, lambda: p.imports("import json"), lambda: replace(p.root / p.t.service, "import json\n", "")


FAULTS = {f.__name__: f for f in (renamed_helper, stdlib_removed, private_moved, numpy_alias, env_missing,
                                  total_off_by_one, lint_unused)}

# (case id, template, [(fault, faults that hide it)])
CASES = [
    ("M1", "flat-shop", [("renamed_helper", ()), ("numpy_alias", ("renamed_helper",))]),
    ("M2", "src-billing", [("private_moved", ()), ("env_missing", ("private_moved",)),
                           ("total_off_by_one", ("private_moved",))]),
    ("M3", "pkg-inventory", [("stdlib_removed", ()), ("lint_unused", ())]),
    ("M4", "unittest-grades", [("env_missing", ()), ("total_off_by_one", ())]),
    ("M5", "fixture-orders", [("renamed_helper", ()), ("private_moved", ("renamed_helper",)),
                              ("numpy_alias", ("private_moved",))]),
]


def acceptable_orders(case) -> list[tuple[str, ...]]:
    """Every order of the required faults in which no fault comes before one that hides it."""
    _, _, faults = case
    hidden_by = {name: set(by) for name, by in faults if name not in OPTIONAL_FAULTS}
    return [
        order for order in permutations(hidden_by)
        if all(hidden_by[name] <= set(order[:position]) for position, name in enumerate(order))
    ]


def apply(case, root: Path):
    """Build the case's project in root; return {fault id: (fault, repair, hidden by)}."""
    _, template_name, faults = case
    template = next(t for t in dc.TEMPLATES if t.name == template_name)
    dc.build_template(root, template)
    project = dc.Project(root, template, dc.TEMPLATES.index(template))
    applied = {}
    for name, hidden_by in faults:
        fault, inject, repair = FAULTS[name](project)
        inject()
        applied[fault.fault_id] = (fault, repair, tuple(hidden_by))
    return applied


def check_output(root: Path, python: str) -> tuple[int, str]:
    """What a user sees: the test run and Ruff's findings."""
    tests = subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=root,
                           capture_output=True, text=True, errors="replace", timeout=600)
    lint = subprocess.run([python, "-m", "ruff", "check", "--no-cache", "."], cwd=root,
                          capture_output=True, text=True, errors="replace", timeout=120)
    return tests.returncode, tests.stdout + tests.stderr + lint.stdout + lint.stderr


def validate(case, root: Path, python: str | None = None) -> list[list[str]]:
    """Repair layer by layer and check what is observable; return the layers in order."""
    python = python or sys.executable
    applied = apply(case, root)
    required = {k: v for k, v in applied.items() if v[0].label != OPTIONAL}
    repaired, layers = set(), []
    while True:
        code, output = check_output(root, python)
        for fault_id, (fault, _, hidden_by) in applied.items():
            seen = bool(re.search(fault.shows, output))
            expected = fault_id not in repaired and set(hidden_by) <= repaired
            if seen != expected:
                state = "observable" if seen else "not observable"
                raise ValueError(f"{case[0]}: {fault_id} is {state} after repairing {sorted(repaired)}")
        layer = [k for k, (_, _, hidden_by) in required.items() if k not in repaired and set(hidden_by) <= repaired]
        if not layer:
            if code != 0:
                raise ValueError(f"{case[0]}: tests still fail after every required repair")
            return layers
        layers.append(layer)
        for fault_id in layer:
            required[fault_id][1]()
            repaired.add(fault_id)


def build_dataset(output: Path, python: str | None = None) -> Path:
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError("Dataset directory already exists; choose a new --output")
    python = python or sys.executable
    output.mkdir(parents=True)
    started = time.monotonic()
    manifest = {
        "schema_version": 1, "suite": "multi", "created_at": now(), "python": sys.version.split()[0],
        "license": "CC0-1.0 for generated fixture code", "definitions": "docs/B4_SCENARIOS.md",
        "cases": [], "rejected": [],
        "limitations": "Generated projects with two or three injected faults each, for the next-step ordering "
                       "evaluation only; they are not a sample of naturally occurring failures.",
    }
    try:
        for case in CASES:
            case_id = f"{case[0]}-{case[1]}"
            try:
                with tempfile.TemporaryDirectory() as scratch:
                    layers = validate(case, Path(scratch) / "project", python)
            except (ValueError, subprocess.TimeoutExpired) as error:
                manifest["rejected"].append({"case_id": case_id, "reason": str(error)})
                print(f"  {case_id}: rejected ({error})", flush=True)
                continue
            project = output / "projects" / case_id
            applied = apply(case, project)
            session = create_session(project, python, case_id, goal="pass_tests")
            scan(session, CHECKS)
            stored, environment = dc.portable(session, project)
            shared = output / "environment.json"
            if not shared.exists():
                dc.write(shared, json.dumps(environment, ensure_ascii=False, indent=1))
            row = {
                "case_id": case_id, "template": case[1],
                "faults": [{"id": f.fault_id, "label": f.label, "stage": f.stage, "shows": f.shows,
                            "repair": f.repair, "hidden_by": list(hidden_by)}
                           for f, _, hidden_by in applied.values()],
                "acceptable_orders": [list(order) for order in acceptable_orders(case)],
                "layers": layers,
                "session": stored,
            }
            with (output / "cases.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            manifest["cases"].append({"case_id": case_id, "faults": [f["id"] for f in row["faults"]],
                                      "layers": layers, "acceptable_orders": row["acceptable_orders"]})
            print(f"  {case_id}: layers {layers}", flush=True)
    finally:
        manifest["seconds"] = round(time.monotonic() - started, 1)
        dc.write(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return output / "manifest.json"
