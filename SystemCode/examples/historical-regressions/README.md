# Minimal reproductions of upstream library defects

Start with `REPORT.md`. Each case's `project/test_regression.py` is a minimal test written from
an upstream issue; the library under test is an unmodified official wheel. `01-broken` and
`02-fixed` each have an HTML report, the session JSON and the graph JSON; `setup.json` records
how the isolated environment was created and which wheels were installed offline.

`results.json` records the upstream fix commits, the versions observed, exit codes, the SHA-256
of the test source and whether both failure and recovery were observed.

These cases show FixFirst's verification semantics on real library versions: the same
unchanged test fails with the broken release and passes with the fixed one, and only then is
the issue closed. They are defects *inside* the libraries, which FixFirst's five root-cause
classes do not model, so they are not part of the diagnosis experiment.

`assets/manifest.json` lists the pinned PyPI URLs, SHA-256 hashes, sizes and licence files of
the nine wheels. They keep their original licences; **the CC0 notice of the generated fixtures
does not apply to them**.

Re-run offline with `fixfirst historical --assets examples/historical-regressions/assets --output <new dir>`.
Paths in these shared copies are replaced; rebuild your own environment instead of running the
recorded commands.
