# Test selection: first-stage validation

Base: `5c224cf`. Requirements SHA256:
`3972f8ec0a33c7f94b92ad3309d24d6ebfdbd8ccb1bc84c0df3fb2f0ecde016f`.
This is the U1–U3 candidate for independent acceptance.

| Check | Result |
|---|---|
| Full suite, Python 3.12.13 | 2276 passed, 35 skipped, 0 failed |
| Focused execution/CLI/MCP regressions | 115 passed |
| Knowledge and saved-selection tests | 187 passed |
| Ruff and diff whitespace | Passed |
| Owners regeneration | 155/155 keys, 23/23 merged; stored audit 0 problems |
| Existing 34 task reports | Every round unchanged after removing paths, session/log IDs and durations |
| Scripted follow checks | Development 10/12; former evaluation pack 17/22; no ungraded cases |
| MCP contract | Identical to base after removing only `diagnose.tests` |
| Model and knowledge bytes | Identical to base |
| Web process check in Microsoft Edge | Unseen selected node failed, then passed in the same saved scope after a source repair |

New process cases cover unseen files/nodes, parameterised tests, unrelated collection
failures, saved rescans, scope changes, incomplete/skipped/deleted tests, all three
entry points, empty discovery and optional missing pip/Ruff. Existing tests were
not edited, removed or relaxed.

The first 34-task attempt inherited this repository's pytest configuration because
its working directory was inside the checkout. That attempt is retained as an
environment failure. Validation and follow checks were rerun outside repositories;
the clean results above have zero observation errors. The first full-suite run
rejected the old owners receipt in two tests. After actual regeneration, the final
full suite passed without weakening either guard.

No language model was invoked. The original 34 tasks are development data for this
candidate. The new held-out materials were not opened and the product was not run
or debugged on fastapi, httpie or thefuck. The known 27 BugsInPy cases have not yet
been rerun: that follows independent acceptance of this delivery.

Custom commands and the project's usual pytest options remain future work under
the approved requirements. Diagnosis tightening is a separate second delivery.
The report draft remains paused; existing frozen experiment results are retained.

Local raw evidence is in `workbench/codex-test-entry-20261009/`: full/focused test
logs, owners verification, `FOLLOW-COMPARISON.json`, `INVARIANCE.json` and
`WEB-CHECK.json`. [TEST_SELECTION.md](../TEST_SELECTION.md) describes the interfaces.
