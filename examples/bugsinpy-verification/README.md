# BugsInPy verification (task B12)

Real code defects from [BugsInPy](https://github.com/soarsmu/BugsInPy/tree/11c5f1eea954a42132cfd06bf257766a7963e0fd)
(commit `11c5f1e`), prepared the way BugsInPy defines a bug: the fixed commit with the bug's
patch reversed, so the tests are the fixed ones and the source has the bug. A bug counts as
reproduced only when its test fails on the buggy source and passes once the patch is applied
again, in the same environment. See [the task card](../../docs/tasks/B12-bugsinpy.md) and
`scripts/bugsinpy_case.py`.

## Phase 1: reproduction without FixFirst (29 September 2026)

Python 3.9.6 (macOS), environments built with uv. BugsInPy used Python 3.6–3.8; FixFirst supports
target interpreters from 3.9, so every bug is run on 3.9 and only bugs that reproduce there are
used. `attempts.csv` lists every attempt, including the failed ones.

| Project | Tried | Reproduced | Test packages that worked |
|---|---|---|---|
| tqdm | 9 | 9 | pytest, nose |
| cookiecutter | 4 | 3 (2, 3, 4) | pytest, pytest-mock, freezegun, pytest-cov |
| tornado | 16 | 15 (all but 3) | pytest<8 (pytest 9 cannot collect this tornado's test classes; 5, 6, 9 and 14 also reproduce with pytest 9) |
| PySnooper | 3 | 1 (2, marked dev) | pytest, python_toolbox, six |

Not reproduced: cookiecutter 1 and tornado 3 pass their tests on the buggy source; PySnooper 1
passes on Python 3.9 / macOS; PySnooper 3's fixed commit is gone from the upstream repository.

FixFirst has not been run on any of these bugs except PySnooper 2 (seen while the script was
being written). Together with the four upstream regressions in packaging and click, the 27
reproduced bugs in three more projects give enough defects for the proposal's verification
check ("at least 8 defects in at least 4 libraries"); the check itself is phase 2.

## Phase 2: FixFirst on the frozen version (after 10/9)

To do after v0.7.0 is tagged: run each reproduced bug without `--no-fixfirst` and record whether
the bug's issue stays open while the test fails and closes only after the fix is verified, and
whether FixFirst suggests any install, upgrade or pin for these code defects.
