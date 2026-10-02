# v0.8 toolchain development comparison

These are A2-informed, generated development mechanisms with provisional author
labels, not independent project generalization or repair-success results.
The new knowledge entries being researched separately are not included.

## Captured product diagnoses, fixed 44-feature model

The generator ran the same project inputs in exact isolated environment locks
against the frozen production source and the integrated rule/parser candidate.
Both used the unchanged packaged 44-feature tree, SHA-256
`4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3`.
No classifier was fitted for this table. A case is correct only when all its
open pytest issues name its expected root-cause category.

| Mechanism family | Cases | Frozen source correct | Candidate correct |
|---|---:|---:|---:|
| Test-tool failures and near counterexamples | 43 | 10 | 43 |
| Django configuration and initialization | 30 | 25 | 30 |
| Older libraries | 10 | 10 | 10 |
| Missing/removed pkg_resources | 20 | 10 | 10 |
| **Total** | **103** | **55 (53.4%)** | **93 (90.3%)** |

The paired summary is [captured-comparison.json](captured-comparison.json).
Its script checks equal scenario definitions, complete environment identities,
project-file hashes, labels, exclusion sets and the frozen model digest. It
retains per-case predictions and hashes for the input manifests and audit files.
This measures root-cause classification, not the specificity or success of the
recommended first step. A reference passing after replacing an environment is
not proof that the product's actual recommendation repaired the old environment.

### Denominators and parser coverage

There are 22 registered scenarios and five templates: 110 combinations. Three
are outside their declared template applicability; four do not exhibit the
intended failure. They remain in the ledger. The fault denominator is 103.

The frozen parser retained 98 cases/108 typed issue rows and could not parse
five conftest failures. Those five are included in the paired denominator as
unparsed. The candidate retained 103 cases/103 issue rows, including all five.
It also avoids reporting an earlier chained exception as a separate root issue.
There are 107 portable audit records per run, including rejected attempts.
No skipped case or extra issue row is silently removed to improve the score.

### Reproduction and source boundary

- Frozen production C: `3e72647952c49c6f1b780cc2cd2402990a8ab5de`.
- Baseline replay checkout: `c26d511dc3260865af0791b245cce208683908ac` (C plus only the generator/portable-data/
  suite-loading changes from `c1cd2a5`, `8b18572`, `e177ddf`). Its diagnostic
  parser, rules, features and packaged model are C's unchanged files.
- Integrated production candidate: `c8de5a0d5a98ce50d59c853b0625dfbec287c445`.
  This includes #55 plus Django, pytest-option scope and source-build guidance.
- [environment-lock.json](environment-lock.json) pins Python 3.12.13/3.11.15,
  OS/architecture, uv version, and every installed package, including pip.
  All environments are fresh, version-checked and dependency-checked.

This is a new paired replay. The initial Claude handoff recorded some Python
versions only as 3.11/3.12; these newly fixed patch versions do not retroactively
establish the missing historical interpreter identities.

In each source checkout, with a development interpreter and uv matching the lock:

```sh
python -m fixfirst dataset --suite toolchain \
  --environment-lock experiments/core_diagnosis/v08-toolchain/environment-lock.json \
  --output fresh-output
```

Then run `compare_captured.py BASELINE_OUTPUT CANDIDATE_OUTPUT NEW_SUMMARY.json`.
Use fresh output and work directories. New-format incomplete suites are refused
by both evaluation loaders. Raw replay directories are retained locally; this
publication includes sanitized summaries, source/input hashes and generators.
The initial supplied saved dataset remains under `examples/toolchain-dataset`;
`INTAKE.json` records its patch provenance and the CSV-only newline conversion.

## Why historical evaluation numbers differed

The packaged tree has 44 features, but frozen source `train_tree(rows)` defaults
to the current **81-feature** layout. An evaluation using `--train` fits a fresh
tree; it is not an evaluation of the packaged tree. Claude's learning-curve and
transfer scripts did not pass an explicit feature layout, and therefore their
"44-feature" description needs correction to 81.

The same 215-row dataset, same Python 3.12.13 and scikit-learn 1.9.1 reproduce:

| Source/layout, leave one scenario out | Tree | Hybrid |
|---|---:|---:|
| Historical source, 44 features | 131/215 = 0.609302 | 200/215 = 0.930233 |
| Frozen source, explicit 44 features | 131/215 = 0.609302 | 200/215 = 0.930233 |
| Frozen source, default 81 features | 185/215 = 0.860465 | 210/215 = 0.976744 |

The old public source is `79a490b6e1e83eab7c17d3d906bc1c545080d20a`.
Its relevant source/data/evaluation files match the historical archive used for
the first probe. Dataset and saved evaluation files are identical between that
revision and C. The old numbers were reproduced exactly, without editing them.

Use `recompute_baseline.py --src SOURCE/src --dataset examples/diagnosis-dataset
--layout legacy|current --out NEW.json`. The three saved `evaluation-*.json`
files record full feature names, integer counts and source/data fingerprints.
Packaged-model training-set replay is explicitly separate from cross-validation.

## Validation and limits

- Integrated own-environment suite: **1376 passed, 12 skipped**. Ten skipped
  Django real-interpreter checks were separately executed; one toolchain network
  test is opt-in, and one requires native Windows PowerShell.
- Django target-interpreter suite on the integrated tree: **67 passed**.
- Both complete locked generator runs reconciled all 110 combinations.
- The source-build fixture verifies a real local no-network pure-Python wheel
  route. Its pg_config failure is synthetic, not a PostgreSQL compilation.
- No native Windows acceptance, held-out input, language-model request, formal
  B3/B7 run or default-model replacement occurred.

First-step quality and real-project completion still require independent
acceptance. The remaining pkg_resources errors are retained, and three classes
of author labels still await external review.
