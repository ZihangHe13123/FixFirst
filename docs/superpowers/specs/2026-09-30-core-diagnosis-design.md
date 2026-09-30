# Core diagnosis improvement, first development round

Date: 2026-09-30

## Approved scope

The user chose complete diagnostic usefulness (root cause and the first actionable
step) as today's priority, and approved improving lost library evidence,
evidence-supported compatibility diagnoses and first-step advice with positive and
negative development examples. UI work, report formatting and unrelated experiment
infrastructure move behind this work. Necessary comparisons and regression tests
remain part of the work.

## Starting point

Baseline: main `11bbe7edb74fe9571bd8c816f4aa0a8126445021`.

A fresh replay of the saved development sessions produced:

| Check | Decision tree | Complete system |
|---|---:|---:|
| 215 diagnosis cases, leave one scenario out | 60.93% | 95.35% |
| 30 hard development cases, bundled tree | 5/30 | 15/30 |

The hard set contains six families and five templates per family. Those 30 cases
are not 30 independent faults and are not the private A1/C1 test set. Rules have
already been developed using them. The two NumPy behavior changes and the Pydantic
coercion change account for the 15 remaining misses in this replay.

The probe has the actual exception source file even when pytest hides library
frames, but evidence extraction currently ignores it when identifying the library.
Some version-related failures and ordinary code defects have identical 44-feature
vectors. Repeating training alone cannot distinguish those observations.

## Design

1. Preserve structured exception provenance when deriving the raising library and
   the path from project code into it. Keep collection-error handling conservative
   and do not interpret arbitrary exception text as a trusted source location.
2. Use the observed failure, installed version and relevant project context together
   for compatibility advice. An old minimum dependency version alone does not prove
   an upgrade caused the failure. Documented behavior changes must cite an upstream
   primary source, and their matchers must distinguish ordinary input/code errors.
3. Generate a concrete first step from the matching evidence. Prefer an explicit
   conversion or call correction when supported. Do not present an untested lower
   dependency bound as a version proved to fix the project.
4. Keep the existing rule/knowledge/tree architecture. Any training experiment is
   saved separately and compared with the bundled tree; there is no automatic
   replacement of the production model, new language-model service or freeze tag.

Implementation follows the existing evidence, domain knowledge, rule and action
interfaces. Add a focused helper module if behavior matching would otherwise
obscure the general evidence extractor. No unrelated refactor is included.

## Verification and first-round acceptance

- Replay exactly the same saved 215+30 cases before and after. Keep the baseline
  immutable; label the results as development replay, not freshly executed projects.
- Preserve the 215-case complete-system results and separately report tree results.
- Improve at least one missed behavior family with a source-supported diagnosis
  and an actionable first step. Report the families still unresolved.
- Execute new disposable positive examples and apply the proposed first step with
  the tests unchanged; verify that the targeted failure disappears.
- Execute counterexamples for normal application errors, invalid inputs, absent or
  incompatible version evidence and similarly worded exceptions. An improvement
  is not accepted if it introduces unsupported version fixes in those checks.
- Run relevant regressions and the main test suite. Existing known limitations
  and any newly observed ambiguity remain explicit in the result report.

This gate decides whether this particular change is ready for review. It does not
declare general real-world performance sufficient or substitute for independent
evaluation.

## Data and release boundaries

Use the existing diagnosis/hard development data and disposable new development
fixtures. The old 13 public development projects may be audited if needed. Do not
read the private A1/C1 candidates or labels, repurpose B12/B17/user-study evaluation
material, or start formal experiments. B5 remains a separate freeze task. The
human-data plan remains available for a subsequent controlled training round.

Deliver code, reproducible development evidence, remaining failures and a reviewable
PR. This design was approved in the conversation before implementation.
