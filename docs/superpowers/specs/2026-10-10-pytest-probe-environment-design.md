# Retain pytest probe transport across project environment changes

## Approved scope

Implement the user's approved rc4 task card, `NEXT-VERSION-RC4-PROBE-20261010.md`
(SHA256 `e3e5f8b4ff37716fe187d493473e95b9b7a6145e5a3629fca526743d4f7ade0b`),
from the rc3 freeze `7baaec9bf38b933cc38d43b8e8d2a120746c2e01` on a new branch and PR.

## Design

Capture `FIXFIRST_PROBE` when the copied stdlib-only pytest plugin is imported.
Every later `emit()` uses this saved destination. Project tests can replace,
clear, delete or change environment entries without losing or redirecting test
outcomes, exception evidence or the final completion record. Retain the current
record schema, size limits, dropped-record handling and file-error behavior.
No startup destination remains a silent no-op.

A full environment copy would retain unrelated project settings. Keeping an open
file handle would change I/O lifetime and resource cleanup. Saving only the
destination solves the approved problem with one startup assignment and one
writer substitution.

Other environment reads are startup observations: encoding restoration occurs
at import, and persistent pytest configuration reads occur in the initial
conftest-loading hook before project conftests and test fixtures execute. Leave
these unchanged and list them in the handoff.

## Verification and delivery

Add real subprocess regressions for the five environment-mutation cases and a
non-mutating control, including passing and mixed outcomes. Verify collection,
exceptions and completion evidence, startup without a destination, and a changed
environment destination. Keep existing tests and assertions intact.

Run the full suite and compare the existing 74 reports and known real defects
under per-run isolated home directories. Regenerate the owners receipt against
the final rc4 contents; do not rehash an unexecuted receipt. Keep the fix and
`0.8.0rc4` version declarations in separate commits. Open a short draft PR and
hand off full commit hashes and validation evidence before freezing.

Old pytest's unsupported `--rootdir` remains a known limitation. Diagnostics,
knowledge entries, features, tree weights, D16, process cleanup, MCP tool
definitions and the experimental runner are outside this change.

Development replay also found pytest 3.10.1 class node IDs with `::()::`.
The repaired writer records those failures, but the existing saved-selection
matcher does not verify two such class methods. Node canonicalization is outside
this transport repair; report the original criterion and raw records separately.

Until rc4 freezes, do not inspect the new held-out materials or run/debug the
product on any commits of ansible, black, keras, luigi, matplotlib, pandas,
sanic, scrapy, spacy or youtube-dl. The previous 19 revealed defects are now
development cases; they may be used without changing their expected outcomes.
