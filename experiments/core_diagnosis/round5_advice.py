"""Execute the recorded manual interpretations of round-five system advice.

This is an audit of seven specific suggestions, NOT an autonomous repair agent or
an automatic first-step accuracy metric. The interpretation was written after
reading the output and project. The generic Click suggestion remains unexecuted.
The pre-registered reference repairs in round5_cases.py are not read here.
"""

import argparse
import json
from pathlib import Path

from round5_cases import CASES, copy, pytest, sha, tests_of


INTERPRETATIONS = {
    "numpy_copy_false": {
        "title": "Use numpy.asarray",
        "reason": "Apply the suggested asarray conversion, retaining dtype and expected shares.",
        "edits": [("app.py", "np.array(values, dtype=float, copy=False)", "np.asarray(values, dtype=float)")],
    },
    "pydantic_optional_required": {
        "title": "Give the optional model field an explicit None default",
        "reason": "Locate email in the model and give it the stated None default. The displayed failure "
                  "location is the constructor call, not the field declaration; this requires source inspection.",
        "edits": [("app.py", "email: Optional[str]\n", "email: Optional[str] = None\n")],
    },
    "numpy_solve_batched_vector": {
        "title": "Pass the batch of right-hand vectors as explicit column vectors",
        "reason": "Apply the exact column-vector expression to the observed solve call.",
        "edits": [("app.py", "np.linalg.solve(a, b)", "np.linalg.solve(a, b[..., None])[..., 0]")],
    },
    "stdlib_safeconfigparser_removed": {
        "title": "Replace configparser.SafeConfigParser",
        "reason": "Replace the removed name in both import and constructor, as suggested.",
        "edits": [("settings.py", "SafeConfigParser", "ConfigParser")],
    },
    "yaml_tab_indentation": {
        "title": "Correct the YAML syntax",
        "reason": "Read the reported tab-token error, and replace indentation tabs with two spaces. "
                  "The advice names the syntax class but does not generate this edit.",
        "edits": [("settings.yaml", "\t", "  ")],
    },
    "numpy_reshape_off_by_one": {
        "title": "Correct the reshape dimensions",
        "reason": "Inspect the requested (2,4) shape for six elements and the expected 2-by-3 grid. "
                  "Remove the extra one from width. The advice does not generate this edit.",
        "edits": [("app.py", "(height, width + 1)", "(height, width)")],
    },
    "pydantic_field_name_typo": {
        "title": "Check the missing model field against the keys actually supplied",
        "reason": "Compare the missing name field with the supplied nmae keyword in the call. "
                  "The exact spelling correction comes from reading the error and source; the system "
                  "suggests this comparison but does not generate the edit.",
        "edits": [("app.py", "nmae=", "name=")],
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tag", required=True, help="an existing diagnose tag; execution folders must be new")
    args = parser.parse_args()
    out = args.out.resolve()
    diagnosis = json.loads((out / f"diagnose-{args.tag}.json").read_text(encoding="utf-8"))
    report = {"kind": "manual_interpretation_execution", "implementation": diagnosis["implementation"],
              "limits": __doc__, "cases": []}
    for result in diagnosis["cases"]:
        case = next(c for c in CASES if c["name"] == result["name"])
        steps = result["steps"]
        row = {"name": case["name"], "actual_step": steps[0] if steps else None,
               "executed": False, "automated_fix": False}
        interpretation = INTERPRETATIONS.get(case["name"])
        if case["kind"] == "control":
            row["result"] = "healthy_no_step" if not steps and result["status"] == "done" else "control_failed"
        elif interpretation is None:
            row["result"] = "generic_advice_not_counted_as_a_repair"
        elif not steps or not steps[0]["title"].startswith(interpretation["title"]):
            row["result"] = "different_advice_not_executed"
        else:
            folder = out / case["name"]
            project = copy(case, folder / "project", folder / f"manual-{args.tag}")
            before = {n: sha(project / n) for n in tests_of(case)}
            for filename, old, new in interpretation["edits"]:
                path = project / filename
                text = path.read_text(encoding="utf-8")
                if old not in text:
                    raise ValueError(f"manual edit no longer matches {case['name']}/{filename}")
                path.write_text(text.replace(old, new), encoding="utf-8")
            run = pytest(project, folder / "venv")
            same = before == {n: sha(project / n) for n in tests_of(case)}
            row.update(executed=True, interpretation=interpretation, tests_unchanged=same,
                       test_sha256=before, exit_code=run["exit_code"], output=run["output"],
                       result="passes_original_tests" if run["exit_code"] == 0 and same else "failed")
        report["cases"].append(row)
        print(row["name"], row["result"], flush=True)
    text = json.dumps(report, ensure_ascii=False, indent=2).replace(str(out), "<runs>")
    with (out / f"advice-{args.tag}.json").open("x", encoding="utf-8") as stream:
        stream.write(text + "\n")


if __name__ == "__main__":
    main()
