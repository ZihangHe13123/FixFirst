# Knowledge verification

`src/fixfirst/knowledge/domain.toml` carries 710 execution-verified blocks that were added in October 2026 (129 recommended and 471
optional `[[removed]]` blocks, 8 `[[deprecated]]` and 2 `[[unmaintained]]` blocks), and 100 more `[[removed]]` blocks that name a library class or
an attribute and are applied only through `owners` (see "Owners" below). This directory holds the programs that checked them, their exact
inputs and machine-readable records of the last runs. The runs are **opt-in**: they need the network, `uv` and several CPython versions, and
take about 25 minutes each. Normal test runs do not execute them; they only check that the shipped knowledge base still matches the records.

## What is here

| Path | What it is |
|---|---|
| `verify.py` | Self-contained program (about 1.2 MB: the checks are literal `Check(...)` and `Support(...)` values between a small harness at the top and `main()` at the bottom). Search for a check id such as `st82-module-pkg_resources` to change one. |
| `verify_owners.py`, `owners/recipes.toml` | The second program, for the `owners` of the blocks that name a class (see "Owners"), and the receiver recipes it runs. |
| `candidates/candidates.toml`, `candidates-optional.toml` | The exact blocks that were verified and then merged into `domain.toml` (tier 1 = names users hit most often on current releases; tier 2 = the verified long tail). |
| `candidates/candidates-parked.toml` | 114 verified blocks (173 keys) that match a bare attribute name or a class name (a project's own `Engine` or `readfp` would be diagnosed as a version problem unless the object's class is checked). They were first parked; 100 blocks (138 keys) are now enabled with `owners`, 23 keys are merged into enabled entries and 7 blocks (12 keys) stay parked (`owners/dispositions.toml` says which and why). The parked ones are `src/fixfirst/knowledge/pending_attribution.toml`, which `fixfirst.domain.load()` does not read. |
| `owners/dispositions.toml` | What became of every one of those candidates: merged into an enabled entry (`covered_by`; the receivers of the merged keys are verified, see "Owners"), or still parked, with the reason. |
| `baseline/domain-c0bd25e.toml` | The knowledge base of the product immediately before the verified candidates were merged into it (`git show c0bd25e:src/fixfirst/knowledge/domain.toml`, byte for byte). It is the explicit base of the loader smoke test of `verify.py` (`--domain`), and the reference for every source and `[[unmaintained]]` entry that the candidates do not define (`tests/test_knowledge_verify.py`). |
| `receipts/knowledge-receipt-20261003.json` | Full record of the last run of `verify.py`: for every check and probe the snippet, its SHA-256, the environments (interpreter and package versions), the exact exception text or output, and the verdict. Local paths are redacted. |
| `receipts/owners-receipt-20261003.json` | Full record of the last run of `verify_owners.py`: for every key with owners (and for every merged key) the receiver recipe, the receiver identities in each release, and what FixFirst did with it (issues, rule, the plan with its replacement text, and the project class of the same name). |

The owners receipt was regenerated on 2026-10-09 against the saved-test-selection candidate based on `5c224cf`, and again after its D16/P13 candidate filtering. All 155 keys and 23 merged keys passed; the stored-record audit found zero problems. The domain entries and 81-feature tree weights are unchanged; only D16/P13's rule conditions changed. Its existing filename is retained. The knowledge-matrix receipt was unchanged and was not rerun.

## What a check proves

A **check** runs one snippet in an isolated environment before the stated release (it must work), in the first release without it (it must raise the
expected exception with the expected text) and in later releases (it must still raise). The harness also confirms from PyPI that the two pinned releases
are neighbours, and that FixFirst derives the entry's key from the observed message. Every key of every block is covered by a passing check (1,239 checks).

A **probe** (299, "support") backs a claim made in a replacement text, on finite inputs: for example that `pd.Series(values).infer_objects().to_numpy()` restores the dtype
`DataFrame.lookup` returned. 373 of the 714 `[[removed]]` blocks have at least one key backed by a probe. **A passing probe is not a proof that the replacement text is right for every input**,
and a block without a probe has had its wording reviewed by hand only. Two replacement texts were found wrong by a probe and dropped (SciPy `get_window` is not `windows.hann`;
scikit-learn `get_feature_names` differs from `get_feature_names_out` for DataFrame input), and the October review found four more (`resource_exists`, `ImpImporter`,
`DataFrame.lookup`, `DataFrame.first/last`) that the first probes had not covered; each now has probes for the reviewer's counterexamples.

A probe whose interpreter is not installed is reported as **NOT CHECKED** and makes the run incomplete (a non-zero exit); it is never counted as a pass.

## Owners

A `[[removed]]` block that names a class (`module = "Engine"`) or a bare attribute (`names = ["readfp"]`) is applied only through `owners`: the
library classes whose attribute was removed. FixFirst (`src/fixfirst/removal_ownership.py`) applies the block when the failed receiver's class, or one
of its bases, is one of them and the module comes from the block's distribution, so a project's own class with the same name is not diagnosed as a version
problem. `owners` is a claim about real classes, and `verify_owners.py` checks it by running real code:

1. `owners/recipes.toml` builds a real object of the class (`obj`) for each key, in the releases of the check that proved the removal: in the last
   release that has the attribute (the lookup must work), in the first release without it and in later releases (it must raise `AttributeError`).
2. In each release the **product's own** `receiver_owners()` (`fixfirst/_runtime_evidence.py`) names the receiver's class identities. A declared owner must
   be one of them in every release where the attribute is gone, from the block's distribution (a dynamic receiver counts only through its own class, as in the
   product), and every declared owner must be a real identity of a receiver in some release.
3. FixFirst itself then diagnoses a script that ends in `obj.<name>` (in the newest release): exactly this entry must be authorized (a second matching entry would
   show the same step twice), the issue must be a version incompatibility decided by the entry's own rule (D02 for `api`, D03 for `attribute`), and the first step of the
   plan must be the removal action ("Replace ...") with the replacement text of the entry. A project class with the same name that calls the same attribute must really fail in its
   own run (a missing record is not a negative) and must not be authorized, diagnosed as a version problem or shown that replacement.
4. The candidates that were **merged** into an enabled entry (`owners/dispositions.toml`, `[[merged]]`) are not enabled, because the entry that covers them
   already matches their receivers through inheritance (a `DiGraph` is a `Graph`; two entries for one receiver would show the same step twice). Each merged key is
   verified with the receiver of its own class (the recipe of the merged key, in the releases of its check): the covering entry, a unique entry of `covered_by` that
   ends in the same attribute, must have the same distribution, removal version and source (and the same replacement, or a `replacement_note` that says why not);
   every release without the attribute must authorize the receiver through that entry and through no other entry of the knowledge base, and FixFirst must
   authorize exactly that entry and show its replacement. Merged keys are listed once; a key that is enabled, merged and parked at the same time, or listed twice, is an error.

Every key of a block with `owners` in the shipped knowledge base and every merged key must pass. The record is a detailed one, not a verdict: `audit_receipt()` in
`verify_owners.py` judges it again from the stored releases, product runs and recipes with the same functions that judged the run (the run ends with that audit), and
`tests/test_knowledge_owners.py` calls it offline, so a record whose details were emptied, edited, duplicated, pasted from another key or no longer agree with its verdict
is rejected. **What it judges**: the keys, the block hashes (by what the block parses to) and the recipe; the releases (exactly the ones the recipe and the verifying checks call
for, each in its environment, on the interpreter and with the pinned packages of that environment); for every release in which the attribute is gone the identities of the
receiver (a declared owner authorizes it, from the block's distribution wherever the interpreter can tell, which is Python 3.10 and newer; exactly one entry of the whole
knowledge base authorizes it; the receiver of a merged key is an object of the merged class); the runs of FixFirst (the authorization, the rule that decided, the first step
with the removal version and all of the replacement text, the project class of the same name, and that each record is the one of its own job). **What it takes as stored**:
what only a new run can show again, that is the raw measurements themselves (the rows of identities, the messages, the installed versions of unpinned packages); and the
informational fields. The record is tied to the blocks, to the recipes (by what they parse to) and to the tool (by its bytes), and in two layers to the product:
`identity_functions_sha256` (the source of the functions that decide a receiver's identity in `_runtime_evidence.py`: owners are claims about those identities), and the
product that the E2E runs executed: `e2e_files_sha256` (every module of the product that the runs loaded, found by the runs themselves, and the scripts that run in the target
interpreter), `e2e_data_sha256` (the knowledge data files besides `domain.toml`) and `e2e_rules_sha256` (every rule). A Python file is bound as the interpreter reads it:
its source encoding (a coding line or a byte order mark) and the text of its strings count, the blank lines and trailing spaces inside a multi-line string and a docstring too;
comments, blank lines between statements, trailing spaces and line endings do not (nor does the position of a line: nothing a diagnosis says is taken from the line numbers of
the product's own source). A data file is bound by what it parses to.
`tests/test_knowledge_owners.py` also runs FixFirst once, with the same runner, and requires that every module it loads is in the record, so a new import in the removal chain
or a cut-down list fails. A change to any of them needs a new run. `package_sha256`, the digest of the whole package, is recorded for information and is not compared.
The tests do not skip when a record is missing: a missing or a second receipt fails them.

**What the record does not bind**: the blocks that the product already had before the candidates (the older blocks of `domain.toml`, among them the four with `owners` that no
candidate carries) are bound by their hash in the record only, so an edit of one of them with a refreshed hash is caught only where the E2E run shows it (the replacement text,
the removal version); the audit of the older entries in the knowledge record was made on the baseline, and later edits of those entries are reviewed by hand; the parts of
`domain.toml` that the E2E runs read besides the blocks with owners (other removal blocks, tool failures, sources) are not bound by this record; and nothing here proves a flow
that the 155 scripts do not exercise.

What an enabled block does **not** mean: the product observes the receiver of a failing attribute load that is a name or an attribute of a name
(`engine.table_names()`, `self.engine.table_names()`), and these entries diagnose those shapes; a block is enabled only if FixFirst authorizes it for the
simplest one, `obj.<name>`. Not observed, so that only the release heuristic answers: a call result (`make_engine().table_names()`), a decorator line
(`@app.before_first_request`) and a lookup that fails inside a library. The product records the identities of a receiver only within bounds (at most 64 base
classes, 128 identities and 32768 bytes of them; a receiver beyond them proves nothing). The 7 blocks (12 keys) that stay parked could not be authorized even for
`obj.<name>`: `ArtistList` is a nested class, Django's `settings` is a `LazySettings` proxy that fails inside Django, and the error of `array.array` is not read.

## Running it

```bash
# interpreters: uv python install 3.8 3.9 3.10 3.11 3.12 3.13 3.14 3.15   (the checks span them)
python scripts/knowledge_verify/verify.py \
    --candidates scripts/knowledge_verify/candidates/candidates.toml \
                 scripts/knowledge_verify/candidates/candidates-optional.toml \
                 scripts/knowledge_verify/candidates/candidates-parked.toml \
    --domain scripts/knowledge_verify/baseline/domain-c0bd25e.toml --fixfirst-src src --receipts /tmp/receipt.json
```

`--domain` is the explicit baseline: the collision checks and the audit read it, and the loader smoke test (the last step: the real loader and rule engine on the
baseline plus every candidate, in a copy) builds its knowledge base from it. The product's own `domain.toml` already holds most candidates, so appending them to
a copy of it would define every source twice; without `--domain` the smoke test accepts only a knowledge base that holds all candidates or none and says so
otherwise. The receipt records the mode (`smoke.mode`) and the digest of the baseline (`domain_toml_sha256`).

```bash
python scripts/knowledge_verify/verify_owners.py --fixfirst-src src --receipts /tmp/owners-receipt.json   # the owners of the shipped blocks
```

Python 3.11 or newer runs the programs. They need about 10 GB of temporary space. It re-checks the unmaintained entries against the newest PyPI releases,
so a new release can make a run fail legitimately. `--only TEXT` runs the checks whose id contains `TEXT`.

## Limits

- Everything was run on macOS arm64. Windows and Linux were not checked; some old wheels do not exist for arm64 (pandas before 1.3.4, scikit-learn before 1.0.2, matplotlib before 3.5.0), so
  removals from before those releases are not covered. Four standard-library modules (`msilib`, `nis`, `ossaudiodev`, `spwd`) cannot be built on this platform.
- The audit part re-checks the 111 older entries of `domain.toml`: 106 are confirmed, four modules are unverifiable here and one claim is contradicted
  (`flask_sqlalchemy.Model` still exists in 3.0; it was removed in 3.1). These are reported, not changed.
- The receipts are bound to the shipped knowledge base by `tests/test_knowledge_verify.py` and `tests/test_knowledge_owners.py`: they fail when a verified block, a source
  or an unmaintained entry that a candidate file or the baseline defines is edited without re-running the verification. The knowledge record is judged again from its
  details as well (`audit_knowledge_record` in the test file): every check and probe against the one of `verify.py` (snippet, environment, expectation, what it covers), the
  exceptions each release raised against the expectation (type, the text a check matches, the keys that FixFirst derives from the message, the warnings of a deprecation), the
  interpreter and the packages that each role really ran with against its environment (the Python release; every package at a version that its requirement allows; a probe
  records its interpreter only), and the summary. A record whose judged details were emptied, edited or removed fails. **Taken as stored**: the raw output that no verdict
  follows from (messages that no check matches or derives a key from, the warnings of the checks of removals, the output of the probes), the versions of the packages
  that are not pinned beyond what their requirement allows, and the lookup of PyPI for the adjacency of two pinned releases (not repeated).
  Edits of the older entries of `domain.toml` (the baseline) are not bound.
