# Exited helper cleanup

The user selected option A in the independently supplied cleanup finding:
fix the crash in this candidate, retain diagnosis/report behavior, and prove
200 repeated Python 3.9.6 checks succeed without leaving live helpers.
Finding SHA256: `075b4e82bdfa18cf6b7140f4401984d26987a326c9434450d89d1495dfe60bb6`.

## Decision

Ignoring every permission error would conceal a live process that could not be
terminated. Retrying signals alone cannot establish whether a group is already
dead. Keep the existing signal/reap/retry path and add evidence for the narrow
case where the leader has exited and the second signal returns EPERM.

Inspect numeric PID, process-group ID and process state with a bounded direct
`ps` invocation. Only an empty group or zombie-only members in two consecutive
complete snapshots establish that no live helper remains. The second snapshot
may lose reaped members but must not introduce new members. Live members, failed
queries or malformed output retain the PermissionError. No other group is signalled.
The Windows job path is unchanged.

## Validation

- Preserve original permission-failure, scope-cancellation and exited-leader
  assertions; mock the new state query when simulating permission failure.
- Check live, mixed, zombie-only, disappearing and uninspectable groups.
- Kill a real surviving helper after its leader exits, and record helper PIDs
  during 200 product checks on the Python 3.9.6 lock fixture.
- Recheck all 34 existing task reports and the full suite; regenerate the bound
  owners receipt from actual execution. Retain the D16 validation separately.

The known development cases remain the only project material used before freeze.
