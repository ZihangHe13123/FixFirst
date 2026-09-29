# Recorded runs, datasets and experiments

Everything here was produced by real executions on macOS (Apple Silicon), Python 3.12. Personal
paths are replaced. `playground/`, `demo/` and `execution-demo/` were re-recorded with version
0.5; `dependency-demo/` and `historical-regressions/` were recorded with 0.3, and replaying them
with 0.5 gives the same results. HTML reports are static and never run anything. Each report has its session
JSON and evidence-graph JSON next to it.

| Folder | What it is | Start with |
|---|---|---|
| `playground/` | Four faults, four root causes, fixed step by step; the best overview of the product | `01-first-scan.html` |
| `diagnosis-evaluation/` | The root-cause experiment: baselines, rules with/without the knowledge graph, decision tree, hybrid; two cross-validation protocols | `REPORT.md` |
| `diagnosis-dataset/` | 215 executed single-fault cases (5 templates × 43 scenarios) with labels; `environment.json` is the shared interpreter snapshot | `manifest.json` |
| `hard-dataset/` | 30 executed hard cases (5 templates × 6 scenarios): documented behaviour changes of installed libraries (NumPy 2, PyYAML 6, pydantic 2, Click 8.2) and a two-layer fault; never used to train the tree, but H07 and H08 were written after seeing them, so they are development data | `manifest.json` |
| `hard-evaluation/` | Diagnosis on the hard cases with the tree trained on the 215 cases; `before/` leaves out the heuristics H07 and H08, which were written after seeing these cases | `REPORT.md` |
| `demo/` | Import error + style finding: fixing style alone does not close the import issue | `01-failure.html` |
| `execution-demo/` | Failing tests: a selected-node pass, a skipped test that is *not* a fix, full recovery | `01-two-failures.html` |
| `dependency-demo/` | `pip check` passes but the project's declaration is not met | `01-broken.html` |
| `historical-regressions/` | Four upstream library defects replayed offline with official wheels | `REPORT.md` |
| `grouping-evaluation/` | Message grouping (exact vs TF-IDF) on the controlled datasets | `collection/REPORT.md` |
| `public-data/` | What PyDFix and BugsInPy contain and the parts FixFirst can use: 22 distinct PyDFix import errors, an index of 501 BugsInPy bugs | `README.md` |
| `dataset/`, `execution-dataset/` | The v0.1/v0.2 controlled datasets (used for grouping only) | `manifest.json` |

## Reproduce

```bash
.venv/bin/fixfirst dataset --suite diagnosis --output workbench/my-diagnosis        # ~2 minutes
.venv/bin/fixfirst evaluate workbench/my-diagnosis --output workbench/my-evaluation
.venv/bin/fixfirst evaluate examples/diagnosis-dataset --output workbench/re-evaluation  # no execution
.venv/bin/fixfirst dataset --suite hard --output workbench/my-hard                    # ~30 seconds
.venv/bin/fixfirst evaluate examples/hard-dataset --train examples/diagnosis-dataset --output workbench/hard-eval
.venv/bin/python scripts/record_playground.py --output workbench/my-playground
.venv/bin/fixfirst historical --assets examples/historical-regressions/assets --output workbench/my-replay
```

Library versions matter: the dataset was generated with the versions listed in
`diagnosis-dataset/manifest.json`. A different NumPy or scikit-learn may raise different errors,
and the generator rejects any case whose fault is not observed.

Generated fixture code is CC0-1.0. The wheels in `historical-regressions/assets/` keep their own
licences. None of these cases is a sample of naturally occurring failures; see the limitations
in each report.
