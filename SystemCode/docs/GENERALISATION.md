# Does FixFirst generalise? A held-out check on 13 real projects

The diagnosis experiment (examples/diagnosis-evaluation) uses generated projects, and the
earlier real-project walk-throughs (docs/REAL_PROJECTS.md) fixed FixFirst while testing it.
Neither shows how it does on projects it has never seen. This check does.

## Set-up

13 open-source projects were chosen on 24 September 2026 to differ in domain, layout, way of
declaring dependencies and Python version (examples/real-world/projects.toml). Each is
installed the way its own files tell a user to, with today's releases wherever it does not pin
a version: what a newcomer following the README gets. `scripts/setup_real_world.py` rebuilds
them; the installed versions are in examples/real-world/environments/.

| Project | Domain | Layout / declarations | Python |
|---|---|---|---|
| flask-sqlalchemy 2.5.1 | Web: Flask extension | package, setup.py | 3.12 |
| django-model-utils 4.0.0 | Web: Django app | package, setup.py, requirements files | 3.11 |
| requests 2.25.1 | HTTP client | package, setup.py, requirements-dev.txt | 3.12 |
| seaborn 0.11.2 | Data visualisation | package, setup.py, requirements.txt | 3.12 |
| imbalanced-learn 0.8.1 | Machine learning | package, setup.py extras | 3.12 |
| typer 0.3.2 | Command-line tools | package, pyproject.toml (flit, old format) | 3.10 |
| aiostream 0.4.5 | Async programming | package, setup.py tests_require | 3.12 |
| jmespath 0.10.0 | Query language | package, setup.py, requirements.txt | 3.12 |
| parsel 1.6.0 | Web scraping | package, setup.py (project fails to install) | 3.12 |
| records 0.5.3 | Databases | single module, setup.py, Pipfile | 3.12 |
| cachetools 5.5.0 | Utilities | src layout, setup.cfg (project not installed) | 3.9 (macOS system) |
| more-itertools 10.7.0 | Utilities (healthy) | package, pyproject.toml (flit) | 3.14, no pip (uv) |
| attrs 25.3.0 | Utilities | src layout, pyproject.toml (hatch) | 3.13 |

**Protocol.** The ground truth (examples/real-world/LABELS.md) was written from plain pytest
output and committed before FixFirst was run on any of these projects, together with the
scoring rules; FixFirst's code was unchanged between that commit and the first run. Only the
first thing FixFirst tells the user is scored: the headline and the first must-fix step. One
label (attrs) was corrected while checking it, before FixFirst's result for it existed; the
correction is recorded in LABELS.md.

## Round 1: FixFirst as it was (held out)

`scripts/run_real_world.py` ran the same checks as the web page's "Check again" with the goal
*Make my tests pass*. Raw results: examples/real-world/results-round1.json.

| Project | Headline | FixFirst's first step | Score |
|---|---|---|---|
| seaborn | 1 problem | Replace distutils: removed in Python 3.12 (`seaborn/rcmod.py:4`, rule D01) | **Correct** |
| flask-sqlalchemy | 4 problems | Try an older flask: `pip install 'flask<3'` (heuristic H01) | **Correct**, hedged. Headline wrong: 1 problem, not 4 |
| django-model-utils | 4 problems | Try an older django: `pip install 'django<5'` (H01) | **Partial**: Django 4.2 still lacks `ugettext_lazy` |
| imbalanced-learn | 3 problems | Try an older scikit-learn: `pip install 'scikit-learn<1'` (H01) | **Partial**: scikit-learn 0.24 does not install on Python 3.12 |
| requests | 1 problem | Replace imp: removed in Python 3.12 (D01) | **Partial**: right cause, but `imp` is used by pytest 3.10.1, not by the project |
| typer | 1 problem | Check the import path and dependency declarations (classifier hint: missing dependency) | **Generic** |
| parsel | 3 problems | Check the import path and dependency declarations | **Generic** |
| records | 1 problem | Inspect the exception raised while running the test | **Generic** |
| aiostream | 3 problems | Compare the failed assertion's expected and actual values (D40) | **Wrong** |
| jmespath | 7 problems | Install Python below 3.12: `pip install 'Python<3.12'` (D01) | **Wrong**: pip cannot install Python (the cause, nose using `imp`, is right) |
| cachetools | 1 problem | Record the current Python environment first | **Wrong**: FixFirst's own environment snapshot fails on Python 3.9 |
| more-itertools | 1 problem | Check that the tool is available and ran to completion | **Wrong**: false alarm on a healthy project (670 tests pass) |
| attrs | 1 problem | Compare the failed assertion's expected and actual values (D40) | **Wrong**: the tests cannot find the `mypy` command |

**Summary: 2 correct (1 confirmed, 1 hedged), 3 partial, 3 generic, 5 wrong out of 13.** The
root cause was named correctly in 6 of the 13 (the correct and partial ones, plus jmespath),
but the first step worked as given in only 2. For comparison, the rule + knowledge + tree
hybrid scores 93% on the generated dataset's unseen fault types: generated single-fault
projects are far easier than real ones.

### Why round 1 went wrong

Each cause is general, not specific to one project:

1. **FixFirst's own compatibility.** The environment snapshot uses
   `importlib.metadata.packages_distributions`, which Python 3.9 lacks (cachetools). The pytest
   probe writes one record per pytest 9 subtest; more-itertools' 12,037 subtests overflow the
   record budget, so the run is not trusted and a healthy project gets a problem. Tests run
   without the environment's `bin` folder on `PATH`, so tests that start a command (attrs:
   `mypy`) fail although they pass in an activated environment.
2. **Evidence.** When the error names the missing name, the other names of the same import
   line were also treated as missing (flask-sqlalchemy's 4 problems are 1). Tracebacks that
   are not in pytest's format (pytest or a plugin crashing at start-up) were not read, so the
   failing library and location were unknown (requests, django-model-utils).
3. **Declarations.** Dependencies declared in `setup.py` (9 of the 13 projects) and in flit's
   old `[tool.flit.metadata]` table were not read, so "declared but not installed" could not be
   recognised (parsel, typer). Packages declared for development only (sphinx, tox, twine)
   counted as problems blocking the tests (django-model-utils, jmespath).
4. **Advice.** A removed Python module used by an installed library produced "install Python
   below 3.12" as a pip command (jmespath) instead of upgrading or replacing the library.
   Stepping back a whole major version is too coarse for libraries that stay on 1.x
   (scikit-learn), and one major version is not enough when a name was removed two majors ago
   (Django).
5. **Out of reach of the evidence.** Behaviour changes that raise no removed-name error
   (SQLAlchemy 2.0 results in records, pytest-asyncio 1.0 ignoring aiostream's loop fixture)
   look like code defects to FixFirst.

## Round 2: after fixing the general causes (not held out)

Every change fixes a cause from the list above, not a single project, and is covered by a test:

| Cause | Change |
|---|---|
| Python 3.8/3.9 targets | The environment snapshot falls back to `top_level.txt`/installed files and the standard-library folder when `packages_distributions` and `sys.stdlib_module_names` are missing |
| pytest 9 subtests | The probe records failing subtests only (a test with 9,000 passing subtests failed before and passes now) |
| Commands started by tests | Checks run as if the environment were activated: its `bin`/`Scripts` folder first on `PATH`, `VIRTUAL_ENV` set |
| One missing name counted as several | When the error names the missing name, the rest of the import line is not treated as missing |
| Start-up crashes | Python's own traceback format is read, so the location and the library that raised are known |
| Declarations | `setup.py` is read statically (its syntax tree, never executed): literal `install_requires`, `extras_require` and `tests_require`, also through a variable; flit's old `[tool.flit.metadata]` is read |
| Development-only declarations | Declared-but-missing packages no longer block the test goals by themselves (rule G04 removed); a failing test that needs one still gets the declaration as evidence (D20) |
| Python removals used by a library | New rules: upgrade the library (`pip install 'pytest>3.10.1'`, P55), or stop using it when it is unmaintained (P56); pinning is kept for names a library removed (P08) |

Two knowledge-base entries were added **after seeing round 1**, and the results that depend
on them are marked: nose is unmaintained (last release 1.3.7), and pytest-asyncio 1.0 removed
the `event_loop` fixture (new rule D25 for removed fixtures). Both are documented upstream and
affect many projects, but they were chosen because of this set.

Raw results: examples/real-world/results-round2.json.

| Project | Headline | First step | Score (round 1 → 2) |
|---|---|---|---|
| seaborn | 1 problem | Replace distutils: removed in Python 3.12 | Correct → **Correct** |
| flask-sqlalchemy | 1 problem | Try an older flask: `pip install 'flask<3'` | Correct (hedged) → **Correct** (hedged); headline now right |
| requests | 1 problem | Upgrade pytest: pytest 3.10.1 still uses imp, which Python 3.12 removed; `pip install 'pytest>3.10.1'` | Partial → **Correct** |
| typer | 1 problem | Install the declared dependency that provides shellingham (`[tool.flit.metadata.requires-extra.test]`) | Generic → **Correct** |
| parsel | 1 problem | Install the declared dependency that provides six (`setup.py install_requires`) | Generic → **Correct** |
| cachetools | 1 problem | Make the project module cachetools importable (src layout) | Wrong → **Correct** |
| more-itertools | All tests pass | (none) | Wrong → **Correct** |
| jmespath | 1 problem | Stop using nose: its last release, 1.3.7, uses imp, which Python 3.12 removed | Wrong → **Correct**, knowledge added after round 1 (without it: upgrade nose, which has no newer release: Partial) |
| aiostream | 3 problems | Replace event_loop: removed in pytest-asyncio 1.0, or pin pytest-asyncio below 1.0 | Wrong → **Correct**, knowledge added after round 1 |
| django-model-utils | 1 problem | Try an older django: `pip install 'django<5'` | Partial → **Partial** (4.2 still lacks the name; the next round suggests < 4) |
| imbalanced-learn | 3 problems | Try an older scikit-learn: `pip install 'scikit-learn<1'` | Partial → **Partial** |
| records | 1 problem | Inspect the exception raised while running the test | Generic → **Generic** |
| attrs | 1 problem | Inspect the exception raised while running the test | Wrong → **Generic**: FixFirst now finds `mypy` itself, and the next layer (33 tests needing an older mypy) gets generic advice |

**Round 2: 9 correct (8 confirmed by rules, 1 hedged), 2 partial, 2 generic, 0 wrong.**
Without the two knowledge entries added after round 1 it would be 7 correct.

### How to read the two rounds

- **Round 1 is the honest measure of generalisation**: 2 of 13 first steps worked as given,
  and the cause was named in 6. It is the number to quote for "FixFirst on unseen projects".
- **Round 2 is not held out.** It shows that the failures had general causes that could be
  fixed without special cases, and the diagnosis evaluation on the generated dataset is
  unchanged by these fixes. Measuring the improved version fairly needs a new set of
  projects, ideally chosen by someone other than the author.
- **What remains out of reach**: version bounds need release history that FixFirst does not
  have offline (Django needs two rounds; scikit-learn's previous series does not install on
  Python 3.12), and behaviour changes that raise no removed-name error (SQLAlchemy 2.0 results,
  mypy's changed messages) still look like code defects.

## Round 3: trying releases and reading lock files (not held out)

Two additions target the partial and generic results of round 2, both general:

- **Release search** (`versions.py`, rules D09, P57–P59). When a name is missing from an
  installed library, the first step now offers to *find* the newest release that still has
  it, instead of guessing one release series back. On "Find it", FixFirst reads the release
  list from PyPI, keeps the newest release of each series that has a prebuilt wheel for the
  target Python and machine, and checks them in a throwaway environment built from the same
  interpreter: stepping back 1, 2, 4, 8 series, then bisecting. Only wheels are installed (no
  build scripts run) and the user's environment is never changed. It runs only when asked,
  because it downloads packages. If no older release has the name, FixFirst says the name is
  probably misspelt instead (H05). The search is a bounded search over an ordered space: at
  most 12 trials, each a real install and import.
- **Tested versions** (rule H06, P61). `Pipfile.lock`, `poetry.lock` and `uv.lock` record
  versions the project worked with. When a failure is raised inside a library that is now a
  major version newer than the locked one, FixFirst suggests returning to the locked release
  series (hedged: a likely cause, not a confirmed one).

Checking FixFirst's suggestion for records showed that the original label was wrong
(SQLAlchemy < 2 still fails; the change came in 1.4). The corrected label is in LABELS.md;
round 1 and 2 scores for records are unaffected. Round 3 ran with `--search`, following a
first "Find it" step as a user would. Raw results: examples/real-world/results-round3.json.

| Project | First step (after "Find it" where offered) | Round 2 → 3 |
|---|---|---|
| flask-sqlalchemy | Install flask below 2.4: 2.3.3 is the newest release that still provides flask._app_ctx_stack (2 trials, 2 s) | Correct (hedged) → **Correct** |
| django-model-utils | Install django below 3.3: 3.2.25 is the newest release that still provides django.utils.translation.ugettext_lazy (6 trials, 4 s) | Partial → **Correct** |
| imbalanced-learn | Install scikit-learn below 1.5: 1.4.2 is the newest release that still provides sklearn.utils._print_elapsed_time (5 trials, 42 s) | Partial → **Correct** |
| records | Try sqlalchemy below 1.3: the project was tested with sqlalchemy 1.2.6 (Pipfile.lock), this environment has 2.0.54 | Generic → **Correct** (hedged) |
| attrs | Inspect the exception raised while running the test | Generic → Generic |
| other 8 | unchanged from round 2 | Correct |

**Round 3: 12 correct (11 confirmed, 1 hedged), 0 partial, 1 generic, 0 wrong.** Checked by
hand: `scikit-learn<1.5` installs 1.4.2 on Python 3.12, which has both missing names;
`sqlalchemy<1.3` installs 1.2.19 and 33 of records' tests pass (the rest fail with SQLite
locking errors, a later layer).

The same caveat as round 2 applies, more strongly: these projects shaped the fixes, so the
held-out number is still round 1's. Two of the corrections to labels were found while checking
FixFirst's output; both are documented with the evidence that settled them.

### Review correction after round 3 (2026-09-24)

The release-search description and commands above record the version used in round 3.
A subsequent code review found that it skipped earlier patches in the installed series and
could mistake an incomplete search for proof that no older release provided the name. The
current search includes those patches, keeps unchecked or failed searches inconclusive, and
pins a successfully tried release with `==`. It does not promise the newest working release.
See [ARCHITECTURE.md](ARCHITECTURE.md#finding-a-release-that-works). The correction has offline
regression coverage; the real-project searches and scores above have not been rerun.
