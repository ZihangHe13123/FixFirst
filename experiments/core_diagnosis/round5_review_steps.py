"""Claude's interpreted execution of FixFirst's first steps at Codex's round 5 head (2026-09-30).

For each of the nine round 5 cases and two review probes, the edit below is what a reader would do
after reading FixFirst's actual first step at 35c9246, with the source of each piece of the edit.
It is applied to a fresh copy and the unchanged tests are run with the case's fixed environment.
This is interpreted execution, not an automatic repair rate, and not the reference fix.

Grades: "complete" = the step gives the place and the concrete change; "partial" = the right cause
and kind of change, but the place or value must be found in the error text or the tests;
"generic" = an inspection step, the edit comes from the error text alone.

  python experiments/core_diagnosis/round5_review_steps.py --runs RUNS --tag TAG
"""

import argparse
import json
from pathlib import Path
import shutil

import round5_cases as rc

STEPS = [
    {"case": "numpy_copy_false", "grade": "complete",
     "edits": [("app.py", "np.array(values, dtype=float, copy=False)", "np.asarray(values, dtype=float)")],
     "from": "Step text: replace numpy.array(values, copy=False, ...) with numpy.asarray(values, ...), keep the "
             "dtype; place app.py:6."},
    {"case": "pydantic_optional_required", "grade": "partial",
     "edits": [("app.py", "    email: Optional[str]\n", "    email: Optional[str] = None\n")],
     "from": "Step text: add = None to the missing Optional field in the model declaration. The place shown is "
             "the call app.py:12; the field name comes from the error ('email Field required') and its line "
             "(app.py:8) from reading the model. The text's example 'email' is a fixed template example."},
    {"case": "numpy_solve_batched_vector", "grade": "complete",
     "edits": [("app.py", "np.linalg.solve(a, b).tolist()", "np.linalg.solve(a, b[..., None])[..., 0].tolist()")],
     "from": "Step text: replace numpy.linalg.solve(a, b) with numpy.linalg.solve(a, b[..., None])[..., 0]; "
             "place app.py:8."},
    {"case": "stdlib_safeconfigparser_removed", "grade": "complete",
     "edits": [("settings.py", "SafeConfigParser", "ConfigParser")],
     "from": "Step text: change the code to use configparser.ConfigParser instead of SafeConfigParser; place "
             "settings.py:1. Applied to every use in settings.py (the import and line 5)."},
    {"case": "stdlib_safeconfigparser_removed", "variant": "import line only", "grade": "complete",
     "edits": [("settings.py", "from configparser import SafeConfigParser", "from configparser import ConfigParser")],
     "from": "Reading only the place shown (settings.py:1): the constructor on line 5 is left as it was."},
    {"case": "yaml_tab_indentation", "grade": "partial",
     "edits": [("settings.yaml", "\t", "  ")],
     "from": "Step text: correct the indentation at the parser's marked line and column. The place shown is the "
             "load call app.py:8; settings.yaml line 3 column 1 and the tab come from the error mark."},
    {"case": "numpy_reshape_off_by_one", "grade": "partial",
     "edits": [("app.py", "(height, width + 1)", "(height, width)")],
     "from": "Step text: the shape must hold the array's size; adjust the dimensions to the required result; "
             "place app.py:6. The value (2, 3) comes from the error (size 6) and the test's expected grid."},
    {"case": "click_option_typo", "grade": "generic",
     "edits": [("cli.py", "nmae", "name")],
     "from": "Step text only says to compare the assertion's expected and actual values at test_cli.py:8. The "
             "misspelt option comes from the assertion message ('No such option: --name Did you mean --nmae?')."},
    {"case": "pydantic_field_name_typo", "grade": "generic",
     "edits": [("app.py", "nmae=", "name=")],
     "from": "Step text only says to inspect the exception, at app.py:10 (the right line). The keyword comes "
             "from the error (name missing, input {'nmae': 'Ada', ...})."},
]

# Grades that changed with a later head's first-step text (the edits and their execution are the same).
REGRADE = {
    "codex-ba52e22": {
        "pydantic_field_name_typo": ("partial", "Step text (H12): compare the missing field with the keys supplied at "
                                     "app.py:10 and check for a misspelt key. The key itself comes from the error."),
        "stdlib_safeconfigparser_removed": ("complete", "Step text now says to update the import and every "
                                            "SafeConfigParser constructor or reference; place settings.py:1."),
    },
}

PROBE_STEPS = [
    {"probe": "optional_swapped_valid_key", "env": "pydantic_optional_required/venv",
     "edits": [("app.py", "    email: Optional[str]\n", "    email: Optional[str] = None\n")],
     "from": "FixFirst's first step: give the missing Optional field (email) an explicit None default."},
]


def apply(project: Path, edits) -> None:
    for name, old, new in edits:
        text = (project / name).read_text(encoding="utf-8")
        assert old in text, (project, name, old)
        (project / name).write_text(text.replace(old, new), encoding="utf-8")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--cases-only", action="store_true", help="skip the probe steps (a 35c9246 finding)")
    args = parser.parse_args(argv)
    runs = args.runs.resolve()
    results = []
    for step in STEPS:
        case = next(c for c in rc.CASES if c["name"] == step["case"])
        folder = runs / case["name"]
        work = folder / f"interpreted-{args.tag}" / step.get("variant", "main").replace(" ", "-")
        shutil.copytree(folder / "project", work)
        tests = rc.tests_of(case)
        before = {n: rc.sha(work / n) for n in tests}
        apply(work, step["edits"])
        run = rc.pytest(work, folder / "venv")
        grade, source = REGRADE.get(args.tag, {}).get(case["name"], (step["grade"], step["from"]))
        if step.get("variant"):
            grade, source = step["grade"], step["from"]
        results.append({"case": case["name"], "variant": step.get("variant"), "grade": grade,
                        "from": source, "edits": step["edits"], "tests_exit": run["exit_code"],
                        "target_error_left": bool(case["error"]) and case["error"] in run["output"],
                        "tests_unchanged": before == {n: rc.sha(work / n) for n in tests},
                        "tail": run["output"][-400:]})
        print(json.dumps({k: results[-1][k] for k in ("case", "variant", "grade", "tests_exit",
                                                      "target_error_left", "tests_unchanged")}), flush=True)
    for step in [] if args.cases_only else PROBE_STEPS:
        source = runs / f"review-{args.tag}" / step["probe"] / "project"
        work = runs / f"review-{args.tag}" / step["probe"] / "interpreted"
        shutil.copytree(source, work)
        apply(work, step["edits"])
        run = rc.pytest(work, runs / step["env"])
        results.append({"probe": step["probe"], "from": step["from"], "edits": step["edits"],
                        "tests_exit": run["exit_code"], "tail": run["output"][-400:]})
        print(json.dumps({"probe": step["probe"], "tests_exit": run["exit_code"],
                          "tail": run["output"][-160:]}), flush=True)
    (runs / f"interpreted-{args.tag}.json").write_text(
        json.dumps(results, indent=1, ensure_ascii=False).replace(str(runs), "<runs>") + "\n")


if __name__ == "__main__":
    main()
