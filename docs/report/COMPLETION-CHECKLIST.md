# Report and guide completion checklist

Version 0.6 is an incomplete working draft for discussion by all three members. It incorporates
the published A2/B3 results, separate local and cloud MCP experiments, scripted follow checks,
BugsInPy and held-out checks, and the diagnosis, ordering and grouping evaluations.

## Work still needed

| Item | Required completion |
| --- | --- |
| Report review | All three members review the wording and evidence; Claude checks the merged additions. Section 2 and reference entries were preserved, not researched again in this revision |
| Real user study C2 | The user chose small real-participant sessions during the week of 12 October. Actual sessions, anonymous source tables and reviewed analysis remain pending. Exclude demonstration fixtures and the unusable submission in #67 |
| Windows C3 | A teammate installs the trial freeze on a real Windows machine and records the result |
| Independent installation | Someone who did not write the guide follows it on their own machine |
| rc5 trial feedback | Record the project, exact command/test selection, observed failure, advice followed and result. Decide the final version after feedback |
| Final release identity | A final version/tag has not been approved. Update installation and submission identities after that decision |
| Original proposal | Attach the original submitted proposal unchanged |
| Two videos | Prepare scripts, check claims, and have people record narration; no AI-generated narration |
| Individual contributions | Each member writes their own reflection and peer evaluation |
| Final packaging | Apply the course filenames and SystemCode layout, check the packaged copy, then upload before the deadline |

## Publication and interpretation

- The cited A2/B3, B7, B12, diagnosis, ordering and grouping evidence is published in main and
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
