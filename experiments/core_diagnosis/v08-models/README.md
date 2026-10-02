# PR5 raw-feature candidate: not selected as the default

This is a separately retained development candidate, not the v0.8 product
candidate. The latter remains integrated source `c8de5a0` with the bundled
44-feature model. Toolchain labels are provisional and the cases were written
after mechanisms were exposed; these results are not formal generalization,
B3/B7 evidence or actual user-project repair success.

## What was fixed before training

- Gini decision tree, depth 6, minimum leaf 2, random_state 42; no parameter or
  seed search. Candidate widths are explicitly 44, 81 and 93.
- Main training input: the committed historical 215-case main dataset. Hard
  regression: the committed 30-case dataset, never added to training.
- Added training input: root's completed exact-lock integrated matrix,
  **103 cases/103 issues, 0 unparsed, 4 rejected, 3 inapplicable**. All 110
  registered combinations are accounted for. Producer source is `c8de5a0`.
- Main cross-validation holds out whole scenarios. Toolchain folds hold out
  whole families and predeclared mechanism groups; pytest-version variants,
  warning-config variants and Django settings-entrypoint variants stay together.
  The same case is never split by issue. These are development comparisons.
- All results include integer counts, predictions, case-level all-issues-correct
  counts, train/test membership, model hashes, source hashes, every input-file
  hash, and known/unknown coverage for each added feature.

The 12 features read raw terminal records, actual failure-operation ownership,
current environment versions, and recorded global-registry bools. Unknown is
-1. They do not read labels, IDs as predictors, rule conclusions, knowledge
matches, fixes or repair outcomes. Old 44/81 prefixes and the default model are
unchanged. Text-only/CollectError-wrapper records without a direct typed
terminal exception leave new exception fields unknown; old registry evidence
is never fabricated. Complete package snapshots can still supply version facts.
The warning flag is the observed terminal type-name suffix, not a runtime
subclass inspection. Stable release coordinates use major*1,000,000 +
minor*1,000 + patch. Scikit-learn consumes float32 inputs, so nearby patch values
at large coordinates may round together; these numeric leads are not exact
compatibility-boundary predicates. This matrix makes no claim depending on such
a tiny patch distinction. Only five toolchain rows contain global-registry
bools; provenance unit tests do not replace a balanced learned-model validation
of other registry states.

## Findings

Historical 81-feature collision audit: main 215 and hard 30 each have no
cross-label identical vectors. Historical toolchain 108 issue rows have one
10-row collision: `st_pkg_resources_absent` versus `st_pkg_resources_removed`,
five rows per label. The newly collected matrix retains that 81-feature
collision; schema 9 separates it using actual environment metadata. This
finite-data observation does not prove the provisional labels correct.

| Fixed comparison | 81 tree / hybrid | 93 tree / hybrid |
|---|---:|---:|
| Main 215 training only → new toolchain 103 | 45 / 93 | 55 / 98 |
| Main leave-scenario-out, main training only, n=215 | 185 / 210 | 190 / 210 |
| Main leave-scenario-out, toolchain added, n=215 | 165 / 210 | 175 / 210 |
| Toolchain leave-mechanism-out, base plus remaining groups, n=103 | 40 / 83 | 35 / 78 |
| Toolchain leave-family-out, base plus remaining families, n=103 | 30 / 98 | 30 / 98 |
| Hard regression, main training only, n=30 | 10 / 20 | 10 / 20 |
| Hard regression, toolchain added, n=30 | 5 / 20 | 5 / 20 |

These two effects must remain separate: adding columns versus adding cases.
For example, adding toolchain cases to the 93-feature model lowers main
leave-scenario-out tree accuracy from 190/215 to 175/215, and hard tree accuracy
from 10/30 to 5/30. The bundled 44 model remains 50/103 tree and 93/103 hybrid
on the fixed toolchain input. Full 44/81/93 tables are in the generated report.

**The apparent base-93 +10 tree gain is not new-signal use.** Direct inspection
of every internal tree node finds no feature index >=81 in `base-93.json`.
Its predictions therefore depend only on old columns. Changing candidate
column count can change selection among old-column splits even with the same
seed; scikit-learn documents per-split feature permutation and random choices
between equal improvements. This explains why width alone is not an attribution
test. [Official DecisionTreeClassifier documentation](https://scikit-learn.org/stable/modules/generated/sklearn.tree.DecisionTreeClassifier.html).

The augmented 93 tree does use tool-operation ownership, unconfigured-settings
text and setuptools release coordinates. Its mechanism holdout regresses and
family holdout ties the 81 tree. The evidence does not justify default promotion.
No parameters, groups or seeds were changed after these results.

## Reproduce and inspect

Use the same Python 3.12.13/scikit-learn 1.9.1 environment recorded in results.
Set `MATRIX` to the unchanged completed root matrix directory, and select a new
output directory; the script refuses overwriting. It checks production source
against `c8de5a0` and permits only the three candidate feature/schema files to
differ. No generator or target project executes during this experiment.

```sh
python experiments/core_diagnosis/v08-models/collisions.py examples/diagnosis-dataset examples/hard-dataset examples/toolchain-dataset --output /tmp/old81-collisions.json
python experiments/core_diagnosis/v08-models/compare.py --toolchain "$MATRIX" --output /tmp/fresh-model-comparison
python experiments/core_diagnosis/v08-models/inspect_results.py experiments/core_diagnosis/v08-models/fixed-matrix-results --matrix "$MATRIX"
```

The first comparison pass had an outdated hybrid-scope description. After
adding the source-base check and correcting that description, an exact replay
produced byte-identical candidate models and identical predictions/folds; no
selection or training parameter changed. The retained results are the verified
replay, and `node-attribution.json` records direct-node/integrity checks.

The default model SHA256 remains
`4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3`.
Source/data/model hashes are in `fixed-matrix-results/results.json`; no default
model file was overwritten. No new native Windows experiment was performed.

## Validation

- Raw-feature provenance/schema tests: 35 passed.
- Classifier/evidence focused gate: 91 passed.
- Final complete suite with all integrated production dependencies:
  **1411 passed, 12 skipped** (`python -m pytest -o pythonpath=src tests -q`).
- Ruff, whitespace checks and `inspect_results.py --matrix ...`: passed.
- The historical 81-prefix collision report is byte-identical before and after
  feature append, including its feature-row hashes.
- `base-93` internal feature indices are exactly
  `[16,22,29,30,44,45,50,61,62]`; no index is >=81. The augmented tree additionally
  uses 82, 83 and 92, as recorded in `node-attribution.json`.

No LLM, heldout data, formal B3/B7 run, default model replacement, push or merge
was performed for this experiment.
