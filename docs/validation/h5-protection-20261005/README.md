# H5 validation, 2026-10-05

Source candidate: `bb77c63d02ba376cbc0e4195babe2c01ae15d475` (tree
`d7481d600f6f73dad836b9415553a157cef824bf`). Later commits in this directory
only save validation records; the grading code identity stays the same.

- Full development suite: **2057 passed, 75 skipped**, zero failures. One existing
  pkg_resources deprecation warning. The log lists every skip: optional live
  interpreter fixtures, environment generation, and Windows-specific checks.
- Explicit macOS sandbox suite: **116 passed** (107 legacy, 9 H5).
- H5 targeted tests: **73 passed** (64 ordinary, 9 sandbox).
- Knowledge guard tests: **170 passed**. Ruff and diff checks passed.
- The supplied executable H5 specification: **29/29** agree. Its content digest
  and individual results are in `CLAUDE_SPEC_CHECK.json`.
- Synthetic Django: **3/3** arms accept a saved settings module, then pass the
  original test in a fresh, clean sandboxed grader process. Packages and scripted
  run receipts are in `DJANGO_SANDBOX.json`.

- Real old-tool startup: pytest 6.2.5 / py 1.10.0 on Python 3.12.13 fails with
  `AttributeError: __spec__` before pytest hooks run. The trusted startup record
  plus its normal exit 1 keeps it **graded, fixed=false**; it is not removed from
  the denominator. Receipt: `EARLY_FAILURE_SANDBOX.json`; reproduction script:
  `early_failure_acceptance.py --python OLD_ENV/bin/python --out NEW_DIR`.

Only synthetic projects and scripted replies were used for H5. No language model
was started, no sealed task contents were read, no old results were regraded, and
neither product source nor the default model changed. These checks establish the
grading behavior, not an MCP performance improvement.

The receipt binds the rule/probe and the integration code by content. Preserve
that identity when reproducing it. Tests and actual grading use pytest 9.1.1 on
CPython 3.12.13, macOS arm64. Linux CI runs the ordinary suite separately; macOS
sandbox execution and Windows execution are not inferred from it.

To repeat the Django check, create a disposable environment with pytest 9.1.1,
pytest-django 4.11.1 and Django 5.2.17, then run:

```bash
.venv/bin/python docs/validation/h5-protection-20261005/django_acceptance.py \
  --python /absolute/path/to/disposable-env/bin/python \
  --out /absolute/path/to/new-folder-outside-repo
```

Independent acceptance should check default CLI behavior plus explicit H5,
all allowed and rejected configuration formats, higher-priority shadow files,
restored violations, reference repairs, exact nodes, missing observations and
cache/protocol separation. New hard selections need qualification and freezing
under the final integrated harness and environment.
