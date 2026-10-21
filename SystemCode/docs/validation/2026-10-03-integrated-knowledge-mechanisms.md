# Integrated knowledge-mechanism validation

Source candidate: `bec27b8b0b7d579871c95d1dc9413294467f48e8`.
Base: `c8de5a0d5a98ce50d59c853b0625dfbec287c445` on
`codex/v08-core-integration-20261002` (the existing v0.8 production changes).
This document was added after validation; it does not change the tested source.

## Delivered behavior

- Object removal diagnoses require the actual failed receiver, its qualified
  library identity, and matching current execution/environment/project evidence.
  Local `Report.readfp` and `EntryPoints.items` retain code-defect diagnoses.
  Real ConfigParser, Thread, unittest, pandas and NumPy examples retain supported
  removal guidance. Ordinary module/import-name diagnosis remains available.
- Native script and module failures can supply structured evidence without
  preloading project imports. Entry arguments, stdin and the original check scope
  are retained. Custom exception hooks remain in control.
- Observed setuptools/pkg_resources failures on CPython 3.12.x receive a bounded
  `setuptools>=66.1,<82` resolver request intersected with applicable declarations
  and installed dependency constraints. Missing, obsolete and removed providers
  are distinguished. Conflicts produce review guidance without an install command.

The [ownership contract](../superpowers/specs/2026-10-03-removal-ownership-validation.md)
and [package policy validation](2026-10-03-package-compatibility.md) describe the
specific guards, official sources and implementation-level examples.

## Integrated gates

Fresh macOS environment: CPython 3.12.13; project installed with `dev,notebooks`
extras, plus uv, httpx and pandas 2.3.3.

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python -m ruff check src tests scripts experiments
git diff --check c8de5a0 HEAD
```

- Full regression: **1471 passed, 12 skipped**, 176.83 seconds.
- Ruff and diff checks: passed.
- Default diagnosis model is byte-identical to the base:
  SHA-256 `4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3`.
- No classifier feature declarations or model training changed.

## Independent acceptance

The script and representative knowledge fixture were frozen before the candidate
was supplied. The original run retains **30 PASS / 1 FAIL** records (29 concrete
checks and two completion records). Its single failing assertion searched only
the explanation for a downgrade warning; the visible title already explicitly
said `Downgrade setuptools within the pkg_resources compatibility range`.

A separately hashed supplement checked the title plus explanation, then executed
the already saved command. It passed. The original script and failure receipt
were retained, not relabelled as an unchanged 31/31 run. No production change was
needed for this assertion correction.

| Concrete execution | Observed outcome |
| --- | --- |
| Local same-name classes, fake message, shadowing | No confirmed external removal; local code guidance retained |
| Imported, stale, absent, conflicting or mixed-run ownership | Cannot authorize object removal |
| Real ConfigParser instance/class and Thread | Correct removal guidance; ConfigParser repair passes the same scope |
| Old setuptools, project pin `==68.2.2`, native script | Generated command installs 68.2.2; pip check and original scope pass |
| Old setuptools, project range `>=66.1,<70`, pytest | Generated command installs 69.5.1; pip check and original scope pass |
| Missing provider, native import | Generated command installs 81.0.0; pip check and original scope pass |
| Removed provider at 84.0.0 | Explicit downgrade; saved command installs 81.0.0; pip check and original scope pass |
| Old fixed pin, contradictory constraints or required `>=82` | Conflict is shown; no setuptools install command |
| Direct project pkgutil use, local shadow, unrelated missing import | No borrowed setuptools repair |

The independent production-diff review found no blocker in this bounded scope.
Commands were executed verbatim, including the generated pip log arguments.
Receipts, frozen scripts and hashes are retained in the private workbench handoff;
the public regression tests contain reproducible mechanism checks.

## Interpretation and handoff

These checks establish the listed repairs and negative boundaries. They do not
measure a population success rate, prove every version in the candidate interval,
or establish native Windows acceptance. Linux CI is a separate gate.

The proposed bulk knowledge expansion remains separate. Its authors should use
qualified `owners` for bare attributes and short class names, run corrected
replacement checks, and preserve their verification receipts. The default
44-feature classifier remains unchanged. No LLM, training run, formal A2/B3/B7
evaluation, or held-out task was used in this change.
