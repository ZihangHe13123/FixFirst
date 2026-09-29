# A2 BugsInPy 真实缺陷验证

| | |
|---|---|
| 负责 | A |
| 截止 | 10/9（五）：选好并复现至少 4 个缺陷（不运行 FixFirst）；10/12（一）：用冻结版跑完，交 PR |
| 预计用时 | 6–8 小时 |
| 要先完成 | [S0](S0-setup.md)、装好 uv；第二阶段要等 B5（10/9 冻结 v0.7.0） |
| 交付 | 主仓库的 `examples/bugsinpy-verification/`，通过 PR 提交 |
| 对应计划 | 后续计划 §4 P0 第 5 项 |

## 为什么要做

proposal 承诺：在**至少 8 个真实缺陷、至少 4 个库**上验证 FixFirst 的"修好了才算修好"。现在只有 packaging 和 click 两个库的 4 个上游回归缺陷（`examples/historical-regressions/`），还差至少 4 个缺陷、2 个库。

[BugsInPy](https://github.com/soarsmu/BugsInPy) 收录了 17 个项目的 501 个真实 bug，全部是项目自己的代码缺陷。它能检验两件事：

1. **验证**：修好之前，这个 bug 对应的问题一直是"未解决"；修好以后，同范围的检查通过了，问题才关闭。
2. **不冤枉环境**：对真正的代码缺陷，FixFirst 不应该建议安装、升级或锁定包。生成数据检验不了这一点。

## 分两个阶段

- **阶段 1（10/6–10/9）：只复现，不运行 FixFirst。** 挑出能在今天的环境里复现的 bug：有 bug 时测试失败，打上修复后测试通过。
- **阶段 2（10/10 以后）：用冻结版 v0.7.0 运行 FixFirst。** 这样结果和 A3 出自同一个版本，B 也没有机会根据这些结果改规则。

## 工具

`scripts/bugsinpy_case.py` 按 BugsInPy 的定义准备一个 bug：

- 取修复后的提交，再把 BugsInPy 的补丁（`bug_patch.txt`，只改源码）反向应用，得到"测试是新的、源码有 bug"的版本；
- 用 uv 建环境，装上项目和你指定的测试依赖；
- 跑 bug 对应的测试（来自 BugsInPy 的 `run_test.sh`），应该失败；
- 用 FixFirst 检查一次，然后重新打上补丁，模拟开发者修好了 bug；
- 再跑测试，应该通过；再用 FixFirst 检查一次。

结果写在 `<目标文件夹>/results/<项目>-<编号>.json`，两次测试的输出放在旁边。脚本开头的说明写了全部细节。

B 在写这个脚本时试过三个 bug，这里说明一下，免得你重复踩坑：

| Bug | 结果 |
|---|---|
| PySnooper 1 | 在 Python 3.9 / macOS 上**不复现**：有 bug 的版本测试也通过 |
| PySnooper 2 | 复现，需要 `--deps pytest python_toolbox six`。**B 看过 FixFirst 在它上面的结果**，所以正式结果里要标注"开发时见过"（dev），不能算独立结果 |
| PySnooper 3 | 修复提交已经不在上游仓库里了，用不了 |
| tqdm 2 | 复现，需要 `--deps pytest nose`。B 只跑了复现部分，没有运行 FixFirst，可以正常使用 |

## 阶段 1：挑选并复现

### 1. 选候选

打开 `examples/public-data/bugsinpy/bugs.csv`，只看 `tier` 为 `1: nothing to compile` 的 70 个 bug，分属 5 个项目：PySnooper、cookiecutter、tqdm、tornado、youtube-dl。

- 至少覆盖 **2 个项目**，3 个更好。
- youtube-dl 的完整测试会去下载网上的视频，FixFirst 的检查会跑完整测试，所以**不建议用 youtube-dl**。
- 每个 bug 的 `bugsinpy_folder` 列是 BugsInPy 网页上这个 bug 的文件夹链接。里面的 `run_test.sh` 写了要跑哪个测试，`bug_patch.txt` 是修复内容，可以先看一眼，判断 bug 大概是什么。

BugsInPy 原本用 Python 3.6–3.8，我们统一用 **Python 3.9**：FixFirst 支持的目标版本是 3.9–3.14，uv 在所有系统上都能装 3.9。这是和 BugsInPy 原始设置的偏差，报告里要写明。

### 2. 复现

在主仓库里运行（`--no-fixfirst` 表示只复现，不运行 FixFirst）：

```bash
.venv/bin/python scripts/bugsinpy_case.py tqdm 3 --target ~/bugsinpy-cases --deps pytest nose --no-fixfirst
```

Windows：

```powershell
.venv\Scripts\python scripts\bugsinpy_case.py tqdm 3 --target $HOME\bugsinpy-cases --deps pytest nose --no-fixfirst
```

最后一行会显示 `reproduced` 或 `not reproduced`。看两行 "tests exit with …"：

| 有 bug 时 | 修复后 | 说明 | 怎么办 |
|---|---|---|---|
| 1 | 0 | 复现成功 | 记下来，进入阶段 2 |
| 2 或 4 | — | 测试没能开始运行，多半缺测试依赖 | 打开 `results/<项目>-<编号>-buggy-test.txt`，找到 `No module named 'xxx'`，把 xxx 加进 `--deps`，重跑 |
| 0 | 0 | 在这个 Python 或系统上不复现 | 可以试 `--python 3.8`；还不行就放弃 |
| 1 | 1 | 修复后仍然失败，还有别的原因 | 看 `fixed-test.txt`；查不清就放弃 |
| 报错说提交不存在，或补丁打不上 | | 上游仓库改过历史 | 放弃 |

找测试依赖的地方：项目的 `tox.ini`、`requirements-dev.txt`、`setup.py` 里的 `tests_require`，或者 BugsInPy 文件夹里的 `requirements.txt`。不要把整个 requirements.txt 都装上，那是 2020 年的完整环境，很多在 Python 3.9 上装不了；只挑其中的测试工具。

老项目的 `setup.py` 在今天的 setuptools 下装不上时，加上 `--deps pytest "setuptools<70" wheel --no-build-isolation` 再试。

### 3. 记录每一次尝试

在主仓库里新建分支，把尝试记录写进 `examples/bugsinpy-verification/attempts.csv`：

```bash
git switch main && git pull && git switch -c a2-bugsinpy
mkdir -p examples/bugsinpy-verification
```

`attempts.csv` 的列如下，每次尝试一行，失败的也要记：

```text
bug,python,deps,result,note
tqdm-3,3.9,pytest nose,reproduced,
PySnooper-1,3.9,pytest python_toolbox,not reproduced,buggy version passes on Python 3.9 / macOS
```

阶段 1 的目标：至少 4 个复现成功的 bug，来自至少 2 个项目。PySnooper 2 如果算进去，要标注 dev。10/9 前在 A2 的 Issue 里报数，例如 "tqdm 2、3，cookiecutter 1，tornado 4 复现成功"。

## 阶段 2：用冻结版运行 FixFirst（10/10 以后）

### 4. 切到冻结版

B 会在 B5 的 Issue 里宣布 v0.7.0 已冻结，然后运行：

```bash
cd ~/FixFirst
git fetch --tags
git switch --detach v0.7.0
.venv/bin/python -m pip install -e .
git describe --tags              # 应该显示 v0.7.0
```

### 5. 逐个运行

用阶段 1 找到的参数，这次**不加** `--no-fixfirst`：

```bash
.venv/bin/python scripts/bugsinpy_case.py tqdm 2 --target ~/bugsinpy-cases --deps pytest nose
```

输出会多出三行：

- `FixFirst before`：修复前 FixFirst 的判断，以及它给的第一步；
- `environment advice`：它有没有给出安装、升级、锁定包之类的建议，应该是 none；
- `FixFirst after`：修复后的状态，以及这个 bug 对应的问题是否已关闭（`resolved`）。

想看界面的话，运行 `.venv/bin/fixfirst --store ~/bugsinpy-cases/.fixfirst serve`。

### 6. 整理结果

回到你的分支（`git switch a2-bugsinpy`），把 `~/bugsinpy-cases/results/` 里选中 bug 的 `.json`、`-buggy-test.txt`、`-fixed-test.txt`、`-bug_patch.txt` 复制到 `examples/bugsinpy-verification/results/`，然后写 `examples/bugsinpy-verification/README.md`，内容包括：

1. **做法**：用 BugsInPy 的哪一版（提交 `11c5f1e`），Python 3.9，怎么判定复现（修复前失败、修复后通过），用的 FixFirst 版本（v0.7.0），以及怎样重跑（命令）。
2. **结果表**：

   | Bug | 项目 | 复现 | FixFirst 修复前的第一步 | 环境类建议 | 修复前问题状态 | 修复后问题状态 | 备注 |
   |---|---|---|---|---|---|---|---|

   "修复前问题状态"应该是 open，"修复后问题状态"应该是 resolved；PySnooper 2 在备注里写 dev。
3. **和已有的 4 个上游回归缺陷合计**：一共多少个缺陷、多少个库，对照 proposal 的"至少 8 个、至少 4 个库"。
4. **发现的问题**，如实写。例如第一步把代码缺陷说成了别的原因，或者给了环境建议。**不要为了结果好看去改标签或重跑**；冻结后发现的问题写进报告的局限和后续工作。

提交前检查有没有本机路径：

```bash
grep -rn "/Users/\|C:\\\\Users" examples/bugsinpy-verification || echo "no local paths"
```

然后提交，开 PR，标题写 "A2: BugsInPy verification"，10/12 前交。

## 完成标准

- [ ] 至少 4 个 bug 复现成功，来自至少 2 个项目（PySnooper 2 如果使用，标注 dev）
- [ ] `attempts.csv` 记下了所有尝试，包括失败的
- [ ] 阶段 2 用的是 v0.7.0（`git describe --tags` 的输出写进 README）
- [ ] README 有做法、结果表、合计、发现的问题
- [ ] 没有本机路径；PR 已提交
