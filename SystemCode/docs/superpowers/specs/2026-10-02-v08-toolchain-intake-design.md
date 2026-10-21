# v0.8 toolchain intake and comparison

The user approved starting the previously discussed v0.8 work after Claude supplied the generator. This change owns dataset intake, reproducible regeneration and development comparisons. Addopts, Django and source-build guidance are separate changes; Claude owns additional knowledge entries.

## Input and interpretation

Import the supplied patch on the fixed PR #55 source, retaining its historical saved data as development evidence. The input registers 22 scenarios, keeps cases from 21, contains 98 cases and 108 issue rows, and records five unparsed and four rejected candidates. Template exclusions are separate. These are not independent generalization data or project repair-success rates.

Keep the case roster and exclusion ledger when comparing source revisions. Report parsing coverage and case/issue counts independently. Do not make unparsed baseline cases disappear from the denominator or mix old and newly produced issue rows into a purported paired comparison. Labels supplied by Claude remain provisional where indicated, especially missing versus removed pkg_resources and Django initialization.

## Reproducible generation

Add a reusable environment lock recording full interpreter identity, OS/architecture, uv identity, and exact installed packages for both fault and reference environments. Pin Python patch versions and all package versions for replay. Refuse partial or incompatible locks; do not silently reuse arbitrary existing environments. Work directories must be newly created/owned, and cleanup must never remove a preexisting caller directory. Preserve source/template identities and original reference changes.

A reference passing after replacement of an entire environment is evidence that the declared reference can pass, not evidence that FixFirst's actual proposed command repaired the initial environment. Validate actual proposals separately and preserve constraints, warnings and test files. A failed verification remains in the audit ledger.

## Evaluation and delivery

Keep suite loading explicit, bounded and predictable, with no path traversal/cycles/duplicate child datasets. Feature extraction stays separate from parser regeneration. Investigate the historical evaluation mismatch before quoting any newly computed number; keep the frozen v0.7.0 artifacts unchanged.

Validate original import, generator/loader contracts and real fixed-environment regeneration. Use root-level case comparisons as the primary development summary, with issue-level measurements separately labeled. Save sanitized evidence, exact source hashes and commands. Commit intake separately from candidate feature/model changes. No formal B3/B7 run, held-out data, LLM startup, release merge or default model replacement is part of this intake.
