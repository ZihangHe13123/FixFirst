# C1 标签复核：独立标注、对比、定稿

| | |
|---|---|
| 负责 | C。和 A 一起讨论分歧 |
| 截止 | 10/8（四）23:59：最终标签的提交号贴到 C1 的 Issue |
| 预计用时 | 4–6 小时 |
| 要先完成 | [A1](A1-heldout-projects.md)（10/5 交），[S0](S0-setup.md)，装好 uv |
| 交付 | 私有仓库中的 `labels-C.csv`（初始判断）、`review-initial-C.md`（待核实项）、`review.md`、`labels.csv`（最终标签），补全 `ai-assistance.md` |
| 对应计划 | 后续计划 §4 P0 第 2 项（"由没写规则的组员复核"） |

## 为什么要做

一个人写的标签带着这个人的盲点。试调研的 13 个项目只有作者一个人标注，这是它的弱点之一。proposal 承诺新项目的标签"由第二人复核"。C 先不看 A 或 AI 的答案，保存自己的判断，再一起查证分歧；这可以减少被先看到的答案带偏。A 允许有记录的 AI 辅助，因此报告应如实描述双方的标注方式。

C 没有写规则，可以当第二个标注人。复核完成后的 `labels.csv`，就是 A2 打分用的标准答案，不用于本轮训练。暂时无法判断的项目可以记“待核实”，不必硬猜；最终标签仍须逐项验证。

## 规矩

和 [A1](A1-heldout-projects.md) 一样：材料不给 B 或其开发助手看，冻结前不在这些项目上运行 FixFirst，AI 线索必须经人工核查和副本验证。

- **先保存独立初判。** `labels-C.csv` 和 `review-initial-C.md` 提交之前，不打开 `labels-A.csv`、A 的 `ai-assistance.md` 或任何针对这些案例的 AI 回答。通用命令说明、非案例文档的翻译可以用 AI，不能让它先替你诊断这批案例。
- **初判提交后可以继续借助 AI 查证。** 用 C 自己的独立会话，按 A1 的验证与记录要求进行；保留原始初判，后续修改进入 `review.md` 和最终 `labels.csv`，不回填成“独立判断”。

## 第 1 步：拿到材料

接受 A 的私有仓库邀请，然后克隆：

```bash
cd ~
git clone https://github.com/<A 的用户名>/fixfirst-heldout.git
```

你要用到的材料都在里面：

- `projects.toml`：每个项目是怎么装的，`scenario` 写了故意少做了什么；
- `pytest/<id>.txt`：原始 pytest 输出；
- `environments/<id>.txt`：装上的版本；
- `candidates.csv`：A 试过的所有候选。

## 第 2 步：检查抽样

浏览 `candidates.csv`，看 A 是不是按 A1 的抽样办法挑的：

- 是否按列表顺序往下看；
- 放弃的理由是否符合规定的几条；
- 每类根因的名额是否合理。

发现问题（比如某个项目要联网、结果不稳定，或者是排除名单里的项目）就和 A 商量换掉。换掉的项目在 `candidates.csv` 里写明原因。

## 第 3 步：独立标注

按 A1 里“根因怎么判断”的表，查看原始 pytest、项目清单、环境记录、源码和你自己查到的官方资料，为能判断的项目写 `root_cause` 和 `first_step`，写进 `labels-C.csv`（用模板，删除 EXAMPLE 行）。

暂时判断不了的项目，**先不往 CSV 里填猜测或新增类别**，在 `review-initial-C.md` 写案例 ID、已查证的事实、尝试过程和“待核实”的原因；没有待定项就写“无”。这份初判记录也先提交，再查看 A/AI 的答案。最终标准答案仍须完整，但独立初判不要求靠猜测凑齐。

拿不准时可以自己动手试，但**不要用 A 的项目文件夹**，也不要改私有仓库里的 `environments/`。做法是把清单复制到一个临时文件夹，在自己的电脑上重新搭一份：

```bash
mkdir -p ~/c-review && cp ~/fixfirst-heldout/projects.toml ~/c-review/
cd ~/FixFirst
.venv/bin/python scripts/setup_real_world.py ~/c-review/projects --manifest ~/c-review/projects.toml --only <id>
cd ~/c-review/projects/<id>
.venv/bin/python -m pytest -q
```

Windows：

```powershell
mkdir $HOME\c-review -Force; Copy-Item $HOME\fixfirst-heldout\projects.toml $HOME\c-review\
cd C:\dev\FixFirst
.venv\Scripts\python scripts\setup_real_world.py $HOME\c-review\projects --manifest $HOME\c-review\projects.toml --only <id>
cd $HOME\c-review\projects\<id>
.venv\Scripts\python -m pytest -q
```

隔了几天再装，个别库可能出了新版本，结果和 A 的记录不完全一样；这种情况写在备注里。`checked_by_trying` 写你自己试了什么。

写完先提交，再往下做：

```bash
cd ~/fixfirst-heldout
git pull
git add labels-C.csv review-initial-C.md
git commit -m "Independent labels (C)"
git push
```

## 第 4 步：对比

在主仓库里运行：

```bash
.venv/bin/python scripts/heldout.py agree ~/fixfirst-heldout/labels-A.csv ~/fixfirst-heldout/labels-C.csv > ~/fixfirst-heldout/review.md
```

脚本只比较两份表**共有的项目**，并列出只在一份表里的 ID。若 C 尚无可独立判断的项目，不运行该命令，直接在 `review.md` 写“一致率和 kappa 无法计算；独立初判 0/N，其余待共同核实”。否则 `review.md` 里会有：

- 根因相同的比例；
- Cohen's kappa；
- 一张逐个项目的对照表，分歧处标 **differs**；
- 两个人各自写的第一步。

Cohen's kappa 衡量扣除按双方类别分布预计的偶然一致后的一致程度：1 表示完全一致，0 表示与该偶然基准相当。小样本和类别分布都会影响它，不能用一个阈值代替逐案核查。

在表前补上：A 是否用过 AI、C 初判的方法、共同可比较的案例数 **m/N**、待核实/不在两表交集的案例数。不得把 C 看过 A/AI 答案后的共同裁决再拿来计算“独立一致率”；A 用过 AI 时也不能写“两人全程纯人工标注”。

## 第 5 步：讨论分歧，定稿

初判提交后，才打开 A 的标签和辅助记录，和 A 开个短会（20–40 分钟），逐个讨论分歧和待核实项。此时双方可以按 A1 借助 AI 找线索，并在 `ai-assistance.md` 追加使用记录；结论必须落实到人实际核查的来源和运行证据：

- **根因不同**：看证据、查文档，必要时在副本里再试一次，商定最终答案。
- **第一步写法不同，但会导向同样的修法**：算一致，合并成一种写法，另一种写进 `also_acceptable`。
- **还是定不下来**：继续记为待核实，不按“谁更自信”定标签。最终仍无法核实的候选按 A1 记录原因后排除/替换，并补做新候选的标注和复核；报告说明数量，不能悄悄删掉。

在 `review.md` 最后加一节 "Decisions"，每个有分歧或初判待定的项目写一条：最后怎么定的，依据是什么，是否用了 AI 辅助，谁复核了验证记录。初判之后才排除的案例仍保留初始记录；如另算最终主集的一致率，单列其分母和排除清单。

然后生成最终的 `labels.csv`：以 `labels-A.csv` 为底稿，把商定的改动改进去，每一行的 `reviewed_by` 填你的名字；改过的行在 `review_notes` 里写一句改了什么。不要改 `labels-A.csv` 和 `labels-C.csv`，它们是原始记录。

检查是否齐全：

```bash
.venv/bin/python scripts/heldout.py check --manifest ~/fixfirst-heldout/projects.toml --labels ~/fixfirst-heldout/labels.csv
```

## 第 6 步：交付

提交 `review.md`、最终 `labels.csv` 和补全的 `ai-assistance.md`；保留已提交的 `labels-C.csv`、`review-initial-C.md`，push，然后取提交号：

```bash
cd ~/fixfirst-heldout && git rev-parse HEAD
```

在**主仓库**的 C1 Issue 里评论，**不写项目名**，数字可以写：

```text
C1 完成：共 N 个项目，共有初始判断 m 个，其中根因一致 X/m，kappa = 0.XX（无可比较记录则写未计算）；AI 辅助方式及共同裁决已记录。最终标签提交号 <40 位提交号>。
```

从这时起标签冻结。A2 打分只用这个提交里的 `labels.csv`。

## 完成标准

- [ ] `labels-C.csv` 和 `review-initial-C.md` 的提交早于你第一次打开 A 的标签或案例 AI 回答
- [ ] `review.md` 有初始判断的一致率、kappa、明确的 m/N 分母、标注辅助方式、对照表和 Decisions；无可比较记录时明确说明
- [ ] 待核实项目已验证定稿或记录排除/替换；`ai-assistance.md` 已补全，不回改原始初判
- [ ] `labels.csv` 通过 `heldout.py check`（显示 `Complete.`）
- [ ] 在 C1 的 Issue 里贴出了最终提交号和一致率，没有写项目名
