# Package project 404: bounded validation

Source candidate: `2e18dfa3c5cd18e1ce1066990b2f89c0c55a878b`.
Baseline: `bab0ad66fd52b4b347f7b2dca87db536d3e34457` (PR #62).
This follow-up changes installation failure classification and advice. It does
not change the model or the independently reviewed PR #62 branch.

## Behavior and limits

- A pip-reported HTTP(S) `/simple/<project>/` 404, matched to the failed
  requirement using normalized names, produces `index_project_missing`.
  Advice asks the user to check the package spelling and intended index.
- It describes the recorded endpoint response. It does not claim that the
  project or version is absent from every index, or that private access works.
- Genuine access failures keep priority, including mixed-index logs. A matching
  source archive retains the existing no-wheel guidance. Requires-Python
  priority is unchanged. Another project's 404 supplies no target evidence.
- Root-index and artifact 404s retain access guidance. Arbitrary custom index
  base layouts are outside the deliberately limited `/simple/` recognition.
- No new network lookup, installation, version relaxation or source-build
  policy is introduced. Both manual installation feedback and dependency trials
  receive the specific classification without an unjustified repair command.

## Execution evidence

All execution below used macOS and CPython 3.12.13. No language model, formal
experiment or held-out data was used.

| Gate | Result |
| --- | --- |
| Targeted parser, feedback and dependency tests | 84 passed |
| Full repository pytest, with three optional pkg_resources interpreters | 1535 passed, 12 skipped |
| Ruff over src, tests, scripts and experiments | Passed |
| Diff whitespace check | Passed |
| Author's real pip 26.2.1 against a localhost server | 404: project missing; 403/503: access failure |

The 12 skips are ten optional isolated Django runtime cases, the opt-in
toolchain builder and the native Windows PowerShell case. The author pip probes
used dry-run and performed no installation. Linux CI is a separate gate; these
numbers are local results.

The shipped model remains byte-identical, SHA-256:
`4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3`.

## Independent before/after acceptance

Eleven fixed cases exercised a missing-dependency program, the product's bound
pip log, scan, the next-step view and rendered workspace HTML. Two cases ran real
pip against localhost (project 404 and 403); nine used explicitly synthetic
logs. The checks covered canonical name aliases, unrelated project 404s,
artifact/root 404s, 401/500, mixed access failures and matching source evidence.
No successful installation or browser interaction is claimed.

The valid original checker recorded baseline **7 pass / 4 fail** and candidate
**8 pass / 3 fail**. The three candidate failures were assertion mistakes: two
required the old `no_distribution` classification despite the intended new
specific category; one banned the string `404` anywhere and matched the fixture
name itself. A separate checker inspected the same saved JSON and HTML against
the semantic contract, yielding baseline **7/4**, candidate **11/0**. It made no
new requests and did not rerun the product. The original results are retained;
this is not a claim that the frozen checker passed 11/11.

An earlier checker version stopped all cases before pip/log feedback because it
required a literal hyphenated requirement spelling. That precondition was
corrected to normalized Requirement comparison. Those records are retained and
are not a product baseline.

Receipt identities (SHA-256):

| Artifact | Digest |
| --- | --- |
| Fixed case list | `46c458022c0c41f1e2f1ff1c2b924f323e43092df1acb319d14f326d78925e6e` |
| Valid original acceptance script | `b36fa4133d06decfa3aed3c9d5a9fbfe21b78ece4a470c81af9a239d9d48d3f9` |
| Baseline results | `d21bbfde9efaf9ab7b9e23df89f8e204d899d2f156ada4bbf95a11df435f5f30` |
| Candidate results | `b1fe1dcd43c59e2b5b8b22228fe0d5154475427183a75df735ba4c4f601e701c` |
| Separate semantic receipt checker | `d8c50dd943dccb9b0d4fd175a53bf55ae344dfa2f2423e03f5942dfdc98442ac` |

These bounded development checks establish the reported mechanism and nearby
controls. They are not a generalization estimate or a rerun of the formal
baseline evaluation.
