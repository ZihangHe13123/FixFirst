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

## Model continuation

The user subsequently asked to continue improving model performance. The next
round targets the learned tree with shared configuration, project-name, import,
external-provider and data-operation contexts. These features contain observed
evidence only, with no diagnosis, rule result or knowledge identifier. Retain the
44-feature schema-3 prefix and support existing models. Train a separate candidate
on the same public 215 development records; keep the hard development cases out of
training. Compare fixed hyperparameters first, then use nested scenario-grouped
validation for any depth selection. Report tuning results as development evidence;
the independent A1/C1 evaluation and B5 freeze remain separate.

## Observation and real-data continuation

The user approved the next proposal to enrich distinguishing observations and
audit a small batch of real development failures. Add bounded, file/scope-aware
call provenance, external bases and relevant version records; pair the old and
new snapshots of the same synthetic faults when training for incomplete-history
compatibility. Those paired views must remain in the same validation group.

Replay publicly documented development faults in separate source exports and
environments, validating only their labelled layer. Preserve failed verification
attempts and explicitly mark human rereview pending. Run real-data and ordinary
API-misuse augmentation as separate comparisons. Neither the stress cases nor
the reserved ordinary-error controls enter fitting.

The real-data trial exposed ordinary argument/validation errors being called
version changes. Correct generic argument guidance and use documented,
version-qualified Click/PyYAML changes for specific migration advice. Evaluate
both the raw tree and complete system; retain rejected variants and any tradeoffs
instead of selecting solely for the highest synthetic score.

## Interface evidence and actual first-step continuation

The user approved continuing with the two proposed priorities: separate local
code errors from genuine interface changes, and execute the system's own first
steps in disposable project copies. Start from `6edc150` and retain its results.

Use file/scope-aware call and class-member evidence. Match historical interface
metadata only to the actual module/callable and installed release; similarly named
parameters on unrelated functions must not inherit a library's removal record.
The classifier may consume explicit, source-cited interface-history metadata in a
separate feature extension. Report this as knowledge-enriched classification and
include a history-disabled ablation; do not attribute that benefit solely to new
training data or call it knowledge-free learning. Keep old model layouts valid.

Train separate candidates on the existing development snapshots, with the same
fault grouped across old/new views. Preserve reserved controls and hard cases
outside fitting. Adopt a candidate only if grouped accuracy, both snapshot stress
sets and ordinary-error controls improve or remain acceptable together; retain
rejected alternatives. Add unrelated callable and local-shadowing counterexamples.

For the six public development faults, record the first action generated by
FixFirst before choosing a repair. Execute its command, or its explicitly stated
manual alternative, inside a fresh sandboxed copy. If the first action is an
inspection, execute it and record its generated next action separately. Check the
same affected tests/collection scope and unchanged test hashes. A missing target
error is not success when execution was blocked earlier. Preserve failed attempts
and later failure layers. Improve a confirmed first-step defect with a general
evidence-supported change, then rerun the affected copy; do not silently substitute
the previous reference repair. Keep A1/C1, B5 and unrelated tasks unchanged.
