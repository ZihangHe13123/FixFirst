# Django test configuration mechanism

Approved scope: the Django item in `CODEX_TO_CLAUDE_V08_REVIEW_20261002.md`,
followed by the user's implementation authorization. Base: `91f1a98`.

## Mechanism and boundaries

Add `django_configuration.py`, a bounded static project collector and a narrowly
matched observation/refinement adapter. Extend the project snapshot and rule
wiring only. Do not change classifier features, trained models or domain data.

The settings mechanism requires the exact Django unconfigured-settings error,
the failing `django/conf/__init__.py` frame, a unique installed Django provider,
and a current environment snapshot taken before the executed failing pytest run.
The apps mechanism requires `AppRegistryNotReady: Apps aren't loaded yet.` at
`django/apps/registry.py`. A visible `django.setup`/registry-population chain
prevents a strong missing-configuration diagnosis: early imports during setup
can cause the same exception. Grouped failures must independently agree; no
cross-failure borrowing. Missing/foreign/hidden frames, stale environments,
local Django shadowing and unrelated ImproperlyConfigured errors do not match.

Static collection covers root tox.ini testenv setenv, Makefile recipes,
runtests.py literal environment assignments, and pytest-django settings in
pytest.ini, .pytest.ini, tox.ini, setup.cfg and pyproject.toml. Read only bounded
regular files contained by the root; reject symlinks, invalid/oversized input;
record unknown sources without blocking the project snapshot. Parse, never
import or execute, Python/configuration. Record presence and source, not
effective configuration. Environment metadata means current distribution/import
ownership and run provenance, not a guess about unrecorded environment variables.

Advice names project-recorded settings and entrypoints. Multiple modules or
dynamic configuration remain an explicit choice to check. Even a unique literal
is a candidate, not proof of importability or intended deployment settings.
Plain pytest may bypass tox/Makefile/runtests; pytest-django requires an active
plugin and configuration. Recommend the existing test setup first; only a
genuinely standalone runner should initialize Django before model imports.
Never add setup to reusable production imports or hardcode tests.settings.

## Integration and validation

Expose `recorded_configuration(root)`, `observations(session, issues)` and
`refine(session, actions, details)`. New direct observation rules D51/D52 and
manual action P86 retain evidence references and official source attribution.
No commands execute from these actions. Keep knowledge additions independently
owned by Claude.

Synthetic tests cover config formats/safety/ambiguity and exact positive and
negative provenance. Separately reproduce small failures and fixes in an
isolated Django environment, including valid setup with another error and an
early import during setup. Run the relevant existing tests, then the full test
suite. No LLM, heldout inputs, formal experiment or generator run.

## Official sources checked

- https://docs.djangoproject.com/en/5.2/topics/settings/
- https://docs.djangoproject.com/en/5.2/ref/applications/#troubleshooting
- https://pytest-django.readthedocs.io/en/latest/configuring_django.html
- https://github.com/django/django/blob/stable/5.2.x/django/conf/__init__.py
- https://github.com/django/django/blob/stable/5.2.x/django/apps/registry.py

The settings exception distinguishes unset settings from other configuration
errors. Registry readiness alone does not distinguish absent setup from an
import-order defect. Static source presence establishes neither precedence nor
execution; CLI, environment, plugin loading and runtime changes remain relevant.
