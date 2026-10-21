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

## Phase 2: FixFirst on real defects (9 to 10 October 2026)

Every count below comes from `results.csv` in this folder, one row per bug, version and way of
use. No language model was involved. A bug is prepared as in phase 1; FixFirst checks the project
with the goal "make the tests pass" before the fix and again after the BugsInPy patch is applied.
Two things are judged per bug:

- **No environment advice for a code defect**: no required step with a command that installs,
  upgrades or pins a package.
- **Closed only when repaired**: FixFirst has an issue for the bug's failing test, the issue is
  open before the fix and resolved after it.

One deviation from the task card: the card names v0.7.0. Phase 2 was run on the version the
agent experiment used, 0.8.0rc2 (`5c224cf`, tag `b7-freeze-20261007`), and on the three versions
that followed.

### 2.1 The frozen 0.8.0rc2 on the 27 phase-1 bugs

All 27 bugs reproduced again (Python 3.9.6). PySnooper 2 was seen during development and is kept
apart.

| Check | 27 bugs not seen before | PySnooper 2 (dev) |
|---|---|---|
| No environment advice with a command | 27 | 1 |
| Open before the fix, resolved after it | 0 | 0 |

The second line is not a wrong verdict but a missing one. In 24 of the 27 bugs FixFirst's own
check never ran the failing test:

| Project | Bugs | What the default pytest run did |
|---|---|---|
| tqdm | 9 | Collected no test: the files are named `tests_*.py` and the project uses nose |
| tornado | 15 | Stopped during collection on two helper files under `maint/` |
| cookiecutter | 3 | Ran the whole suite |

For the three cookiecutter bugs the issue stayed open before the fix and was not marked resolved
after it: two waited for verification because the check had not used the project's own pytest
options, one was not observed again. Nothing was closed that was not repaired.

On real repositories the problem therefore lay before diagnosis: FixFirst could not be told
which tests to check. This decided the next version.

### 2.2 What changed afterwards

| Version | Commit and tag | Change that matters here |
|---|---|---|
| 0.8.0rc3 | `7baaec9`, `b12-freeze-20261010` | The tests to check can be named (`--tests`, the MCP `diagnose` tool, the web form); one rule narrowed; a crash while cleaning up child processes fixed |
| 0.8.0rc4 | `1cad89a`, `b12-rc4-freeze-20261010` | The pytest plugin no longer depends on environment variables while tests run |
| 0.8.0rc5 | `646c12a`, `b12-rc5-freeze-20261010` | pytest from 3.2.1; test names of pytest 3.x classes; large suites keep their failure records; a second run with the project's own pytest options confirms a repair |

The decision tree and the feature computation are the same file in all four versions.

### 2.3 Three held-out tests

Each set was chosen by reproduction only, sealed, and used once, on a version frozen before the
test. FixFirst was not run on a bug while the set was chosen. Every bug and way of use had its own
copy of the code, environment and home directory. The second and third test ran without network
access. "Tests named" means FixFirst was given the test that BugsInPy lists for the bug.

| | Version tested | Material | 0.8.0rc2, default use: saw the failure / closed correctly | Tested version, tests named: saw the failure / closed correctly |
|---|---|---|---|---|
| Test 1 | 0.8.0rc3 | 19 bugs in 3 projects not used before (fastapi, httpie, thefuck) | 2 / 2 | 10 / 9 |
| Test 2 | 0.8.0rc4 | 28 bugs in 6 projects not used before (ansible, black, luigi, sanic, scrapy, youtube-dl) | 5 / 3 | 27 / 21 |
| Test 3 | 0.8.0rc5 | 28 new bugs in 7 projects used before | 10 / 4 | 28 / 27 |

With the tests named, no bug in any of the three tests got environment advice with a command, no
wrong cause was stated without the "unconfirmed" mark, and no issue was closed that was not
repaired.

What each test ran into, and what it led to:

- **Test 1.** thefuck 0 of 8: the project's `conftest.py` replaces the environment variables for
  every test, and the plugin lost the path of its record file (fixed in 0.8.0rc4). httpie 1: its
  environment has pytest 3.2.1, which rejects an option FixFirst passed (fixed in 0.8.0rc5).
  fastapi 1: the fix also changes a test file, so FixFirst reports that the tests changed and
  does not close.
- **Test 2.** scrapy 0 of 5 closed: the project sets its own pytest options and FixFirst would
  not confirm a repair it had checked without them (fixed in 0.8.0rc5). sanic 1 does not
  reproduce without network access and counts as not passed by the rule registered beforehand.
  ansible 5: the fix changes a test file. 0.8.0rc3 and 0.8.0rc4 gave the same result on every
  bug of this set.
- **Test 3.** luigi 9: the fix changes a test file. The four scrapy bugs close on 0.8.0rc5 and
  wait for verification on 0.8.0rc4; the other 24 bugs are the same on both.

How to read the table:

- **The three lines are not one rising curve.** Versions and material differ. Test 3 has no new
  project; the first two tests each met a problem nobody knew of in a new project, which the
  material of the third cannot do.
- **The default-use column is low partly because of the setup.** Each environment holds only the
  packages the bug's own test needs, and tests 2 and 3 had no network, so a default run often
  stops at a package some other test imports. How much default use sees in a complete development
  environment was not measured.

### 2.4 The used bugs as development data

The 75 bugs used up to test 2 (27 + PySnooper 2, 19, 28), on 0.8.0rc5:

| | Tests named | Default use |
|---|---|---|
| Saw the failing test | 74 | 25 |
| Open before the fix, resolved after it | 69 | 8 |

The one not seen is sanic 1 (not reproduced offline). The five seen but not closed with the tests
named are all fixes that also change a file the project counts as a test (fastapi 1, ansible 5,
tornado 13, scrapy 4 and 5; scrapy's own configuration counts every `__init__.py` as a test
file, so `results.csv`, which looks at BugsInPy's test paths only, says "no" for these two). These
numbers are not held-out results: the versions were changed after looking at these bugs.

### 2.5 Against the proposal

The proposal asks for the check "repaired means verified" on at least 8 real defects in at least
4 libraries. Before phase 2 there were four upstream regressions in packaging and click
(`examples/historical-regressions/`).

- With the tests named, the frozen versions closed 9, 21 and 27 held-out bugs correctly, in 2, 5
  and 7 projects, and closed none wrongly.
- In default use on these repositories the check mostly does not get as far as the failing test.

### 2.6 Problems found and limits that remain in 0.8.0rc5

- A fix that also changes a file the project counts as a test is reported as "the tests changed"
  and not closed. This protects against passing by editing tests.
- In default use: one rule (D16) still states a wrong cause without the "unconfirmed" mark when a
  missing module resembles a project file (5 of 28 bugs in test 3); an incomplete environment
  stops the run at packages other tests need; a very large suite reaches the record limit, which
  is now said, and the repair cannot be confirmed. None of the three occurs with the tests named.
- When no rule matches, the tree's guess is sometimes wrong. It is marked "unconfirmed" and comes
  without a command.
- pytest before 3.2.1 is not supported (said in the output). Windows was not tested.
- BugsInPy used Python 3.6 to 3.8; every run here uses Python 3.9.6 with the test packages the
  bug's own test needs.

## Files

| File | Content |
|---|---|
| `attempts.csv` | Phase 1: every attempt to reproduce a bug, the failed ones included |
| `results.csv` | Phase 2: one row per bug, FixFirst version and way of use (459 rows) |
| `heldout/selection-1.json`, `-2`, `-3` | The bugs of each held-out test as they were chosen and sealed: project, number, installed packages, the bug's tests, the fixed commit. Byte for byte the sealed files |
| `heldout/attempts-1.csv`, `-2`, `-3` | Every attempt made while a set was chosen, including bugs that did not reproduce or could not be built. The folder of the working copies is written as `<work>` |
| `tools/` | The scripts as they were run, unchanged |

`results.csv` gives, per row: whether the bug reproduced, whether FixFirst ran, whether it had an
issue for the bug's test, the issue's status before and after the fix, the number of required
steps with an environment command, the first step and its cause, and whether the cause was marked
unconfirmed. The records of the single runs (FixFirst's sessions, test output, console logs) are
not in the repository; they contain paths of the machine they were made on.

The scripts mention a "registry" and its addenda. That is the log of this check, kept outside the
repository, in which each rule was written down before the run it governs.

## Running a set again

A set needs a checkout of each FixFirst version with its own `.venv` (the product installed in
it), [uv](https://docs.astral.sh/uv/) and network access while the environments are built. The
first test used `tools/heldout_case.py` (the default) and no `--offline` or `--mid`; the second
and third were run as below, with 0.8.0rc3 and 0.8.0rc4 as the version in between.

```bash
cd examples/bugsinpy-verification
# build every environment and reproduce every bug; FixFirst is not run
python tools/heldout_test.py OLD NEW heldout/selection-3.json TARGET --phase prepare \
    --case-script heldout2_case.py --mid MID
# the same without network, to see that each bug still reproduces
python tools/heldout_test.py OLD NEW heldout/selection-3.json TARGET --phase prepare --offline \
    --case-script heldout2_case.py --mid MID
# the test itself
python tools/heldout_test.py OLD NEW heldout/selection-3.json TARGET --phase run --offline \
    --case-script heldout2_case.py --mid MID
python tools/heldout_check.py TARGET heldout/selection-3.json
```

`OLD`, `MID` and `NEW` are the checkouts (for the third test: tags `b7-freeze-20261007`,
`b12-rc4-freeze-20261010`, `b12-rc5-freeze-20261010`); `TARGET` is an empty folder outside the
repository. Each run gets a new home directory, because a project's tests may write there. Phase
2.1 is `tools/b12_phase2.py TREE TARGET` followed by `tools/b12_phase2_check.py TARGET`.
