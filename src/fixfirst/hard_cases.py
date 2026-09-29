"""Hard cases: library behaviour changes and a two-layer fault, never used to train the tree.

In the main diagnosis dataset (diagnosis_cases.py) the error usually names the cause, and the
decision tree is trained on those cases. These scenarios are harder and are never used to train
the tree. Heuristics H07 and H08 were written after seeing them, so results on them are
development results, not held-out ones. Each uses a documented change in a library that is really
installed (NumPy 2, PyYAML 6, pydantic 2, Click 8.2) and raises no "name was removed" error,
or two faults where the second appears only after the first is fixed. None of them is in the
knowledge base. Like a real project, each declares the library with the lower bound its code
was written for (numpy>=1.21, PyYAML>=5.1, ...). Every added test checks a function's result,
so deleting the faulty code does not make it pass.
"""

import json
from pathlib import Path

from . import diagnosis_cases as dc

HARD_SCENARIOS: list[dc.Scenario] = []


def h(scenario_id, label, description):
    def register(function):
        HARD_SCENARIOS.append(dc.Scenario(scenario_id, label, False, description, function))
        return function

    return register


def add_check(p, name, body):
    """A test of one project function, appended to the template's test module."""
    p.add_test(f"def test_{name}():\n    from {p.t.module} import {name}\n\n{body}\n")


def declare(p, requirement):
    path = p.root / "requirements.txt"
    path.write_text(path.read_text(encoding="utf-8") + requirement + "\n", encoding="utf-8")


@h("vb_numpy_repr", "version_incompatibility",
   "NumPy 2 prints scalars as np.float64(...) (NEP 51), so a formatted summary changes")
def _(p):
    declare(p, "numpy>=1.21")
    p.imports(
        "import numpy as np\n\n\ndef describe(values):\n"
        "    return f\"max={np.max(np.asarray(values, dtype=float))!r}\"\n"
    )
    add_check(p, "describe", "    assert describe([1, 2]) == \"max=2.0\"")


@h("vb_numpy_promotion", "version_incompatibility",
   "NumPy 2 keeps float32 when a Python float is added (NEP 50), so json.dumps rejects the result")
def _(p):
    declare(p, "numpy>=1.21")
    p.imports(
        "import json\n\nimport numpy as np\n\n\ndef price_json(values):\n"
        "    return json.dumps({\"price\": np.float32(values[0]) + 0.5})\n"
    )
    add_check(p, "price_json", "    assert price_json([1]) == '{\"price\": 1.5}'")


@h("vb_yaml_loader", "version_incompatibility", "PyYAML 6.0 made the Loader argument of yaml.load required")
def _(p):
    declare(p, "PyYAML>=5.1")
    p.imports("import yaml\n\n\ndef load_settings(text):\n    return yaml.load(text)\n")
    add_check(p, "load_settings", "    assert load_settings(\"rate: 2\") == {\"rate\": 2}")


@h("vb_pydantic_coercion", "version_incompatibility",
   "pydantic 2 no longer turns numbers into strings for str fields")
def _(p):
    declare(p, "pydantic>=1.8")
    p.imports(
        "from pydantic import BaseModel\n\n\nclass Label(BaseModel):\n    code: str\n\n\n"
        "def label_code(value):\n    return Label(code=value).code\n"
    )
    add_check(p, "label_code", "    assert label_code(7) == \"7\"")


@h("vb_click_mix_stderr", "version_incompatibility", "Click 8.2 removed CliRunner's mix_stderr argument")
def _(p):
    declare(p, "click>=8.0")
    p.imports(
        "import click\nfrom click.testing import CliRunner\n\n\n@click.command()\ndef hello():\n"
        "    click.echo(\"hello\")\n\n\ndef run_hello():\n"
        "    return CliRunner(mix_stderr=False).invoke(hello).output\n"
    )
    add_check(p, "run_hello", "    assert run_hello() == \"hello\\n\"")


@h("ml_renamed_then_alias", "local_module",
   "Helper module renamed; once the import is fixed, a NumPy alias removed in 1.24 fails at run time")
def _(p):
    declare(p, "numpy>=1.21")
    (p.root / p.t.helper).rename(p.root / p.t.renamed)
    p.body("    import numpy\n    numpy.float(1)")


def build_dataset(output: Path, python: str | None = None) -> Path:
    manifest_path = dc.build_dataset(output, python, scenarios=HARD_SCENARIOS)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["suite"] = "hard"
    manifest["limitations"] = (
        "Hard cases, never used to train the decision tree: documented behaviour changes of "
        "installed libraries and one two-layer fault (labelled by the first layer), executed "
        "against real installed libraries. None is in the knowledge base. Heuristics H07 and H08 "
        "were written after seeing them, so results on these cases are development results, not "
        "held-out evidence."
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path
