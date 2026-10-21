# FixFirst on real open-source projects

The diagnosis experiment (examples/diagnosis-evaluation) uses generated projects with one
injected fault each. This page records what happened on real projects whose failures nobody
injected. `scripts/setup_real_projects.sh` rebuilds the same setup; everything below was run on
macOS, Python 3.12, on 24 September 2026, with the goal *Make my tests pass*.

## Three projects

| Project | Situation | What FixFirst said | Correct? |
|---|---|---|---|
| [humanize](https://github.com/python-humanize/humanize) @ 392aef7 | Healthy, test dependencies installed | "All tests pass" (verified by the test run). Ruff not installed in that environment, listed as a non-blocking finding. | Yes |
| humanize, same commit | Only pytest installed; `freezegun` and the other `[tests]` extras missing | Round 1: "Install the declared dependency that provides freezegun", citing `pyproject.toml [project.optional-dependencies.tests]` (rule D20). Round 2: "Install pytest-benchmark: the tests use its benchmark fixture" (rule D23, see below) | Yes, after the round-2 rule was added |
| [Flask](https://github.com/pallets/flask) 1.1.4 | Installed with today's Jinja2 3.1, Werkzeug 3.1, itsdangerous 2.2, click 8.5, MarkupSafe 3.0, pytest 9.1 | See the walk-through below | 5 of 7 steps led to a fix |

After round 1 of humanize, 15 benchmark tests still failed with `fixture 'benchmark' not
found`. The first version had no rule for this; it showed the decision tree's guess, *likely a
defect in project code or tests*, which was wrong. The fixture comes from the pytest-benchmark
plugin, which the project declares in the same `[tests]` extra. FixFirst now knows which
plugins provide 44 common fixtures and says "Install pytest-benchmark: the tests use its
benchmark fixture", with the install command and the declaration it found (rules D23 + P21).
With pytest-benchmark installed the suite passes (761 passed, 110 skipped; checked in a
separate environment).

Flask 1.1.4 (2021) caps its dependencies below their next major versions. Installing today's
releases without those caps (an unpinned `requirements.txt` does exactly this) breaks it in
several layers, which is how many Flask 1.x applications broke in 2022–2023.

## Following FixFirst's advice on Flask 1.1.4

Each round: run the checks, do the first step FixFirst gives, check again.

| Round | FixFirst's first step | Why (rule) | Result after doing it |
|---|---|---|---|
| 1 | Install the jinja2 version that flask 1.1.4 requires (<3.0,>=2.10.1) at `src/flask/__init__.py:14` | `jinja2.escape` removed in Jinja2 3.1 (knowledge base) and pip check shows Flask requires Jinja2<3.0 (D02 + P09) | Import of Jinja2 now fails deeper |
| 2 | Install markupsafe below 2.1: the installed jinja2 still uses `markupsafe.soft_unicode` | `soft_unicode` removed in MarkupSafe 2.1; the call is inside the installed Jinja2, not the project (D02 + D05 + P08) | Next import error |
| 3 | Install the itsdangerous version that flask 1.1.4 requires (<2.0) | Name missing from a library whose version breaks another package's requirement, from pip check alone, no knowledge entry needed (D06 + P07) | Next import error |
| 4 | Install the werkzeug version that flask 1.1.4 requires (<2.0) | Same rule, via pip check (D06 + P07) | Tests now import, one test module fails to load |
| 5 | Check whether pytest 9.1.1 still provides `_pytest.monkeypatch.notset` (likely version incompatibility, not confirmed) | A name missing from an installed library usually means a version change (heuristic H01) | Installing pytest<8 lets the suite run: **524 passed, 2 failed, 14 skipped** |
| 6 | Compare the failed assertion's expected and actual values, `tests/test_basic.py:1980` | Assertion failure (D40) | Not fixed: the test expects 1 warning and gets 4 because newer Python emits extra deprecation warnings. FixFirst calls it a code defect; the cause is really the environment. |
| 7 | Inspect the exception raised while running the test, `tests/conftest.py:187` (classifier: likely a code defect) | No rule matched | Not fixed: the test runs `setup.py bdist_egg`, which needs setuptools; Python 3.12 virtual environments no longer include it. The subprocess's error text is not in the traceback, so FixFirst had no evidence to name it. |

After this walk-through the round-5 step gained a concrete command: FixFirst now suggests the
previous release series (`pytest<9`, which installs 8.4.2 and still provides `notset`) and steps
back further if the name is still missing. The table records what was run at the time.

### Round 5 again, with the suggested `pytest<9`

Following the new round-5 command installs pytest 8.4.2. The suite runs (520 passed) but four
more tests fail with `TypeError: exceptions must be derived from Warning, not <class
'NoneType'>`: Flask 1.1.4's tests call `pytest.warns(None)`, which pytest 8.0 removed. The first
version of FixFirst missed this: no rule applied, and the decision tree, trained on generated
cases, suggested *missing configuration*, which was wrong (shown as unconfirmed, but misleading).
Three additions now explain every remaining failure:

| Failure | FixFirst now says | Rule |
|---|---|---|
| 4 tests, `TypeError ... not <class 'NoneType'>` | Replace pytest.warns(None): removed in pytest 8.0 (or pin pytest below 8.0), citing the pytest deprecation notes | D07: a *removed usage* in the knowledge base, recognised by its error message |
| `test_egg_installed_paths` | Likely: install setuptools, with the command; the test runs `setup.py bdist_egg` and Python 3.12 virtual environments no longer include setuptools | H03 (heuristic). Verified separately: the same command fails without setuptools and succeeds with it |
| `test_max_cookie_size` (4 warnings instead of 1) | Optional: make the test ignore werkzeug's ast.Str deprecation warnings (or run the tests with Python older than 3.12). Your code runs normally; Python 3.14 removes ast.Str, so werkzeug 1.0.1 will fail there | D45 + P33, D46: the probe records which warnings the test's recorder held; the knowledge base says Python warns about `ast.Str` since 3.12 and removes it in 3.14 |

Doing both (pytest<8 and installing setuptools, as a user following the steps) gives
**525 passed, 1 failed, 14 skipped, 1 xfail**. The last failure, `test_max_cookie_size`,
expects exactly one recorded warning (the cookie-size warning) and records four. The other
three are deprecation warnings about `ast.Str`: Werkzeug 1.0.1, the newest version Flask 1.1.4
accepts, uses it to compile the test's route, and Python 3.12 deprecates it. The first version
of FixFirst only saw `assert 4 == 1` and called it a code defect. The probe now also records
which warnings the test held when it failed, so FixFirst names the library, the line
(`werkzeug/routing.py:957`) and the warning text, and suggests counting only the warning the
test checks, or using Python older than 3.12. Because the code itself works, the page lists
this as an optional step and its headline reads "No problems that affect your code" instead
of "1 problem to fix". It also warns that Python 3.14 removes `ast.Str`: Werkzeug 1.0.1 uses
it when compiling routes, so on 3.14 the application itself would fail. Changing the assertion to
`recwarn.pop(UserWarning)` makes the test pass (checked on a copy of the tests).

Every step was verified by a real check before FixFirst marked it fixed: after round 4 the
workspace showed four fixed issues and the previously unreachable ones as "waiting to be
re-checked", not as new problems.

## What real projects changed in FixFirst

Testing on these projects exposed problems that the generated dataset did not contain. Each
was fixed and is covered by a test:

1. **Conftest import errors were not treated as blocking.** pytest fails before collection, so
   no structured records exist. The parser now treats any failure of an executed run without
   records as a collection-stage error, and the evidence builder uses the surrounding output
   lines as the traceback.
2. **Goal relevance by stage only.** A pytest failure of any stage now affects the test goal
   (rules G07–G09), so the headline never says "nothing to fix" while tests cannot run.
3. **pip check evidence was not connected to the diagnosis.** New rules (D06, P07, P09) turn
   "Flask requires Jinja2<3.0" into the advice to install that version instead of editing
   library code.
4. **Removed names used by another library.** Rule D05/P08 recommends pinning the dependency
   when the removed API is used inside an installed library rather than the project.
5. **A name missing from an installed library without knowledge coverage.** Heuristic phase
   (H01, H02) marks a version change as likely, worded as unconfirmed. On the generated
   dataset these heuristics added 3.7 points of rule coverage with no false positives.
6. **Complete checks that no longer report a finding** (pip check, Ruff) now close that finding
   even while others remain; previously one remaining warning kept every fixed one open.
7. **Paths outside the project** (`../.cache/python/lib/...`) are no longer shown as project
   files, and the default check timeout is 10 minutes instead of 30 seconds, so real test
   suites finish.
8. **Install advice is a copyable command** that uses the project's own interpreter, because
   `pip install` in a user's terminal often targets a different Python.
9. **Removed usages** that the error message does not name (`pytest.warns(None)`) are matched by
   their message signature, and a missing setuptools behind a failing `setup.py` step is
   suggested (H03).
10. **The decision tree generalised poorly** to error types absent from its training data
    (a `TypeError` raised inside pytest, a `FixtureLookupError`): it confidently suggested the
    wrong cause. Its advice stays labelled as unconfirmed and is ranked after rule-based steps.
11. **Warnings a test counts.** When a test fails, the probe records the warnings held by its
    `recwarn` or `pytest.warns` recorder. Deprecation warnings raised by an installed library
    or by Python are named with their origin (rules G10, D44, D45, P33–P35), and the knowledge
    base lists deprecations that Python 3.11 and 3.12 started warning about.
12. **Missing pytest plugins.** `fixture 'x' not found` is matched to the plugin that provides
    the fixture and to the project's declarations (D23, P21, P22). A fixture defined in the
    project but out of the test's reach (D24) and an unknown fixture (heuristic H04) get their
    own advice.
13. **Must fix vs optional.** Failures that rules judge not to affect how the code runs (so
    far: a warning count broken by the environment's deprecation warnings) are shown as
    optional and left out of the problem count; knowledge of a scheduled removal adds when they
    will start to matter.
14. **Code-check findings sorted by risk.** With the code-check goal, Flask 1.1.4 showed "2
    problems to fix" and called 433 findings "possibly real bugs". None was: 271 were outdated
    syntax that Python 2 support required, 51 import order, 48 unused imports. Flask lints with
    flake8 (`setup.cfg [flake8]`), which Ruff does not read, so Ruff applied its own default
    rules. Now only rules that usually mean a bug (undefined names, syntax errors, format
    strings that raise, a few bugbear rules) are must-fix (D47); the rest is one optional
    clean-up step counted by kind (D48), and the page says when Ruff used its defaults because
    the project configures another linter. Flask's code check now reads "No problems that
    affect your code" with 492 optional suggestions.

## Limits seen on real projects

- Environment effects that surface as assertion failures are only recognised when the test
  records warnings. Others (for example a changed output format) are still diagnosed as code
  defects: the evidence FixFirst reads does not distinguish them.
- Errors inside subprocesses that a test starts are opaque unless their output reaches the
  traceback.
- FixFirst takes version constraints (for example `werkzeug<2.0`) from pip check and its
  knowledge base. When neither says anything it steps back one release series at a time, which
  can take several rounds and may downgrade further than needed.
