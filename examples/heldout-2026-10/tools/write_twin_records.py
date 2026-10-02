"""Write one twin record per project into twins/<id>.txt (task A1).

The twin check answers four questions per project:
  Original        --repeat 2 reproduced the target failure (pytest/<id>.txt).
  Twin            only the change the first step prescribes -- no other difference.
  Target failure  did the original error go away?
  After twin      pass, or a clearly different next-layer failure.

The numbers below were read off twins/<id>.raw*.txt, which hold the raw pytest
output of the runs that produced them.  Re-run this script after adding a twin.

    python tools/write_twin_records.py
"""

from __future__ import annotations

import pathlib
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent
TWINS = ROOT / "twins"

HEADER = """# Twin check for the held-out batch (task A1)
#
# project: {id} ({repo})
# The twin is a copy of the project with the same environment (scripts/heldout.py twin).  The
# original project and its environment are untouched, so pytest/{id}.txt stays valid.
# Raw pytest output of each run: twins/{id}.raw*.txt
#
# What was checked
#   Original        --repeat 2 reproduced the target failure (pytest/{id}.txt).
#   Twin            only the change the first step prescribes -- no other difference.
#   Target failure  did the original error go away?
#   After twin      pass, or a clearly different next-layer failure.
#
# Machine paths in the raw captures are shortened to <home>, and the user name in
# pytest's own temporary-directory names to <user>, the way scripts/heldout.py does
# for pytest/<id>.txt.  Nothing else in them was edited.
"""

RECORDS = {
    "click": {
        "repo": "pallets/click 8.0.3",
        "original": [("exit 1", "AttributeError: __spec__")] * 2,
        "whats": [
            ("A", "the pinned pytest==6.2.5 replaced by pytest 9.1.1, nothing else",
             "exit 1, AttributeError: __spec__ -- the SAME error, so the pytest version is not the cause"),
            ("B", "py 1.10.0 (pinned in requirements/tests.txt) upgraded to py 1.11.0, nothing else",
             "exit 2, 1 error -- pytest starts; the target error is gone"),
            ("C", "py 1.11.0 kept and the pinned pytest==6.2.5 put back, so only py differs from the original",
             "exit 2, 19 errors -- pytest starts here too"),
        ],
        "target": (
            "Gone in B and C, NOT gone in A.  The symptom comes from the pinned py 1.10.0, which Python "
            "3.12 cannot import at all, and not from the pytest version."
        ),
        "after": [
            "A: unchanged (AttributeError: __spec__).",
            "B (modern pytest): tests/test_basic.py fails to collect -- PytestRemovedIn10Warning: Passing "
            "a non-Collection iterable to parametrize is deprecated; argvalues type: chain (click's own "
            "test passes itertools.chain), raised as an error by click's filterwarnings.",
            "C (pinned pytest 6.2.5 + py 1.11.0, i.e. the project's own toolchain on 3.12): 19 collection "
            "errors, all DeprecationWarning: ast.Str is deprecated ... -- the same layer httpx and the "
            "pytest project hit, coming from pytest 6.2.5's own src/_pytest/assertion/rewrite.py:823.",
        ],
    },
    "pytest": {
        "repo": "pytest-dev/pytest 6.2.5",
        "original": [("exit 4", "DeprecationWarning: ast.Str is deprecated and will be removed in "
                                "Python 3.14; use ast.Constant instead")] * 2,
        "whats": [
            ("", "the same checkout and the same pinned dependencies, run on Python 3.10.21 instead of "
                 "3.12.7 (uv venv -p 3.10, then -e .[testing] and pygments>=2.7.2, exactly the "
                 "manifest's install lines)",
             None),
        ],
        "target": "Gone -- no conftest import failure; the suite starts and 2849 tests pass.",
        "after": [
            "exit 1, 86 failed, 2849 passed, 100 skipped, 9 xfailed, 12 errors in 290 s.",
            "next layer: 67 lines are ModuleNotFoundError: No module named 'pkg_resources' (this venv "
            "has no setuptools -- uv venv --seed installs pip only), and the rest are expected-output "
            "mismatches of a 2021 test suite (assertion dumps and pytester RunResult text).",
        ],
    },
    "httpx": {
        "repo": "encode/httpx 0.21.1",
        "original": [("exit 4", "DeprecationWarning: ast.Str is deprecated and will be removed in "
                                "Python 3.14; use ast.Constant instead")] * 2,
        "whats": [
            ("", "the pinned pytest==6.2.4 (requirements.txt:29) replaced by pytest 9.1.1, nothing else",
             None),
        ],
        "target": "Gone -- ast.Str appears 0 times in the whole output.",
        "after": [
            "exit 4, and the conftest still cannot be imported, but for a different reason: "
            "tests/conftest.py:20 -> httpx/_models.py:1 -> import cgi -> DeprecationWarning: 'cgi' is "
            "deprecated and slated for removal in Python 3.13, escalated to an error by httpx's own "
            "setup.cfg filterwarnings = error.",
            "so the second layer is httpx's own use of the module Python 3.13 removes, not the test "
            "toolchain.",
        ],
    },
    "python-qrcode": {
        "repo": "lincolnloop/python-qrcode v7.3.1",
        "original": [("exit 1", "9 failed, 62 passed, 2 skipped")] * 2,
        "whats": [
            ("step 1", "only qrcode/release.py:34, the first-step change: strftime('%-d %b %Y') (a glibc "
                       "extension CPython on Windows does not implement) replaced by a portable equivalent",
             "exit 1, 9 failed, 62 passed, 2 skipped -- 'Invalid format string' still appears once"),
            ("step 2", "the same nonportable directive at its second site, tests/test_release.py:37 (the "
                       "test's own expectation), nothing else",
             "exit 1, 9 failed, 62 passed, 2 skipped -- 0 format errors"),
        ],
        "target": (
            "Gone after step 2: 'Invalid format string' drops from 1 to 0.  It took two sites -- the "
            "directive is in the project code and in the test that asserts on it."
        ),
        "after": [
            "step 1: the same ValueError is now raised from tests/test_release.py:37, so the first-step "
            "change moved the failure instead of clearing it.",
            "step 2: the date handling is fine, and the release test now fails at tests/test_release.py:39, "
            "mock_file().write.has_calls(...): modern unittest.mock rejects the name -- AttributeError: "
            "'has_calls' is not a valid assertion (the typo deny-list).",
            "unchanged in both steps: the 8 ScriptTest failures from qrcode/console_scripts.py:36 "
            "('from pkg_resources import get_distribution') -> ModuleNotFoundError: No module named "
            "'pkg_resources'.  Deliberately not touched: a second, independent cause.",
        ],
    },
    "robotframework": {
        "repo": "robotframework/robotframework v4.1.3",
        "original": [("exit 2", "98 errors")] * 2,
        "whats": [
            ("", "one root conftest.py doing only what utest/run.py does for the package: sys.path.insert "
                 "of src/.  Nothing else, and no project file was edited",
             None),
        ],
        "target": "Gone -- all 98 'No module named robot' errors disappear (robot 4.1.3 imports from src/).",
        "after": [
            "exit 2, 45 warnings, 5 errors in 1.48 s (collection is interrupted, so no test runs yet).",
            "next layer, 4 of the 5: utest/api/test_run_and_rebot.py:18 and utest/running/test_running.py:11 "
            "-> No module named 'resources'; utest/running/test_handlers.py:17 and test_testlibrary.py:12 -> "
            "No module named 'classes'.  Those are the project's own test-support packages: utest/run.py:28-33 "
            "inserts ../src AND ../atest/testresources/testlibs, and its discovery inserts the utest/ "
            "directory itself (run.py:42), so the runner supplies three paths and src/ alone is only the "
            "first of them.",
            "the 5th is utest/utils/test_encoding.py:9 UNICODE.encode(CONSOLE_ENCODING) -> UnicodeEncodeError: "
            "'gbk' codec ... That one is the machine's console codepage (cp936), not a project defect, and "
            "PYTHONUTF8 does not help because the test encodes with the console codepage explicitly.",
        ],
    },
    "seleniumlibrary": {
        "repo": "robotframework/SeleniumLibrary v6.3.0",
        "original": [("exit 2", "33 errors")] * 2,
        "whats": [
            ("", "one root conftest.py doing only what utest/run.py does for the package: sys.path.insert "
                 "of src/.  Nothing else, and no project file was edited",
             None),
        ],
        "target": "Gone -- all 33 'No module named SeleniumLibrary' errors disappear.",
        "after": [
            "exit 1, 3 failed, 217 passed, 24 skipped, 6 warnings in 9.93 s.",
            "next layer: the 3 failures are firefox cases in utest/test/keywords/test_selenium_options_parser.py, "
            "e.g. FileNotFoundError: ...\\utest\\output_dir\\geckodriver-1.log -- browser/driver dependent tests "
            "(selenium is unpinned in requirements-dev.txt and installed as 4.49.0), unrelated to the import layer.",
        ],
    },
    "django-cacheops": {
        "repo": "Suor/django-cacheops 6.0",
        "original": [("exit 2", "2 warnings, 1 error")] * 2,
        "whats": [
            ("step 1", "DJANGO_SETTINGS_MODULE=tests.settings in the environment for the run, and nothing "
                       "else (no file touched)",
             "exit 2, 2 warnings, 1 error -- ImproperlyConfigured appears 0 times"),
            ("step 2", "the same step completed the way the project's own runner does it (run_tests.py:3 sets "
                       "the settings module, run_tests.py:20 calls django.setup()): a root conftest.py with "
                       "exactly those two lines",
             "exit 1, 8 failed, 3 passed, 3 warnings, 4 errors in 344 s"),
        ],
        "target": (
            "Gone after step 1: 'Requested setting CACHEOPS_DEGRADE_ON_FAILURE, but settings are not "
            "configured' drops to 0."
        ),
        "after": [
            "step 1: exit 2, 1 error -- django.core.exceptions.AppRegistryNotReady: Apps aren't loaded yet, "
            "which is the second thing run_tests.py:20 does.",
            "step 2: collection finally works and the tests run, revealing a third layer: "
            "sqlite3.OperationalError: no such table: tests_category (run_tests.py also runs makemigrations "
            "itself) and redis.exceptions.ConnectionError ... localhost:6379 (no Redis service on this "
            "machine).",
            "the step-2 run took 344 s, most of it Redis connection retries -- do not re-run it casually.",
        ],
    },
    "django-storages": {
        "repo": "jschneier/django-storages 1.14.6",
        "original": [("exit 1", "253 errors")] * 2,
        "whats": [
            ("", "DJANGO_SETTINGS_MODULE=tests.settings in the environment for the run, and nothing else "
                 "(no file touched, no conftest.py added)",
             "exit 1, 2 failed, 251 passed, 296 warnings in 9.95 s -- ImproperlyConfigured appears 0 times"),
        ],
        "target": (
            "Gone -- all 253 'Requested setting DATABASES, but settings are not configured' errors disappear "
            "with the environment variable alone."
        ),
        "after": [
            "exit 1, 2 failed, 251 passed.",
            "next layer: the 2 failures are Windows path handling -- dropbox's stone validator rejecting "
            "'C:/foo' ('did not match pattern ...') and an assertion 'parent\\chil.txt' != 'parent/chil.txt'. "
            "Neither is a configuration problem.",
        ],
    },
    "python-markdown": {
        "repo": "Python-Markdown/markdown 3.4.3",
        "original": [("exit 2", "2 errors")] * 2,
        "whats": [
            ("", "the declared testing dependency installed and nothing else: uv pip install pyyaml into "
                 "the copy's venv.  No project or test file was edited, and the testing extra's other "
                 "entry (coverage) was deliberately left out so the intervention stays one package",
             "exit 2, 1 error -- the target error is gone and collection now reaches 1090 items"),
        ],
        "target": (
            "Gone: 'No module named yaml' at tests/test_apis.py:34 drops to 0 occurrences.  In the "
            "untouched environment the same interpreter fails `import yaml` on its own, so the twin's one "
            "intervention is what removed it."
        ),
        "after": [
            "exit 2, 1090 items collected, 1 error in 0.92 s.",
            "next layer, the only one left: tests/test_syntax/extensions/test_md_in_html.py imports "
            "unittest.TestSuite, and modern pytest refuses to collect a Test* class that has an __init__ "
            "constructor -- pytest.PytestCollectionWarning raised during collection, which interrupts it.",
            "that residual cannot come from project config: the repository has no pytest configuration at "
            "all (no pytest.ini, no setup.cfg, no [tool.pytest.ini_options] in pyproject.toml, no [pytest] "
            "section in tox.ini), so it is modern pytest against 2021 test code -- the same kind of layer "
            "as httpx's cgi and python-qrcode's has_calls.",
            "extra evidence for the first layer, outside the twin: the project's own documented test "
            "command, python -m unittest discover tests (docs/contributing.md:298), run in the untouched "
            "environment, dies on the same line -- Ran 894 tests, FAILED (errors=1, skipped=129), "
            "ModuleNotFoundError: No module named yaml at tests/test_apis.py:34.  Raw output: "
            "twins/python-markdown.docpath.txt.",
        ],
    },
    "dateparser": {
        "repo": "scrapinghub/dateparser v1.1.0",
        "original": [("exit 2", "17 warnings, 3 errors")] * 2,
        "whats": [
            ("", "the declared extra installed: uv pip install fasttext, which is the first step the label "
                 "prescribes",
             None),
        ],
        "target": (
            "NOT gone, and it cannot be made to go away here.  The install itself fails with 'error: "
            "Microsoft Visual C++ 14.0 or greater is required', fasttext is still absent from the "
            "environment, and the run is identical to the original (exit 2, 3 errors, all 'No module named "
            "fasttext')."
        ),
        "after": [
            "exit 2, 17 warnings, 3 errors in 9.07 s -- unchanged.",
            "this is the one case in the batch whose first layer cannot be closed in the target environment: "
            "the dependency is declared by the project (setup.py extras_require={'fasttext': ['fasttext']}) "
            "but has no Windows/cp312 wheel and needs a C++ toolchain to build.",
        ],
    },
}

SLUGIFY = [
    "# Twin check for the held-out batch (task A1)",
    "#",
    "# project: python-slugify (un33k/python-slugify v9.1.0, checked out at the parent of the fix,",
    "#          c442cd4cb61763c85b078d6ea83b5959c3ff364a)",
    "# The twin is a copy of the project with the same environment (scripts/heldout.py twin).  The",
    "# original project and its environment are untouched, so pytest/python-slugify.txt stays valid.",
    "# Raw pytest output: twins/python-slugify.raw.txt",
    "#",
    "# What was checked",
    "#   Original        --repeat 2 reproduced the target failure (pytest/python-slugify.txt).",
    "#   Twin            only the change the first step prescribes -- no other difference.",
    "#   Target failure  did the original error go away?",
    "#   After twin      pass, or a clearly different next-layer failure.",
    "",
    "Original (pytest/python-slugify.txt)",
    "  run 1: exit 1, 7 failed, 124 passed",
    "  run 2: exit 1, 7 failed, 124 passed",
    "  same_every_run: true",
    "  the 7 are 1 failure plus 6 failing subtests of the two regression tests taken from the fix",
    "  commit 8f9a550 (tests/test_release.py), e.g. 'one-' != 'one' and '-' != ''.",
    "",
    "Twin",
    "  slugify/slugify.py replaced by the file from the fix commit 8f9a550 (#200), and nothing else;",
    "  the regression tests stay exactly as the fix commit wrote them.",
    "",
    "Target failure",
    "  Gone -- both regression tests pass.",
    "",
    "After twin",
    "  exit 0, 125 passed in 2.04 s.  (125 items: 124 passed + 1 failed = 131 in the original footer,",
    "  because pytest counts the 6 subtest failures on top of the item counts.)",
    "  next layer: none -- nothing is left failing, so python-slugify has no later_layers.",
    "",
]


def main() -> int:
    for pid, record in RECORDS.items():
        lines = [HEADER.format(id=pid, repo=record["repo"]).rstrip(), ""]
        lines.append("Original (pytest/%s.txt)" % pid)
        for i, (code, summary) in enumerate(record["original"], 1):
            lines.append("  run %d: %s, %s" % (i, code, summary))
        lines.append("  same_every_run: true")
        lines.append("")
        lines.append("Twin")
        for tag, what, result in record["whats"]:
            prefix = "%s: " % tag if tag else ""
            lines.append(textwrap.fill(prefix + what, 96, subsequent_indent="      "))
            if result:
                lines.append(textwrap.fill("      -> " + result, 96, subsequent_indent="         "))
        lines.append("")
        lines.append("Target failure")
        lines.append(textwrap.fill("  " + record["target"], 96, subsequent_indent="  "))
        lines.append("")
        lines.append("After twin")
        for item in record["after"]:
            lines.append(textwrap.fill("  " + item, 96, subsequent_indent="  "))
        lines.append("")
        (TWINS / ("%s.txt" % pid)).write_text("\n".join(lines), encoding="utf-8")
        print("wrote twins/%s.txt" % pid)
    (TWINS / "python-slugify.txt").write_text("\n".join(SLUGIFY), encoding="utf-8")
    print("wrote twins/python-slugify.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
