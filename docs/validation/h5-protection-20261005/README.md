# H5 validation, 2026-10-05

Source candidate: `d410eb02cde78bb2926aa94378d95668f659afed` (tree
`194d8ab69f845449cd8a7a786da8cbb035f147f6`). Later commits in this directory
only save validation records; the grading code identity stays the same.

- Full development suite: **2051 passed, 75 skipped**, zero failures. One existing
  pkg_resources deprecation warning. The log lists every skip: optional live
  interpreter fixtures, environment generation, and Windows-specific checks.
- Explicit macOS sandbox suite: **116 passed** (107 legacy, 9 H5).
- H5 targeted tests: **67 passed** (58 ordinary, 9 sandbox).
- Knowledge guard tests: **170 passed**. Ruff and diff checks passed.
- The supplied executable H5 specification: **29/29** agree. Its content digest
  and individual results are in `CLAUDE_SPEC_CHECK.json`.
- Synthetic Django: **3/3** arms accept a saved settings module, then pass the
  original test in a fresh, clean sandboxed grader process. Packages and scripted
  run receipts are in `DJANGO_SANDBOX.json`.

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
