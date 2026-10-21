# v0.8 test-tool compatibility: development acceptance

Four recorded repair commands were executed in newly rebuilt toy environments.
Each installation completed, `pip check` passed, and the original test command
passed with its tests and warning filters unchanged. The structured results are
in [results.json](results.json).

## Source and scope

| Item | Recorded identity |
|---|---|
| Frozen baseline C | `3e72647952c49c6f1b780cc2cd2402990a8ab5de` |
| Candidate production source | `77f23b2e01ab68b01fcf403a4233737c042a6834` |
| Knowledge change | `a99d448` |
| Target interpreter | Python 3.12.13 on macOS |
| Classifier artifact SHA-256 | `4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3` |

Candidate source hashes captured during execution match the fixed production
commit. The classifier artifact stayed unchanged. These are preregistered toy
development cases; this report provides no new generalization estimate. No A2
rerun or language-model request was made. Windows was not exercised on a real
host.

## Separate environment preparation tracks

The frozen builder initially created environments without pip. Its SHA-256 was
`372e6d55f2380b34e5fcedb8004071eed8abcbae2d99489ddca09dcd99d0a9fe`.
Ten environments and twenty baseline records from that track were preserved.

A later, separate **seeded supplemental amendment** added `uv venv --seed`
and an explanatory comment. Its builder SHA-256 was
`966201c9f7b60801a29f81c4cb4230f591e35056b3963e5f3d0b848b4bcb8118`.
The amendment rebuilt ten environments with the same Python version, every
original package version, case files and expectations. The sole package
addition was `pip==26.2.1`; it enabled execution of the proposed pip commands.
This provisioning is recorded as environment preparation. It is not counted as
a FixFirst repair.

Frozen C and the candidate each recorded both modes on the supplemental
starting environments:

- `default_scan`: the actual default FixFirst scan, including its pytest probe.
- `registered_argv`: the exact preregistered pytest arguments, recorded with
  environment/project evidence and without adding the probe. A successful
  text-only result cannot establish FixFirst's verified completion state.

All twenty original and supplemental starting environments still matched their
saved package versions and case-file hashes after verification. Repair commands
were executed only in four further rebuilt copies. Only interpreter and log
paths were relocated; command flags and package requirements were preserved.

## Observations

| Case and evaluated mode | Frozen C | Candidate | Executed repair result |
|---|---|---|---|
| T1: vendored `py` metadata; default scan | F01 `code_defect` | D49 `version_incompatibility` | `py==1.11.0,>=1.8.2`; installation and dependency check passed; original test: 1 passed, 12 warnings |
| T2: `ast.Str`, INI warning filter; default scan | F01 `config_missing` | D50 `version_incompatibility` | `pytest==7.3.2`; installation and dependency check passed; original test: 1 passed |
| T3: `ast.Str`, CLI warning filter; registered arguments | Unknown | D50 `version_incompatibility` | `pytest==7.3.2`; installation and dependency check passed; original test with `-W error::DeprecationWarning`: 1 passed |
| T4: initial conftest rewrite; default scan | Unknown | D50 `version_incompatibility` with new probe evidence | `pytest==7.3.2`; installation and dependency check passed; original test: 1 passed |
| N1: old tool emits ordinary warnings; default scan | Goal achieved | Goal achieved | No repair |
| N2: project-owned promoted warning; both modes | Unknown / F01 `code_defect` | `code_defect`; no tool compatibility diagnosis | No repair |
| N3: missing plugin option; registered arguments | Generic usage error | Generic usage error; no tool compatibility diagnosis | Named plugin remedy remains unverified |
| N4: missing conftest dependency; both modes | D21 `missing_dependency` | D21 `missing_dependency` | No repair |
| N5: local `pluggy` shadow; both modes | D10 `local_module` | D10 `local_module` | No repair |
| C1: constrained legacy stack; both modes | F01 `code_defect` | D49, then declaration-conflict review; no installation command | Review only |

## Boundaries that affect interpretation

- **T3 and N3 have different command modes.** Default scanning omits T3's
  external CLI warning filter and clears N3's configured `addopts`; those
  default scans pass. Their registered-command failures remain separately
  recorded and are not replaced by the default results.
- **T4 needs the new probe evidence.** Historical output from the registered
  command without a probe lacks the necessary tool frames and remains unknown.
  The successful D50 attribution above comes from a fresh default scan that
  captures the original initial-conftest traceback.
- **C1 was not repaired.** The first step names the conflict between
  `py==1.10.0` and proposed `py==1.11.0`, with no direct installation command.
  The retained declaration also contains `pytest>=6,<7`. The first-step text
  says other constraints remain in force but does not literally repeat this
  pytest upper bound. No declaration edit or dependency-resolution trial was
  performed, and C1 contributes no repair success.
- **N3 remains generic.** Avoiding an incorrect compatibility diagnosis does
  not demonstrate a complete, named missing-plugin remedy.

These observations support four specific executed toy repairs and the listed
counterexample behavior. They do not establish complete acceptance of every
registered expectation or behavior on other projects and operating systems.

## Implementation regression checks

The implementation task reported the following checks for the fixed production
source, separately from the independent toy runs above:

- Full suite: 1,239 passed, 1 skipped.
- Targeted suite: 141 passed.
- Ruff: passed.

This directory contains only sanitized summaries and command placeholders.
Raw logs, local paths, account names and original record identifiers are not
published here.
