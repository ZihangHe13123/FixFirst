# Diagnosis on a held-out set

98 executed cases (108 failing-test issues). Labels: code_defect 5, config_missing 30, local_module 5, missing_dependency 15, version_incompatibility 53. The decision tree was trained on diagnosis-dataset (215 issues); the rule base and knowledge graph were not changed for these cases.

| Method | Accuracy (95% CI) | Macro-F1 | Coverage | Precision when answering |
|---|---|---|---|---|
| Parser category only (v0.3 baseline) | 0.185 (0.112–0.262) | 0.146 | 1.000 | 0.185 |
| Rules without knowledge graph | 0.046 (0.009–0.093) | 0.200 | 0.046 | 1.000 |
| Rules + knowledge graph | 0.093 (0.044–0.155) | 0.234 | 0.093 | 1.000 |
| Rules + KG + heuristics | 0.139 (0.074–0.211) | 0.264 | 0.139 | 1.000 |
| Decision tree only | 0.417 (0.319–0.519) | 0.353 | 1.000 | 0.417 |
| Rules + heuristics without KG, then tree | 0.463 (0.365–0.570) | 0.462 | 1.000 | 0.463 |
| Rules + KG + heuristics, then tree (FixFirst) | 0.509 (0.411–0.614) | 0.524 | 1.000 | 0.509 |

## Per scenario (accuracy)

| Scenario | Cause | Rules | Rules + heuristics | Tree | FixFirst | FixFirst said (cases) |
|---|---|---|---|---|---|---|
| dj_apps_not_ready | config_missing | 0.00 | 0.00 | 0.00 | 0.00 | code_defect (tree) ×5 |
| dj_unset_makefile | config_missing | 0.00 | 0.00 | 1.00 | 1.00 | config_missing (tree) ×5 |
| dj_unset_pytest_django | config_missing | 0.00 | 0.00 | 1.00 | 1.00 | config_missing (tree) ×5 |
| dj_unset_runtests | config_missing | 0.00 | 0.00 | 1.00 | 1.00 | config_missing (tree) ×5 |
| dj_unset_runtime | config_missing | 0.00 | 0.00 | 1.00 | 1.00 | config_missing (tree) ×5 |
| dj_unset_tox | config_missing | 0.00 | 0.00 | 1.00 | 1.00 | config_missing (tree) ×5 |
| ol_nose_imp | version_incompatibility | 1.00 | 1.00 | 0.00 | 1.00 | version_incompatibility (D01) ×5 |
| ol_six_moves | version_incompatibility | 0.00 | 1.00 | 1.00 | 1.00 | version_incompatibility (H09) ×5 |
| st_get_distribution | missing_dependency | 0.00 | 0.00 | 0.00 | 0.00 | local_module (tree) ×5 |
| st_pkg_resources_absent | missing_dependency | 0.00 | 0.00 | 1.00 | 1.00 | missing_dependency (tree) ×5 |
| st_pkg_resources_removed | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | missing_dependency (tree) ×5 |
| st_pkg_resources_runtime | missing_dependency | 0.00 | 0.00 | 1.00 | 1.00 | missing_dependency (tree) ×5 |
| tt_ast_str_ini | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | config_missing (tree) ×4 |
| tt_ast_str_narrow | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | config_missing (tree) ×4 |
| tt_ast_str_setupcfg | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | config_missing (tree) ×4 |
| tt_ast_str_t625 | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | config_missing (tree) ×2 |
| tt_ast_str_toml | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | config_missing (tree) ×4 |
| tt_own_warning | code_defect | 0.00 | 0.00 | 1.00 | 1.00 | code_defect (tree) ×5 |
| tt_py_spec_t625 | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | code_defect (tree) ×10 |
| tt_py_spec_t713 | version_incompatibility | 0.00 | 0.00 | 0.00 | 0.00 | code_defect (tree) ×10 |
| tt_shadow_pluggy | local_module | 1.00 | 1.00 | 0.00 | 1.00 | local_module (D10) ×5 |

Real runs in pinned virtual environments, one fix verified per case. Scenarios were written after the 2026-10 held-out run showed these mechanisms, so results on them are development results, never held-out ones. They are not a sample of naturally occurring failures.
