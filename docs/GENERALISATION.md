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
3. **Declarations.** Dependencies declared in `setup.py` (8 of the 13 projects) and in flit's
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
