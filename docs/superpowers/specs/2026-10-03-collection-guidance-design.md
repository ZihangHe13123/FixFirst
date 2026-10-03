# Collection wrapper and package repair guidance

The user approved F1-F3 after Claude's independent PR #62 acceptance. Continue
on a separate branch from PR #63 `1bd7bade8a6a9867d6f2e57695b988405e6dee97`.
The reviewed branches and Claude's knowledge/owners work remain fixed here.

## F1: nested conftest collection

Recognize the actual loaded pytest ConftestImportFailure wrapper and its
retained exception. Reuse the bounded failed-operation observer, with explicit
wrapper identity, underlying exception type and source point. Keep collection
node, stage, event, outer-source and current-environment checks at the policy
boundary. Both pass-tests and collect-tests scopes receive the same repair
eligibility. Text resembling an import failure, a user-defined wrapper or
missing/mismatched structured metadata cannot authorize a setuptools command.

Alternatives considered: parsing the wrapper's message would discard provenance;
unwrapping arbitrary cause chains would broaden eligibility beyond the reported
pytest mechanism. The selected approach adds the specific pytest wrapper and
preserves the existing direct-import/receiver contract.

## F2: blocked version route

When the pkg_resources repair conflicts with recorded setuptools requirements,
preserve those requirements and keep the command empty. Show their locations and
give a concrete manual route: identify the consumer of pkg_resources; migrate
metadata queries to importlib.metadata and package-resource access to
importlib.resources, or update the dependency that imports pkg_resources.
Do not assert one replacement works for every pkg_resources API. Do not advise
blindly weakening the declaration to install an incompatible provider. Other
packages' constraint guidance remains unchanged. No dependency-trial extension.

## F3: unavailable operation evidence

When a current failure mentions pkg_resources but its failing direct import or
receiver is not established, the review step names the evidence gap and gives a
recorded source location or collection node when available. Dynamic import and
exception rethrow are examples to inspect, not claims inferred from message
text. Keep no-command behavior and all current freshness/ownership constraints.
Stale, imported, ambiguous or mismatched metadata must not be presented as a
verified failed operation. No new model features, observation permission or
bulk knowledge changes.

## Verification and delivery

1. Freeze independent before/after cases, retain baseline failures and receipts.
2. Exercise real nested conftest in provider-absent, removed-provider and old
   provider environments, plus root conftest and module collection controls.
3. Check dynamic imports, explicit raises, wrong wrapper/source/node/stage,
   unrelated missing modules and constraint conflicts. Verify user-facing
   next-step text, command absence where required, and repair eligibility.
4. Run targeted tests, one full repository gate with available optional
   interpreters, Ruff, publication scan and unchanged shipped-model digest.
5. Commit, publish a separate draft PR, attach it and verify Linux CI. Record a
   concise Claude handoff. No merge, tag, language-model run, formal experiment
   or held-out data access.

User approval is the latest instruction to proceed with this already described
F1-F3 split. No additional approval gate is needed for these bounded fixes.
