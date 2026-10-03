# Repairs after full development regression and independent acceptance

Base: `090aa105c2b1d9e1c0dc24b6040adcd7306954ea`. The user has authorized
continued v0.8 improvements and supplied Claude's counterexamples for repair.
Keep this reviewed base fixed; implement in a separate branch.

## Required corrections

1. F4: distinguish a recorded setuptools constraint below the provider repair
   range from one above it. For a provably old requirement, review the named
   declaration/dependent package to admit the validated candidate range. For a
   provably newer provider requirement, preserve it and migrate the consumer.
   Mixed, impossible or unclassifiable sets require coordinated review. Keep
   conflict commands empty and do not open the deferred dependency-trial path.
2. Restore migration guidance for a real library-raised missing-name failure by
   observing the executed import, loaded module and its actual module-level
   __getattr__ code/argument. Do not infer ownership from copied message text or
   rerun a getter. Retain issue/run/statement/source/provider binding.
3. Historical receiver records lacking ancestry must remain incomplete when a
   known removed alias is involved. Do not convert missing evidence into a
   definite local-code defect. Fresh, fully observed local lookalikes retain
   their code-defect behavior.

## Receiver bounds decision

Measure the supplied SQLAlchemy cases before selecting a limit. The options are
retaining the present limit (unsupported cases remain parked), recording only
direct aliases (would lose legitimate inherited aliases), or bounded expansion
with a serialized-size ceiling. Prefer the last if the measured cases fit.

The intended envelope is at most 64 MRO entries and 128 owner rows, preserving
the existing per-module dictionary and parent-module limits. Add a 32 KiB ASCII
JSON limit on the owner list in both producer and validator. Return no ownership
record on overflow, without using a truncated list as proof. This leaves room
under the probe's existing 100,000-character single-record ceiling. Exact
behavior and actual object measurements are gates before accepting this policy.
Preserve alias/inheritance coverage and absence of getter/import side effects.

Changing the receiver identity functions invalidates Claude's previous owners
receipt. The 16 still-parked keys require updated owners and a new verification
receipt on the published candidate. Do not activate them using old receipt data.

## Validation and delivery

Use frozen regression inputs and independent counterexamples, retaining
before/after records. Run focused tests first, one full combined gate, unchanged
default-model hash, publication scan, and exact-head Linux CI. Publish a separate
draft PR and handoff; do not merge, tag, retrain, start an LLM, or use holdouts.
Owners/knowledge review remains a separate decision. Its unresolved verifier
binding findings cannot be hidden by passing product tests.
