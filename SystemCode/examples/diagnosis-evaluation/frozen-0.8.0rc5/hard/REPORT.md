# Diagnosis on a held-out set

30 executed cases (30 failing-test issues). Labels: local_module 5, version_incompatibility 25. The decision tree was trained on diagnosis (220 issues); the rule base and knowledge graph were not changed for these cases.

| Method | Accuracy (95% CI) | Macro-F1 | Coverage | Precision when answering |
|---|---|---|---|---|
| Parser category only (v0.3 baseline) | 0.000 (0.000–0.000) | 0.000 | 1.000 | 0.000 |
| Rules without knowledge graph | 0.167 (0.033–0.300) | 0.200 | 0.333 | 0.500 |
| Rules + knowledge graph | 0.167 (0.033–0.300) | 0.200 | 0.167 | 1.000 |
| Rules + KG + heuristics | 1.000 (1.000–1.000) | 0.400 | 1.000 | 1.000 |
| Decision tree only | 0.500 (0.333–0.667) | 0.314 | 1.000 | 0.500 |
| Rules + heuristics without KG, then tree | 0.167 (0.033–0.300) | 0.200 | 1.000 | 0.167 |
| Rules + KG + heuristics, then tree (FixFirst) | 1.000 (1.000–1.000) | 0.400 | 1.000 | 1.000 |

## Per scenario (accuracy)

| Scenario | Cause | Rules | Rules + heuristics | Tree | FixFirst | FixFirst said (cases) |
|---|---|---|---|---|---|---|
| ml_renamed_then_alias | local_module | 1.00 | 1.00 | 1.00 | 1.00 | local_module (D16) ×5 |
| vb_click_mix_stderr | version_incompatibility | 0.00 | 1.00 | 1.00 | 1.00 | version_incompatibility (H10) ×5 |
| vb_numpy_promotion | version_incompatibility | 0.00 | 1.00 | 0.00 | 1.00 | version_incompatibility (H10) ×5 |
| vb_numpy_repr | version_incompatibility | 0.00 | 1.00 | 0.00 | 1.00 | version_incompatibility (H10) ×5 |
| vb_pydantic_coercion | version_incompatibility | 0.00 | 1.00 | 0.00 | 1.00 | version_incompatibility (H10) ×5 |
| vb_yaml_loader | version_incompatibility | 0.00 | 1.00 | 1.00 | 1.00 | version_incompatibility (H10) ×5 |

Hard cases, never used to train the decision tree: documented behaviour changes of installed libraries and one two-layer fault (labelled by the first layer), executed against real installed libraries. Three behavior families now have curated knowledge. Heuristics and behavior knowledge were written after seeing these cases, so their results measure development coverage, not held-out generalisation.
