# Knowledge verification

`src/fixfirst/knowledge/domain.toml` carries 610 execution-verified blocks that were added in October 2026 (129 recommended and 471
optional `[[removed]]` blocks, 8 `[[deprecated]]` and 2 `[[unmaintained]]` blocks), and 90 more `[[removed]]` blocks that name a library class or
an attribute and are applied only through `owners` (see "Owners" below). This directory holds the programs that checked them, their exact
inputs and machine-readable records of the last runs. The runs are **opt-in**: they need the network, `uv` and several CPython versions, and
take about 25 minutes each. Normal test runs do not execute them; they only check that the shipped knowledge base still matches the records.

## What is here

| Path | What it is |
|---|---|
| `verify.py` | Self-contained program (about 1.2 MB: the checks are literal `Check(...)` and `Support(...)` values between a small harness at the top and `main()` at the bottom). Search for a check id such as `st82-module-pkg_resources` to change one. |
| `verify_owners.py`, `owners/recipes.toml` | The second program, for the `owners` of the blocks that name a class (see "Owners"), and the receiver recipes it runs. |
| `candidates/candidates.toml`, `candidates-optional.toml` | The exact blocks that were verified and then merged into `domain.toml` (tier 1 = names users hit most often on current releases; tier 2 = the verified long tail). |
| `candidates/candidates-parked.toml` | 114 verified blocks that match a bare attribute name or a class name (a project's own `Engine` or `readfp` would be diagnosed as a version problem unless the object's class is checked). They were first parked; 90 are now enabled with `owners` (122 keys), 7 are merged into enabled blocks and 17 stay parked (`owners/dispositions.toml` says which and why). The parked ones are `src/fixfirst/knowledge/pending_attribution.toml`, which `fixfirst.domain.load()` does not read. |
| `owners/dispositions.toml` | What became of every one of those candidates: merged into an enabled entry, or still parked, with the reason. |
| `receipts/knowledge-receipt-20261003.json` | Full record of the last run of `verify.py`: for every check and probe the snippet, its SHA-256, the environments (interpreter and package versions), the exact exception text or output, and the verdict. Local paths are redacted. |
| `receipts/owners-receipt-20261003.json` | Full record of the last run of `verify_owners.py`: for every key with owners the receiver recipe, the receiver identities in each release, and what FixFirst did with it. |

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
   show the same step twice) and the issue must be a version incompatibility. A project class with the same name that calls the same attribute must not be
   authorized.

Every key of a block with `owners` in the shipped knowledge base must pass; `tests/test_knowledge_owners.py` ties the record to the blocks, to the recipes,
to the tool and to the source of the product functions that decide a receiver's identity (a change there needs a new run).

What an enabled block does **not** mean: the product observes the receiver of a failing attribute load that is a name or an attribute of a name
(`engine.table_names()`, `self.engine.table_names()`), and these entries diagnose those shapes; a block is enabled only if FixFirst authorizes it for the
simplest one, `obj.<name>`. Not observed, so that only the release heuristic answers: a call result (`make_engine().table_names()`), a decorator line
(`@app.before_first_request`) and a lookup that fails inside a library. The 17 blocks that stay parked could not be authorized even for `obj.<name>`:
`ArtistList` is a nested class, the SQLAlchemy expression classes exceed the probe's bounds (more than 16 base classes, 32 alias rows), Django's `settings` is a
`LazySettings` proxy that fails inside Django, and the error of `array.array` is not read.

## Running it

```bash
# interpreters: uv python install 3.8 3.9 3.10 3.11 3.12 3.13 3.14 3.15   (the checks span them)
git show 769028d:src/fixfirst/knowledge/domain.toml > /tmp/domain-before.toml     # the knowledge base before these entries
python scripts/knowledge_verify/verify.py \
    --candidates scripts/knowledge_verify/candidates/candidates.toml \
                 scripts/knowledge_verify/candidates/candidates-optional.toml \
                 scripts/knowledge_verify/candidates/candidates-parked.toml \
    --domain /tmp/domain-before.toml --fixfirst-src src --receipts /tmp/receipt.json
```

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
- The receipts are bound to the shipped knowledge base by `tests/test_knowledge_verify.py`: it fails when a verified block is edited without re-running the verification.
