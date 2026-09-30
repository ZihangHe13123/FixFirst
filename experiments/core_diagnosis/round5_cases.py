"""Round 5 development cases (Claude, 2026-09-30): errors that look like the wrong kind of cause.

Ordinary code or input errors raised inside a library that was upgraded past the project's declared
minimum, real version changes whose error looks like bad input, and a healthy control. Every case is
a new small project with its own interpreter and pinned dependencies. Its label, the error it must
show, what a usable first step must do and a reference fix were written here before FixFirst was
run on any case. Reference fixes change application code or data only, never a test.

The counterfactual environment shows the label is not a guess: a version change passes on the
older release (or Python) with the same code; an ordinary error fails there too.

This is development material, not a held-out set and not a human gold standard.

  python experiments/core_diagnosis/round5_cases.py build --out RUNS
  python experiments/core_diagnosis/round5_cases.py reference --out RUNS
  python experiments/core_diagnosis/round5_cases.py diagnose --out RUNS --tag before [--model TREE]
  python experiments/core_diagnosis/round5_cases.py first-step --out RUNS --tag before

RUNS must be outside any project (pytest looks for settings in parent folders).
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

TEST = "pytest>=8,<9"

CASES = [
    {
        "name": "numpy_copy_false",
        "kind": "positive",
        "label": "version_incompatibility",
        "python": "3.12", "install": ["numpy==2.2.6"], "old": ["numpy==1.26.4"],
        "files": {
            "requirements.txt": "numpy>=1.21\n",
            "app.py": "import numpy as np\n\n\ndef shares(values):\n"
                      "    \"\"\"Each value as a share of the total.\"\"\"\n"
                      "    data = np.array(values, dtype=float, copy=False)\n"
                      "    return (data / data.sum()).tolist()\n",
            "test_app.py": "from app import shares\n\n\ndef test_shares():\n"
                           "    assert shares([1, 1, 2]) == [0.25, 0.25, 0.5]\n",
        },
        "error": "Unable to avoid copy while creating an array as requested",
        "fix": [("app.py", "np.array(values, dtype=float, copy=False)", "np.asarray(values, dtype=float)")],
        "first_step": "Point at app.py:6 and replace np.array(..., copy=False) with np.asarray(...) "
                      "(or allow a copy); pinning numpy<2 also works but keeps the old API.",
        "why": "NumPy 2.0 made copy=False mean 'never copy' and raise; 1.x copied when needed "
               "(numpy_2_0_migration_guide, copy keyword).",
    },
    {
        "name": "pydantic_optional_required",
        "kind": "positive",
        "label": "version_incompatibility",
        "python": "3.12", "install": ["pydantic==2.11.9"], "old": ["pydantic==1.10.22"],
        "files": {
            "requirements.txt": "pydantic>=1.8\n",
            "app.py": "from typing import Optional\n\nfrom pydantic import BaseModel\n\n\n"
                      "class Contact(BaseModel):\n    name: str\n    email: Optional[str]\n\n\n"
                      "def load(record):\n    return Contact(**record)\n",
            "test_app.py": "from app import load\n\n\ndef test_email_is_optional():\n"
                           "    assert load({\"name\": \"Ada\"}).email is None\n",
        },
        "error": "Field required",
        "fix": [("app.py", "email: Optional[str]\n", "email: Optional[str] = None\n")],
        "first_step": "Point at the model field in app.py:8 and give the Optional field a default "
                      "(= None); pinning pydantic<2 also works. Asking the caller to send email is wrong.",
        "why": "Pydantic V2: an Optional[T] field without a default is required; V1 implied None "
               "(migration guide, required/optional fields).",
    },
    {
        "name": "numpy_solve_batched_vector",
        "kind": "positive",
        "label": "version_incompatibility",
        "python": "3.12", "install": ["numpy==2.2.6"], "old": ["numpy==1.26.4"],
        "files": {
            "requirements.txt": "numpy>=1.21\n",
            "app.py": "import numpy as np\n\n\ndef solve_all(matrices, vectors):\n"
                      "    \"\"\"Solve A x = b for each pair.\"\"\"\n"
                      "    a = np.asarray(matrices, dtype=float)\n"
                      "    b = np.asarray(vectors, dtype=float)\n"
                      "    return np.linalg.solve(a, b).tolist()\n",
            "test_app.py": "from app import solve_all\n\n\ndef test_solve_all():\n"
                           "    matrices = [[[2, 0], [0, 2]], [[4, 0], [0, 4]], [[1, 0], [0, 1]]]\n"
                           "    vectors = [[2, 4], [8, 4], [3, 5]]\n"
                           "    assert solve_all(matrices, vectors) == [[1.0, 2.0], [2.0, 1.0], [3.0, 5.0]]\n",
        },
        "error": "mismatch in its core dimension",
        "fix": [("app.py", "np.linalg.solve(a, b).tolist()", "np.linalg.solve(a, b[..., None])[..., 0].tolist()")],
        "first_step": "Point at app.py:8 and pass b as a stack of column vectors (b[..., None], then "
                      "[..., 0]); pinning numpy<2 also works. 'Fix the input shapes' alone is not enough.",
        "why": "NumPy 2.0: linalg.solve treats b as a stack of vectors only when it is 1-D; 1.x did so "
               "whenever b.ndim == a.ndim - 1 (numpy.linalg.solve, 'Changed in version 2.0').",
    },
    {
        "name": "stdlib_safeconfigparser_removed",
        "kind": "positive",
        "label": "version_incompatibility",
        "python": "3.12", "install": [], "old": [], "old_python": "3.11",
        "files": {
            "settings.py": "from configparser import SafeConfigParser\n\n\ndef read_settings(path):\n"
                           "    parser = SafeConfigParser()\n    parser.read(path)\n"
                           "    return dict(parser[\"app\"])\n",
            "app.ini": "[app]\nname = demo\nretries = 3\n",
            "test_settings.py": "from pathlib import Path\n\nfrom settings import read_settings\n\n\n"
                                "def test_read_settings():\n"
                                "    values = read_settings(Path(__file__).with_name(\"app.ini\"))\n"
                                "    assert values == {\"name\": \"demo\", \"retries\": \"3\"}\n",
        },
        "error": "cannot import name 'SafeConfigParser'",
        "fix": [("settings.py", "SafeConfigParser", "ConfigParser")],
        "first_step": "Say that Python 3.12 removed configparser.SafeConfigParser and replace it with "
                      "ConfigParser in settings.py (or run Python 3.11). Installing a package is wrong.",
        "why": "Python 3.12 removed the SafeConfigParser alias, deprecated since 3.2 (What's New 3.12).",
    },
    {
        "name": "yaml_tab_indentation",
        "kind": "counterexample",
        "label": "code_defect", "also_correct": ["config_missing"],
        "python": "3.12", "install": ["PyYAML==6.0.2"], "old": None,
        "files": {
            "requirements.txt": "PyYAML>=5.1\n",
            "settings.yaml": "name: demo\nlimits:\n\tretries: 3\n\ttimeout: 10\n",
            "app.py": "from pathlib import Path\n\nimport yaml\n\n\ndef load_settings():\n"
                      "    with open(Path(__file__).with_name(\"settings.yaml\"), encoding=\"utf-8\") as stream:\n"
                      "        return yaml.safe_load(stream)\n",
            "test_app.py": "from app import load_settings\n\n\ndef test_limits():\n"
                           "    assert load_settings()[\"limits\"] == {\"retries\": 3, \"timeout\": 10}\n",
        },
        "error": "found character '\\t' that cannot start any token",
        "fix": [("settings.yaml", "\t", "  ")],
        "first_step": "Point at settings.yaml line 3 and replace the tab indentation with spaces. "
                      "Any YAML release rejects tabs here, so a version change or pin is wrong.",
        "why": "YAML forbids tabs for indentation; the data file is wrong, not PyYAML.",
    },
    {
        "name": "numpy_reshape_off_by_one",
        "kind": "counterexample",
        "label": "code_defect",
        "python": "3.12", "install": ["numpy==2.2.6"], "old": ["numpy==1.26.4"],
        "files": {
            "requirements.txt": "numpy>=1.21\n",
            "app.py": "import numpy as np\n\n\ndef to_grid(values, width):\n"
                      "    height = len(values) // width\n"
                      "    return np.reshape(values, (height, width + 1)).tolist()\n",
            "test_app.py": "from app import to_grid\n\n\ndef test_to_grid():\n"
                           "    assert to_grid([1, 2, 3, 4, 5, 6], 3) == [[1, 2, 3], [4, 5, 6]]\n",
        },
        "error": "cannot reshape array of size 6 into shape (2,4)",
        "fix": [("app.py", "(height, width + 1)", "(height, width)")],
        "first_step": "Point at app.py:6 and fix the target shape (width, not width + 1). NumPy 1.x "
                      "raises the same error, so a version change or pin is wrong.",
        "why": "An off-by-one in project code; the library only reports it.",
    },
    {
        "name": "click_option_typo",
        "kind": "counterexample",
        "label": "code_defect",
        "python": "3.12", "install": ["click==8.2.1"], "old": ["click==7.1.2"],
        "files": {
            "requirements.txt": "click>=7.0\n",
            "cli.py": "import click\n\n\n@click.command()\n"
                      "@click.option(\"--nmae\", default=\"world\", help=\"Who to greet.\")\n"
                      "def hello(nmae):\n    click.echo(f\"Hello {nmae}!\")\n",
            "test_cli.py": "from click.testing import CliRunner\n\nfrom cli import hello\n\n\n"
                           "def test_hello_by_name():\n"
                           "    result = CliRunner().invoke(hello, [\"--name\", \"Ada\"])\n"
                           "    assert result.exit_code == 0, result.output\n"
                           "    assert result.output == \"Hello Ada!\\n\"\n",
        },
        "error": "No such option: --name",
        "fix": [("cli.py", "nmae", "name")],
        "first_step": "Point at the option declared in cli.py:5 and rename --nmae to --name (and the "
                      "parameter). Click 7 rejects it the same way, so a version change is wrong.",
        "why": "A misspelt option in project code; the test uses the documented name.",
    },
    {
        "name": "pydantic_field_name_typo",
        "kind": "counterexample",
        "label": "code_defect",
        "python": "3.12", "install": ["pydantic==2.11.9"], "old": ["pydantic==1.10.22"],
        "files": {
            "requirements.txt": "pydantic>=1.8\n",
            "app.py": "from pydantic import BaseModel\n\n\nclass Contact(BaseModel):\n"
                      "    name: str\n    email: str = \"\"\n\n\ndef from_form(form):\n"
                      "    return Contact(nmae=form[\"name\"], email=form.get(\"email\", \"\"))\n",
            "test_app.py": "from app import from_form\n\n\ndef test_from_form():\n"
                           "    assert from_form({\"name\": \"Ada\"}).name == \"Ada\"\n",
        },
        "error": "Field required",
        "fix": [("app.py", "nmae=", "name=")],
        "first_step": "Point at the call in app.py:10 and fix the keyword nmae= to name=. Pydantic 1 "
                      "fails the same way, so a version change or pin is wrong.",
        "why": "A misspelt keyword in project code; the extra key is ignored and name is missing. "
               "Same message as pydantic_optional_required, different cause.",
    },
    {
        "name": "healthy_deprecations",
        "kind": "control",
        "label": None,
        "python": "3.12", "install": ["numpy==2.2.6", "pydantic==2.11.9"], "old": None,
        "files": {
            "requirements.txt": "numpy>=1.21\npydantic>=1.8\n",
            "app.py": "import numpy as np\nfrom pydantic import BaseModel\n\n\nclass Reading(BaseModel):\n"
                      "    t: float\n    value: float\n\n\ndef area(readings):\n"
                      "    t = np.array([r.t for r in readings])\n"
                      "    v = np.array([r.value for r in readings])\n"
                      "    return float(np.trapz(v, t))\n\n\ndef export(reading):\n"
                      "    return reading.dict()\n",
            "test_app.py": "from app import Reading, area, export\n\n\ndef test_area():\n"
                           "    points = [Reading(t=0, value=0), Reading(t=1, value=2), Reading(t=2, value=2)]\n"
                           "    assert area(points) == 3.0\n\n\ndef test_export():\n"
                           "    assert export(Reading(t=1, value=2)) == {\"t\": 1.0, \"value\": 2.0}\n",
        },
        "error": None,
        "fix": [],
        "first_step": "No required step: the tests pass. Deprecation warnings (np.trapz, .dict()) may "
                      "be listed as optional, never as a failure or a required version change.",
        "why": "Deprecated but working APIs on NumPy 2.2 and Pydantic 2.11.",
    },
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_env() -> dict:
    return {k: v for k, v in os.environ.items()
            if k not in ("PYTHONPATH", "PYTEST_ADDOPTS", "VIRTUAL_ENV", "PYTHONHOME")}


def write_project(case: dict, folder: Path) -> None:
    folder.mkdir(parents=True)
    for name, text in case["files"].items():
        (folder / name).write_text(text, encoding="utf-8")


def make_venv(folder: Path, python: str, packages: list) -> dict:
    # Seeded with pip, like `python -m venv`: FixFirst runs pip check in it.
    subprocess.run(["uv", "venv", "-q", "--seed", "--python", python, str(folder)], check=True)
    subprocess.run(["uv", "pip", "install", "-q", "--python", str(folder / "bin/python"), TEST, *packages],
                   check=True)
    freeze = subprocess.run(["uv", "pip", "freeze", "--python", str(folder / "bin/python")],
                            capture_output=True, text=True, check=True).stdout
    version = subprocess.run([str(folder / "bin/python"), "-c", "import sys; print(sys.version.split()[0])"],
                             capture_output=True, text=True, check=True).stdout.strip()
    return {"python": version, "packages": sorted(freeze.split())}


def pytest(folder: Path, venv: Path) -> dict:
    run = subprocess.run([str(venv / "bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                         cwd=folder, capture_output=True, text=True, env=clean_env(), timeout=300)
    return {"exit_code": run.returncode, "output": run.stdout[-4000:] + run.stderr[-2000:]}


def tests_of(case: dict) -> list:
    return sorted(n for n in case["files"] if Path(n).name.startswith("test_"))


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=False)
    manifest = []
    for case in CASES:
        folder = out / case["name"]
        write_project(case, folder / "project")
        envs = {"current": make_venv(folder / "venv", case["python"], case["install"])}
        if case.get("old") is not None:
            envs["old"] = make_venv(folder / "venv-old", case.get("old_python", case["python"]), case["old"])
        manifest.append({"name": case["name"], "environments": envs,
                         "files": {n: sha(folder / "project" / n) for n in case["files"]}})
        print(case["name"], json.dumps(envs), flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")


def copy(case: dict, source: Path, target: Path) -> Path:
    shutil.copytree(source, target)
    return target


def reference(out: Path) -> None:
    results = []
    for case in CASES:
        folder = out / case["name"]
        work = folder / "reference"
        if work.exists():
            raise SystemExit(f"{work} exists; use a new RUNS folder")
        original = pytest(copy(case, folder / "project", work / "original"), folder / "venv")
        row = {"name": case["name"], "kind": case["kind"], "label": case["label"],
               "original_exit": original["exit_code"],
               "error_seen": bool(case["error"]) and case["error"] in original["output"]}
        if case["kind"] == "control":
            row["ok"] = original["exit_code"] == 0
        else:
            fixed = copy(case, folder / "project", work / "fixed")
            before = {n: sha(fixed / n) for n in tests_of(case)}
            for name, old, new in case["fix"]:
                text = (fixed / name).read_text(encoding="utf-8")
                assert old in text, (case["name"], name, old)
                (fixed / name).write_text(text.replace(old, new), encoding="utf-8")
            after = pytest(fixed, folder / "venv")
            row.update(fixed_exit=after["exit_code"],
                       tests_unchanged=before == {n: sha(fixed / n) for n in tests_of(case)})
            ok = original["exit_code"] != 0 and row["error_seen"] and after["exit_code"] == 0 and row["tests_unchanged"]
            if case.get("old") is not None:
                older = pytest(copy(case, folder / "project", work / "original-old"), folder / "venv-old")
                row["old_exit"] = older["exit_code"]
                row["old_same_error"] = case["error"] in older["output"]
                if case["kind"] == "positive":
                    ok = ok and older["exit_code"] == 0
                else:
                    ok = ok and older["exit_code"] != 0
                row["old_output_tail"] = older["output"][-600:]
            row["ok"] = ok
        row["original_output_tail"] = original["output"][-900:]
        results.append(row)
        print(json.dumps({k: row[k] for k in row if not k.endswith("_tail")}), flush=True)
    (out / "reference.json").write_text(json.dumps(results, indent=1) + "\n")


def implementation() -> dict:
    import fixfirst

    root = Path(fixfirst.__file__).resolve().parents[2]
    files = sorted((root / "src/fixfirst").glob("*.py")) + sorted((root / "src/fixfirst/knowledge").glob("*"))
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "src"],
                           capture_output=True, text=True).stdout.strip()
    return {"head": head, "src_uncommitted": bool(dirty),
            "source_sha256": hashlib.sha256(b"".join(sha(p).encode() for p in files if p.is_file())).hexdigest(),
            "python": sys.version.split()[0],
            "scikit-learn": importlib.metadata.version("scikit-learn")}


def diagnose(out: Path, tag: str, model: Path | None) -> None:
    from fixfirst.evidence import issue_evidence
    from fixfirst.service import create_session, scan
    from fixfirst.workspace import build_view

    record = {"implementation": implementation(), "model": str(model) if model else "bundled",
              "model_sha256": sha(model) if model else None, "cases": []}
    for case in CASES:
        folder = out / case["name"]
        work = folder / f"diagnose-{tag}"
        project = copy(case, folder / "project", work / "project")
        session = create_session(project, folder / "venv/bin/python", goal="pass_tests",
                                 model=str(model) if model else None)
        scan(session)
        view = build_view(session)
        issues = [i for i in session.issues if i.status in ("open", "awaiting_verification")]
        row = {
            "name": case["name"], "kind": case["kind"], "label": case["label"],
            "status": view["status"].get("kind"), "headline": view["status"].get("headline"),
            "issues": [{"tool": i.tool, "title": i.title[:200], "diagnosis": i.diagnosis,
                        "rule": i.diagnosis_rule, "source": i.diagnosis_source,
                        # What the tree alone suggested, whatever the rules then concluded.
                        "tree": i.prediction, "tree_confidence": i.prediction_confidence,
                        "evidence": {k: v for k, v in issue_evidence(session, i).items()
                                     if k in ("exception", "raised_in", "where", "source_location", "library")}}
                       for i in issues],
            "steps": [{k: step.get(k) for k in ("title", "explanation", "command", "cause", "possible",
                                                "where", "rules", "suspected", "gather", "search")}
                      for step in view["steps"][:3]],
            "optional": [step["title"] for step in view["optional"]],
        }
        target = [i for i in issues if i.tool == "pytest_run"]
        row["first_diagnosis"] = target[0].diagnosis if target else None
        row["first_step"] = row["steps"][0]["title"] if row["steps"] else None
        record["cases"].append(row)
        print(json.dumps({k: row[k] for k in ("name", "label", "first_diagnosis", "first_step", "status")}),
              flush=True)
    text = json.dumps(record, indent=1, ensure_ascii=False).replace(str(out), "<runs>")
    (out / f"diagnose-{tag}.json").write_text(text + "\n")


def first_step(out: Path, tag: str) -> None:
    """Run the system's first step as given, when it is a command, in a fresh copy of the environment
    and project (the case environment itself is never changed), then the same tests."""
    import shlex

    record = json.loads((out / f"diagnose-{tag}.json").read_text())
    results = []
    for row in record["cases"]:
        case = next(c for c in CASES if c["name"] == row["name"])
        step = row["steps"][0] if row["steps"] else None
        entry = {"name": case["name"], "first_step": step and step["title"], "command": step and step["command"]}
        if not step or not step["command"]:
            entry["executed"] = False
            results.append(entry)
            continue
        folder = out / case["name"]
        venv = folder / f"venv-step-{tag}"
        if venv.exists():
            raise SystemExit(f"{venv} exists; use a new tag")
        make_venv(venv, case["python"], case["install"])
        argv = shlex.split(step["command"].replace("<runs>", str(out)))
        argv[0] = str(venv / "bin/python")  # the same command, in the copy
        install = subprocess.run(argv, capture_output=True, text=True, env=clean_env(), timeout=600)
        tests = pytest(copy(case, folder / "project", folder / f"step-{tag}"), venv)
        entry.update(executed=True, command_exit=install.returncode,
                     command_tail=(install.stdout + install.stderr)[-700:],
                     tests_exit=tests["exit_code"],
                     target_error_left=bool(case["error"]) and case["error"] in tests["output"],
                     tests_tail=tests["output"][-500:])
        results.append(entry)
        print(json.dumps({k: entry[k] for k in entry if not k.endswith("_tail")}), flush=True)
    (out / f"first-step-{tag}.json").write_text(json.dumps(results, indent=1).replace(str(out), "<runs>") + "\n")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("build", "reference", "diagnose", "first-step", "list"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--tag", default="before")
    parser.add_argument("--model", type=Path, help="a decision tree to use instead of the bundled one")
    args = parser.parse_args(argv)
    if args.command == "list":
        for case in CASES:
            print(f"{case['name']:34} {case['kind']:15} {case['label']}")
        return
    out = args.out.resolve()
    if args.command == "build":
        build(out)
    elif args.command == "reference":
        reference(out)
    elif args.command == "first-step":
        first_step(out, args.tag)
    else:
        diagnose(out, args.tag, args.model.resolve() if args.model else None)


if __name__ == "__main__":
    main()
