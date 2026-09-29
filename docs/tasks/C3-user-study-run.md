# C3 用户研究：试用、正式实验、分析

| | |
|---|---|
| 负责 | C。A 协助计时和记录 |
| 时间 | 试用 10/11–10/12；正式 10/13–10/19；分析 10/21 前 |
| 预计用时 | 15–20 小时：每人约 90 分钟，另加准备和分析 |
| 要先完成 | C2（方案和参与者）；B8（任务项目和判分脚本，10/10 交） |
| 交付 | 主仓库 `docs/user-study/` 下的 `sessions.csv`（匿名）、`questionnaire.csv`（匿名）、`analysis.py`、`RESULTS.md`，通过 PR 提交 |
| 对应计划 | 后续计划 §4 P0 第 9 项 |

## B8 会交给你什么

B 在 10/10 前把下面这些放进主仓库的 `experiments/user_study/`，用法以其中的 README 为准：

- 4 个任务项目 T1–T4：A 组是 T1、T2，B 组是 T3、T4；
- `prepare.py`：在指定文件夹里建一套全新的任务副本，每个都带好自己的环境。每个参与者开始前运行一次；
- `grade.py`：给一个任务判分，打印 PASS 或 FAIL 和原因。它会跑全部测试，并检查测试文件有没有被改、测试数量对不对；
- 参考答案，只给实验员看，用来确认判分脚本正常。

## 第 1 步：准备电脑（试用前一天）

1. 更新主仓库，切到冻结版，按 [C4](C4-windows-check.md) 的方法确认测试全部通过。
2. 按 B8 的 README 运行 `prepare.py` 建好任务副本，然后确认：
   - 每个新建的任务，`grade.py` 都判 FAIL；
   - 用参考答案改好以后，都判 PASS。
3. 关掉所有 AI 功能：VS Code 里停用 Copilot 等扩展；浏览器不登录任何 AI 助手；不开 Claude、ChatGPT 客户端。
4. 准备好：
   - 一个空白终端；
   - FixFirst 网页界面，先不打开；
   - 手机计时器；
   - 打印好的同意书和问卷，或者网页表单；
   - 自己的记录表，按 `docs/tasks/templates/sessions.csv` 的列建。

## 第 2 步：试用（1–2 人，10/11–10/12）

完全按 PROTOCOL.md 走一遍，重点看这几件事：

- 12 分钟够不够。试用者一个都做不完，或者 3 分钟就做完，都要调整；
- 任务说明看得懂吗；
- FixFirst 的教学 5 分钟够吗；
- 判分和计时顺不顺手。

结束后，把改动写进 PROTOCOL.md 的 "Changes after the pilot" 一节，开 PR 合并。**试用者的数据不计入结果**；`sessions.csv` 里要么不写，要么参与者编号用 `PILOT1`、`PILOT2`。

任务本身有问题（太难、有歧义、判分不对），在 B8 的 Issue 里告诉 B，由 B 修改任务项目。

## 第 3 步：正式实验（10/13–10/19）

每个参与者照这张清单做：

1. 开始前：运行 `prepare.py` 重建全部任务，关掉上一个人留下的浏览器标签和终端。
2. 说明研究、签同意书；给参与者编号（P01…），按 C2 的平衡表确定这个人的顺序。
3. 问背景：Python 经验多少年，用过 pytest 吗。
4. 进入第一轮。有 FixFirst 的一轮，先用 FixFirst 的样例项目（Open a sample project）教 5 分钟。
5. 每个任务：
   - 读完说明就开始计时；
   - 参与者说"好了"，你就运行 `grade.py`；
   - PASS 就记下用时；FAIL 就说一句"还没通过"，计时继续，`false_done_claims` 加 1；
   - 到 12 分钟停止，记为未完成；
   - 问一句把握有多大，1–5 分。
6. 第二轮同上。
7. 填问卷（用过 FixFirst 以后填 SUS），问访谈的两个问题，简要记下回答。
8. 当天就把数据录进 `sessions.csv` 和 `questionnaire.csv`，只写编号，不写名字。

实验员只回答"任务说明是什么意思"，不给排错提示。参与者问怎么修，就说"按你平时的做法来"。

## 第 4 步：分析（10/21 前）

在主仓库里写 `docs/user-study/analysis.py`，读两个 CSV，输出 `RESULTS.md` 要用的数字。主仓库的 `.venv` 里已经有 scipy（scikit-learn 依赖它），可以直接用：

```python
import csv
from statistics import median
from scipy.stats import wilcoxon

rows = [r for r in csv.DictReader(open("docs/user-study/sessions.csv", encoding="utf-8-sig"))
        if not r["participant"].startswith(("PILOT", "P00"))]
for condition in ("fixfirst", "baseline"):
    group = [r for r in rows if r["condition"] == condition]
    done = sum(r["success"] == "yes" for r in group)
    print(condition, f"completed {done}/{len(group)}",
          "median seconds", median(int(r["seconds"]) for r in group))

# Paired: each participant's mean time with and without FixFirst (unfinished tasks count as 720 s).
people = sorted({r["participant"] for r in rows})
def mean_time(p, c):
    times = [int(r["seconds"]) for r in rows if r["participant"] == p and r["condition"] == c]
    return sum(times) / len(times)
with_ff = [mean_time(p, "fixfirst") for p in people]
without = [mean_time(p, "baseline") for p in people]
print("Wilcoxon signed-rank:", wilcoxon(with_ff, without))
```

`condition` 这一列统一写成 `fixfirst` 或 `baseline`。

`RESULTS.md` 写这几部分：

1. 参与者概况：人数、Python 经验的分布；
2. 完成率和中位用时的对照表，写明和 proposal 目标（80%，降低 20%）的差距；
3. 配对比较：每个人的用时差，以及检验结果（n 小，只作参考）；
4. SUS 平均分和分布，以及怎么解读（68 分左右是平均水平）；
5. 错误声称"好了"的次数、改测试文件的次数；
6. 访谈里反复出现的意见；
7. 局限：人数少、学习效应（第二轮更熟练）、任务是人为构造的、实验员是组员；
8. 试用后对方案做了哪些调整。

开 PR，标题写 "C3: user study results"。C7 的用户研究章节由这份结果改写而来。

## 完成标准

- [ ] 试用完成，调整写进了 PROTOCOL.md
- [ ] 正式参与者至少 6 人，平衡顺序按表执行
- [ ] `sessions.csv`、`questionnaire.csv` 匿名，没有名字和联系方式
- [ ] `analysis.py` 能直接跑出 `RESULTS.md` 里的数字
- [ ] 结果如实报告，包括没达到目标的部分
