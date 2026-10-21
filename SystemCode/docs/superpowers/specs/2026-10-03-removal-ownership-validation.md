# Removal ownership implementation and validation

The D02/D03 removal rules now require an `issue -> removal_owner -> entity`
fact. A similarly named receiver in another issue cannot supply that fact.
Ordinary module-attribute and import-name diagnoses retain their established
path. Object/class diagnoses require the actual failed attribute operation,
its one executed exception record, and its matching same-run source statement.

The current selected interpreter's environment snapshot must precede the
failure. The project index must link to that snapshot; it may follow the
failure, as it does in the default scan. Unknown, imported, conflicting,
grouped, or stale receiver evidence does not authorize an object removal.
Provider identity must be unique, non-project, and consistent with the loaded
module's file inside the selected interpreter's recorded library directories.

## Knowledge contract

- Bare attribute names require qualified `owners`, for example
  `owners = ["configparser.ConfigParser", "configparser.RawConfigParser"]`.
- An API entry using a short class spelling also requires qualified `owners`:
  `module = "EntryPoints"` needs `owners = ["importlib.metadata.EntryPoints"]`.
- A fully qualified attribute or API already supplies its owner identity,
  for example `numpy.ndarray.ptp` or API module `importlib.metadata.EntryPoints`.
- The shipped `DataFrame.append` entry gains `owners = ["pandas.DataFrame"]`.
  No proposed bulk knowledge is merged; ConfigParser and EntryPoints additions
  are representative test fixtures.

The target observer records only registered class identities and actual public
aliases from already loaded parent modules. It reads Python's builtin type
descriptors directly, without invoking user properties, `__class__`, `dir`,
`__getattr__`, or import expressions. The supported metaclasses are builtin
`type` and the already loaded standard `abc.ABCMeta`. The MRO is capped at 16,
each namespace at 5,000 entries, parent module depth at 8, aliases at 8 per
module, and retained ownership records at fewer than 32. Over-limit identity
sets remain unknown.

Inherited standard-library ownership supports unittest assertion aliases.
Dynamic library classes and retained removal descriptors require an exact
registered concrete class, not a project subclass borrowing an MRO identity.
This preserves real pandas.DataFrame and NumPy 2.2 removal stubs. The general
operation projection and bounded-action consumers keep their stricter default
handling of dynamic or present members.

## Executed acceptance

The targeted regression command is:

```sh
.venv/bin/python -m pytest -q tests/test_removal_ownership.py tests/test_symbol_observations.py tests/test_observed_operations.py tests/test_input_diagnosis.py tests/test_source_context.py tests/test_reasoning.py tests/test_native_observer.py tests/test_program_execution.py
```

Result: **279 passed** on Python 3.12.13/macOS. Ruff on the changed Python
sources/tests and `git diff --check` also passed.

These tests execute ConfigParser/readfp, EntryPoints instance and class APIs,
inherited unittest aliases, pandas.DataFrame/append, and NumPy ndarray
removals. The corresponding supported manual replacements are executed again
in the same scope. Native script and module tests cover both real positives
and local Report/EntryPoints negatives. Additional cases reject fabricated
exception fields, missing owners, foreign module origins, provider conflicts,
local shadowing, own distributions, stale environments, ambiguous statements,
and grouped events. A default `scan()` positive covers its actual check order.

An additional Python 3.12.13 environment with NumPy 2.2.6 and pytest 9.1.1
executed the retained `ndarray.ptp` descriptor: it produced D03 and the
`numpy.ptp(array, ...)` guidance. Replacing `data.ptp()` with `np.ptp(data)` and
rerunning the same pytest scope achieved the test goal.

The default 44-feature model and feature declarations are unchanged. No formal
experiments, held-out datasets, or LLM comparisons were run. Native Windows
acceptance remains separate from the macOS runs and existing path-shape tests.
