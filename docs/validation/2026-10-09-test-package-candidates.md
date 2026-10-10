# Test-package candidate validation

Base: `f886de5bdfe02c80bb56847c524b12d04e27ad61`.
Task-card SHA256: `8630ba968d69dee1bd596f2a99ea89801674c78f35d970d2ac57da38f2469288`.

The only production change is one line in `evidence.py`: a candidate ending in
`__init__.py` is checked against test affixes using its parent directory name.
Affixes, case sensitivity, importer identity, rule conditions, feature
calculations, tree weights, MCP and the experiment runner are unchanged.

| Check | Result |
|---|---|
| Added package tests | Four test-affix negatives and one genuine renamed-package positive passed |
| Focused new and existing regressions | 65 passed |
| Previous four manual projects | Identical to the accepted candidate |
| 34 existing tasks | 74 reports unchanged; follow results 10/12 and 17/22 |
| 28 known defects, both entries, both source versions | Zero differences in default and saved-scope results |
| Full suite, Python 3.12.13 | 2310 passed, 35 skipped, 0 failed |
| Actual owners regeneration | 155/155 keys, 23/23 merged; stored audit zero problems |
| Cleanup code and original tests | Unchanged; repeated cleanup experiments not rerun |

The first default-entry attempt inherited shared user Cookiecutter caches and
produced additional errors in two historical repositories. The accepted
baseline showed those errors too. The initial bytecode explanation was not
confirmed; tracebacks located failures in the repositories' own cleanup of
`.cookiecutters.backup`. Final comparisons use the same existing drivers with
separate test homes for every case, source version and entry. Initial errors
and controls are retained in the local evidence; no product workaround was added.

The version chosen for the next freeze is `0.8.0rc3`. Its version-only commit
will follow functional acceptance, keeping these report comparisons on `0.8.0rc2`.
New held-out projects remain unopened. No language model was called.

Evidence: `workbench/codex-test-entry-20261009/`, including the package-focused
and full-suite logs, `INVARIANCE-PACKAGE.json`, `FOLLOW-COMPARISON-PACKAGE.json`,
isolated 28-case comparisons and the regenerated owners receipt.
