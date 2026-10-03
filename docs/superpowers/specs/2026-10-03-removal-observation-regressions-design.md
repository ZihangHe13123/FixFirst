# Preserve removal diagnoses with executable ownership evidence

## Scope and approved direction

Implement the two development regressions discovered against candidate
`090aa105c2b1d9e1c0dc24b6040adcd7306954ea`. The user has authorized continuing
this optimization, and the assigned implementation scope explicitly permits an
actual loaded library getter, its input name, and import bytecode as evidence.
This specification records that existing authorization; it does not introduce
a separate approval gate.

Do not change dependency advice, package compatibility, knowledge entries,
receiver-owner enumeration limits, model bytes, or feature layouts. No model
training, language-model requests, private evaluation, push, or merge.

## Observed regressions

1. Real `from sklearn.datasets import load_boston` and
   `from pydantic import BaseSettings` fail inside the installed libraries.
   The importer executes `IMPORT_NAME` and the loaded module's registered
   `__getattr__` receives the actual requested name. The current extractor
   recognizes an API from the executed statement, but removal ownership only
   accepts conventional error text or instance/class observations. D02 and the
   named migration action disappear; the fixed tree hides the label regression.
2. Five historical public unittest-alias cases have no receiver-owner record.
   D03 correctly refuses to infer inherited ownership from a name alone, but
   D43 then calls the locally defined subclass a code defect. The classifier
   can repeat that unsupported label. Fresh observations already prove the real
   unittest base and remain correct.

## Alternatives

- Broaden message matching: small, but copied or hand-raised messages could
  borrow a library identity. Rejected.
- Re-evaluate a getter or import during diagnosis: might establish a current
  object, but executes user behavior and does not prove the original failure.
  Rejected.
- Record the actually executing import/getter relationship and reuse the
  existing ownership contract. Selected: no extra user-code execution, no
  package-specific branches, and replayable provenance.

## Runtime import observation

Extend the existing symbol record only for an ImportError or its real subclass
when all of the following are observed in the traceback:

- A bounded, absolute `IMPORT_NAME` with a literal level zero and a bounded
  tuple of imported identifiers; no relative import, star, jump ambiguity, or
  dynamic CALL reconstruction.
- The importing frame uses the actual builtin import function. Its immediately
  following traceback frame is the registered module `__getattr__` function.
- The module is an exact already-loaded ModuleType under the imported name.
  The getter is an exact Python function in that module namespace; its code
  object is the executing frame, its globals are that namespace, and its file
  matches the loaded module origin. Its single actual parameter is one of the
  requested import names, not a name guessed from the message.
- The requested member is absent from the module dictionary. Introspection
  reads dictionaries/code/frames only; it does not call dir, getters, imports,
  properties, repr, or arbitrary descriptors.

The symbol record retains importer file/line, IMPORT_NAME, module, requested
member, and bounded getter/module provenance. It remains a dynamic namespace
for spelling advice. Record validation rejects partial/malformed proof.

## Diagnosis ownership

The existing operation-context join verifies one executed exception, its same
run/issue failure statement, and the matching absolute ImportFrom statement.
Only the removal consumer may recheck this proven dynamic module record. It
also requires the existing current environment/project snapshots, unique
installed provider, actual origin under that interpreter's library directory,
no local shadow, and no own-distribution claim. The exact recorded module/name
must match an existing removed API entry without instance-owner overrides.
D02 supplies the existing named migration action; no new knowledge is added.

The real pytest CollectError wrapper may carry the underlying custom
ImportError observation using the existing exact-wrapper provenance. An
arbitrary hand-raised lookalike is not a substitute for import bytecode and a
registered getter frame.

## Incomplete legacy ownership

For AttributeError on a locally named class and an existing removed-attribute
entry, absence of a usable executed receiver-owner record is a distinct
observed limitation. It does not prove the known library owner and does not
prove that the attribute belongs exclusively to project code.

Expose an ownership-unobserved fact/detail, prevent D43 from converting that
case to a definite code defect, suppress promotion of a classifier guess for
that issue, and propose re-running the failed check to capture ownership.
Do not manufacture an owner or rewrite old records. Actual fresh namesake
objects with observed local ownership continue through ordinary diagnosis.
Fresh real unittest inheritance continues to use D03.

## Counterexamples and validation

- Hand-raised ImportError/PydanticImportError text, including explicit public
  exception attributes and a real error rethrown by unrelated project code.
- Project shadow packages, same-named project objects, a replaced module hook,
  direct getter calls, dynamic `__import__`/importlib calls, and changed builtin
  import hooks.
- Stale/wrong environment, imported or incomplete runs, wrong statement,
  malformed getter proof, conflicting provider, local shadows, and grouped
  issues borrowing another operation.
- Getter/property counters show no extra invocation by observation.
- Real installed load_boston and BaseSettings restore D02 plus the captured
  named first action, with the same fixed model.
- All five original public legacy unittest snapshots become unconfirmed and
  request a new observation; they must not become a fabricated D03 success.
- Fresh inherited unittest positives and fresh local namesakes retain their
  expected distinctions.

Use the prior 21-package Python 3.12.13 target environment for a narrow paired
baseline/fixed run. Retain the independent 215/30 evidence untouched. Run only
the relevant ownership, runtime-symbol, operation-context, and new regression
tests; no 735-case re-execution or full pytest suite.

## Review checklist

- Context inspected: completed; both regressions reproduced from saved raw
  sessions and actual import traceback frames.
- Visual companion: unnecessary for these evidence contracts.
- Clarifications: scope, fixed source, exclusions, and success criteria are
  explicit in the assigned authorized task.
- Alternatives and selected design: recorded above.
- Design self-review: no placeholders; legacy unknown is distinct from fresh
  correctness, source identity is required, and unrelated modules are excluded.
- Implementation and targeted validation: follow this committed specification.
