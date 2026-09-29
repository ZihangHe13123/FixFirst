# User-study data and analysis rules / 用户研究的数据和分析规则

Three anonymous UTF-8 CSV tables, analysed by [analysis.py](analysis.py) as the
[protocol](PROTOCOL.md) describes. Participants appear only as `P01`, `P02` …; pilot participants
as `PILOT1`, `PILOT2`. Rows whose participant starts with `PILOT` or `P00` (the template's example
row) are never analysed.

三张匿名的 UTF-8 CSV 表。参与者只写编号；试用者写 `PILOT1`、`PILOT2`，模板里的示例行是 `P00-EXAMPLE`，这两类行都不进统计。

## `sessions.csv`: one row per participant and task / 每人每题一行

C records it during the sessions ([C2](../tasks/C2-user-study-sessions.md)); template:
[templates/sessions.csv](../tasks/templates/sessions.csv).

| Column | Values | Rule |
|---|---|---|
| `participant` | `P01` … | Required |
| `date`, `order`, `start_time`, `notes` | Free text | Not analysed |
| `fixfirst_set` | `A` or `B` | The task set done with FixFirst; the same on all of a participant's rows |
| `task` | `T1`–`T4` | Set A is T1 and T2, set B is T3 and T4. FixFirst tasks come from `fixfirst_set`, baseline tasks from the other set |
| `condition` | `fixfirst` or `baseline` | |
| `success` | `yes`, `no`, `withdrawn` | `yes`: the grade passed within 12 minutes. `no`: not completed. `withdrawn`: the participant left the study before finishing this task. Blank: not recorded |
| `seconds` | 1–720 | From the experimenter's "start" to the passing grade. A task not completed is recorded as 720 (a blank counts as 720 by definition) |
| `false_done_claims` | 0, 1, 2 … | Blank: not recorded |
| `tests_modified` | `yes` or `no` | A task with modified tests cannot be a success |
| `confidence_1to5` | 1–5 | Blank: not recorded |
| `cause_explanation` | The participant's words | Write `(no answer)` when they could not say; leave blank only when the question was not asked |

中文要点：没完成的题 `seconds` 记 720；参与者中途退出，`success` 写 `withdrawn`；说不出原因写 `(no answer)`，没问到才留空。

## `questionnaire.csv`: one row per participant / 每人一行

Template: [templates/questionnaire.csv](../tasks/templates/questionnaire.csv). Columns: `participant`,
`python_years` (a number, for example 0.5), `used_pytest` (`yes`/`no`), `sus_1` … `sus_10` (whole
numbers 1–5, [QUESTIONNAIRE.md](QUESTIONNAIRE.md) section 3), and the verbatim answers
`easier_condition`, `most_helpful`, `confusing`, `interview_stuck`, `interview_would_use`.
An unanswered SUS item stays blank: it is never filled in. 没答的 SUS 题留空，不要补。

## `cause_scores.csv`: a person's score of each explanation / 由人给原因解释评分

A person scores, not an AI tool and not a keyword search. Make the scoring sheet with

```bash
.venv/bin/python docs/user-study/analysis.py --cause-sheet cause_sheet.csv
```

It lists every usable task's explanation with the task's known cause, grouped by task and
shuffled, **without the condition**. Fill `cause_score` and `scorer`, and save the file as
`docs/user-study/cause_scores.csv` (template: [templates/cause_scores.csv](../tasks/templates/cause_scores.csv)).

| `cause_score` | When |
|---|---|
| `correct` | Names the actual cause: what was removed, missing or not installed (T1: Jinja2 3.1 removed `Markup`; T2: the project in `src/` is not installed; T3: Python 3.12 removed `distutils`; T4: `settings.toml` was never created from the example) |
| `partly` | Names the kind of problem or the symptom, not the cause ("an import problem", "a config file") |
| `wrong` | Another cause, or `(no answer)` |

A blank `cause_score` means not scored yet; it is reported as unscored, never as wrong.

## What the analysis does / 分析怎么算

- **Usable task record**: `success` is `yes` or `no`. Withdrawn tasks and tasks without a recorded
  `success` are left out and listed with the reason; a missing value never becomes 0 seconds or a
  success.
- **Completion rate** per condition: completed ÷ usable tasks. Proposal target: at least 80% with
  FixFirst.
- **Median time of completed tasks** per condition. Proposal target: at least 20% lower with FixFirst,
  that is (baseline − FixFirst) ÷ baseline ≥ 0.20. Not assessable when a condition has no completed
  task.
- **Median time with unfinished tasks counted as 720 s**: reported under that name and never used
  for the target.
- **Paired comparison, one unit per participant**: only participants with the configured number of
  usable tasks in both conditions (two, as the protocol says; `--tasks-per-condition 1` if the pilot
  changes the protocol, which the output records; then a participant's two tasks must be the matched
  pair the protocol names, T1 and T3 or T2 and T4, in either condition). Each participant's mean time per condition, with
  unfinished tasks counted as 720 s; difference = FixFirst − baseline, negative = faster with
  FixFirst. The Wilcoxon signed-rank test (two-sided, zero differences dropped) is a supplement;
  it is not computed without pairs or when every difference is zero.
- **False completion claims, modified tests, confidence, cause scores**: per condition, each with
  the number of tasks that have a value and the number missing.
- **SUS**: only complete questionnaires. Odd items score − 1, even items 5 − score, the sum × 2.5
  (0–100), once per participant. A missing or out-of-range item leaves that participant's SUS
  unscored, with the reason.
- **Open answers**: listed verbatim. Recurring points are identified by a person when RESULTS.md is
  written; the script does not invent themes or quotes.
- **A missing questionnaire** does not remove a participant's task records: every measure uses
  its own valid records.

## When the analysis stops / 哪些情况会直接报错

These are recording mistakes, so the analysis lists all of them and analyses nothing until the
table is corrected:

- a required column is missing; a participant code is empty;
- the same participant and task twice; an unknown condition or task; `fixfirst_set` not A or B,
  different on one participant's rows, or tasks outside the sets it implies;
- more tasks in a condition than configured; with one task per condition, a participant's two tasks
  that are not T1 and T3 or T2 and T4 (a participant with one task missing is simply not paired);
- `--time-limit` that is not a positive number of seconds;
- `seconds` not a whole number, negative, or above 720; a success without a time or after the time
  limit; a task not completed with a time other than 720;
- a success with modified tests;
- `false_done_claims`, `tests_modified`, `confidence_1to5`, `used_pytest` or `python_years` with an
  invalid value;
- in `cause_scores.csv`: a score other than correct, partly or wrong; the same task twice; a task
  without a usable record in `sessions.csv`.

## Output / 输出

```bash
.venv/bin/python docs/user-study/analysis.py --output docs/user-study/ANALYSIS.md --json docs/user-study/analysis.json
```

The Markdown lists the inputs' SHA-256, the protocol version, the script's version and SHA-256,
and the configuration, then every number with its sample size. RESULTS.md is written by a person
from it. `fixtures/` holds a fictional example: its output, `fixtures/DEMO_RESULTS.md`, is marked
DEMO and is not a result.
