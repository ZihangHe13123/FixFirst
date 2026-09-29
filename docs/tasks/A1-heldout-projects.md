# A1 新真实项目：挑选、搭环境、写标签

| | |
|---|---|
| 负责 | A。C 复核（[C1](C1-label-review.md)） |
| 截止 | 10/5（一）23:59：标签写完、提交到私有仓库，并在 A1 的 Issue 里贴出提交号 |
| 预计用时 | 15–20 小时。每个项目 1–1.5 小时，大约要试 20 个候选 |
| 要先完成 | [S0](S0-setup.md)，并且装好 uv |
| 交付 | 私有仓库 `fixfirst-heldout` 中的 `projects.toml`、`environments/`、`pytest/`、`labels-A.csv`、`candidates.csv` |
| 对应计划 | 后续计划 §4 P0 第 2 项 |

## 为什么要做

proposal 承诺用 10–15 个**没见过的**真实项目做留出测试。报告里"FixFirst 在新项目上表现如何"只能拿这批项目回答，老师也最可能追问这一点。

9/24 试调研用过的 13 个项目，已经在第 2、3 轮被用来改规则，不能再当测试集。规则由 B 在 AI 协助下编写，所以新项目必须由别人挑、别人标注，而且**标签要先于运行**。10/9 冻结版本以后，你在 A2 里用这批项目只跑一次 FixFirst，按这里写的标签打分。

## 规矩（违反任何一条，这批数据就不能再当留出测试）

1. **只放私有仓库，只给 C 看。** 名单、pytest 输出、标签都放在你自己的私有仓库里。不要在群里或公开 Issue 里提具体项目，不要给 B 看。
2. **冻结前不在这些项目上运行 FixFirst。** 网页界面、`fixfirst` 命令、`run_real_world.py`、MCP 都不行。只用 `heldout.py pytest` 查看原始的 pytest 输出。
3. **标签是你自己的判断。** 可以查官方文档、release notes、GitHub issue，也可以在副本里动手试（第 5 步）。不要把 pytest 输出贴给 AI 让它下结论：之后要用同样的输出测试大模型基线，标签如果来自 AI，这个比较就不成立了。
4. **下面这些项目不能用**：试调研的 13 个（见 `examples/real-world/projects.toml`）、flask 1.1.4、humanize，以及 `examples/` 里出现过的其他项目。BugsInPy 里的 17 个项目留给 B12，这里也不用。
5. **挑项目时不考虑 FixFirst 能不能做对。** 你也不需要知道它有哪些规则。按下面的抽样办法做，试过的每个候选都记下来，包括放弃的，并写明原因。

## 要凑成什么样

目标是 12 个项目，最少 10 个，各类根因都要有：

| 根因（`root_cause`） | 个数 | 真实情况举例 |
|---|---|---|
| `version_incompatibility` | 4 | 旧版本项目配上今天的库或 Python：库删掉了某个 API，Python 删掉了某个模块，测试工具太老 |
| `missing_dependency` | 2 | 只装了项目，没装测试依赖（extra 或 requirements-test.txt）；项目安装失败，导致声明的依赖都没装上 |
| `local_module` | 2 | src 布局的项目没安装就跑测试；项目里的文件和某个库重名 |
| `config_missing` | 2 | 没设置需要的环境变量；没按说明复制配置文件；Django 项目没配置 settings |
| `code_defect` | 1 | 项目自己的真实 bug：取修复提交的父提交，加上修复时新增的测试（做法见文末） |
| `healthy` | 1 | 按说明装好，测试全部通过。这是对照组：FixFirst 不应该报出"必须修"的问题 |

版本问题最容易自然出现；其他几类需要在"新人照着 README 装"的基础上做一个**真实会发生**的变化（比如漏装测试 extra），并在 `scenario` 里写清楚。

## 根因怎么判断

标注的是**用户第一个要处理的失败**（第一层）的根因。修好它以后才出现的问题，写进 `later_layers`。

| 根因 | 定义（和 FixFirst 知识库一致） | 典型报错 |
|---|---|---|
| `missing_dependency` | 代码导入的第三方包在这个解释器里没装（不管有没有声明） | `No module named 'shellingham'`，而 shellingham 是一个库 |
| `local_module` | 项目自己的模块找不到或导入不对：src 布局没装、改名或挪了位置、循环导入、项目文件遮住了同名的库或标准库模块 | `No module named 'cachetools'`，而 cachetools 就是项目本身 |
| `version_incompatibility` | 装的库或 Python 版本不再提供代码（或测试工具）要用的东西，或者行为变了：删掉的模块、属性、函数、参数，改变的返回值或报错方式，太老的测试工具 | `cannot import name '_app_ctx_stack' from 'flask'`；`No module named 'imp'`（Python 3.12 删了它） |
| `config_missing` | 运行时缺少需要的环境变量、配置项、配置文件或外部服务 | `KeyError: 'DATABASE_URL'`；`ImproperlyConfigured: settings are not configured` |
| `code_defect` | 环境没问题，是项目自己的逻辑错了：断言、函数实现、拼写、语法错误 | 修复提交之前的 `AssertionError` |
| `healthy` | 测试全部通过 | `N passed` |

几种容易混的情况：

- `No module named X` 要看 X 是什么。X 是没装的库，属于 `missing_dependency`；X 是项目自己的包，属于 `local_module`；X 是被 Python 删掉的模块（`imp`、`distutils`），属于 `version_incompatibility`。
- 报 `ImportError` 或 `cannot import name`，但原因是装的库太新，属于 `version_incompatibility`。
- 同时出现几种失败时，标出现最早、挡住最多测试的那一个，其余的写进 `later_layers`。
- 测试要联网的项目不要用：结果取决于网络。
- 跑两次结果不一样（flaky）的项目不要用。

## 怎么挑项目（抽样办法）

为了避免只挑"自己觉得容易"的项目，按固定办法抽：

1. **候选来源**：[awesome-python](https://github.com/vinta/awesome-python) 列表。至少覆盖 6 个不同的分类，例如 Web、数据处理、命令行、测试、日期时间、文本处理、图像、网络、数据库。
2. **在每个分类里按列表顺序往下看**，不按个人偏好跳着挑。跳过的项目在 `candidates.csv` 里写明原因。跳过条件只有这几条：
   - 不是纯 Python，需要编译 C 扩展；
   - 仓库里没有 pytest 能跑的测试；
   - 测试要联网或者要付费服务；
   - 在规矩 4 的排除名单里。
3. **选版本**：版本问题优先取 2022-01-01 之前的最后一个发布版本（在仓库的 Releases / Tags 页面，或 PyPI 的 Release history 里找），healthy 和 code_defect 取近两年的版本。
4. **怎么装**：按项目自己的说明装，看 README、CONTRIBUTING、tox.ini、requirements-dev.txt，或者 setup.py、pyproject.toml 里的测试 extra。没有锁版本的依赖，就装今天的最新版。Python 默认用 3.12，有两三个项目改用 3.10、3.11 或 3.13，让版本分布更分散。
5. **补齐非版本类的根因**：在第 4 条的基础上，做一个真实会发生的变化（漏装测试 extra、没安装项目、没设环境变量……）。这个变化要在跑 pytest **之前**写进 `scenario`。
6. **记下每个候选**，写进 `candidates.csv`。某类根因的名额满了以后，再遇到这一类的候选也要记下来，`kept` 写 `no`，理由写 "quota full"。

## 第 0 步：准备私有仓库

1. 在 GitHub 上新建仓库：右上角 + → New repository → 名字填 `fixfirst-heldout` → 选 **Private** → 勾选 Add a README → Create。
2. 进入仓库的 Settings → Collaborators → Add people，添加 C。不要加 B。
3. 克隆到本地，并复制模板：

macOS / Linux：

```bash
cd ~
git clone https://github.com/<你的用户名>/fixfirst-heldout.git
cp ~/FixFirst/docs/tasks/templates/projects.toml ~/fixfirst-heldout/projects.toml
cp ~/FixFirst/docs/tasks/templates/labels.csv ~/fixfirst-heldout/labels-A.csv
cp ~/FixFirst/docs/tasks/templates/candidates.csv ~/fixfirst-heldout/candidates.csv
```

Windows（PowerShell）：

```powershell
cd $HOME
git clone https://github.com/<你的用户名>/fixfirst-heldout.git
Copy-Item C:\dev\FixFirst\docs\tasks\templates\projects.toml $HOME\fixfirst-heldout\projects.toml
Copy-Item C:\dev\FixFirst\docs\tasks\templates\labels.csv $HOME\fixfirst-heldout\labels-A.csv
Copy-Item C:\dev\FixFirst\docs\tasks\templates\candidates.csv $HOME\fixfirst-heldout\candidates.csv
```

模板里以 `EXAMPLE` 开头的行只是示范，写第一个真实项目之前删掉。示范的内容来自试调研的 typer 项目，演示每一列该写到多细。

下面的命令都在**主仓库**里运行（`cd ~/FixFirst` 或 `cd C:\dev\FixFirst`）。项目会装在 `~/heldout-projects`，它不属于任何仓库。

## 第 1 步：把候选写进 projects.toml

照模板里的说明，每个项目写一段 `[[project]]`。`scenario` 用一句话写清楚：按什么说明装的，故意少做了什么。

## 第 2 步：搭环境

```bash
.venv/bin/python scripts/setup_real_world.py ~/heldout-projects --manifest ~/fixfirst-heldout/projects.toml --only <id>
```

Windows：

```powershell
.venv\Scripts\python scripts\setup_real_world.py $HOME\heldout-projects --manifest $HOME\fixfirst-heldout\projects.toml --only <id>
```

这一步会：

- 把项目克隆到 `~/heldout-projects/<id>`；
- 在项目里用 uv 建 `.venv`；
- 按 `install` 逐行安装；
- 把装上的版本清单写到私有仓库的 `environments/<id>.txt`。

安装失败会打印出来，并按"场景的一部分"记录，就像试调研里的 parsel。重跑这条命令会删掉旧的 `.venv` 重新装，但不会重新克隆。

## 第 3 步：跑两遍原始 pytest

```bash
.venv/bin/python scripts/heldout.py pytest ~/heldout-projects --manifest ~/fixfirst-heldout/projects.toml --only <id> --repeat 2
```

Windows 同样，把开头换成 `.venv\Scripts\python`，路径换成 `$HOME\...`。

输出写在私有仓库的 `pytest/<id>.txt`：开头几行是记录信息（命令、Python 版本、每一遍的结果），下面是第一遍的完整输出。汇总在 `pytest/index.json`。

- 两遍结果不同时，文件里会写 WARNING。这个项目不能用，除非你查清了原因。
- 一遍超过 20 分钟会被停掉，太慢的项目也不要用。

**写标签只依据这份输出**，这也是 FixFirst 之后会看到的东西。

## 第 4 步：判断根因和正确的第一步

读第一个错误和它的调用栈，回答四个问题：

1. 异常是在哪里抛出的：项目代码、测试、第三方库，还是标准库？
2. 缺的或出错的是哪个名字？
3. 这个名字属于谁：项目自己、某个库，还是 Python？
4. 按上面的表，这属于哪一类根因？

然后写出**用户照做就能解决这一层**的第一步。写成具体的动作，例如 "Install Flask < 2.4 (2.3.3 still provides `_app_ctx_stack`)"，不要写 "fix the version"。

## 第 5 步：在副本里验证

标签要经过实际验证，这是它最有价值的地方。**不要**在 `~/heldout-projects` 里的原项目上试：A2 要用原样的环境运行 FixFirst。用 `twin` 复制一份，副本的包版本和原项目完全一样：

```bash
.venv/bin/python scripts/heldout.py twin ~/heldout-projects --manifest ~/fixfirst-heldout/projects.toml --id <id> --to ~/heldout-try
cd ~/heldout-try/<id>
uv pip install --python .venv/bin/python "flask<2.4"     # 举例：试你认为正确的第一步
.venv/bin/python -m pytest -q
```

Windows：

```powershell
.venv\Scripts\python scripts\heldout.py twin $HOME\heldout-projects --manifest $HOME\fixfirst-heldout\projects.toml --id <id> --to $HOME\heldout-try
cd $HOME\heldout-try\<id>
uv pip install --python .venv\Scripts\python.exe "flask<2.4"
.venv\Scripts\python -m pytest -q
```

把试了什么、结果如何写进 `checked_by_trying`，例如 "Twin: flask<2.4 installs 2.3.3; the conftest import error is gone; 12 failed, 88 passed (next layer: SQLAlchemy 2)"。修好这一层以后出现的问题写进 `later_layers`。试完删掉 `~/heldout-try/<id>`；下次再试同一个项目，要先删掉旧的副本。

## 第 6 步：写标签，记候选

`labels-A.csv` 一个项目一行。各列的含义：

| 列 | 写什么 |
|---|---|
| `id` | 和 projects.toml 里的一样 |
| `pytest_shows` | 原始 pytest 看到的第一个失败，一句话，例如 "2 collection errors: No module named 'shellingham'" |
| `root_cause` | 六选一：`missing_dependency`、`local_module`、`version_incompatibility`、`config_missing`、`code_defect`、`healthy` |
| `first_step` | 正确的第一步：照做就能解决这一层 |
| `also_acceptable` | 别的也能解决这一层的第一步（没有就空着） |
| `partial_if` | 什么样的建议只算"部分正确"：原因对了，但照做不行，或者不够。比如版本界限还不够低 |
| `wrong_if` | 什么样的建议明确算错。比如让 pip 安装 Python、把问题当成代码缺陷 |
| `checked_by_trying` | 你在副本里试了什么，结果如何（第 5 步） |
| `later_layers` | 修好第一层以后出现的问题；没有就写 `none` |
| `labelled_by` | 你的名字 |
| `labelled_on` | 日期，例如 2026-10-02 |
| `reviewed_by`、`review_notes` | 留给 C 在 C1 里填 |

`also_acceptable`、`partial_if`、`wrong_if` 是 A2 打分时的依据。写得越具体，打分时的争议就越少。

`candidates.csv` 里每个试过的候选各写一行，包括放弃的，写明来源（awesome-python 的哪个分类）和放弃的原因。

## 第 7 步：随时提交到私有仓库

每做完一个项目就提交一次。提交时间本身就是"标签先于运行"的证据：

```bash
cd ~/fixfirst-heldout
git add projects.toml environments pytest labels-A.csv candidates.csv
git commit -m "Label <id>"
git push
```

## 第 8 步：10/5 交付

1. 检查是否齐全。在主仓库里运行：

   ```bash
   .venv/bin/python scripts/heldout.py check --manifest ~/fixfirst-heldout/projects.toml --labels ~/fixfirst-heldout/labels-A.csv
   ```

   它会列出每一类根因的数量。只有显示 `Complete.` 才算齐：每个项目都有完整的标签、跑了两遍且结果稳定的 pytest 输出，以及版本清单。

2. 最后提交一次并 push，然后取完整的提交号：

   ```bash
   cd ~/fixfirst-heldout && git rev-parse HEAD
   ```

3. 在**主仓库**的 A1 Issue 里评论，**不写项目名**：

   ```text
   A1 完成：N 个项目的标签已提交到私有仓库，提交号 <40 位提交号>。
   ```

   GitHub 会记下这条评论的时间。等私有仓库公开以后，任何人都能核对：这个提交里的标签早于 FixFirst 的运行。

4. 私下告诉 C 可以开始 C1。从这时起，标签只能通过 C1 的复核流程修改，改动写进复核记录。

## 代码缺陷项目怎么准备

1. 找一个近两年合并的、带回归测试的 bug 修复。可以在 GitHub 上搜 `is:pr is:merged label:bug`，或者翻 commit 历史里 "Fix …" 并且改了 `tests/` 的提交。选这个时间段，是因为今天的环境基本是好的，唯一的失败就是这个 bug。
2. 记下修复提交的完整提交号，以及它改了哪些测试文件（在 PR 的 Files changed 页面看）。
3. 父提交的提交号：在克隆的仓库里运行 `git rev-parse <修复提交>~1`；也可以打开修复提交的 GitHub 页面，看上面写的 "1 parent"。
4. 在 projects.toml 里写上 `commit`（父提交）、`tests_from`（修复提交）和 `test_files`（写法见模板）。第 2 步的脚本会检出父提交，再从修复提交取测试文件。
5. 确认新测试在父提交上失败。第 5 步的副本里，把修复提交的源文件换进去（`git checkout <修复提交> -- <源文件>`），确认测试通过，并写进 `checked_by_trying`。

## 常见问题

- **`uv` 找不到**：装完 uv 以后要新开一个终端。
- **克隆时报 "Remote branch … not found"**：`ref` 必须和 GitHub 上的 tag 名一字不差，注意有没有 `v`。
- **安装很慢或卡住**：多半是在编译 C 扩展，按规则跳过这个项目。
- **不确定属于哪一类根因**：先按上面的表判断；还是拿不准，就在 `review_notes` 里写下你的犹豫，留给 C1 讨论。不要去问 B。
- **磁盘**：每个项目连环境大约 100 MB–1 GB。A2 完成之前不要删 `~/heldout-projects`，也不要在里面升级或安装任何东西。

## 完成标准

- [ ] 至少 10 个项目，每类根因都有（`heldout.py check` 显示的数量）
- [ ] `heldout.py check` 显示 `Complete.`
- [ ] 每个标签都在副本里验证过（`checked_by_trying` 不空）
- [ ] `candidates.csv` 记下了所有试过的候选，放弃的写明了原因
- [ ] 私有仓库只邀请了 C
- [ ] 10/5 23:59 前，在 A1 的 Issue 里贴出了提交号，没有写项目名
- [ ] 冻结前没有在这些项目上运行过 FixFirst
