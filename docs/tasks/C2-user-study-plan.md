# C2 用户研究：方案、知情同意书、招募

| | |
|---|---|
| 负责 | C。全员帮忙找人 |
| 截止 | 方案初稿 10/5（一）；10/10（六）前定好 8 名正式参与者和 2 名试用者的时间 |
| 预计用时 | 6–8 小时 |
| 要先完成 | 无，**招募今天就可以开始** |
| 交付 | 主仓库的 `docs/user-study/`：`PROTOCOL.md`、`CONSENT.md`、`QUESTIONNAIRE.md`、`RECRUITING.md`，通过 PR 提交；参与者名单**不进仓库** |
| 对应计划 | 后续计划 §4 P0 第 9 项、§9.4 |

## 为什么要做

商业价值和"好不好用"只能靠用户研究来证明，这是 proposal 的承诺：6–8 人，完成率 80%，中位用时降低 20%。现在只差这一项实验还没开始，而找人最花时间，所以要最先动手。无论结果好坏都如实报告，做了就比没做强得多。

## 研究设计（写进 PROTOCOL.md，可以在这个基础上改）

**研究问题**：有 FixFirst 时，修好一个出错的 Python 项目，完成率和用时有没有改善？

**设计**：组内对照。每个人两种条件都做，任务组和先后顺序都做平衡。

| 条件 | 能用的工具 |
|---|---|
| 有 FixFirst | FixFirst 网页界面 + 终端 + 网页搜索 |
| 没有 FixFirst | 终端 + 网页搜索 |

两种条件下都**不能用 AI 助手**：ChatGPT、Copilot、Gemini、Claude、搜索引擎里的 AI 对话都不行，普通搜索结果页可以看。

**任务**：B 在 B8 里准备 4 个故障项目，分成两组，每组 2 个，两组难度相当：

- A 组：T1、T2；
- B 组：T3、T4。

每个项目只有一个真实的问题。给参与者的说明是：

> 这个项目的测试跑不通。请让 `pytest` 全部通过。不要修改或删除 `tests/` 里的文件；项目代码可以改，包可以装或卸。觉得完成了就告诉我。

每个任务限时 **12 分钟**。试用之后可以调整，调整要写进方案。

**平衡顺序**：8 个人按下表轮换，每 4 个人一轮：

| 参与者 | 第一轮 | 第二轮 |
|---|---|---|
| P01、P05 | 有 FixFirst，A 组 | 没有 FixFirst，B 组 |
| P02、P06 | 有 FixFirst，B 组 | 没有 FixFirst，A 组 |
| P03、P07 | 没有 FixFirst，A 组 | 有 FixFirst，B 组 |
| P04、P08 | 没有 FixFirst，B 组 | 有 FixFirst，A 组 |

**参与者**：

- 会写 Python（上过课，或者做过项目），用过终端和 pip；
- 没用过 FixFirst，不是本组成员；
- 其他组的同学可以参加。

正式 6–8 人，另找 1–2 人试用。试用者的数据不计入结果。

**流程**（每人约 70 分钟）：

1. 说明和知情同意，5 分钟；
2. 背景问题，1 分钟：Python 经验多少年，用过 pytest 吗；
3. 第一轮的两个任务。如果这一轮有 FixFirst，开始前先用样例项目教 5 分钟怎么用；
4. 第二轮的两个任务（如果这一轮才用 FixFirst，教学放在这一轮开始前）；
5. 问卷：用过 FixFirst 以后填 SUS 量表，再加三个问题，5 分钟；
6. 简短访谈两个问题，3 分钟。

**记录什么**：每个任务记下面几项，表头见 `docs/tasks/templates/sessions.csv`：

| 指标 | 含义 |
|---|---|
| `success` | 限时内判分脚本通过 |
| `seconds` | 从开始读任务，到判分脚本通过；没通过记作限时 720 秒 |
| `false_done_claims` | 说"好了"但判分没通过的次数 |
| `tests_modified` | 是否改过测试文件。改过的不算成功 |
| `confidence_1to5` | 做完后自评"项目现在能用了"的把握，1–5 分 |

**分析**（在 C3 里做）：

- 每种条件的完成率；
- 用时的中位数；
- 每个人两种条件的用时差；
- Wilcoxon 符号秩检验作为补充；
- SUS 平均分；
- 访谈里提到的主要问题；
- 和 proposal 的目标对照（完成率 80%，中位用时降低 20%）。

人数少，重点是描述结果，检验结果只作参考。

## 知情同意书（CONSENT.md，要点）

中英文各一份，内容包括：

- 研究目的；
- 大约多长时间；
- 要做什么；
- 记录什么：用时、是否完成、问卷答案，**不录屏，不记姓名**；
- 数据怎么用：匿名编号 P01…，只用于这门课的报告，课程结束后删除；
- 自愿参加，随时可以停止，不需要说明理由；
- 联系人。

最后是签名和日期。签好的同意书由 C 自己保存，扫描件也不进仓库。

发封邮件问一下课程老师，这样的课程用户研究需不需要额外审批，把回复存档。这封邮件由组长或 C 来发。

## 问卷（QUESTIONNAIRE.md）

1. **SUS（System Usability Scale）**：10 个标准问题，1–5 分（Brooke, 1996），可以免费使用，注明出处即可。只在用过 FixFirst 以后填。

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

   计分：奇数题得分减 1，偶数题用 5 减去得分，加总后乘以 2.5，得到 0–100 分。
2. **每个任务做完问一句**："你有多大把握项目现在能用了？"1–5 分。
3. **最后三问**：
   - 哪种条件更顺手，为什么？
   - FixFirst 哪一步最有用？
   - 哪里让你困惑？

## 招募（RECRUITING.md 里放消息模板，名单不进仓库）

消息模板：

```text
【招募】帮我们测一个 Python 排错工具（约 70 分钟）
我们是 IRS 课程第 24 组。想请会写 Python 的同学，在我们的电脑上修 4 个出错的小项目，
其中一半可以用我们的工具。不录屏、不记名，数据只用于课程报告。
时间：10/11–10/19，地点：学校（或 Zoom 远程控制）。有兴趣请回复可以的时间段。

[Recruiting] Help us test a Python troubleshooting tool (about 70 minutes)
We are IRS Group 24. You will fix 4 small broken Python projects on our laptop, half of them
with our tool. No screen recording, no names; data is used only for our course report.
When: 11–19 Oct, on campus (or remotely via Zoom remote control). Reply with times that suit you.
```

- 发在课程群、其他小组、朋友圈，每位组员至少找 3 个人。
- 名单、联系方式、时间表放在 C 自己的表格里，参与者只用 P01、P02……编号。
- 一个时段 90 分钟，含准备和收尾。试用放在 10/11–10/12，正式实验放在 10/13–10/19。

## 步骤

1. **今天**：发招募消息，建自己的时间表。
2. 10/5 前：写好 `PROTOCOL.md`、`CONSENT.md`、`QUESTIONNAIRE.md`、`RECRUITING.md`，开 PR，请 B 看任务部分，请 A 看流程。
3. 10/10 前：确定试用者 2 人、正式参与者 8 人的时间；把研究是否需要额外审批的回复存档。
4. 接着做 [C3](C3-user-study-run.md)。

## 完成标准

- [ ] 四个文件都已通过 PR 合并
- [ ] 10/10 前确定了至少 6 名正式参与者和 1 名试用者的时间，最好是 8 + 2
- [ ] 名单和同意书没有进仓库
- [ ] 已向老师确认是否需要额外审批
