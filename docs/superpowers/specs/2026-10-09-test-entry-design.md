# Saved test scope: first delivery

Approved requirements: `NEXT-VERSION-REQUIREMENTS-20261009.md`, SHA256
`3972f8ec0a33c7f94b92ad3309d24d6ebfdbd8ccb1bc84c0df3fb2f0ecde016f`.
Base: `5c224cf`. This delivery implements U1–U3; diagnosis changes follow separate acceptance.

## Interface and execution

Save a list of project test files or pytest node IDs in the session. CLI `init` and
`configure` accept `--tests`; the existing `scan --checks pytest_run --nodes` also
saves a selection, including previously unseen files/nodes. A normal rescan reuses it.
MCP adds only optional `tests` to `diagnose`; `check_again` reuses the session settings.
The web start/settings forms use the same validation and saved field.

Selection is restricted to regular files inside the project, optionally followed by
pytest node components. Reject external paths, option arguments, control characters,
duplicates and oversized input before running code. No arbitrary command execution.
Keep FixFirst's current pytest options and probe. Quoted source test commands are
suggestions only. Explicit selection does not execute neighbouring files by default.

Use a saved scope rather than replacing the existing temporary rerun target list:
file selection is not a list of executed nodes. Existing service rerun actions retain
their partial-node semantics. Requested selection, actual argv and executed outcomes
remain distinct records.

## Verification and compatibility

Hash the saved selection into pytest execution and integrity scopes. Issue identity,
member carry-over, closure and goal status must compare that scope and interpreter.
An unrelated selection cannot settle a previous failure. A selected pass covers the
selected scope only; do not label it as the entire suite passing. Missing, skipped,
cancelled or incomplete outcomes never verify the original failing test.

Without a selection, keep legacy scope IDs and pytest behaviour. Existing MCP tool
names, descriptions, parameters and facts mode are unchanged apart from the new
`diagnose.tests` property. Model, knowledge files and experiment code remain unchanged.
U2/U3 deliberately improve the no-tests/missing-optional-tool cases; the registered
34 development/evaluation task reports must remain unchanged in this delivery.

## Empty discovery and optional tools

Give zero default pytest discovery its own first step: default pytest found no tests,
then show how to supply a file or node through CLI, MCP and web. Read bounded regular
`tox.ini`, `Makefile`, `setup.cfg` and `pyproject.toml` files to quote identifiable
project test-command declarations with their source. Do not expand variables or run
those commands. Keep that step separate from tool availability errors.

During default scans, skip pip/Ruff when a fresh successful environment snapshot
proves they are absent and they are not the chosen goal. Explicitly requested tool
checks and the Ruff goal retain their normal handling. Do not skip pytest.

## Validation and delivery

1. Real process cases: unseen node/file, nonstandard filename, adjacent collection
   failure, saved rescan, parameterised tests and incomplete/skipped/deleted targets.
2. Scope changes: selection, interpreter and baseline changes cannot close old issues.
3. CLI/MCP/web use the same selection; old sessions and temporary reruns still work.
4. Empty discovery quotes source declarations without execution; optional missing
   pip/Ruff do not become required repairs.
5. Existing tests stay intact; run focused tests, full suite, Ruff and diff checks.
   Compare frozen model/knowledge bytes and 34 task reports/follow outcomes.

Deliver one independently reviewable first-stage PR. After Claude accepts it, rerun
the known 27 BugsInPy defects using their declared test selections. Use those results
to decide the separately submitted diagnosis tightening. Before the next freeze,
do not inspect held-out materials or run/debug the product on fastapi, httpie or
thefuck. Report edits remain paused; previous frozen experiments are retained.
