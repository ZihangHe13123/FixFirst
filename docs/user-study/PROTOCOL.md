# User study protocol

Version 1.1, 29 September 2026. Task B13 writes and maintains it; C runs the sessions
([C2](../tasks/C2-user-study-sessions.md)). Changes after the pilot go in the last section.

## Research question and targets

Does FixFirst help people repair a broken Python project, compared with the tools they
normally use? The proposal (section 8) set two targets:

- **Completion**: at least 80% of tasks completed with FixFirst.
- **Time**: the median time of **successfully completed** tasks is at least 20% lower with FixFirst
  than without it.

Failures and timeouts are reported alongside the timing results. A second time measure, with
unfinished tasks counted as the time limit, is reported separately under its own name and is
never used to claim the time target.

## Design

Within subjects: every participant works under both conditions, on different tasks.

| Condition | Tools allowed |
|---|---|
| FixFirst | The FixFirst web interface, a terminal, web search |
| Baseline | A terminal, web search |

No AI assistant in either condition (ChatGPT, Copilot, Gemini, Claude, or the AI answers of a
search engine). Ordinary search results may be read.

**Tasks** (B8, [experiments/user_study](../../experiments/user_study/README.md)): four small projects,
each with one real fault, in two sets of matched difficulty. Each set has one version problem
and one set-up or configuration problem:

- Set A: T1 (a library removed a name), T2 (src layout not installed);
- Set B: T3 (Python removed a module), T4 (a settings file was never created).

**Order**: counterbalanced over four groups of participants.

| Participants | First round | Second round |
|---|---|---|
| P01, P05 | FixFirst, set A | Baseline, set B |
| P02, P06 | FixFirst, set B | Baseline, set A |
| P03, P07 | Baseline, set A | FixFirst, set B |
| P04, P08 | Baseline, set B | FixFirst, set A |

**Time limit**: 12 minutes per task.

**Deviation from the proposal**: the proposal gave each participant one task per condition. Two
tasks per condition reduce the effect of any single task being easier than its counterpart.
If the pilot shows that a 70-minute session is too long, fall back to one task per condition
(T1 and T3, or T2 and T4) and record the change below.

## Participants

- Have written Python (a course or a project) and used a terminal and pip.
- Have not used FixFirst and are not members of the team. Students of other groups may take part.
- Six to eight in the main study, plus one or two for the pilot, whose data are not analysed.

## Setting

In person, on C's laptop (Windows), or remotely through Zoom remote control of that laptop.
FixFirst at the frozen version (v0.7.0, or the v0.7.x that B names in the B8 issue). Before each
participant, `prepare.py` rebuilds all four tasks.

Before each task, the experimenter starts the participant terminal with `open_task.py TARGET TASK`
(commands in the B8 README). It opens in that task's directory, binds Python and pip to its own
`.venv`, and starts without user shell profiles or temporary Python, pytest, pip and application
variables. Confirm the interpreter with `python -c "import sys; print(sys.executable)"`.
Both conditions use this terminal; in the FixFirst condition, select the same project and
interpreter in FixFirst. Do not reveal test output during setup. Keep a separate experimenter
terminal in the FixFirst repository for `grade.py`. Exit the task shell after each task and open
the next task through the launcher. Setup and interpreter checks are outside the timed period.

## Procedure (about 70 minutes)

1. Welcome, explain the study, sign the consent form (5 min).
2. Background questions: years of Python, whether they have used pytest (1 min).
3. First round: two tasks. If the round uses FixFirst, first the 5-minute tutorial below.
4. Second round: two tasks, with the tutorial first if FixFirst comes now.
5. Questionnaire after the FixFirst round and at the end (5 min).
6. Short interview, two questions (3 min).

**Instruction read at the start of every task:**

> This project's tests fail. Please make `python -m pytest` pass in the prepared task terminal.
> Do not change or delete the files in `tests/`; you may change the project's code and install or
> remove packages. It counts as fixed when the tests also pass in a fresh task terminal using
> this same environment, without temporary variable settings. Tell me when you think you are done.

Chinese version: 这个项目的测试跑不通。请在准备好的任务终端里让 `python -m pytest` 全部通过。不要修改或删除 `tests/` 里的文件；项目代码可以改，包可以装或卸。修好的标准是：重新用同一任务环境打开干净终端，测试也能全部通过，临时设置的变量不算。觉得完成了就告诉我。

**FixFirst tutorial (5 minutes, on the sample project, never on a task):** start FixFirst, press
*Open a sample project* (this already runs the first check); read the first step under *Must fix*
and open its *Details*. Apply the two import fixes in `FIXES.md`: `from collections.abc import Mapping`
in `pricing.py`, and `from helpers import double` in `reports.py`. Press *Check again*: the two
collection issues now move to *Fixed and verified*, while two runtime faults become visible.
Explain that fixing only the first import leaves collection blocked and does not verify it.
Do not fix the remaining runtime faults during the tutorial.

**Timing and grading**: finish setup, the tutorial and the spoken task instruction first. The
clock starts when the experimenter says "start" and allows the participant to inspect and work
on the project. Preparation, instruction and tutorial time are excluded. When they
say they are done, the experimenter runs `grade.py`. PASS stops the clock. FAIL: say "not yet",
keep the clock running and count a false completion claim. At 12 minutes, stop and record the task
as not completed. The experimenter explains the instruction only; no hints about the fault.

## Measures

Recorded per task in `sessions.csv` (columns in [templates/sessions.csv](../tasks/templates/sessions.csv)):

| Measure | Meaning |
|---|---|
| `success` | `grade.py` passed within the time limit |
| `seconds` | from the experimenter's "start" to the passing grade; 720 when not completed |
| `false_done_claims` | times the participant said "done" and the grade failed ("unsuccessful attempts" in the proposal) |
| `tests_modified` | whether a file under `tests/` was changed (the grade then fails) |
| `confidence_1to5` | "How confident are you that the project works now?" |
| `cause_explanation` | the participant's own one-sentence explanation of the cause, written down verbatim; B later marks it correct, partly correct or wrong against the known cause ("understanding of the advice" in the proposal) |

After the FixFirst round: the System Usability Scale; at the end: three open questions and the
interview ([QUESTIONNAIRE.md](QUESTIONNAIRE.md)).

## Analysis (B13)

- Completion rate per condition.
- Median time of completed tasks per condition, against the 20% target.
- Median time with unfinished tasks counted as 720 seconds, reported under that name.
- Per participant: mean time with and without FixFirst; Wilcoxon signed-rank test as a
  supplement (with six to eight people the result shows a trend, not a general effect).
- False completion claims and modified tests per condition.
- Share of correct cause explanations per condition.
- SUS score (mean and spread; about 68 is average).
- Recurring points from the open answers and interviews.

## Data handling

- Participants appear only as P01, P02 …; names, contact details and signed consent forms stay with
  C, outside the repository, and are deleted after the course.
- No screen or audio recording.
- The anonymous tables (`sessions.csv`, `questionnaire.csv`) are published with the report.

## Threats to validity

Few participants; learning between rounds; constructed tasks chosen within FixFirst's scope; the
experimenter is a team member; the time limit cuts off slow solutions.

## Changes after the pilot

(Fill in after the pilot, with the reason for each change.)
