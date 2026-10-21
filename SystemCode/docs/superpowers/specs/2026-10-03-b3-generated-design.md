# B3 generated and hard batch preparation

The user approved continuing B3 preparation after the 2026-10-03 preflight. This implements that next step; model inference is a separate execution phase after the preparation gates pass.

## Scope

Use frozen v0.7.0 `c8151af7bd6c19d71605dd3add38ea2dcda98ec2`, including its unchanged 44-feature factory model. Recollect the frozen 44 scenarios × 5 templates and six hard scenarios × 5 templates in one independent pinned environment. Save successful and rejected acquisition outcomes, healthy-template evidence, commands, environment, code identity and hashes. Do not mix five new cases into the historical 215. These are public development scenarios; no claim of unseen-task generalisation.

## Approach

Reuse the approved real-project B3 raw-evidence and seal mechanisms from `5cff6702351272829e2424c54f0d1232963d021f`; import those existing helpers unchanged, and add a separate generated-batch adapter. This retains the generated task's five-cause protocol while supplying bounded raw failure/outcome records and package requirements that the legacy sender omitted. It is a new named protocol, not the historical development-trial prompt or the real-project six-class prompt.

Keeping the legacy sender would preserve its prompt but retain its evidence omissions and weak completion seal. Directly using the real-project sender would silently introduce healthy as a sixth class. The separate thin adapter avoids both inconsistencies. Product source, knowledge and classifier are unchanged.

## Preparation and inference boundary

- Preparation reads generated case records and their shared environment storage; reconstructs the stored session, checks run/snapshot provenance, and uses the existing raw-field allowlists and bounded redaction. Shared storage restoration must be identified in provenance, never described as a fresh observation.
- Exact source case/environment files, resulting evidence bytes, ordering and separated labels are hashed. Case IDs, scenario IDs, labels, knowledge coverage, FixFirst issues/facts/actions/conclusions do not appear in model messages. All three models receive the same evidence bytes.
- The sender only reads the label-free bundle. Independent requests, five causes, no tools/history/retry, temperature 0, top_p 1, max_tokens 1024, thinking off, seed 20260929. Invalid or failed requests remain recorded. A process interruption leaves an unsealed result; no automatic resend of uncertain outcomes.
- Input/model/token/context identity and runner source must be fixed before starting the intended 750 requests. An acquisition rejection or failed gate is recorded and resolved transparently before that registration; cases are not replaced based on model answers.

## Offline scoring

Read truth only after validating a complete answer seal and exact unique model × registered-case coverage, source/input/protocol hashes, labels hash and explicit suite membership. Root-cause accuracy includes missing/invalid roots as incorrect. Preserve the legacy rule that a valid root with missing first_step can count for root accuracy, while reporting its incomplete answer separately.

Report diagnosis and hard suites separately. Diagnosis uses the fixed five-class Macro-F1. Hard reports accuracy, per-class counts, Macro-F1 over its two preregistered truth-supported classes, and separately the historical fixed-five Macro-F1 with its 0.4 all-correct ceiling. Supported classes come from registered truth, not model predictions. First-step presence is not a quality score; recommendations remain unscored without an explicit human-scoring plan. Do not combine this batch with the real-project score.

## Verification and deliverables

Use synthetic inputs/fake responses for protocol tests: forbidden fields absent; snapshot mismatch rejected; labels separated; exact pairing and all hashes enforced; failures retained; no outputs overwritten; bad/partial seals rejected. Check hard all-correct gives supported F1 1 and fixed-five F1 .4. Audit the actual fresh snapshots for coverage and expected fault shapes before preparing final inputs. Independently review the adapter and seal tests.

Deliver an isolated preparation commit, fresh snapshots and rejection ledger, environment lock, label-free input bundle, separate labels, offline tokenizer counts, full model-file identity receipt, and a concrete run registration candidate. No push, merge or inference is implied by saving this preparation.
