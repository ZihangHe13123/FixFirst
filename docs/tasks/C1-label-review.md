# C1 标签复核：独立标注、对比、定稿

| | |
|---|---|
| 负责 | C。和 A 一起讨论分歧 |
| 截止 | 10/8（四）23:59：最终标签的提交号贴到 C1 的 Issue |
| 预计用时 | 4–6 小时 |
| 要先完成 | [A1](A1-heldout-projects.md)（10/5 交），[S0](S0-setup.md)，装好 uv |
| 交付 | 私有仓库中的 `labels-C.csv`、`review.md`、`labels.csv`（最终标签） |
| 对应计划 | 后续计划 §4 P0 第 2 项（"由没写规则的组员复核"） |

## 为什么要做

一个人写的标签带着这个人的盲点。试调研的 13 个项目只有作者一个人标注，这是它的弱点之一。proposal 承诺新项目的标签"由第二人复核"。更好的做法是：**两个人各自独立标注，再对比**，并报告一致率和 Cohen's kappa，报告里这是标准做法。

C 没有写规则，可以当第二个标注人。复核完成后的 `labels.csv`，就是 A2 打分用的标准答案。

## 规矩

和 A1 一样：不给 B 看，冻结前不在这些项目上运行 FixFirst，标签是自己的判断，不找 AI 下结论。另外还有一条：

- **先独立标注，再看 A 的标签。** `labels-C.csv` 提交之前，不要打开 `labels-A.csv`。提交记录能证明先后顺序。

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

按 A1 里"根因怎么判断"的表，只看 `pytest/<id>.txt` 和 `projects.toml`，给每个项目写 `root_cause` 和 `first_step`，写进 `labels-C.csv`（格式和 `labels-A.csv` 相同，用模板 `docs/tasks/templates/labels.csv`）。

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
git add labels-C.csv
git commit -m "Independent labels (C)"
git push
```

## 第 4 步：对比

在主仓库里运行：

```bash
.venv/bin/python scripts/heldout.py agree ~/fixfirst-heldout/labels-A.csv ~/fixfirst-heldout/labels-C.csv > ~/fixfirst-heldout/review.md
```

`review.md` 里会有：

- 根因相同的比例；
- Cohen's kappa；
- 一张逐个项目的对照表，分歧处标 **differs**；
- 两个人各自写的第一步。

Cohen's kappa 衡量扣除偶然因素后的一致程度：1 表示完全一致，0 表示和随便猜一样，0.6 以上一般算"较好"。

## 第 5 步：讨论分歧，定稿

和 A 开个短会（20–40 分钟），逐个讨论：

- **根因不同**：看证据、查文档，必要时在副本里再试一次，商定最终答案。
- **第一步写法不同，但会导向同样的修法**：算一致，合并成一种写法，另一种写进 `also_acceptable`。
- **还是定不下来**：以证据更充分的一方为准，把分歧写清楚。报告里会如实说明。

在 `review.md` 最后加一节 "Decisions"，每个有分歧的项目写一条：最后怎么定的，依据是什么。

然后生成最终的 `labels.csv`：以 `labels-A.csv` 为底稿，把商定的改动改进去，每一行的 `reviewed_by` 填你的名字；改过的行在 `review_notes` 里写一句改了什么。不要改 `labels-A.csv` 和 `labels-C.csv`，它们是原始记录。

检查是否齐全：

```bash
.venv/bin/python scripts/heldout.py check --manifest ~/fixfirst-heldout/projects.toml --labels ~/fixfirst-heldout/labels.csv
```

## 第 6 步：交付

提交 `review.md` 和 `labels.csv`，push，然后取提交号：

```bash
cd ~/fixfirst-heldout && git rev-parse HEAD
```

在**主仓库**的 C1 Issue 里评论，**不写项目名**，数字可以写：

```text
C1 完成：独立标注后根因一致 X/N，Cohen's kappa = 0.XX；讨论后定稿。最终标签提交号 <40 位提交号>。
```

从这时起标签冻结。A2 打分只用这个提交里的 `labels.csv`。

## 完成标准

- [ ] `labels-C.csv` 的提交早于你第一次打开 `labels-A.csv`
- [ ] `review.md` 有一致率、kappa、对照表和 Decisions
- [ ] `labels.csv` 通过 `heldout.py check`（显示 `Complete.`）
- [ ] 在 C1 的 Issue 里贴出了最终提交号和一致率，没有写项目名
