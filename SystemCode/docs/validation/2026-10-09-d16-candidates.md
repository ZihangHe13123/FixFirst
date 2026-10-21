# D16: second-stage candidate validation

Accepted first stage: `ae6359d1152e3a308c7d19bbbe9e54fdd0e6cd34`.
Task-card SHA256: `3d330e79af87d3d0ea02e490c2fe6a2fd15d43652beed815670aa609a4954211`.
This candidate is for independent acceptance before choosing the new version and freeze.

## Change

D16 receives issue-specific candidates. It excludes the recorded importing file
itself and filenames whose stem is the missing module's last component plus
`test_`, `tests_`, `_test` or `_tests`. Affix matching is exact and case-sensitive.
An outer project caller is not treated as the importer of an exception raised in
a library. Other similar candidates remain eligible.

P13 uses the same eligible candidates, so an excluded filename cannot return in
the advice when another candidate matches. Its wording is unchanged.
The original `similar_local` observations, `module_context()` and `features()`
are unchanged; the rule filter does not change the tree's input.

## Checks

| Check | Result |
|---|---|
| New tests | 12 passed; importing-file identity, four affixes, remaining candidate, path normalization and library attribution |
| New and existing focused regressions | 60 passed; both existing rename/spelling tests unchanged |
| Final full suite, Python 3.12.13 | 2288 passed, 35 skipped, 0 failed |
| Existing 34 tasks | 74 reports identical to the first stage, which was identical to the freeze; follow results 10/12 and 17/22 |
| Known 27 scoped BugsInPy cases | 27 reproduced and observed; 24 closed after repair; 25 first reasons name a code defect; 27 without environment commands; same as first stage |
| Known default scans | All 11 incorrect D16 steps replaced by existing unconfirmed advice without commands; 27/27 without environment commands |
| Recorded feature replay | 88 sessions, 1853 vectors of 81 features, zero differences between first-stage and candidate code |
| Model, domain and parked knowledge | Byte-identical to the first stage |
| MCP definitions and experiment runner | Identical to the first stage |
| Wheel | 81 runtime files byte-identical to source |
| Owners receipt | Actual regeneration: 155/155 keys, 23/23 merged, stored audit zero problems |
| Ruff and diff whitespace | Passed |

The three scoped cases that remain awaiting verification retain their original
guards for differing pytest options or test-source changes. Selection IDs include
the project root: comparisons normalize only these IDs while checking identical
saved selections and consistent before/after scopes. The first unnormalized
comparison is preserved in the local evidence.

All process checks ran on macOS. Windows path handling was checked with unit
inputs. No language model was invoked. These task packs and BugsInPy cases are
already-used development data. The new held-out materials were not opened and
the product was not run or debugged on fastapi, httpie or thefuck.

Evidence is under `workbench/codex-test-entry-20261009/`, including
`FOLLOW-COMPARISON-STAGE2.json`, `B12-SCOPED-STAGE2.json`,
`B12-DEFAULT-STAGE2.json`, `FEATURE-REPLAY-STAGE2.json`, `INVARIANCE-STAGE2.json`,
the owners log and receipt, and final test logs. The knowledge matrix was not rerun.
