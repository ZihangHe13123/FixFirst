# Fixed candidate feature comparison

Development data with provisional toolchain labels. No default promotion.

Tree columns are root-cause classifications; hybrid columns use this checkout's rules/heuristics.
Production source is checked against the fixed integrated base; only the candidate feature files differ.

Parameters: Gini, depth 6, minimum leaf 2, random_state 42; no hyperparameter search.

| Protocol | Model | Tree correct/rows | Hybrid correct/rows |
|---|---|---:|---:|
| main_training_replay | bundled44 | 200/215 | 210/215 |
| main_training_replay | base44 | 200/215 | 210/215 |
| main_training_replay | augmented44 | 196/215 | 210/215 |
| main_training_replay | base81 | 215/215 | 215/215 |
| main_training_replay | augmented81 | 212/215 | 212/215 |
| main_training_replay | base93 | 215/215 | 215/215 |
| main_training_replay | augmented93 | 212/215 | 212/215 |
| hard_external_regression | bundled44 | 5/30 | 20/30 |
| hard_external_regression | base44 | 5/30 | 20/30 |
| hard_external_regression | augmented44 | 5/30 | 20/30 |
| hard_external_regression | base81 | 10/30 | 20/30 |
| hard_external_regression | augmented81 | 5/30 | 20/30 |
| hard_external_regression | base93 | 10/30 | 20/30 |
| hard_external_regression | augmented93 | 5/30 | 20/30 |
| toolchain_base_transfer | bundled44 | 50/103 | 93/103 |
| toolchain_base_transfer | base44 | 50/103 | 93/103 |
| toolchain_base_transfer | base81 | 45/103 | 93/103 |
| toolchain_base_transfer | base93 | 55/103 | 98/103 |
| main_leave_scenario_out | base44 | 131/215 | 200/215 |
| main_leave_scenario_out | augmented44 | 146/215 | 200/215 |
| main_leave_scenario_out | base81 | 185/215 | 210/215 |
| main_leave_scenario_out | augmented81 | 165/215 | 210/215 |
| main_leave_scenario_out | base93 | 190/215 | 210/215 |
| main_leave_scenario_out | augmented93 | 175/215 | 210/215 |
| toolchain_leave_mechanism_out | augmented44 | 45/103 | 93/103 |
| toolchain_leave_mechanism_out | augmented81 | 40/103 | 83/103 |
| toolchain_leave_mechanism_out | augmented93 | 35/103 | 78/103 |
| toolchain_leave_family_out | augmented44 | 25/103 | 93/103 |
| toolchain_leave_family_out | augmented81 | 30/103 | 98/103 |
| toolchain_leave_family_out | augmented93 | 30/103 | 98/103 |

## Coverage

| Dataset | Retained cases | Issue rows | Unparsed | Rejected | Inapplicable |
|---|---:|---:|---:|---:|---:|
| main | 215 | 215 | 0 | 0 | 0 |
| hard | 30 | 30 | 0 | 0 | 0 |
| toolchain | 103 | 103 | 0 | 4 | 3 |

Training replays are explicitly labeled and are not out-of-sample scores. Family/mechanism folds retain
all same-case rows and near-neighbor variants together. Inspect fold predictions and feature importances
in results.json before interpreting gains; a version coordinate can correlate with a generated environment.
No test accuracy proves labels, natural-project repair success, or a default-model improvement.

## Attribution check

New columns used by the base-93 tree: none.
If this list is empty, a changed base-93 score is not evidence that the tree used the new raw signals.
Existing-feature split choices can change when the candidate feature set changes, including tied gains.
