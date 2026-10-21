# Django configuration validation

2026-10-02. Development acceptance on Darwin arm64, not heldout evaluation.
No LLM, training, toolchain generator, A2 run or production project was used.

## Environment

The host test interpreter is the existing v0.8 development `.venv/bin/python`;
pytest was invoked with `-o pythonpath=src`, never global PYTHONPATH.
The independent target environment was freshly created outside the repository
with uv 0.11.27 and CPython 3.12.13. Its complete package freeze:

```text
asgiref==3.12.1
django==5.2.1
iniconfig==2.3.0
packaging==26.3
pluggy==1.6.0
pytest==8.3.5
pytest-django==4.11.1
sqlparse==0.6.0
```

## Commands and results

Run from this checkout, with `HOST_PYTHON` set to the development interpreter
and `TARGET_PYTHON` to the isolated Django interpreter:

```sh
FIXFIRST_DJANGO_PYTHON="$TARGET_PYTHON" "$HOST_PYTHON" -m pytest -o pythonpath=src tests/test_django_configuration.py -q
"$HOST_PYTHON" -m pytest -o pythonpath=src tests -q
"$HOST_PYTHON" -m ruff check src/fixfirst/django_configuration.py src/fixfirst/_runtime_evidence.py src/fixfirst/project.py src/fixfirst/reasoning.py tests/test_django_configuration.py
git diff --check
```

- Django focused suite: **62 passed**, including 10 independently executed
  target-environment cases. Windows paths are synthetic; no native Windows run.
- Existing complete suite plus new tests: **1291 passed, 11 skipped**. Ten
  skips are opt-in Django subprocess cases, exercised separately above.
- Ruff and whitespace checks: passed.

The real cases cover unset settings and unready global apps both at collection
and runtime. Their confirmed changes (a selected settings module, or setup in
the synthetic test entrypoint before imports) made the original pytest scope
pass. Healthy configuration, a different ImproperlyConfigured error,
initialization-in-progress import order, a custom Apps instance, missing Django
and a project-local Django shadow did not trigger D51/D52.

Initial reproduction exposed the existing probe's 20-frame cap. It was not
relaxed into evidence of absence: the approved small runtime extension records
native bools on the actual global Apps receiver. Missing/old/non-bool/custom
registry state cannot support D52. This does not establish whether setup ran
historically; advice explicitly describes the state at the failing access.

## Deliberate limits

Only exact typed terminal exceptions with current execution, environment and
distribution ownership support the new rules. Text-only old snapshots remain
unknown. Configuration collection is root-only, bounded and static; no settings,
runtests, tox or Makefile code executes. Dynamic substitutions, configuration
classes, invalid/unsafe files and multiple settings candidates require review.
A literal is not proof of importability, precedence or intended deployment.
Actions name sources and test entrypoints, but do not silently replace the
recorded pytest invocation or claim an alternative runner verified that scope.

No classifier feature, model artifact or domain knowledge table changed.
