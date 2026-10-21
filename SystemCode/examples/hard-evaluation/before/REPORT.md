# Diagnosis on a held-out set

30 executed cases (30 failing-test issues). Labels: local_module 5, version_incompatibility 25. The decision tree was trained on diagnosis-dataset (215 issues); the rule base and knowledge graph were not changed for these cases. Rules left out: H07, H08.

| Method | Accuracy (95% CI) | Macro-F1 | Coverage | Precision when answering |
|---|---|---|---|---|
| Parser category only (v0.3 baseline) | 0.000 (0.000–0.000) | 0.000 | 1.000 | 0.000 |
| Rules without knowledge graph | 0.167 (0.033–0.300) | 0.200 | 0.333 | 0.500 |
| Rules + knowledge graph | 0.167 (0.033–0.300) | 0.200 | 0.333 | 0.500 |
| Rules + KG + heuristics | 0.167 (0.033–0.300) | 0.200 | 0.333 | 0.500 |
| Decision tree only | 0.167 (0.033–0.300) | 0.200 | 1.000 | 0.167 |
| Rules + heuristics without KG, then tree | 0.167 (0.033–0.300) | 0.200 | 0.833 | 0.200 |
| Rules + KG + heuristics, then tree (FixFirst) | 0.167 (0.033–0.300) | 0.200 | 0.833 | 0.200 |

## Per scenario (accuracy)

| Scenario | Cause | Rules | Rules + heuristics | Tree | FixFirst | FixFirst said (cases) |
|---|---|---|---|---|---|---|
| ml_renamed_then_alias | local_module | 1.00 | 1.00 | 1.00 | 1.00 | local_module (D16) ×5 |
| vb_click_mix_stderr | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | none (none) ×5 |
| vb_numpy_promotion | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | code_defect (tree) ×5 |
| vb_numpy_repr | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | code_defect (D40) ×5 |
| vb_pydantic_coercion | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | code_defect (tree) ×5 |
| vb_yaml_loader | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | code_defect (tree) ×5 |

Hard cases for evaluation only: documented behaviour changes of installed libraries and one two-layer fault (labelled by the first layer), executed against real installed libraries. None is in the knowledge base, and the decision tree is never trained on them.
