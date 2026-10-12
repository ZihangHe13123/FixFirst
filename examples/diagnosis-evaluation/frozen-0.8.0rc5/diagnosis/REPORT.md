# Root-cause diagnosis experiment

220 executed cases (220 failing-test issues; 0 generated cases rejected because the fault was not observed). Labels: code_defect 60, config_missing 30, local_module 30, missing_dependency 30, version_incompatibility 70. Python 3.12.14; Jinja2 3.1.6, MarkupSafe 3.0.3, PyYAML 6.0.3, click 8.5.0, numpy 2.5.3, packaging 26.3, pydantic 2.13.5, pytest 9.1.1, scikit-learn 1.9.0, scipy 1.18.1.

Each case is a small project with exactly one injected fault, run for real against the installed libraries. Labels come from the scenario definition. The decision tree is retrained for every fold without the held-out group; the rule base and knowledge graph are fixed and were written by the project team, so their scores on scenarios the team designed are optimistic. Scenarios marked *not covered* use removed APIs, packages or configuration patterns that the knowledge graph does not list. The heuristic rules H01/H02 (a name missing from an installed library suggests a version change) were added after testing on real projects (docs/REAL_PROJECTS.md); rows without heuristics are kept for comparison.

## Unseen project structure (leave one template out)

| Method | Accuracy (95% CI) | Macro-F1 | Coverage | Precision when answering |
|---|---|---|---|---|
| Parser category only (v0.3 baseline) | 0.409 (0.345–0.473) | 0.276 | 1.000 | 0.409 |
| Rules without knowledge graph | 0.477 (0.414–0.545) | 0.603 | 0.500 | 0.955 |
| Rules + knowledge graph | 0.782 (0.727–0.836) | 0.884 | 0.782 | 1.000 |
| Rules + KG + heuristics | 0.832 (0.782–0.882) | 0.903 | 0.832 | 1.000 |
| Decision tree only | 1.000 (1.000–1.000) | 1.000 | 1.000 | 1.000 |
| Rules + heuristics without KG, then tree | 0.932 (0.900–0.964) | 0.945 | 1.000 | 0.932 |
| Rules + KG + heuristics, then tree (FixFirst) | 1.000 (1.000–1.000) | 1.000 | 1.000 | 1.000 |

## Unseen fault type (leave one scenario out)

| Method | Accuracy (95% CI) | Macro-F1 | Coverage | Precision when answering |
|---|---|---|---|---|
| Parser category only (v0.3 baseline) | 0.409 (0.345–0.473) | 0.276 | 1.000 | 0.409 |
| Rules without knowledge graph | 0.477 (0.414–0.545) | 0.603 | 0.500 | 0.955 |
| Rules + knowledge graph | 0.782 (0.727–0.836) | 0.884 | 0.782 | 1.000 |
| Rules + KG + heuristics | 0.832 (0.782–0.882) | 0.903 | 0.832 | 1.000 |
| Decision tree only | 0.868 (0.823–0.914) | 0.844 | 1.000 | 0.868 |
| Rules + heuristics without KG, then tree | 0.932 (0.900–0.964) | 0.945 | 1.000 | 0.932 |
| Rules + KG + heuristics, then tree (FixFirst) | 1.000 (1.000–1.000) | 1.000 | 1.000 | 1.000 |

## Knowledge-graph coverage (leave one scenario out, accuracy)

| Method | Faults the KG covers | Faults the KG does not cover |
|---|---|---|
| Parser category only (v0.3 baseline) | 0.214 (n=70) | 0.500 (n=150) |
| Rules without knowledge graph | 0.071 (n=70) | 0.667 (n=150) |
| Rules + knowledge graph | 0.900 (n=70) | 0.727 (n=150) |
| Rules + KG + heuristics | 0.900 (n=70) | 0.800 (n=150) |
| Decision tree only | 0.929 (n=70) | 0.840 (n=150) |
| Rules + heuristics without KG, then tree | 0.786 (n=70) | 1.000 (n=150) |
| Rules + KG + heuristics, then tree (FixFirst) | 1.000 (n=70) | 1.000 (n=150) |

## Hybrid per class (leave one template out)

| Cause | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| missing_dependency | 1.000 | 1.000 | 1.000 | 30 |
| local_module | 1.000 | 1.000 | 1.000 | 30 |
| version_incompatibility | 1.000 | 1.000 | 1.000 | 70 |
| config_missing | 1.000 | 1.000 | 1.000 | 30 |
| code_defect | 1.000 | 1.000 | 1.000 | 60 |

## Hybrid confusion matrix (leave one template out; rows = truth)

| Truth \ predicted | missing_dependency | local_module | version_incompatibility | config_missing | code_defect | none |
|---|---|---|---|---|---|---|
| missing_dependency | 30 | 0 | 0 | 0 | 0 | 0 |
| local_module | 0 | 30 | 0 | 0 | 0 | 0 |
| version_incompatibility | 0 | 0 | 70 | 0 | 0 | 0 |
| config_missing | 0 | 0 | 0 | 30 | 0 | 0 |
| code_defect | 0 | 0 | 0 | 0 | 60 | 0 |

## Hardest scenarios for the hybrid (leave one scenario out)

| Scenario | Cause | KG covers | Naive | Rules | Rules + heuristics | Tree | Hybrid |
|---|---|---|---|---|---|---|---|
| cd_assertion | code_defect | no | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| cd_attribute_typo | code_defect | no | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| cd_dict_key | code_defect | no | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 |
| cd_fixture_bug | code_defect | no | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 |
| cd_index_error | code_defect | no | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| cd_local_kwarg | code_defect | no | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| cd_missing_name | code_defect | no | 0.00 | 1.00 | 1.00 | 0.00 | 1.00 |
| cd_name_error | code_defect | no | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

## Final decision tree

Trained on all 220 issues (7 leaves, hyperparameters {'max_depth': 6, 'min_samples_leaf': 2} fixed in advance). Most important features: context_external_api 0.32, context_configuration 0.19, module_mentioned 0.19, context_project_names 0.15, context_local_symbol 0.09, interface_history_match 0.05. The full tree is in decision_tree.txt; per-issue predictions are in predictions.csv.

## Limitations

- Five templates and one fault per case; real projects have several interacting faults.
- The knowledge graph lists removals the team looked up; coverage elsewhere is partial by design.
- A suggestion below the confidence threshold (0.6) is not shown, so the hybrid may answer fewer cases than the tree.
- No user study yet: these numbers measure diagnosis, not time saved.
