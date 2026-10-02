# v0.8 candidate evidence features and controlled comparisons

The user authorized this PR5 development experiment. It does not replace the
bundled classifier or establish heldout generalization. Training waits for the
root agent's fixed environment/input matrix. Do not rerun the 30-seed learning
curve or tune model parameters against the new outcomes.

## Feature contract

Append schema 9 to the existing 81-feature schema 8; preserve every older
layout and its prefix. Keep the bundled 44-feature JSON byte-for-byte unchanged.
An independent module reads current raw observations, never final diagnoses,
rule facts/matches, labels, scenario/case IDs, knowledge entries or repairs.

Twelve candidate values:

1. Terminal exception is a Warning.
2. The last non-stdlib failing operation belongs to a unique current pytest,
   py or pluggy provider (project shadowing prevents this attribution).
3. Exact unconfigured-settings terminal message.
4. Exact apps-not-ready terminal message.
5. Actual global Django registry apps_ready boolean.
6. Actual global Django registry loading boolean.
7. Exact pkg_resources ModuleNotFoundError terminal message.
8. Setuptools installed in the current complete environment snapshot.
9–12. Stable Python, pytest, py and setuptools release coordinates.

Unknown is -1, distinct from observed false/absence. Release coordinates encode
major/minor/patch only, without hand-written affected-version boundaries;
pre/dev/post/local/noncanonical extra-release forms remain unknown. Exception
records must belong to each referenced failure independently. Grouped events
use a value only when all members agree. Environment metadata must precede the
current executed failing run in the same interpreter/scope. Stale, imported,
truncated or mismatched records do not supply candidate values. Registry data
requires the existing runtime's actual global receiver flag and native bools.
No Django API or project code is executed during feature extraction.

## Fixed comparison plan

First report exact cross-label collisions in historical 81-feature vectors,
with distinct datasets, row/case counts, vector hashes and conflict label counts.
This is a finite-data ambiguity measurement, not a proof of universal
inseparability or correctness of provisional labels.

Use Gini, max_depth=6, min_samples_leaf=2, random_state=42 throughout. Compare
the frozen bundled 44 model and explicit retrained 44/81/93 layouts. Keep data
constant when comparing layouts, then compare base training data with augmented
training data separately. Group all cases and mechanism variants together:
scenario groups for the original main set and whole mechanism/family groups
for the toolchain set. No row-random split and no near-neighbor variant split.

Report original main and hard regressions separately. A bundled model's main
training replay is labeled as such, not cross-validation. Root-cause tree
predictions, fixed rules/heuristics and mixed-system predictions remain separate.
Show parse coverage and the retained/unparsed/rejected/inapplicable roster beside
conditional issue metrics. Do not silently remove baseline unparsed cases or
interpret a parser-induced denominator change as model improvement.

Capture exact source/data/model hashes, feature order, software versions, split
membership, integer numerators/denominators and candidate artifacts. Labels from
Claude remain development/provisional. A negative or inconclusive comparison is
an acceptable result; no default promotion is authorized.

## Gates

Unit tests prove unknown/false separation, per-failure provenance, terminal
warnings versus successful warning summaries, project/tool ownership, settings
and registry facts, package absence/versions, and resistance to label/rule/ID
changes. Check schema-3/schema-8 compatibility and the bundled model digest.
Run focused existing classifier/evidence tests and the necessary suite gate.
Only candidate code/scripts/results may be committed; no LLM, training on
heldout data, formal B3/B7 execution, push, merge or default-model replacement.
