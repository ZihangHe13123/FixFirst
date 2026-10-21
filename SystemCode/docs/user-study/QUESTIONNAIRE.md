# Questionnaire / 问卷

The experimenter asks the per-task questions aloud and writes the answers into `sessions.csv`.
The rest is filled in on paper or in a form and entered into `questionnaire.csv` under the
participant's code only. 每个任务后的两问由实验员口头问、记进 `sessions.csv`；其余部分用纸或表单填写，录进 `questionnaire.csv` 时只写编号。

## 1. Background (start) / 背景（开始时）

1. How many years have you been writing Python? / 你写 Python 多少年了？
2. Have you used pytest before? (yes / no) / 用过 pytest 吗？（是 / 否）

## 2. After each task (asked aloud) / 每个任务之后（口头问）

1. How confident are you that the project works now? 1 (not at all) to 5 (completely).
   你有多大把握项目现在能用了？1（完全没把握）到 5（完全有把握）。
2. In one sentence, what caused the problem? (Write down the answer as said; do not correct it.)
   用一句话说说，刚才是什么原因出的错？（照原话记下，不要纠正。）

## 3. After the FixFirst round: System Usability Scale / 用过 FixFirst 之后：SUS 量表

Brooke (1996), free to use with attribution. Answer each item from 1 (strongly disagree) to 5
(strongly agree), thinking of FixFirst. 每题 1（非常不同意）到 5（非常同意），针对 FixFirst 回答。

1. I think that I would like to use this system frequently.
2. I found the system unnecessarily complex.
3. I thought the system was easy to use.
4. I think that I would need the support of a technical person to be able to use this system.
5. I found the various functions in this system were well integrated.
6. I thought there was too much inconsistency in this system.
7. I would imagine that most people would learn to use this system very quickly.
8. I found the system very cumbersome to use.
9. I felt very confident using the system.
10. I needed to learn a lot of things before I could get going with this system.

Scoring (done by B): odd items score minus 1, even items 5 minus score; the sum times 2.5 gives
0–100.

## 4. At the end / 结束时

1. Which condition felt easier, and why? / 哪种条件更顺手，为什么？
2. Which part of FixFirst helped most? / FixFirst 哪一部分最有用？
3. What confused you? / 哪里让你困惑？

## 5. Interview (about 3 minutes) / 访谈（约 3 分钟）

1. Tell me about one moment where you were stuck. What did you try?
   说一个你卡住的时刻：当时你试了什么？
2. Would you use a tool like FixFirst on your own projects? Why or why not?
   你会在自己的项目上用这样的工具吗？为什么？

## `questionnaire.csv` columns

Template: [templates/questionnaire.csv](../tasks/templates/questionnaire.csv); rules: [DATA.md](DATA.md).
Leave an unanswered SUS item blank; it is never filled in. 没答的 SUS 题留空，不要补。

`participant, python_years, used_pytest, sus_1, …, sus_10, easier_condition, most_helpful,
confusing, interview_stuck, interview_would_use`
