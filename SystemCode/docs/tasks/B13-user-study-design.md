# B13 用户研究：方案、同意书、问卷和分析

| | |
|---|---|
| 负责 | B（AI 协助）。招募和现场实验由 C 负责（[C2](C2-user-study-sessions.md)） |
| 截止 | 方案文件 10/5（一）；分析脚本 10/1（四）前用虚构数据写好并验证；正式分析 10/21（三） |
| 预计用时 | 约 4 小时 |
| 要先完成 | 方案和分析脚本都没有前置；正式分析要等 C2 交数据 |
| 交付 | 主仓库 `docs/user-study/` 下：`PROTOCOL.md`、`CONSENT.md`、`QUESTIONNAIRE.md`（10/5）；`analysis.py` 和虚构数据的样例（本批）；`RESULTS.md`（10/21） |
| 对应计划 | 后续计划 §4 P0 第 9 项 |

## 为什么要做

商业价值和"好不好用"只能靠用户研究来证明，这是 proposal 的承诺：6–8 人，完成率 80%，中位用时降低 20%。找人最花时间，所以 C 今天就开始招募；方案要在 10/5 前写好，试用之后再调整。无论结果好坏都如实报告。

## 研究设计（写进 PROTOCOL.md，可以在这个基础上改）

**研究问题**：有 FixFirst 时，修好一个出错的 Python 项目，完成率和用时有没有改善？

**设计**：组内对照。每个人两种条件都做，任务组和先后顺序都做平衡。

| 条件 | 能用的工具 |
|---|---|
| 有 FixFirst | FixFirst 网页界面 + 终端 + 网页搜索 |
| 没有 FixFirst | 终端 + 网页搜索 |

两种条件下都**不能用 AI 助手**：ChatGPT、Copilot、Gemini、Claude、搜索引擎里的 AI 对话都不行，普通搜索结果页可以看。

**任务**：B8 准备 4 个故障项目，分成两组，每组 2 个，两组难度相当：

- A 组：T1、T2；
- B 组：T3、T4。

每个项目只有一个真实的问题。给参与者的说明是：

> 这个项目的测试跑不通。请在准备好的任务终端里让 `python -m pytest` 全部通过。不要修改或删除 `tests/` 里的文件；项目代码可以改，包可以装或卸。修好的标准是：重新用同一任务环境打开干净终端，测试也能全部通过，临时设置的变量不算。觉得完成了就告诉我。

每题由实验员先用 `open_task.py` 准备任务终端并核对解释器；有 FixFirst 时指定同一个解释器。
环境准备、说明和教学不计时。说明结束、实验员说“开始”并允许参与者查看项目和操作时开始计时。

每个任务限时 **12 分钟**。试用之后可以调整，调整要写进方案。

proposal 写的是每人两个任务（每种条件一个）。这里每种条件做两个，是为了减少单个任务难易带来的偶然影响；如果试用时发现太累，就改回每种条件一个，并写进方案。

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
| `seconds` | 从说明结束、实验员说“开始”并允许操作，到判分脚本通过；没通过记作限时 720 秒。环境准备、说明和教学不计时 |
| `false_done_claims` | 说"好了"但判分没通过的次数 |
| `tests_modified` | 是否改过测试文件。改过的不算成功 |
| `confidence_1to5` | 做完后自评"项目现在能用了"的把握，1–5 分 |
| `cause_explanation` | 做完后用一句话说出刚才出错的原因，照原话记下；B 事后对照任务的已知原因判断说对没有。对应 proposal 的"对建议的理解"（understanding of the advice） |

**分析**（B 在本卡片最后一步做）：

- 每种条件的完成率；
- **成功完成的任务的中位用时**：这是 proposal 目标（降低 20%）用的指标；
- 另报"未完成按 720 秒计入"的中位用时，和上一项分开命名，不能用它宣布达到 proposal 的目标；
- 说对原因的比例（`cause_explanation`）；
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

B 发封邮件问一下课程老师，这样的课程用户研究需不需要额外审批，把回复存档。

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

招募消息的模板在 [C2](C2-user-study-sessions.md) 里，C 直接用，不用等这里的方案。

## 分析（C2 交数据以后）

`docs/user-study/analysis.py` 读取 C 提交的 `sessions.csv` 和 `questionnaire.csv`，输出 `RESULTS.md` 要用的数字。主仓库的 `.venv` 里已经有 scipy（scikit-learn 依赖它）。核心部分：

```python
import csv
from statistics import median
from scipy.stats import wilcoxon

rows = [r for r in csv.DictReader(open("docs/user-study/sessions.csv", encoding="utf-8-sig"))
        if not r["participant"].startswith(("PILOT", "P00"))]
for condition in ("fixfirst", "baseline"):
    group = [r for r in rows if r["condition"] == condition]
    solved = [int(r["seconds"]) for r in group if r["success"] == "yes"]
    print(condition, f"completed {len(solved)}/{len(group)}",
          "| median seconds of solved tasks (proposal target):", median(solved) if solved else "n/a",
          "| median seconds, unsolved counted as 720:", median(int(r["seconds"]) for r in group))

# Paired: each participant's mean time with and without FixFirst (unfinished tasks count as 720 s).
people = sorted({r["participant"] for r in rows})
def mean_time(p, c):
    times = [int(r["seconds"]) for r in rows if r["participant"] == p and r["condition"] == c]
    return sum(times) / len(times)
with_ff = [mean_time(p, "fixfirst") for p in people]
without = [mean_time(p, "baseline") for p in people]
print("Wilcoxon signed-rank:", wilcoxon(with_ff, without))
```

上面只是最初的思路。**脚本在看到任何数据之前就写好**：先用一份标明是虚构的样例数据和能手算的预期值验证，样例结果标为 DEMO，不当成研究结果。原因解释说得对不对由人评分，脚本只读评分。试用数据（`PILOT…`）只用来检查脚本能读 C 的表，不进正式统计；C 交正式数据以后，运行一条命令得到 `RESULTS.md` 要用的数字。

`RESULTS.md` 写这几部分，报告（[B11](B11-report.md)）的用户研究一节由它改写：

1. 参与者概况：人数、Python 经验的分布；
2. 完成率、**成功任务的中位用时**的对照表，写明和 proposal 目标（完成率 80%，成功任务的中位用时降低 20%）的差距；"未完成按 720 秒计入"的中位用时单独列一行，名称写清楚；
3. 配对比较：每个人的用时差，以及检验结果（n 小，只作参考）；
4. SUS 平均分和分布，以及怎么解读（68 分左右是平均水平）；
5. 错误声称"好了"的次数、改测试文件的次数，以及说对原因的比例；
6. 访谈里反复出现的意见；
7. 局限：人数少、学习效应（第二轮更熟练）、任务是人为构造的、实验员是组员；
8. 试用后对方案做了哪些调整。

## 步骤

1. 10/5 前：写好 `PROTOCOL.md`、`CONSENT.md`、`QUESTIONNAIRE.md` 并合并，在 C2 的 Issue 里告诉 C；发邮件问老师是否需要额外审批。
2. 现在（10/1 前）：写好 `analysis.py`，用虚构数据和能手算的预期值验证，单独开 PR。
3. 试用（10/11–10/12）以后：按 C 的反馈修改方案，写进 PROTOCOL.md 的 "Changes after the pilot" 一节；用试用数据检查脚本能读 C 的表。如果改成每种条件一题，要在分析配置里写明，不能让脚本悄悄换算法。
4. C 交正式数据以后：由人给原因解释评分，运行 `analysis.py`，写 `RESULTS.md`，10/21 前合并。

## 完成标准

- [ ] 三个方案文件 10/5 前合并，C 已经在用
- [ ] 已向老师确认是否需要额外审批
- [ ] `analysis.py` 能直接跑出 `RESULTS.md` 里的数字
- [ ] 结果如实报告，包括没达到目标的部分
