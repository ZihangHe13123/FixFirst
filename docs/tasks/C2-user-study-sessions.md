# C2 用户研究：招募、试用、正式实验

| | |
|---|---|
| 负责 | C。全员帮忙找人；A 可以协助计时 |
| 时间 | 招募今天开始，10/10 前定好人；试用 10/11–10/12；正式实验 10/13–10/19 |
| 预计用时 | 15–20 小时：每人约 90 分钟，另加招募和准备 |
| 要先完成 | 招募不用等；实验要等 B13（方案、同意书、问卷，10/5）和 B8（任务项目和判分脚本，10/10） |
| 交付 | 匿名的 `docs/user-study/sessions.csv` 和 `questionnaire.csv`，通过 PR 提交 |
| 对应计划 | 后续计划 §4 P0 第 9 项 |

## 为什么要做

"FixFirst 能不能帮人更快修好项目"只能靠真人实验回答，这是 proposal 的承诺：6–8 人，完成率 80%，中位用时降低 20%。实验必须有人在现场带，所以由你来做。

**你只需要做三件事：找人、带实验、记数据。** 研究方案、同意书、问卷由 B 在 [B13](B13-user-study-design.md) 里写好；任务项目、重建和判分脚本由 B8 提供；数据分析也由 B 做。

## 第 1 步：招募（今天开始）

把下面这段发到课程群、其他小组和朋友圈。每位组员至少找 3 个人，名单由你汇总：

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

- **参与者条件**：会写 Python（上过课或做过项目），用过终端和 pip；没用过 FixFirst，不是本组成员。其他组的同学可以参加。
- **人数**：正式 8 人（至少 6 人），试用 2 人。试用者的数据不计入结果。
- **时间**：一个时段约 90 分钟，含准备和收尾。试用放在 10/11–10/12，正式实验放在 10/13–10/19。
- **名单、联系方式、时间表只放在你自己的表格里，不进仓库，也不要写在 Issue 里。** 每人给一个编号（P01、P02……），按 PROTOCOL.md 里的平衡顺序表确定他先用还是后用 FixFirst、做哪组任务。
- 10/10 前在 C2 的 Issue 里报一下人数，例如"已约 8 + 2 人"。

## 第 2 步：准备电脑（试用前一天）

1. 更新主仓库，切到 B 在 B8 的 Issue 里指定的版本标签（一般是 v0.7.0；试用后如果改过任务项目，会是 v0.7.1，FixFirst 本身不变），按 [C3](C3-windows-check.md) 的方法确认测试全部通过。
2. 按 [B8 的 README](../../experiments/user_study/README.md) 运行一次自检：

   ```powershell
   .venv\Scripts\python experiments\user_study\prepare.py C:\study --self-test
   ```

   应该看到 4 行 `as expected`，最后是 `Self-test passed`。不对就在 B8 的 Issue 里告诉 B。自检会用参考答案把任务改好，所以之后要再运行一次 `prepare.py C:\study`（不带 `--self-test`）重建。
3. 关掉所有 AI 功能：VS Code 里停用 Copilot 等扩展；浏览器不登录任何 AI 助手。
4. 准备好：
   - 一个空白终端；
   - FixFirst 网页界面（先不打开）；
   - 手机计时器；
   - 打印好的同意书和问卷，或者网页表单；
   - 记录表，按 `docs/tasks/templates/sessions.csv` 的列建。

## 第 3 步：试用（1–2 人，10/11–10/12）

完全按 PROTOCOL.md 走一遍，重点看这几件事：

- 12 分钟够不够：试用者一个都做不完，或者 3 分钟就做完，都要调整；
- 任务说明看得懂吗；
- FixFirst 的 5 分钟教学够不够；
- 判分和计时顺不顺手。

试用完，把看到的问题写在 C2 的 Issue 里，由 B 修改方案。任务本身有问题（太难、有歧义、判分不对），在 B8 的 Issue 里说。试用者的编号用 `PILOT1`、`PILOT2`，数据照常记，也一起交给 B，用来先把分析脚本跑通。

## 第 4 步：正式实验（10/13–10/19）

每个参与者照这张清单做：

1. **开始前**：运行 `prepare.py C:\study` 重建全部任务，关掉上一个人留下的浏览器标签和终端。
2. **说明研究**，签同意书。签好的同意书你自己保存，不进仓库。告诉参与者修好的标准：新开一个终端直接运行 `pytest` 也能全部通过（临时设置的环境变量不算）。
3. **问背景**：Python 经验多少年，用过 pytest 吗。
4. **第一轮**：如果这一轮有 FixFirst，先用样例项目（Open a sample project）教 5 分钟。
5. **每个任务**：
   - 参与者读完说明就开始计时；
   - 他说"好了"，你就运行 `grade.py C:\study T1`（换成当前任务的编号）；
   - PASS：记下用时；
   - FAIL：说一句"还没通过"，计时继续，`false_done_claims` 加 1；
   - 到 12 分钟停止，记为未完成，用时记 720 秒；
   - 问一句"你有多大把握项目现在能用了"，1–5 分；
   - 再问一句"你觉得刚才是什么原因出的错"，照原话记进 `cause_explanation`，不要纠正他。
6. **第二轮**：同上。
7. **结束**：用过 FixFirst 以后填问卷（SUS 加三个问题）；再问访谈的两个问题，简要记下回答。
8. **当天就把数据录进表格**：只写编号，不写名字。

规矩：

- 两种条件下都不能用 AI 助手，普通搜索可以。
- 你只解释"任务说明是什么意思"，不给排错提示。参与者问怎么修，就说"按你平时的做法来"。

## 第 5 步：交数据

全部做完以后：

1. 新建分支 `c2-study-data`。
2. 把记录表存成 `docs/user-study/sessions.csv`（`condition` 这一列统一写 `fixfirst` 或 `baseline`），问卷答案存成 `docs/user-study/questionnaire.csv`。
3. 开 PR，在 C2 的 Issue 里告诉 B。

B 会用 `analysis.py` 跑出结果，写成 `RESULTS.md`，你看一遍数字对不对就行。

## 完成标准

- [ ] 试用完成，发现的问题已经告诉 B
- [ ] 正式参与者至少 6 人，平衡顺序按表执行
- [ ] `sessions.csv`、`questionnaire.csv` 匿名，没有名字和联系方式
- [ ] 同意书和名单没有进仓库
- [ ] 数据已通过 PR 提交，B 的结果你核对过
