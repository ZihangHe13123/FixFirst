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

**Grading for B17** (fixed before the freeze, applied after it). Two questions are scored
separately: whether a method picks the right problem (ordering), and whether the step it proposes
is itself right (advice). A step that picks the right problem with the wrong action counts for the
first and against the second.

*Acceptable orders* are all orders consistent with "hidden by"; no single order is the answer.

*Ordering: which problem comes first.*

- The fault *behind* an issue is the observable required fault whose repair alone makes that issue
  go away in the next check (`multi_cases.targeted`). The observable texts in the table only show
  that a fault is visible; one fault can break several tests with different messages.
- *First issue right*: the first step's issue has a fault behind it that is observable now.
- *Wrong-issue attempts before the goal* (`multi_cases.replay`): let the method pick an issue;
  when a fault is behind it, apply that fault's reference repair, otherwise (a hidden fault, the
  optional lint finding, an issue behind no required fault) apply nothing and count one attempt.
  Check again and repeat until every required fault is repaired, at most 10 steps. The reference
  repair stands in for whatever the method suggested, so this measures the choice of problem only,
  never whether the advice was right.
- Baselines (ordering only; they propose no action): *message order*, the first failure in
  pytest's output as FixFirst's parser read it; *fixed category order*, each issue's root cause
  from its parser category alone (FixFirst v0.3), in the order missing dependency, local module,
  version, configuration, code defect, then Ruff findings, ties in message order.

*Advice: is the proposed action right.* Scored only for methods that propose actions (FixFirst,
and the language models of B3/B7), and never by putting the reference repair in place of the
method's action.

- *First step correct*: the first step's issue has a fault behind it that is observable now, and
  the action itself is one of that fault's allowed repairs (the table above). The action is judged
  as written: for FixFirst from the action's kind, target and command; for a model from its text,
  by two raters with the allowed repairs and without knowing which method wrote it. An action that
  is not an allowed repair is *wrong* even when it is attached to the right issue: for example
  `pip install helper` for the renamed helper module in M1. Advice that names no concrete change
  (re-run the tests, check the environment) is *generic*.
- If a replay that follows the method's own actions is reported, a step changes the project only
  when its action is an allowed repair of the fault behind its issue; any other step changes
  nothing and counts as an invalid attempt, at most 10 steps; a method that does not reach the goal
  is reported as such.

**What these cases can measure** (development check, 29 September, before any FixFirst ordering
result): both naive baselines were replayed on M1–M5 (`multi_cases.baseline_report()`). Both picked
a right first issue in 5 of 5 cases, made no wrong-issue attempts and reached the goal in every
case. In these cases a collection error hides everything behind it, the faults visible together
(M2, M4) may be repaired in either order, and the only decoy is the optional lint finding, which
neither baseline picks. So **the ordering measures cannot show an advantage over the naive
baselines on this suite**; B17 reports that as it is. M1–M5 are not changed or extended after
this check to create an advantage; the other data on B17's task card (the playground project and
the two-layer hard cases) are used as planned. What the suite can still show: whether a method's first step
picks a hidden fault or the optional lint finding (the baselines do not), and whether its actions
are allowed repairs (advice).

The same check found a flaw in the first version of this grading, which decided the fault behind
an issue from the observable text alone: after `env_missing` is repaired, `total_off_by_one` also
fails `test_<function>` (for example `8 != 6` in M4), which the text `4 != 3` does not match, so
both baselines were counted wrong from then on and never reached the goal in M2 and M4. The rule
above (the repair that makes the issue go away) replaced it before the results were used for
anything.

**Validation.** When the suite is built, every case is checked by real runs: the faults that should
be observable are, the hidden ones are not, repairing each layer reveals exactly the next one, and
repairing everything makes the tests pass. A case that behaves otherwise is rejected and listed in
the manifest.

## After B4

At the freeze (B5), the diagnosis dataset is regenerated with the final 44 scenarios, the bundled
decision tree is retrained on it and the committed evaluation is updated (B6). Until then, the
committed 215-case dataset and its report describe the 43-scenario set without H09.
