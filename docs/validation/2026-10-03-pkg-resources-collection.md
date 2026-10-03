# pkg_resources collection binding repair (E1/E2)

Baseline: `ce69894356fbef2e7697839857a9b2ed4f120582` from PR #62.
This is a targeted acceptance repair; no knowledge entries, model features,
dependency-trial behavior or array diagnosis are changed.

## Reproduced cause

On CPython 3.12.13 / pytest 9.1.1, collecting a test with a top-level
`import pkg_resources` and no installed setuptools produced:

- event code: empty string; message: `ModuleNotFoundError: No module named 'pkg_resources'`;
- structured outer exception: `_pytest.nodes.CollectError`, raised in `_pytest/python.py`;
- captured package operation: `missing_pkg_resources`, actual `ModuleNotFoundError`,
  failed `IMPORT_NAME` in the test file at line 1, `wrapper=pytest_collect_error`.

The import branch of `exception_event` omitted the code. Normal structured
exceptions subsequently supplied it, but the collection wrapper deliberately
did not overwrite the underlying parsed exception. The package contract then
correctly rejected the incomplete event type. The removed provider at setuptools
84 followed the same path. Prior acceptance covered native absence/removal and
the old-setuptools AttributeError collection path, missing this combination.

## Change

The parser now preserves `ModuleNotFoundError` as the import event code.
This parsed text remains insufficient to authorize a package change: the actual
failed instruction and executed record are still required.

For the existing, exact pytest CollectError wrapper only, the probe separately
records the underlying exception's type and innermost source point. The policy
checks that point against the package operation, the outer wrapper against its
own innermost frame, and the event against the wrapper's collection node and
stage. Direct exceptions keep the existing type/location checks.

## Targeted validation

`test_package_collection.py` plus the existing `test_package_compatibility.py`:
**72 passed**, with explicit disposable interpreters supplied for absent
setuptools, setuptools 84.0.0 and setuptools 65.7.0.

The live pytest probes cover test-file top-level import, imported-module top-level
import, two-hop import, from-import, test-call and conftest import, plus the
collect-only goal. Negatives mutate the operation location, independent exception
location/type, wrapper identity/location, event type/node and a grouped member;
real manually raised messages cannot fabricate an observed import.

The existing compatibility tests retain native execution, unsupported Python,
project/Requires-Python/transitive pins, imported/stale records, local shadowing
and installation-feedback contracts. The new live matrix generates bounded
commands but does not execute them. Independent command execution and the
integrated full-suite gate are performed by the root task after this commit.

The runtime tests never install packages themselves. For the optional installed
provider matrix, set `FIXFIRST_PKG_RESOURCES_REMOVED_PYTHON` and
`FIXFIRST_PKG_RESOURCES_OLD_PYTHON` to disposable CPython 3.12 interpreters with
pytest and the exact named setuptools version. The absent environment can be
selected with `FIXFIRST_PKG_RESOURCES_ABSENT_PYTHON` or defaults to the test
interpreter when its provider is absent.

Repair-worktree receipts: `workbench/e1-collection/before-root.json` and
`workbench/e1-collection/after-root.json` retain the original failure and the
first successful bounded advice with the added source point.
