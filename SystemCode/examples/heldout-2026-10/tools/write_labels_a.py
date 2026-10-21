"""Write the official label rows into labels-A.csv (task A1).

root_cause, first_step, also_acceptable, partial_if and wrong_if are the label
author's own wording, given row by row; they are transcribed here unchanged apart
from dropping markdown backticks (the CSV holds plain text, like the template and
labels-reserve.csv).  The evidence columns (pytest_shows, checked_by_trying,
later_layers) are the recorded observations from pytest/<id>.txt and twins/<id>.txt.

reviewed_by and review_notes are written empty on purpose: the card assigns those two
columns to C in C1 (docs/tasks/A1-heldout-projects.md, the column table in step 6), so
A must not pre-fill them.  The per-row "notes" kept below are provenance only -- they are
deliberately NOT written into the CSV; the same conclusions are already in
checked_by_trying and in twins/<id>.txt.

    python tools/write_labels_a.py
"""

from __future__ import annotations

import csv
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIELDS = ["id", "pytest_shows", "root_cause", "first_step", "also_acceptable",
          "partial_if", "wrong_if", "checked_by_trying", "later_layers",
          "labelled_by", "labelled_on", "reviewed_by", "review_notes"]

LABELLED_BY = "Yongjun Chi"
LABELLED_ON = "2026-09-30"

GENERIC_NOTE = ("Reviewed against two repeat runs and the recorded causal twin; later-layer "
                "failures were excluded from the first-step label.")

ROWS = {
    "click": {
        "shows": "pytest cannot start: AttributeError: __spec__ (exit 1, run 1 and run 2 identical)",
        "cause": "version_incompatibility",
        "step": "Replace the pinned py==1.10.0 with a Python-compatible version (e.g. py==1.11.0).",
        "also": "Upgrade py from 1.10.0 to a Python-compatible version; alternatively use a Python "
                "version compatible with py==1.10.0.",
        "partial": "Identifies a dependency/version incompatibility involving the pinned test stack but "
                   "does not identify py==1.10.0.",
        "wrong": "Recommends upgrading pytest alone; attributes the first failure to click source code; "
                 "or treats a later-layer failure as the first blocker.",
        "tried": "Ablation in the twin, three runs: pytest 9.1.1 with py 1.10.0 still fails with the "
                 "same AttributeError: __spec__; upgrading only py to 1.11.0 makes pytest start (1 "
                 "collection error left); py 1.11.0 with the original pytest 6.2.5 also starts (19 "
                 "collection errors). The blocker is the py pin, not pytest.",
        "later": "With a startable pytest 6.2.5 the suite hits 19 collection errors of "
                 "DeprecationWarning: ast.Str is deprecated (pytest 6.2.5's own "
                 "src/_pytest/assertion/rewrite.py:823 on Python 3.12); with pytest 9.1.1 instead, "
                 "tests/test_basic.py fails to collect because click's own test passes itertools.chain "
                 "as parametrize argvalues.",
        "notes": "Confirmed by controlled A/B/C twin: upgrading pytest alone preserved the target "
                 "failure; upgrading py==1.10.0 to 1.11.0 removed it.",
    },
    "pytest": {
        "shows": "ConftestImportFailure while loading testing/conftest.py: DeprecationWarning: ast.Str "
                 "is deprecated and will be removed in Python 3.14; use ast.Constant instead (exit 4, "
                 "both runs)",
        "cause": "version_incompatibility",
        "step": "Run the pinned test stack on a compatible Python version (Python 3.10).",
        "also": "Run the pinned dependency stack on Python 3.10 or another demonstrated compatible "
                "Python version.",
        "partial": "Correctly identifies a Python-version incompatibility but does not identify changing "
                   "the interpreter as the first action.",
        "wrong": "Treats pkg_resources or later test failures as the original root cause, or proposes "
                 "project-code changes for the initial collection failure.",
        "tried": "Twin on Python 3.10.21 with the same pinned dependencies: the conftest import failure "
                 "is gone and the suite runs -- 2849 passed.",
        "later": "86 failed, 2849 passed, 100 skipped, 9 xfailed, 12 errors. 67 of the error lines are "
                 "ModuleNotFoundError: No module named 'pkg_resources' (environment artifact: the uv venv "
                 "has no setuptools, uv --seed installs pip only); the rest are expected-output "
                 "mismatches of a 2021 test suite.",
        "notes": GENERIC_NOTE,
    },
    "dateparser": {
        "shows": "3 collection errors, every one ModuleNotFoundError: No module named 'fasttext' "
                 "(exit 2, 17 warnings, both runs)",
        "cause": "missing_dependency",
        "step": "Install the declared fasttext test extra; on this Windows/Python 3.12 environment this "
                "additionally requires a working MSVC build toolchain because no usable wheel is "
                "available.",
        "also": "Install the declared fasttext extra/dependency; using a compatible wheel, "
                "compiler-equipped environment, or supported environment in which the declared dependency "
                "can be installed is acceptable.",
        "partial": "Correctly identifies fasttext as missing but does not account for the native-build/"
                   "install requirement in this Windows/Python 3.12 environment.",
        "wrong": "Attributes the initial collection errors to dateparser application logic, removes/skips "
                 "the affected tests, or claims fasttext is an undeclared dependency.",
        "tried": "Twin verification: unresolved / intervention unavailable in the current environment. "
                 "`uv pip install fasttext` fails with 'error: Microsoft Visual C++ 14.0 or greater is "
                 "required', fasttext stays absent and the run is identical to the original. The root "
                 "cause (the declared extra is not installed) is confirmed; the intervention itself "
                 "cannot be executed here.",
        "later": "Not measured: the first layer cannot be closed in this environment, so nothing behind "
                 "it is observable.",
        "notes": "Root cause confirmed from the missing declared fasttext extra; causal installation "
                 "twin remains unresolved because fasttext cannot build in the current Windows/Python "
                 "3.12 environment without MSVC.",
    },
    "python-qrcode": {
        "shows": "9 failed, 62 passed, 2 skipped (exit 1, both runs). The first failure is ValueError: "
                 "Invalid format string at qrcode/release.py:34; the other 8 are ModuleNotFoundError: No "
                 "module named 'pkg_resources' at qrcode/console_scripts.py:36 (ScriptTest)",
        "cause": "version_incompatibility",
        "step": "Replace the non-portable strftime('%-d %b %Y') usage in both the release code and its "
                "corresponding test with a Windows-compatible date formatting approach.",
        "also": "Replace the non-portable %-d date formatting in both qrcode/release.py and the "
                "corresponding regression test with an equivalent Windows-compatible implementation.",
        "partial": "Fixes only one of the two %-d occurrences, or correctly identifies the portability "
                   "issue without removing it from both production and test code.",
        "wrong": "Treats has_calls or missing pkg_resources as the first blocker, or changes only "
                 "unrelated dependencies without addressing %-d.",
        "tried": "Twin step 1 (qrcode/release.py:34 only): the same ValueError, now raised from "
                 "tests/test_release.py:37 -- the directive is in two places, so the first layer is not "
                 "cleared. Twin step 2 (both sites): 'Invalid format string' drops to 0 occurrences. The "
                 "8 pkg_resources failures are untouched by design.",
        "later": "Layer 2a: after the format fix the release test fails at tests/test_release.py:39, "
                 "mock_file().write.has_calls(...) -- modern unittest.mock rejects the name ('has_calls' "
                 "is not a valid assertion). Layer 2b (environment/tooling artifact, not a second project "
                 "defect): the uv-created venv has no setuptools, so qrcode/console_scripts.py:36 'from "
                 "pkg_resources import get_distribution' raises ModuleNotFoundError and 8 ScriptTest "
                 "cases fail.",
        "notes": "Confirmed by two-step twin: changing only production code moved the same %-d failure to "
                 "the regression test; changing both occurrences removed the target failure.",
    },
    "httpx": {
        "shows": "ConftestImportFailure while loading tests/conftest.py: DeprecationWarning: ast.Str is "
                 "deprecated and will be removed in Python 3.14; use ast.Constant instead (exit 4, both "
                 "runs)",
        "cause": "version_incompatibility",
        "step": "Upgrade the pinned legacy pytest version to one compatible with the current Python "
                "interpreter.",
        "also": "Upgrade pytest 6.2.4 to a version compatible with the current Python interpreter, or use "
                "an interpreter compatible with the pinned pytest version.",
        "partial": "Identifies the pinned pytest/Python compatibility problem but gives only a generic "
                   "dependency-upgrade action.",
        "wrong": "Attributes the initial failure to httpx's cgi import/deprecation warning or modifies "
                 "httpx application code before resolving the pytest compatibility blocker.",
        "tried": "Twin with pytest 9.1.1 instead of the pinned pytest==6.2.4: ast.Str appears 0 times in "
                 "the whole output.",
        "later": "With the new pytest the conftest still fails to import, but on httpx's own code: "
                 "tests/conftest.py:20 -> httpx/_models.py:1 -> `import cgi`, DeprecationWarning: 'cgi' is "
                 "deprecated and slated for removal in Python 3.13, escalated to an error by httpx's own "
                 "setup.cfg filterwarnings = error.",
        "notes": GENERIC_NOTE,
    },
    "python-ftfy": {
        "shows": "318 passed, 10 xfailed (exit 0, both runs)",
        "cause": "healthy",
        "step": "No action required; the test suite passes in the held-out environment.",
        "also": "No change; leave the environment/project unchanged.",
        "partial": "Recognizes that the suite passes but suggests unnecessary investigation or "
                   "non-functional cleanup.",
        "wrong": "Diagnoses a root cause or recommends a required fix despite the held-out suite passing.",
        "tried": "No twin: there is no failure to remove.",
        "later": "None -- nothing fails after the first (non-)step.",
        "notes": GENERIC_NOTE,
    },
    "robotframework": {
        "shows": "98 errors, every one ModuleNotFoundError: No module named 'robot' (exit 2, both runs)",
        "cause": "local_module",
        "step": "Make the repository's src/ directory importable before test collection, matching the "
                "path setup performed by the project's test runner.",
        "also": "Make src/ importable before collection, including reproducing the relevant "
                "sys.path/PYTHONPATH setup used by the project's own test runner.",
        "partial": "Correctly identifies that the local robot package is not on the import path but gives "
                   "only a generic import-error diagnosis.",
        "wrong": "Installs an unrelated external robot package, treats resources/classes or the GBK error "
                 "as the initial root cause, or modifies tests to suppress the import failure.",
        "tried": "Twin with a root conftest.py that inserts src/ and nothing else: all 98 No module named "
                 "'robot' errors disappear.",
        "later": "4 collection errors remain from the other paths utest/run.py supplies (utest/run.py:28-33 "
                 "adds ../src and ../atest/testresources/testlibs, and its discovery adds the utest/ "
                 "directory itself): No module named 'resources' and No module named 'classes'. The 5th is "
                 "a GBK UnicodeEncodeError from utest/utils/test_encoding.py:9, which encodes with the "
                 "machine's cp936 console codepage.",
        "notes": GENERIC_NOTE,
    },
    "python-slugify": {
        "shows": "7 failed, 124 passed (exit 1, both runs): one failure plus 6 failing subtests, all in "
                 "tests/test_release.py and all from the two regression tests taken from fix commit "
                 "8f9a550, e.g. 'one-' != 'one' and '-' != ''",
        "cause": "code_defect",
        "step": "Fix _modern_truncate so repeated delimiters do not cause hard-cut results to end with a "
                "delimiter.",
        "also": "Correct _modern_truncate so empty tokens caused by repeated delimiters cannot leave a "
                "trailing delimiter after a hard cut; an equivalent logic fix is acceptable.",
        "partial": "Identifies _modern_truncate/repeated-delimiter handling but proposes an incomplete fix "
                   "that does not satisfy the regression case.",
        "wrong": "Changes the test expectation, attributes the failure to environment/dependencies, or "
                 "suppresses the failing regression instead of fixing the truncation logic.",
        "tried": "Twin with the fix commit's slugify/slugify.py: 125 passed, exit 0, twice.",
        "later": "None -- after the fix every one of the 125 items passes.",
        "notes": GENERIC_NOTE,
    },
    "django-cacheops": {
        "shows": "1 collection error: django.core.exceptions.ImproperlyConfigured: Requested setting "
                 "CACHEOPS_DEGRADE_ON_FAILURE, but settings are not configured ... define the environment "
                 "variable DJANGO_SETTINGS_MODULE or call settings.configure() (exit 2, both runs)",
        "cause": "config_missing",
        "step": "Initialize the Django test configuration before collection by setting "
                "DJANGO_SETTINGS_MODULE=tests.settings and running django.setup(), as the project's test "
                "runner does.",
        "also": "Set DJANGO_SETTINGS_MODULE=tests.settings and initialize Django with django.setup(), "
                "matching the project's runner.",
        "partial": "Sets DJANGO_SETTINGS_MODULE only: this removes ImproperlyConfigured but leaves "
                   "AppRegistryNotReady; or correctly identifies missing Django initialization without "
                   "completing both required initialization steps.",
        "wrong": "Treats the later database-table or Redis failures as the original root cause, or changes "
                 "application logic instead of initializing the Django test environment.",
        "tried": "Twin step 1 (DJANGO_SETTINGS_MODULE only): ImproperlyConfigured drops to 0. Twin step 2 "
                 "(the same initialisation as run_tests.py:3 + :20, settings module plus django.setup()): "
                 "collection works and the tests run.",
        "later": "Step 1 revealed django.core.exceptions.AppRegistryNotReady: Apps aren't loaded yet (the "
                 "second thing run_tests.py:20 does). Step 2 revealed a third layer: "
                 "sqlite3.OperationalError: no such table: tests_category (run_tests.py also runs "
                 "makemigrations itself) and redis.exceptions.ConnectionError ... localhost:6379 (no "
                 "Redis service on this machine).",
        "notes": "Confirmed by staged twin: DJANGO_SETTINGS_MODULE removed ImproperlyConfigured but "
                 "exposed AppRegistryNotReady; django.setup() completed the required initialization.",
    },
    "seleniumlibrary": {
        "shows": "33 errors, every one ModuleNotFoundError: No module named 'SeleniumLibrary' (exit 2, "
                 "both runs)",
        "cause": "local_module",
        "step": "Make the repository's src/ directory importable before test collection, matching the "
                "path setup performed by utest/run.py.",
        "also": "Make src/ importable before collection, matching the path setup in utest/run.py; "
                "equivalent PYTHONPATH/pytest pythonpath configuration is acceptable.",
        "partial": "Identifies the missing local SeleniumLibrary import path but does not specify how to "
                   "expose src/.",
        "wrong": "Treats the later Firefox/geckodriver failures as the initial root cause, or installs an "
                 "unrelated package instead of exposing the repository's local source tree.",
        "tried": "Twin with a root conftest.py that inserts src/ and nothing else: all 33 No module named "
                 "'SeleniumLibrary' errors disappear.",
        "later": "3 failed, 217 passed, 24 skipped. The 3 failures are firefox cases in "
                 "utest/test/keywords/test_selenium_options_parser.py, e.g. FileNotFoundError for "
                 "utest/output_dir/geckodriver-1.log (selenium is unpinned in requirements-dev.txt and "
                 "installed as 4.49.0), unrelated to the import layer.",
        "notes": GENERIC_NOTE,
    },
    "django-storages": {
        "shows": "253 errors, every one django.core.exceptions.ImproperlyConfigured: Requested setting "
                 "DATABASES, but settings are not configured ... define the environment variable "
                 "DJANGO_SETTINGS_MODULE (exit 1, both runs)",
        "cause": "config_missing",
        "step": "Set DJANGO_SETTINGS_MODULE=tests.settings before running pytest, matching the project's "
                "tox configuration.",
        "also": "Set DJANGO_SETTINGS_MODULE=tests.settings before pytest, including via an equivalent "
                "pytest/conftest initialization.",
        "partial": "Correctly identifies missing Django settings configuration but does not identify "
                   "tests.settings or an equivalent initialization.",
        "wrong": "Treats the later Windows path failures as the original blocker, or changes storage "
                 "implementation code before supplying the missing Django configuration.",
        "tried": "Twin with DJANGO_SETTINGS_MODULE=tests.settings in the environment and nothing else: "
                 "ImproperlyConfigured drops to 0, 2 failed and 251 passed.",
        "later": "The 2 remaining failures are Windows path handling: dropbox's stone validator rejecting "
                 "'C:/foo' ('did not match pattern ...') and an assertion 'parent\\chil.txt' != "
                 "'parent/chil.txt'. Neither is a configuration problem.",
        "notes": GENERIC_NOTE,
    },
    "python-markdown": {
        "shows": "2 collection errors (exit 2, both runs); the first is ModuleNotFoundError: No module named "
                 "'yaml' at tests/test_apis.py:34",
        "cause": "missing_dependency",
        "step": "Install the project's declared testing extra (for example, pip install -e .[testing]) so "
                "that PyYAML is installed before running the test suite; the 3.4.3 contributing instructions "
                "omit this testing extra.",
        "also": "Install PyYAML directly before running the tests, since PyYAML is the specific missing "
                "dependency that blocks test collection.",
        "partial": "Identifies PyYAML/yaml as the missing dependency or recommends installing the testing "
                   "dependencies, but does not connect the missing package to the testing extra omitted by the "
                   "documented editable-install command.",
        "wrong": "Attributes the initial failure to pytest compatibility or project code, modifies/skips tests "
                 "to avoid importing yaml, or addresses the later TestSuite collection failure before making "
                 "PyYAML available.",
        "tried": "Original --repeat 2 is stable (exit 2, 2 errors, both runs) and the project's own documented "
                 "command fails the same way: python -m unittest discover tests in the untouched environment "
                 "gives Ran 894 tests, FAILED (errors=1, skipped=129) on the same line, tests/test_apis.py:34 "
                 "(raw output: twins/python-markdown.docpath.txt). Twin: the same interpreter fails 'import "
                 "yaml' on its own, then exactly one package is installed in the copy (uv pip install pyyaml "
                 "6.0.3 -- the testing extra's other entry, coverage, deliberately left out; no project or test "
                 "file edited), and the target error drops to 0 occurrences with collection reaching 1090 items.",
        "later": "After PyYAML was installed, the target yaml import failure disappeared. A distinct pytest "
                 "collection incompatibility then surfaced involving a unittest.TestSuite-derived test class "
                 "in tests/test_syntax/extensions/test_md_in_html.py (modern pytest refuses to collect a Test* "
                 "class with an __init__ constructor, so the PytestCollectionWarning interrupts collection); "
                 "this is not part of the missing-dependency root cause. The repository has no pytest "
                 "configuration at all (no pytest.ini, no setup.cfg, no [tool.pytest.ini_options], no [pytest] "
                 "section in tox.ini), so the residual is modern pytest against 2021 test code, not project "
                 "config. Installing PyYAML therefore closes the first layer; it does not leave a failing "
                 "missing-dependency layer behind.",
        "notes": "Confirmed by single-intervention twin: installing PyYAML alone removed the target yaml "
                 "import failure and left only a distinct pytest collection incompatibility, which the first "
                 "step is not expected to fix.",
    },
}


def strip_ticks(value: str) -> str:
    """The CSV holds plain text; the label author's wording was given in markdown."""
    return value.replace("`", "")


def main() -> int:
    path = ROOT / "labels-A.csv"
    rows = []
    for pid, row in ROWS.items():
        rows.append({
            "id": pid,
            "pytest_shows": strip_ticks(row["shows"]),
            "root_cause": row["cause"],
            "first_step": strip_ticks(row["step"]),
            "also_acceptable": strip_ticks(row["also"]),
            "partial_if": strip_ticks(row["partial"]),
            "wrong_if": strip_ticks(row["wrong"]),
            "checked_by_trying": strip_ticks(row["tried"]),
            "later_layers": strip_ticks(row["later"]),
            "labelled_by": LABELLED_BY,
            "labelled_on": LABELLED_ON,
            # C's columns (C1), see the module docstring: written empty by design.
            "reviewed_by": "",
            "review_notes": "",
        })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print("wrote %s with %d labels" % (path, len(rows)))
    empty = [r["id"] for r in rows if not r["also_acceptable"] or not r["partial_if"] or not r["wrong_if"]]
    if empty:
        print("still empty judgement columns:", ", ".join(empty))
    taken = [r["id"] for r in rows if r["reviewed_by"] or r["review_notes"]]
    if taken:
        print("A must not fill the review columns (they are C1's):", ", ".join(taken))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
