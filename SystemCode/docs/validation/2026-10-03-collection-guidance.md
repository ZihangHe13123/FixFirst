# Nested conftest and blocked repair guidance

Baseline: `1bd7bade8a6a9867d6f2e57695b988405e6dee97` (PR #63).
Integrated F1-F3 candidate: `dcf32c84fcc84f862cf15b6c1bccb6f0542795e4`.
Final source: `75b43045b80f9cfa59bdcdc23469db056dc31a5a`.
The final source adds a small F3 location correction and two regression tests.

## Changes

- **F1:** recognize the actual loaded pytest `ConftestImportFailure` and its
  retained original failure. The raising code must be pytest's loaded
  `_importconftest` method; retained cause and `__cause__` must agree. Existing
  failed-operation, source, node, stage, provider and environment checks remain.
  Hand-raised wrappers and matching message text do not authorize a repair.
- **F2:** when the bounded setuptools request conflicts with recorded
  requirements, retain those requirements, give no install/trial command and
  direct the user to migrate the code or dependency that imports pkg_resources.
  Metadata queries and resource access are distinguished; no blanket replacement
  equivalence or completed migration is claimed. Other package guidance is
  unchanged.
- **F3:** explain which operation evidence is missing, name recorded context and
  frame dynamic imports/rethrows as possibilities to inspect. During collection,
  use the recorded node rather than directing edits to pytest's wrapper file.
  Dynamic imports remain outside the supported direct-import repair policy.

## Local gates

CPython 3.12.13 on macOS. The three supplied target environments used pytest
9.1.1, with setuptools absent, 84.0.0 and 65.7.0 respectively.

| Source / gate | Result |
| --- | --- |
| F1 author: nested conftest and previous package regressions | 108 passed |
| F2/F3 initial targeted slice | 64 passed |
| Integrated `dcf32c8` full pytest | 1582 passed, 12 skipped |
| Final `75b4304` combined package/collection/guidance slice | 138 passed |
| Final Ruff and diff checks | Passed |

The full local gate preceded the small F3 location correction. Its final source
was checked by the focused slice above; exact-head Linux CI is recorded on the
PR. The 12 local skips were ten optional isolated Django cases, the opt-in
toolchain environment builder and native Windows PowerShell quoting.

No model file changed. Shipped model SHA-256:
`4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3`.

## Independent acceptance

Eleven cases and their contract were frozen before the independent baseline and
candidate runs. They cover nested/root conftest and module imports, absent/removed/old
providers, PyYAML, two declaration conflicts and three dynamic/rethrown failures.
Real diagnostic runs, next-step views and rendered workspace HTML were saved.
The learned classifier was disabled consistently in this bounded mechanism
comparison; these are not default-model accuracy or generalization estimates.

The unchanged machine checks recorded **7 pass / 4 fail** on the baseline and
**11 pass / 0 fail** on `dcf32c8`. The four improvements are two nested conftest
repair cases and two conflicts gaining migration directions. F2/F3 semantic
wording was separately reviewed against five predeclared criteria.

For the nested missing-provider case, the verifier copied the absent-provider
environment, reproduced failure there, executed the product-generated bounded
command, then ran `pip check` and the same pytest scope. Pip installed setuptools
81.0.0; dependency check and the original test passed and the goal became
achieved. Source, tests and configuration were unchanged; inventories of the
three shared target environments were also unchanged.

The first candidate met the frozen F3 criterion because the UI already showed
the relevant project position. Nevertheless, two bodies directed inspection to
pytest's outer wrapper file. This limitation is preserved in that receipt. The
final correction prefers a labelled collection node, including when pytest is
inside a project-local virtual environment. Only the original three F3 cases
were rerun on final source: **3/3 passed**, with separate **3/3** semantic wording
checks. The first candidate's records and criteria were not rewritten; F1/F2
were unchanged and their earlier execution receipts remain the evidence for
those parts. No second installation or full 11-case rerun is claimed.

Receipt identities (SHA-256):

| Artifact | Digest |
| --- | --- |
| Case list | `bff92728248ace3fd52af489471fa21742dbe42de06468ddb745987e11884706` |
| Original acceptance script | `ce56dd3be78a0a1ef5fde6aaf6c5fc71b9812f4503887b98be03064ac3b0deb2` |
| Frozen protocol | `d658ee16c9c9cd55b07c7954fc73e27619a5dfdcd9bcfc4fbd42685dee7b6a7d` |
| Baseline execution receipt | `bc370bc6be9bb006f7039fbe2296550da654962517a136da69ff84cfe256147c` |
| Integrated execution receipt | `28dbf2c3b08e667beb684b0618394984d53725200b9b5c07c56d0b3a4dca1946` |
| Final three-case F3 execution receipt | `3a99c28c7fdb28e257e240e36d60f2be50717e3bd4946e8979a1f1cadc5185f7` |

## Limits

No language model, formal B3/B7 experiment, held-out data or bulk knowledge
activation was involved. Real Windows execution, pytest-xdist, other pytest
versions and broad consumer migrations are not established by these checks.
The existing CPython 3.12 package policy is unchanged. E3 dependency trials and
E4 C-type attribution remain separate work.
