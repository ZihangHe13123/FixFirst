# Knowledge verification

`src/fixfirst/knowledge/domain.toml` carries 610 execution-verified blocks that were added in October 2026 (129 recommended and 471
optional `[[removed]]` blocks, 8 `[[deprecated]]` and 2 `[[unmaintained]]` blocks). This directory holds the program that checked them,
its exact inputs and a machine-readable record of the last run. The run is **opt-in**: it needs the network, `uv` and several CPython versions, and
it takes about 25 minutes. Normal test runs do not execute it; they only check that the shipped knowledge base still matches the record.

## What is here

| Path | What it is |
|---|---|
| `verify.py` | Self-contained program (about 1.2 MB: the checks are literal `Check(...)` and `Support(...)` values between a small harness at the top and `main()` at the bottom). Search for a check id such as `st82-module-pkg_resources` to change one. |
| `candidates/candidates.toml`, `candidates-optional.toml` | The exact blocks that were verified and then merged into `domain.toml` (tier 1 = names users hit most often on current releases; tier 2 = the verified long tail). |
| `candidates/candidates-parked.toml` | 114 verified blocks that are **not enabled**: they match a bare attribute name or a class name, which FixFirst cannot yet bind to the object's real module (a project's own `Engine` or `readfp` would be diagnosed as a version problem). The shipped copy is `src/fixfirst/knowledge/pending_attribution.toml`, which `fixfirst.domain.load()` does not read. |
| `receipts/knowledge-receipt-20261003.json` | Full record of the last run: for every check and probe the snippet, its SHA-256, the environments (interpreter and package versions), the exact exception text or output, and the verdict. Local paths are redacted. |

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

Python 3.11 or newer runs the program. It needs about 10 GB of temporary space. It re-checks the unmaintained entries against the newest PyPI releases,
so a new release can make a run fail legitimately. `--only TEXT` runs the checks whose id contains `TEXT`.

## Limits

- Everything was run on macOS arm64. Windows and Linux were not checked; some old wheels do not exist for arm64 (pandas before 1.3.4, scikit-learn before 1.0.2, matplotlib before 3.5.0), so
  removals from before those releases are not covered. Four standard-library modules (`msilib`, `nis`, `ossaudiodev`, `spwd`) cannot be built on this platform.
- The audit part re-checks the 111 older entries of `domain.toml`: 106 are confirmed, four modules are unverifiable here and one claim is contradicted
  (`flask_sqlalchemy.Model` still exists in 3.0; it was removed in 3.1). These are reported, not changed.
- The receipts are bound to the shipped knowledge base by `tests/test_knowledge_verify.py`: it fails when a verified block is edited without re-running the verification.
