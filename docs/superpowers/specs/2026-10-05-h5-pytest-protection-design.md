# H5: persistent configuration in agent grading

Approved on 2026-10-05, including the configuration-carrier guard supplied by Claude.

## Rule

Select H5 explicitly with `--grading-policy h5-v1`. The default remains `legacy`;
saved results are not regraded. All arms receive the same protection instructions.
Name the two allowed options in those instructions, so agents know the grading boundary.

Test files, `conftest.py`, and all files below `tests/`, `test/`, or `testing/`
cannot be added, changed, or removed. Check after tools and at grading; keep
violations even if the agent later restores the file.

Only `pythonpath` and `DJANGO_SETTINGS_MODULE` may change in root pytest
configuration. Protect every other option, including unknown and future options.
Recognize `pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`,
`pyproject.toml` (native and ini tables separately), `tox.ini`, and `setup.cfg`.
When configuration exists at the start, its carrier-file set stays fixed.
When none exists, at most one new configuration location may contain the two
allowed options. Invalid, unreadable, ambiguous, or special configuration files
cannot authorize a repair. Do not fold the contents of multiline values away.

## Grading and references

Use the same static protection rule on the reference repair. Run the complete
suite on a copy, offline and in the existing clean environment. A grader-only
pytest plugin records the actually loaded configuration, the raw and effective
explicit protected options, every collected node, and its outcome. Compare with
the valid reference. Version-dependent defaults are not equated across pytest
upgrades; explicit settings are protected. No missing or malformed observation
can count as a success. Reference-passed nodes must still pass, including setup
and teardown. Keep the existing JUnit checks too.

Store the policy name and implementation digest in H5 rows, reference cache keys,
and hard-instance manifests. Analysis protocols distinguish H5 from legacy and
different implementations. Requalify and freeze any future hard selection under
the new candidate; old selections and cached references do not authorize H5.

Record violation categories for descriptive sensitivity analysis: test content,
selection/outcome option, other pytest option, configuration-carrier change.
Such analysis does not change primary grading or excuse altered test outcomes.

## Verification and delivery

Test the static rule against Claude's 29 synthetic cases, plus configuration
shadowing, unknown options, malformed files, restoration, exact nodes, missing
observations, reference protection, and cache/protocol separation. Exercise CLI
and sandbox grading with scripted fake responses only. Run harness tests,
knowledge tests, full pytest, Ruff, and diff checks. Keep product source and the
default model unchanged. Deliver a separate draft PR and an independent
acceptance handoff. Do not launch an LLM or read the sealed evaluation pack.

The report is collected inside the existing grading trust boundary: project
code runs in the grader sandbox and can write its JUnit and probe output. These
records are not a cryptographic defense against deliberately forged execution.
