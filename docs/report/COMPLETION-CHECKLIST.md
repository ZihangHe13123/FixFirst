# Report and guide completion checklist

Version 0.8 is an incomplete working draft for discussion by all three members. It incorporates
the published A2/B3 results, separate local and cloud MCP experiments, scripted follow checks,
BugsInPy and held-out checks, the diagnosis, ordering and grouping evaluations, and the
second-round participant study.

## Completed participant study

C2 is complete: six participants across the sessions on 12 and 13 October, with 24 task
records and six questionnaires in `docs/user-study/sessions.csv` and `questionnaire.csv`.
The second-round data are in main via #67. The first-round submission was superseded and
is not used. Arithmetic is verified; session procedures are reported by the experimenter.
Small-sample interpretation and final wording still need group review.

## Work still needed

| Item | Required completion |
| --- | --- |
| Report review | All three members review the wording and evidence; Claude rechecks the corrected bibliography. Background-paper numbers and descriptions have been checked; the group still decides whether to extend the literature review |
| Windows C3 | #100 at `14bfb63` has passing CI; Wei Yi still needs to run the full Windows suite on that commit and attach the log before the merge decision |
| Independent installation | Someone who did not write the guide follows it on their own machine |
| rc5 trial feedback | Record the project, exact command/test selection, observed failure, advice followed and result. Decide the final version after feedback |
| Final release identity | A final version/tag has not been approved. Update installation and submission identities after that decision |
| Original proposal | Attach the original submitted proposal unchanged |
| Two videos | Prepare scripts, check claims, and have people record narration; no AI-generated narration |
| Individual contributions | Each member writes their own reflection and peer evaluation |
| Final packaging | Apply the course filenames and SystemCode layout, check the packaged copy, then upload before the deadline |

## Publication and interpretation

- The cited A2/B3, B7, B12, diagnosis, ordering, grouping and participant evidence is published in main and
  pinned in [SOURCES.md](SOURCES.md). The original scores and evaluated tags stay unchanged.
- Agent effects belong to `5c224cf` (rc2). Later output compatibility and product verification
  checks are reported separately; they do not remeasure rc5 agent performance.
- B12 and B17 are no longer unrun tasks. Their limitations remain: default runs often miss the
  bug test, the available ordering cases show no advantage, and removing evidence display needs
  a participant arm that has not been run.
- Hard-pair grouping precision is 0.274, below the proposal target of 0.90. Keep this result.
- Main includes a later execution-dataset generator repair (#95); the frozen tags identify the
  product and runner actually evaluated. This documentation work does not alter them.
- The current guide installs the immutable rc5 trial tag. Earlier screenshots are labelled as
  the rc2 sample workflow. Windows and independent human installation are still pending.
- After human review and remaining evidence, render and inspect the final documents again.
