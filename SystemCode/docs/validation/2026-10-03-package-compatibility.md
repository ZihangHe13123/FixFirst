# Bounded pkg_resources compatibility repair

The `package-compatibility:pkg_resources` contract observes the actual failed
attribute or import instruction in the selected interpreter. It accepts the
setuptools-owned `pkg_resources/__init__.py` frame plus the standard-library
pkgutil receiver, or the actual missing `pkg_resources` import with absent or
removed provider metadata. Probed pytest collection, pytest calls, native
scripts/modules, and unittest can carry these records. Older text-only records
remain insufficient for installation advice.

The structured policy is in `knowledge/package_compatibility.toml`. The bounds
are `setuptools>=66.1,<82`; the supported policy scope is CPython 3.12.x. This
scope is an implementation/acceptance boundary, not an upstream claim that all
versions in the range support every Python or application.

Sources checked on 2026-10-03:

- [Setuptools 66.1.0 history](https://setuptools.pypa.io/en/stable/history.html#v66-1-0): fixes the removed pkgutil APIs on Python 3.12.
- [Setuptools 82.0.0 history](https://setuptools.pypa.io/en/stable/history.html#v82-0-0): removes pkg_resources.
- [Python 3.12 removal notes](https://docs.python.org/3.12/whatsnew/3.12.html#removed): pkgutil API removal and setuptools no longer provided by venv/ensurepip.

Project declarations, active target markers, selected extras and installed
Requires-Dist constraints intersect the policy range. Empty intersections name
their sources and produce no install command or replacement setuptools trial.
Unsupported Python, project Requires-Python conflicts, incomplete metadata,
shadowing and stale/imported evidence do not license a package change. Existing
local-code remedies remain available. Missing setuptools is classified as a
missing dependency; an old or removed provider is classified as a version
incompatibility only when current evidence and the policy match.

Commands remain manual pip requests and retain session log feedback. A failed
request cannot silently reopen an unbounded setuptools trial. Success still
requires pip check and the original check, interpreter and execution scope.

## Actual isolated acceptance

Executed on macOS with CPython 3.12.13 in fresh temporary virtual environments.
The exact generated commands were executed; this was not a prose-only review.

| Initial state and check | Generated request | Actual result |
| --- | --- | --- |
| setuptools 65.7.0, native script | setuptools>=66.1,<82 | pip selected 81.0.0; pip check and the same script scope passed |
| setuptools 65.7.0, pytest collection failure | setuptools>=66.1,<82 | pip selected 81.0.0; pip check and the original pytest scope passed |
| setuptools absent, native import | setuptools>=66.1,<82 | pip selected 81.0.0; pip check and the same script scope passed |
| setuptools 84.0.0, native import | setuptools>=66.1,<82 | explicit downgrade selected 81.0.0; pip check and the same script scope passed |
| project pin setuptools==65.7.0 | none | named requirements.txt:1 conflict; no install or trial |
| project pin setuptools==66.1.0, installed 65.7.0 | setuptools==66.1.0,>=66.1,<82 | exact lower bound installed; pip check and the same script scope passed |

Full command/stdout/stderr, pre/post runs, installation feedback and selected
versions are retained under `workbench/k6-acceptance/results.json`, with the
reproduction script in `workbench/k6-acceptance/run_acceptance.py` on the
implementation worktree. These receipts establish the listed cases only.

The targeted package, dependency, installation-feedback/source-build, tool,
Django and native-observer regression run passed 177 tests with 10 optional
Django runtime probes skipped. Ruff passed.
The original program/execution regressions passed 66 tests during the native
observer change. Integrated full-suite and native Windows acceptance are
separate gates.

The native observer preserves tested entry globals, argv/orig_argv, stdin, cwd,
script/module import paths, SystemExit and custom exception-hook behavior.
It loads diagnostic helpers after failure, observes only supported exact builtin
exceptions with safe arguments, and skips structured capture when a loaded local
module shadows the standard library. It preserves the existing exit-zero
program-success meaning; it does not establish application correctness.
