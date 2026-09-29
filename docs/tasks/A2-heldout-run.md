# A2 冻结版本上的留出测试和打分

| | |
|---|---|
| 负责 | A 运行和打分；C 独立复评 |
| 时间 | 10/10（六）运行；10/11（日）两人打分并对齐；10/12（一）交 PR；10/15（四）前给大模型基线打分 |
| 预计用时 | A 5–7 小时，C 3 小时（都含给大模型基线打分） |
| 要先完成 | A1、C1（最终标签的提交号已贴出），B5（B 在 Issue 里宣布 v0.7.0 已冻结）；第 7 步要等 B3 |
| 交付 | 私有仓库中的运行结果和打分；之后私有仓库公开，并通过 PR 把全部材料合进主仓库的 `examples/heldout-2026-10/` |
| 对应计划 | 后续计划 §4 P0 第 6 项 |

## 为什么要做

这是 FixFirst 在"没见过的项目"上的正式成绩：冻结的版本、事先写好并经过复核的标签、每个项目只跑一次。报告的真实项目结果、B 的大模型基线（B3、B7）都以它为准。

## 规矩

- **只跑一次。** 运行中断了（死机、断网），只补跑没跑完的项目（`--only`）。不要因为结果不好而重跑。
- **标签不再改。** 打分时发现标签有问题，不要改 `labels.csv`，在打分表的 `notes` 里写清楚。报告里会另外说明，做法参考 `examples/real-world/LABELS.md` 的 Corrections 一节。
- **不重建环境。** 用 A1 时装好的 `~/heldout-projects`，这样 FixFirst 看到的环境就是标签依据的环境。
- 结果公开之前，仍然不在群里提项目名。

## 第 1 步：确认版本和标签

```bash
cd ~/FixFirst
git fetch --tags
git switch --detach v0.7.0
.venv/bin/python -m pip install -e .
git describe --tags                        # 应该显示 v0.7.0
cd ~/fixfirst-heldout && git pull && git rev-parse HEAD
```

最后一行显示的提交号，应该和 C1 的 Issue 里贴出的最终提交号**一样**。如果不一样，说明有人在复核之后又改过文件，先查清楚再继续。

## 第 2 步：确认环境没有变

把原始 pytest 再跑一遍，输出放进一个**新文件夹**，不要覆盖 A1 的记录：

```bash
cd ~/FixFirst
.venv/bin/python scripts/heldout.py pytest ~/heldout-projects --manifest ~/fixfirst-heldout/projects.toml --output ~/fixfirst-heldout/pytest-before-run
```

逐个比较 `pytest-before-run/index.json` 和 `pytest/index.json` 里的 `summary`。都一样就继续；不一样的项目，把两次的结果记进这次运行的说明，照常运行，不要修环境。

## 第 3 步：运行 FixFirst（只跑一次）

```bash
.venv/bin/python scripts/run_real_world.py ~/heldout-projects --manifest ~/fixfirst-heldout/projects.toml --search --output ~/fixfirst-heldout/results-v0.7.0.json
```

Windows：

```powershell
.venv\Scripts\python scripts\run_real_world.py $HOME\heldout-projects --manifest $HOME\fixfirst-heldout\projects.toml --search --output $HOME\fixfirst-heldout\results-v0.7.0.json
```

`--search` 的意思是：第一步如果是"找一个还能用的旧版本"（界面上的 **Find it**），就像用户点了它一样继续跑，记录搜索之后的第一步。这一步要联网，整批大约需要 10–60 分钟。

跑完立刻提交到私有仓库：

```bash
cd ~/fixfirst-heldout
git add pytest-before-run results-v0.7.0.json
git commit -m "Held-out run with FixFirst v0.7.0"
git push
```

想在界面里看每个项目的结果：

```bash
cd ~/FixFirst && .venv/bin/fixfirst --store ~/heldout-projects/.fixfirst serve
```

报告要用的截图，就在这里截。

## 第 4 步：打分

生成打分表。A 和 C 各生成一份，各打各的：

```bash
.venv/bin/python scripts/heldout.py sheet --labels ~/fixfirst-heldout/labels.csv --results ~/fixfirst-heldout/results-v0.7.0.json --output ~/fixfirst-heldout/scores-A.csv
```

C 把最后的文件名换成 `scores-C.csv`。

表里每一行，左边是标签（根因、正确的第一步、`also_acceptable`、`partial_if`、`wrong_if`），右边是 FixFirst 的输出：

- `fixfirst_headline`：页面顶部那句话；
- `fixfirst_first_step`：第一步；如果用了 Find it，这里是搜索之后的第一步，搜索前的那一步在 `search_offered`；
- `fixfirst_cause`：FixFirst 给的根因；
- `fixfirst_hedged`：`yes` 表示它只说"可能是"；
- `fixfirst_rules`：用到的规则。

每个项目填三列：`score`、`scored_by`、`notes`。**只给第一步打分**，也就是新用户第一件会去做的事。

| score | 含义 |
|---|---|
| `correct` | 第一步针对的就是标注的根因，照做（或运行它给的命令）能解决这一层，之后可能还剩下一层。`fixfirst_hedged` 为 yes 时，报告里会注明"只说了可能"。 |
| `partial` | 原因说对了，但照做不行，或者不够。比如给的版本界限还不够低，或者命令装不上。 |
| `generic` | 没有说出原因，只给了"检查一下这个异常"之类的通用建议。 |
| `wrong` | 第一步指向了别的原因，或者照做没有用。 |

- 健康项目：没有"必须修"的问题（`(no must-fix step)`），记 `correct`；否则记 `wrong`。
- 拿不准照做行不行，就用 A1 的 `twin` 在副本里试一次，把结果写进 `notes`。这是最有说服力的依据。
- 打分只看标签和 FixFirst 的输出，不要因为"它其实也有道理"就放宽标准；有道理的地方写进 `notes`。

## 第 5 步：两人对齐

```bash
.venv/bin/python scripts/heldout.py agree ~/fixfirst-heldout/scores-A.csv ~/fixfirst-heldout/scores-C.csv --column score > ~/fixfirst-heldout/scores-review.md
```

逐个讨论不一致的项目，商定后写进最终的 `scores.csv`（以 `scores-A.csv` 为底稿），在 `scores-review.md` 末尾记下每个决定和理由。然后统计：

```bash
.venv/bin/python scripts/heldout.py summary ~/fixfirst-heldout/scores.csv
```

把统计结果（总数和按根因分列的表）保存下来，写 README 时要用。

## 第 6 步：公开并合进主仓库

1. 在私有仓库里写 `README.md`：
   - 整个流程的时间线：标签提交号（A1）、复核后的最终提交号（C1），以及它们在 Issue 里贴出的时间；冻结版本 v0.7.0；运行时间；
   - 抽样办法和候选数量；
   - 标签一致率和 kappa（来自 C1）；
   - 打分一致率（来自第 5 步）；
   - 总成绩和按根因分列的表；
   - 每个非 correct 的项目一两句话：FixFirst 说了什么，为什么不对。

   提交并 push。
2. 私有仓库改为公开：Settings → General → 最下面 Danger Zone → Change visibility → Public。这样任何人都能核对提交时间。
3. 复制进主仓库：新建分支 `a2-heldout-results`，把私有仓库里除 `.git` 以外的全部文件复制到 `examples/heldout-2026-10/`。
4. 检查没有本机路径和个人信息：

   ```bash
   grep -rn "/Users/\|C:\\\\Users\|@gmail\|@u.nus" examples/heldout-2026-10 || echo "clean"
   ```

   Windows 上可以在 Git Bash 里运行这条命令。

   `pytest/` 里的输出如果单个超过 5 MB，就在 PR 里说明，由 B 决定怎么处理。
5. 开 PR，分支名 `a2-heldout-results`，标题写 "A2: held-out results on v0.7.0"，10/12 前交。
6. PR 合并以后，在 A2 的 Issue 里告诉 B："结果已合并，可以开始 B3、B7 的基线"。从这时起，B 可以看这批项目。

## 第 7 步：给大模型基线打分（10/14–10/15）

B 在 B3 里让几个本地大模型只看 FixFirst 诊断时读取的同一批原始记录（pytest 输出和探针记录、环境快照、项目索引），回答每个项目的根因和第一步。它们的第一步也要由人按同样的规则打分，这样才能和 FixFirst 公平比较。你们只给 B3 的这些回答打分；B7 的修复实验由测试自动判分，不需要你们打分，也不用等它跑完。

1. B 会在 A2 的 Issue 里给出打分表：每个模型一份，格式和第 4 步的一样，模型名换成 `model-1`、`model-2`……，你们不知道哪个是哪个。
2. A 和 C 各自打分（`score`、`scored_by`、`notes`），规则和第 4 步完全相同。
3. 用第 5 步的 `agree --column score` 对齐分歧，把最终打分表交回 B。

每个模型大约 20–30 分钟。

## 完成标准

- [ ] 运行用的是 v0.7.0，标签的提交号和 C1 贴出的一致
- [ ] 每个项目只跑了一次（中断时只补跑了没跑完的）
- [ ] A、C 各自打分，分歧记在 `scores-review.md` 里
- [ ] `heldout.py summary` 的结果写进了 README
- [ ] 私有仓库已公开，材料已通过 PR 合进 `examples/heldout-2026-10/`
- [ ] 没有本机路径和个人信息
- [ ] 大模型基线的回答也由 A、C 各自打分并对齐（第 7 步）
