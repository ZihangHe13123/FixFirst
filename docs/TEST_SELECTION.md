# Run the tests that failed

For `pass_tests`, save project test files or pytest node IDs. They need not have been
observed before. Each check uses the selected project Python. Files must be inside
the project; shell commands, options, directories and symlinks are rejected.

## Command line

```sh
fixfirst init /path/to/project --goal pass_tests --tests tests_ledger.py
fixfirst scan SESSION
fixfirst configure SESSION --tests tests/test_orders.py::test_total
fixfirst scan SESSION
```

The existing command `fixfirst scan SESSION --checks pytest_run --nodes
tests/test_orders.py::test_total` also saves the selection, including unseen files
or nodes. Later `fixfirst scan SESSION` reuses it. Use `fixfirst configure SESSION
--tests` to return to default discovery. Quote paths or node IDs containing spaces
or shell metacharacters.

## MCP

Add optional `tests` to `diagnose`:

```json
{"project":"/path/to/project","goal":"pass_tests","tests":["tests_ledger.py","tests/test_orders.py::test_total"]}
```

`check_again` reuses the saved selection. A different selection in `diagnose` gets
its own session. Other tool names, arguments and descriptions remain unchanged.

## Python

```python
from fixfirst.service import create_session, scan
from fixfirst.test_selection import configure_tests

session = create_session("/path/to/project", "/path/to/project/.venv/bin/python",
                         goal="pass_tests", tests=["tests_ledger.py"])
scan(session)
configure_tests(session, ["tests/test_orders.py::test_total"])
scan(session)
```

## Web

Choose **Make my tests pass**, then enter one file or node ID per line in
**Tests to run**. An existing session has the same field under **Python and run
settings**. Save settings, then **Check again**.

## What a pass means

A complete passing check verifies the saved selection, not the entire suite.
Changing the selection or Python does not close failures in an earlier scope.
Skipped, deleted or incomplete tests do not confirm a repair. FixFirst still
uses its bounded pytest options; if the project's usual options differ, it
reports that limitation and keeps verification pending.

When default discovery finds no tests, the first step asks for a selection and
quotes identifiable test commands from project configuration, without executing
them. Missing pip/Ruff are optional for a default test check; pytest is required.
