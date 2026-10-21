# Declared version does not match the installed one

Open `01-broken.html`, then `02-fixed.html`. The demo adds an authored declaration,
`packaging>=24.2`, to the Packaging #788 reproduction. With 24.1 installed, `pip check` passes
but the declaration check and the test fail; after switching to the official 24.2 wheel the
original declaration is satisfied and the test passes.

This is a controlled version-mismatch scenario, not a fifth natural defect. The test and the
declaration stay unchanged; only the library version in the isolated environment changes.
The commands are in `scripts/demo_dependencies.py`.
