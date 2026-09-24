# Ground truth for the real-world generalisation check

Written on 24 September 2026 **before FixFirst was run on these projects**, from the plain
`pytest` output of each environment built by `scripts/setup_real_world.py` (versions in
`environments/`). FixFirst's code was not changed between writing this file and the first run;
the git history shows the order. The labels are the author's own diagnosis (one annotator), so
they share the author's blind spots; each gives the evidence it rests on.

## How a first run is scored

Only the first thing FixFirst tells the user is scored: the headline and the first must-fix
step (what a newcomer would do first).

| Score | Meaning |
|---|---|
| **Correct** | The first step addresses the labelled root cause, and doing it (or running its command) resolves that failure, possibly leaving the next layer. Marked *hedged* when FixFirst shows it as likely rather than confirmed. |
| **Partial** | The cause is right, but the step as given cannot work or does not reach a working state (for example a version bound that still lacks the name, or a command that cannot install). |
| **Generic** | No cause is named; only generic advice ("inspect the exception"). |
| **Wrong** | The step points at another cause, or following it does not help. |

For a healthy project, **Correct** means no must-fix problem is reported. Later layers
(problems that only appear once the first one is fixed) are listed for information and are
not scored in the first run.

## Labels

| Project | What plain pytest shows | Root cause | Correct first step (also acceptable) |
|---|---|---|---|
| flask-sqlalchemy 2.5.1 (Py 3.12) | conftest import fails: `flask_sqlalchemy/__init__.py:14` imports `_app_ctx_stack` from flask | Version incompatibility: Flask 3.0 removed `_app_ctx_stack` (checked: 2.3.3 has it, 3.0.0 does not); Flask 3.1.3 installed | Install Flask < 3 (or change the project code). Later layer: SQLAlchemy 2.0 is also too new for 2.5.1 |
| django-model-utils 4.0.0 (Py 3.11) | pytest aborts at start-up (pytest-django sets up Django): `model_utils/models.py:4` imports `ugettext_lazy` | Version incompatibility: Django 4.0 removed `ugettext_lazy`; Django 5.2.17 installed | Install Django < 4, or use `gettext_lazy` in the project code. *Partial*: Django < 5 (4.2 still lacks it). Later layer: the tests need a PostgreSQL server |
| requests 2.25.1 (Py 3.12) | pytest itself crashes on import: `_pytest/assertion/rewrite.py` imports `imp` | Version incompatibility: pytest 3.10.1, pinned by requirements-dev.txt, predates Python 3.12, which removed `imp` | Install a newer pytest (relax the pin), or use Python ≤ 3.11. *Wrong*: anything asking pip to install Python |
| seaborn 0.11.2 (Py 3.12) | collecting `seaborn` fails: `seaborn/rcmod.py:4` imports `distutils.version` | Version incompatibility: Python 3.12 removed `distutils`; the project's own code uses it | Replace `distutils.version.LooseVersion` (e.g. `packaging.version`), install setuptools (its `distutils` shim), or use Python ≤ 3.11. Later layers: NumPy 2 / pandas 3 removals |
| imbalanced-learn 0.8.1 (Py 3.12) | 49 collection errors: `cannot import name '_print_elapsed_time' from 'sklearn.utils'` (44), `'_maybe_mark_xfail' from 'sklearn.utils.estimator_checks'` (3) | Version incompatibility: imblearn 0.8.1 imports private scikit-learn helpers that scikit-learn 1.9.1 moved or removed (`_print_elapsed_time` moved in 1.5; checked: 1.4.2 and 1.2.2 still have both names) | An older scikit-learn that still has the names and installs on Python 3.12 (< 1.5), or a newer imbalanced-learn. *Partial*: a bound that still lacks them (e.g. < 1.9) or cannot install on 3.12 (< 1: no 3.12 wheels) |
| typer 0.3.2 (Py 3.10) | 2 collection errors: `No module named 'shellingham'` | Missing dependency: shellingham is declared in the `[test]` extra (flit metadata), which was not installed | Install shellingham (or the `[test]` extra) |
| aiostream 0.4.5 (Py 3.12) | 66 failed, 28 passed, 1 error in 250 s: timing assertions (`assert [] == [1, 1, 3, ...]`) and `AttributeError: '_UnixSelectorEventLoop' object has no attribute 'open_resources'` | Version incompatibility: pytest-asyncio 1.4.0 no longer runs tests in a loop provided by an overriding `event_loop` fixture (removed in 1.0); aiostream's simulated-time loop is ignored, so real sleeps happen | Install pytest-asyncio < 1.0. *Wrong*: code defect / compare expected and actual values |
| jmespath 0.10.0 (Py 3.12) | 2 collection errors: `tests/test_compliance.py` imports `nose.tools`; nose imports `imp` | Version incompatibility: nose 1.3.7 (the last release) cannot run on Python 3.12 | Stop using nose in the tests (plain asserts / pytest), or use Python ≤ 3.11. *Wrong*: an older nose (1.3.7 is the last); asking pip to install Python |
| parsel 1.6.0 (Py 3.12) | 14 errors: `No module named 'six'` | Missing dependency: the declared dependencies (six, lxml, w3lib, cssselect) were never installed, because installing the project failed (its setup.py imports `pkg_resources`, which today's setuptools does not ship) | Install the declared dependencies (six first is fine). *Partial*: an undeclared-package framing that does not point at the project's declarations |
| records 0.5.3 (Py 3.12) | 2 failed, 14 errors: `sqlalchemy.exc.ResourceClosedError: This result object does not return rows` from iterating the result of `CREATE TABLE` | Version incompatibility: SQLAlchemy 2.0 changed result behaviour; records 0.5.3 was written for 1.x | Install SQLAlchemy < 2 |
| cachetools 5.5.0 (system Py 3.9) | 12 errors: `No module named 'cachetools'` | Local module problem: src layout, and the project itself is not installed | Install the project (`pip install -e .`) or put `src` on the path |
| more-itertools 10.7.0 (Py 3.14, no pip) | 670 passed, 1 skipped | Healthy (the environment has no pip) | All tests pass; no must-fix problem. A pip-related finding may appear, but not as a must-fix step for the test goal |
| attrs 25.3.0 (Py 3.13) | 85 failed, all in `tests/test_mypy.yml`: mypy output does not match the expected messages | Version incompatibility: mypy 2.3.1 words its messages differently from the mypy attrs 25.3.0 was tested with (attrs only sets a lower bound and notes that the messages keep changing) | Install the older mypy the tests expect (mypy < 2). *Wrong*: code defect in attrs |

Prediction before the run, from what FixFirst's rules and heuristics cover: seaborn,
cachetools, typer, parsel and flask-sqlalchemy should get a useful first step; aiostream,
records and attrs fall outside what its evidence can show.

## Corrections

**attrs (corrected on 24 September 2026, before FixFirst's result for attrs existed).** While
checking this label in a separate copy, the failure message turned out to be
`AssertionError: mypy executable is not found`, not a message mismatch: the mypy tests start
the `mypy` command, and running `.venv/bin/python -m pytest` without activating the
environment leaves `.venv/bin` off `PATH` (the baseline ran the tests that way, and so does
FixFirst). With the environment's `bin` folder on `PATH`, 53 of the 85 pass and 32 still fail
(with mypy 1.20.2), the version problem the original label described. Corrected label:

| Project | What plain pytest shows | Root cause | Correct first step (also acceptable) |
|---|---|---|---|
| attrs 25.3.0 (Py 3.13) | 85 failed in `tests/test_mypy.yml`: `mypy executable is not found` | Environment not activated: the tests run the `mypy` command, which is only on `PATH` when the environment is activated | Run the tests with the environment activated (its `bin` folder on `PATH`). Later layer: 32 tests need an older mypy. *Wrong*: code defect in attrs; installing mypy (it is installed) |
