# B4: generated cases added before the freeze

Definitions fixed on 29 September 2026, before the freeze (v0.7.0, 9 October). Everything here
uses generated projects and the 13 pilot projects only. The new held-out batch is kept by A and
C; the rule author does not see it before the freeze, and the formal evaluation after the freeze
is not used to change rules.

## Scope

Chosen on 29 September:

1. **One new diagnosis scenario family, "private API moved"** (`vi_private_moved`).
2. **A small multi-fault suite** for the next-step ordering evaluation (task B17):
   `fixfirst dataset --suite multi`.

Left out, and why: *old test tools on a new Python* and *an install failure that leaves the
declared dependencies missing*. The generator runs every case in FixFirst's own environment, so
modelling them would need a separate environment per case. Both occur in the pilot projects
(requests, jmespath, parsel) and are evaluated on real projects instead.

## 1. Scenario `vi_private_moved`

**Definition.** The project imports a private or internal name through a module path that the
installed library has moved or removed; the name still exists elsewhere in the library. Label
`version_incompatibility`. Not in the knowledge base.

**Variants**, one per template, each checked against the installed libraries (scikit-learn
1.9.0, pydantic 2.13.5, SciPy 1.18.1, NumPy 2.5.3) on 29 September:

| Template | Import added at module level | Failure when the tests are collected | Where the name is now |
|---|---|---|---|
| flat-shop | `from sklearn.utils import _print_elapsed_time` | `ImportError: cannot import name '_print_elapsed_time'` | `sklearn.utils._user_interface` (moved in scikit-learn 1.5; the pilot's imbalanced-learn failure) |
| src-billing | `from pydantic.fields import ModelField` | `ImportError: cannot import name 'ModelField'` | `pydantic.v1.fields` |
| pkg-inventory | `from scipy.sparse.sputils import isdense` | `ImportError: cannot import name 'isdense'` | `scipy.sparse._sputils` |
| unittest-grades | `from numpy.lib.function_base import iterable` | `ModuleNotFoundError: No module named 'numpy.lib.function_base'` | `numpy.iterable` |
| fixture-orders | `from sklearn.metrics.scorer import _check_multimetric_scoring` | `ModuleNotFoundError: No module named 'sklearn.metrics.scorer'` | `sklearn.metrics._scorer` |

**Allowed repairs** (any one): import the name from its new location; pin the library to a
release that still has the old path (for example through the release search); stop depending on
the private name. Not accepted: installing another package, renaming project files, changing
tests.

**Grading.** In the diagnosis dataset only the root cause is scored, as for every scenario. The
first step is reported separately: correct when it names the library and proposes one of the
allowed repairs; generic advice counts as generic.

**FixFirst before B4** (development check, 29 September): the three `cannot import name`
variants got H01 and a release search (an allowed repair). The two missing-submodule variants
got the decision tree's suggestion (right cause, marked unconfirmed) and a generic first step.

### Rule added: H09

*A submodule of an installed third-party library cannot be found: the installed version
probably moved or removed it.* It needs a `ModuleNotFoundError` for a dotted module whose
top-level package an installed distribution provides and which is not a project file, and no
diagnosis so far. It concludes a likely version incompatibility (shown as unconfirmed), so the
existing release search (P58) is offered when the imported name is known. The evidence now
records which package a missing submodule belongs to (`submodule_of`), so the rule cannot pick
up an unrelated module from the traceback.

H09 was written after seeing `vi_private_moved` and the older `vi_unknown_submodule`, so results
on those two scenarios are development results, like H07 and H08.

### Development effect (29 September, not a held-out result)

On the committed 215 cases, H09 changes one scenario only: `vi_unknown_submodule` goes from
wrong to right under the heuristic phase, and the hybrid's leave-one-scenario-out accuracy rises
from 0.930 to 0.954. Regenerating the dataset with `vi_private_moved` gives 220 cases; the new
scenario is right in 5 of 5 with the heuristic phase and with the hybrid (0.955 overall). Both
figures come from rules written after seeing these scenarios.

## 2. Multi-fault suite (for B17)

**Purpose.** Next-step ordering needs projects with several faults, where some faults hide
others. Each case lists its faults, which fault hides which, the allowed repair of each and the
text that shows a fault is observable.

**Faults**, applied to the template's own files:

| Fault | Root cause | Where it shows | Observable when the output contains | Allowed repair |
|---|---|---|---|---|
| `renamed_helper` | local_module | collection | `No module named '<helper module>'` | move the helper file back, or import the new name |
| `stdlib_removed` | version_incompatibility | collection | `No module named 'imp'` | remove the import (use importlib) |
| `private_moved` | version_incompatibility | collection | `cannot import name '_print_elapsed_time'` | import from `sklearn.utils._user_interface` |
| `numpy_alias` | version_incompatibility | run: `test_<function>` | `has no attribute 'float'` | use the builtin `float` |
| `env_missing` | config_missing | run: `test_<function>` | `KeyError: '<ENV>'` | provide a default for the variable |
| `total_off_by_one` | code_defect | run: `test_<class>_total` (and `test_<function>` once nothing else fails first) | `4 == 3` or `4 != 3` | restore `sum(self.values)` |
| `lint_unused` (optional) | none: style only | Ruff F401 | `F401` | remove the unused import; not needed for the goal |

**Cases.** "Hidden by" means the fault cannot be observed until the listed faults are repaired.

| Case | Template | Faults (hidden by) | Acceptable repair orders |
|---|---|---|---|
| M1 | flat-shop | `renamed_helper`; `numpy_alias` (renamed_helper) | 1 |
| M2 | src-billing | `private_moved`; `env_missing` (private_moved); `total_off_by_one` (private_moved) | 2: after `private_moved`, the other two in either order |
| M3 | pkg-inventory | `stdlib_removed`; optional `lint_unused` | 1 required fault; fixing the lint first is an invalid attempt |
| M4 | unittest-grades | `env_missing`; `total_off_by_one` | 2: either order |
| M5 | fixture-orders | `renamed_helper`; `private_moved` (renamed_helper: same module, later line); `numpy_alias` (private_moved) | 1 |

**Grading for B17** (fixed now, applied after the freeze):

- *Acceptable orders* are all orders consistent with "hidden by". No single order is the answer.
- A step *targets* a fault when one of its issues shows the fault's observable text.
- *First step reasonable*: the first step targets a required fault that is observable now.
- *Invalid attempts before the goal*: follow the method's first step, apply the allowed repair of
  the fault it targets, check again, and repeat until every required fault is repaired (at most
  10 steps). A step that targets no observable required fault (a hidden fault, an optional lint
  finding, generic advice) counts as one invalid attempt.
- Baselines: *message order* (the first failure in pytest's output) and *fixed category order*
  (missing dependency, local module, version, configuration, code defect, then style).

**Validation.** When the suite is built, every case is checked by real runs: the faults that should
be observable are, the hidden ones are not, repairing each layer reveals exactly the next one, and
repairing everything makes the tests pass. A case that behaves otherwise is rejected and listed in
the manifest.

## After B4

At the freeze (B5), the diagnosis dataset is regenerated with the final 44 scenarios, the bundled
decision tree is retrained on it and the committed evaluation is updated (B6). Until then, the
committed 215-case dataset and its report describe the 43-scenario set without H09.
