# v0.8 knowledge ownership and bounded package repair

## Approved scope

The user approved the division of work and explicitly asked Codex to implement its portion on 2026-10-03. This document records that scope and the implementation decisions; it does not introduce another approval gate.

Baseline: product combination `c8de5a0d5a98ce50d59c853b0625dfbec287c445`.
Claude owns the new knowledge text and its verification receipts. Codex owns production ownership and package-repair mechanisms. The 724-entry proposal is not merged by this task; representative additions are test inputs. Frozen v0.7 results, held-out/B3 inputs, and the default 44-feature model remain outside the edits.

## 1. Confirm actual receiver ownership before removal diagnoses

Current failure: object text such as `Report.readfp` or a locally defined `EntryPoints.items` can activate a library removal solely through a bare attribute/class name. `owners` metadata is not currently enforced.

Considered approaches: removing the new entries loses valid coverage; adding name/regex exceptions is brittle; consuming bounded runtime owner observations preserves valid cases and supplies a reusable contract. Use the third approach.

- Reuse the actual exception's executed receiver/module observations, their run/environment/source links, and recorded provider identity. Extend bounded observations only where the existing contract cannot establish a valid library receiver; no expression evaluation, property invocation, object serialization, or new module import solely for diagnosis.
- An object attribute removal must match the knowledge entry's explicit qualified owner, or an unambiguous qualified identity already encoded in the entry. A short class spelling is never proof of its module.
- Keep project-defined types, local shadowing, conflicting providers, absent/imported/stale/ambiguous observations from producing a confirmed external removal. Preserve ordinary module/import-name diagnoses where their established evidence remains sufficient.
- Real ConfigParser and supported class-API positives must remain reachable; inherited standard-library methods need explicit, bounded ownership handling where supported. Unprovable cases retain conservative behavior.
- Keep classifier feature widths and the shipped model unchanged; add no training or score-driven heuristics.

## 2. Bound setuptools repair by both the fix and the removed provider

Current failure: `pkg_resources` from setuptools 65.7.0 on Python 3.12 references removed `pkgutil.ImpImporter`. Existing major-version limiting produces `setuptools>65.7.0,<66`, while an unbounded `>=66.1` may remove pkg_resources entirely at setuptools 82.

Considered approaches: hardcoding one version in prose is not consumed by planning; globally relaxing major-version bounds creates regressions; a source-backed repair range tied to this observed mechanism can intersect ordinary constraints. Use the third approach.

- Represent the repair lower bound and provider-removal upper bound as structured, source-cited data. Keep this small policy separate from Claude's bulk domain entries where practical.
- Recognize the actual setuptools/pkg_resources failure from selected-runtime evidence, not arbitrary text mentioning ImpImporter. Cover supported native and pytest execution paths. Respect project shadowing and source/environment provenance.
- For the supported Python range and a project still requiring pkg_resources, request an available bounded candidate satisfying `setuptools>=66.1,<82` and every recorded applicable requirement; retain normal resolver/installation feedback and same-scope rerun behavior.
- A known fix bound can cross the old package's major-version heuristic, but only for this evidenced mechanism. Conflicting pins, Python requirements, unsupported versions, and ambiguous ownership yield a clear review action without an installation command.
- A missing provider may be installed within the same supported provider range when absence and the failed import are observed. It is not inferred from unrelated missing modules. Keep any extension to six or other mechanisms out of this first bounded repair unless separately specified.
- Installation is user-run and logged through the existing workflow. Do not claim a range or successful pip operation proves the application fixed; actual acceptance executes the proposed command in an isolated test environment and reruns the original failure.

## Implementation separation

Ownership and package repair are separate commits/worktrees. Prefer dedicated helpers with small hooks in evidence/reasoning/domain/dependency advice. Preserve Claude's unmerged branch. Integrate the two code changes into this candidate, resolving shared hooks explicitly.

## Acceptance

1. Negative programs: local Report.readfp, local EntryPoints.items, and a second unrelated same-name type do not become confirmed library removals. Fake/imported/stale/grouped observations cannot lend another failure's receiver identity.
2. Positive programs: real ConfigParser.readfp (and a supported real class-form API case) obtain useful migration guidance; the relevant manual code repair reruns successfully.
3. Real package sequence: Python 3.12 + setuptools65.7 fails; the generated install command respects the compatibility bounds and reruns successfully without missing pkg_resources. Missing setuptools and constraints that exclude the whole range are tested separately.
4. Preserve old tool/Django/sdist behavior through targeted regressions, then run the repository's full local gate and Ruff once the integrated candidate is stable. Native Windows acceptance remains separate from path-shape tests.
5. Independent review checks the counterexamples and command execution. Publish reviewable draft PR(s) and exact commits; do not merge or change release tags.
