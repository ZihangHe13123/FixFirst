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

## Integrated and independent results

Tested source: `d44ab2110fbf362f52b46464e1264179ca9fce2b`. The later documentation
commit does not change this tested production code.

- Full macOS/CPython 3.12.13 regression, with all three explicit provider
  interpreters: **1507 passed, 12 skipped**, 153.78 seconds. All 36 new collection
  tests executed. Skips were 10 optional Django runtime probes, the opt-in
  toolchain environment builder, and the Windows PowerShell test.
- `ruff check src tests scripts experiments` and `git diff --check`: passed.
- Default 44-feature model is unchanged, SHA-256:
  `4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3`.

The independent 13-case inputs were frozen before execution. The retained
original run has **5 PASS / 8 FAIL** on `ce69894`, and **12 PASS / 1 FAIL** on the
fixed source. The remaining failure is a fixture-root boundary described below;
the original result is not relabelled as an unchanged 13/13 run.

The fixed candidate's ten repair commands were executed verbatim in fresh
CPython 3.12.13/pytest 8.3.5 environments. Each installed setuptools 81.0.0, passed
pip check and the original check scope. Coverage includes direct test/module
imports, from-import, two-hop imports, collect-only, provider removal at 84, and
the old65/native/function/conftest controls. Collect-only proves collection;
it is not labelled as passing test assertions.

The other three cases confirm that a manually fabricated error cannot borrow a
repair and that `setuptools>=82` blocks installation, both with and without a
representative knowledge entry. The latter no longer leaves a generic
`install setuptools<82` suggestion after the constraint conflict is established.

The collect-only fixture initially inherited pytest's root directory from the
repository above its workbench. Its actual install, pip check and collection
succeeded, but existing goal bookkeeping could not match the prefixed node IDs
to the fixture's recorded tests. A separately hashed supplement fixed the
fixture root with an empty pytest.ini and replayed this same case on both
candidates. The old source still lacked a repair; the fixed source installed,
passed pip check, collected in the same scope and reached goal=achieved with an
unchanged baseline. The original failure receipt is retained. This patch does
not change the nested-root bookkeeping behavior.

Frozen scripts, original/supplementary results and checksums are retained in
the private `workbench/codex-pr62-e1-20261003/acceptance/` handoff. No LLM,
training run, formal experiment, held-out task or bulk knowledge activation
was part of this acceptance. Native Windows acceptance remains separate.
