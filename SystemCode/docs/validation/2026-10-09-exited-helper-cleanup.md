# Exited helper cleanup: candidate validation

The user selected option A of the cleanup finding, SHA256
`075b4e82bdfa18cf6b7140f4401984d26987a326c9434450d89d1495dfe60bb6`.
This is a separate repair on top of D16 candidate `f4fe736`.

## Change

The existing reap-and-signal-again path is retained. When the leader has exited
and both group signals return EPERM, two bounded `/bin/ps -A` snapshots inspect
only numeric PIDs, group IDs and states. Cleanup is accepted only if the group
is absent or contains only zombies, without new members between snapshots.
Live members, malformed or failed observations retain the PermissionError.
The Windows job path is unchanged. No diagnosis or report wording changed.

## Checks on macOS, target Python 3.9.6

| Check | Result |
|---|---|
| Original lock reproduction | 200/200 checks passed, zero exceptions |
| Original no-lock control | 200/200 checks passed, zero exceptions |
| Child sleeping for 300 seconds | 20/20 checks passed; zero live leftovers, zero missing PID records |
| Resource-tracker helper | 20/20 checks passed; zero live leftovers |
| Deliberately detached-session control | Checker detected all 20 live leftovers, then removed them |
| Scoped known tqdm 4 defect | 15/15 reproduced, observed, repaired and closed; zero exceptions |
| Cleanup unit and real-process tests | 23 passed |
| Existing 34 tasks | All 74 report texts unchanged; follow results 10/12 and 17/22 |
| Final full suite, Python 3.12.13 | 2305 passed, 35 skipped, 0 failed |
| Actual owners regeneration on the combination | 155/155 keys, 23/23 merged; stored audit zero problems |
| Final wheel | 81 runtime files byte-identical to source |

The real-process test also simulates denied signals while a genuine live helper
remains: cleanup raises and stays registered; after restoring signalling the
helper is terminated. The original permission-failure test keeps every prior
assertion and adds a mock for the newly introduced state query.

The detached-session arm is a control of the checker, not a claim that this
repair reaches a child that escapes its managed group. Process tests ran on
macOS; Windows was not executed. All projects used here are minimal fixtures or
already-used development cases. New held-out projects remain unopened.

Raw local evidence: `workbench/codex-test-entry-20261009/`, including
`CLEANUP-REPRODUCTIONS.json`, `CLEANUP-TQDM4-REPEAT.json`,
`FOLLOW-COMPARISON-CLEANUP.json`, `INVARIANCE-CLEANUP.json`, original reproduction
and leftover logs, and individual repeated-case records.
