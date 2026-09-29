# DEMO: fictional data

> These numbers come from the made-up tables in `docs/user-study/fixtures/` and only check the analysis script. They are **not** results of the user study.

## Inputs and configuration

- Script: analysis.py 1.0 (SHA-256 453717ce63bd); protocol version 1.2
- Tasks per condition: 2; time limit: 720 s; rows whose participant starts with PILOT or P00 are not analysed

| Input | Rows | SHA-256 |
|---|---|---|
| docs/user-study/fixtures/demo_sessions.csv | 26 | `a18939dca0674d43` |
| docs/user-study/fixtures/demo_questionnaire.csv | 6 | `aeb82948d5b4c696` |
| docs/user-study/fixtures/demo_cause_scores.csv | 22 | `b76c58655a33fdef` |

## Records

Participants analysed: 6 (P01, P02, P03, P04, P05, P06). Usable task records: 22.

Left out:

| File | Line | Participant | Task | Reason |
|---|---|---|---|---|
| demo_sessions.csv | 2 | P00-EXAMPLE | T1 | pilot or example row (not analysed) |
| demo_sessions.csv | 3 | PILOT1 | T1 | pilot or example row (not analysed) |
| demo_sessions.csv | 4 | PILOT1 | T3 | pilot or example row (not analysed) |
| demo_sessions.csv | 27 | P06 | T1 | withdrawn from the study |
| demo_questionnaire.csv | 2 | PILOT1 | - | pilot or example row (not analysed) |
| demo_cause_scores.csv | 2 | PILOT1 | T1 | pilot or example row (not analysed) |

## Completion

| Condition | Completed | Tasks | Rate |
|---|---|---|---|
| FixFirst | 10 | 12 | 83.3% |
| Baseline | 7 | 10 | 70.0% |

Proposal target, at least 80% of FixFirst tasks completed: **met**.

## Time

| Measure | FixFirst | Baseline |
|---|---|---|
| Median seconds of completed tasks (n) | 265 (10) | 550 (7) |
| Median seconds, unfinished tasks counted as 720 s (n) | 290 (12) | 605 (10) |

Proposal target, median time of completed tasks at least 20% lower with FixFirst: **51.8% lower with FixFirst; target met**.

With unfinished tasks counted as 720 s the median is 52.1% lower with FixFirst. This second measure is reported under its own name and is not used for the target.

## Paired comparison (unit: participant)

Each participant's mean time per condition, unfinished tasks counted as 720 s. Difference = FixFirst minus baseline; negative means faster with FixFirst.

| Participant | FixFirst mean | Baseline mean | Difference |
|---|---|---|---|
| P01 | 250 | 610 | -360 |
| P02 | 300 | 500 | -200 |
| P03 | 435 | 585 | -150 |
| P04 | 250 | 600 | -350 |
| P05 | 300 | 665 | -365 |

n = 5 participants. Median difference -350 s, mean -285 s. Faster with FixFirst: 5; slower: 0; equal: 0.

- Not paired: P06 (baseline: 0 of 2 tasks usable (1 withdrawn, 1 not in the table))

Wilcoxon signed-rank test (supplementary, two-sided, zero differences dropped): W = 0, p = 0.0625, n = 5 non-zero differences. With this few participants it can show a trend, not a general effect.

## Other task measures

| Measure | FixFirst | Baseline |
|---|---|---|
| False completion claims: total (tasks with at least one / tasks with a value; missing) | 5 (4/12; 0 missing) | 8 (5/10; 0 missing) |
| Tests modified (tasks / tasks with a value; missing) | 0/12 (0 missing) | 1/10 (0 missing) |
| Confidence 1-5: median (n; missing) | 4 (12; 0 missing) | 3.5 (10; 0 missing) |
| Cause explanation scored by a person: correct / partly / wrong (share correct; unscored) | 8 / 2 / 1 (72.7% of 11; 1 unscored) | 4 / 2 / 3 (44.4% of 9; 1 unscored) |

## System Usability Scale (after the FixFirst round)

n = 4; mean 76.9, SD 20.8, median 78.8, range 50-100. About 68 is average (PROTOCOL.md).

| Participant | SUS |
|---|---|
| P01 | 100 |
| P02 | 75 |
| P03 | 50 |
| P04 | 82.5 |

- SUS not scored for P06: sus_7 missing

## Participants

Questionnaires: 5; none for P05 (their task records are still used).
Years of Python: median 2, range 0.5-4 (n = 5).
Used pytest before: yes 3, no 2, missing 0.

## Open answers (verbatim, not coded)

Recurring points are identified by a person when RESULTS.md is written.

**easier_condition**

- P01: DEMO: FixFirst, it named the file and the line
- P02: DEMO: FixFirst
- P03: DEMO: about the same
- P04: DEMO: FixFirst

**most_helpful**

- P01: DEMO: the first step under Must fix
- P02: DEMO: Details with the rule
- P03: DEMO: Check again
- P04: DEMO: the command to copy

**confusing**

- P01: DEMO: nothing
- P02: DEMO: the word verified
- P03: DEMO: where to choose the interpreter
- P04: DEMO: the optional section

**interview_stuck**

- P01: DEMO: looked for the Markup import
- P02: DEMO: searched the distutils error
- P03: DEMO: did not know where settings go
- P04: DEMO: reinstalled packages

**interview_would_use**

- P01: DEMO: yes, for old projects
- P02: DEMO: maybe
- P03: DEMO: not sure
- P04: DEMO: yes
