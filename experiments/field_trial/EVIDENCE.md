# 第六轮证据索引：真实项目试用、验收用例与交叉复核（Claude）

这是开发阶段的证据，不是独立留出，也不是人工金标准。A1/C1 的私有数据、BugsInPy、冻结和正式实验都没有参与。

新批次复测用最终生产提交 `5d661e6` 的前 8 位十六进制作种子（1566973541），规则见 `RETEST.md`。它的抽样、逐步日志和结果在第二个证据提交里：`results/retest-5d661e6/`，结果摘要追加在 `RETEST.md` 末尾。第一个证据提交里不包含这些内容。

## 提交方式

- 本目录分四个证据提交：第一个的父提交是 `365aa84`，包含旧证据；第二个紧接其后，只加入新批次复测；第三个加入第一批配对回归、补充轨迹和审核说明；第四个加入第七轮验收脚本、`5d661e6` 基线和对候选 `9b74c2a` 的窄复核。
- 这个提交只新增 `experiments/field_trial/`，不改任何生产代码或测试，可以直接 cherry-pick 到 `5d661e6` 或 PR 分支上。
- 下文的提交号都在 Claude 的工作分支 `claude/field-trial-20260930` 上。四个证据提交里的本目录分别与该分支 `72e8ce4`、`e572f37`、`868febd`、`a3af186` 中的同名目录完全相同，都只多了这份索引。

## 时间线（先提交预期，再运行）

| 提交 | 内容 |
|---|---|
| `d5e842a` | 试用规则和带种子的抽样（`README.md` 前半部分、`sample.py`），在运行任何项目之前写好 |
| `af819c0`、`7ff4bc8` | 修正抽样路径；确定选中的项目和人工排除项（`selection.json`）；加入逐步记录器 `trial.py` |
| `2083f1d`、`9e2f814` | 第一批中期结果和逐步日志。N3 记为 U（下载未完成）；日志里一条错误记录后面追加了两次更正 |
| `0cd70c9` | `RETEST.md` 和 `sample_retest.py`：复测规则，在 Codex 给出最终生产提交之前写好 |
| `73504d6` | `acceptance.py` 初版，写好了 A–G 的预期 |
| `c516787`、`6264397`、`39ef4ba` | 验收修订，每次都在运行对应的修复版本之前提交：A 改为 A2，D2 改为 D2b，新增 B2，修正 D1 的判定。原用例和原判定都保留 |
| `9c93518` | `9db099d` 的交叉验收 |
| `dbc3733` | `b344455` 的复核和人工照做 |
| `44419ec` | `d8b1c0a` 的窄复核和 docopt 探针；N3 附录关闭 |
| `542621d` | `365aa84` 的窄复核：A2、C、D2b 的验收和照做；真实 uv 输出探针；旧包（orphan）探针 |
| `b124247` | 在 14 个真实 uv 输出上核对 `5d661e6` 的匹配；确定它为复测用的生产 SHA |
| `72e8ce4` | 补做脱敏：`N3.jsonl` 里残留一段左侧被截断的本机路径，已替换为 `<field>` |
| `e572f37` | 用 `5d661e6` 做新批次复测：抽样（含人工排除）、9 个任务的逐步日志和结果（追加在 `RETEST.md` 末尾） |
| `603f65f`、`539adde`、`09e74cf`、`a3af186` | 第七轮：先登记验收（12 个用例，逐字照做），在任何第七轮提交之前提交；`5d661e6` 基线；对候选 `9b74c2a` 的窄复核（C1 严格照做、旧 A2/C/D2b、重点探针） |
| `868febd` | 第一批开发回归：在 `5d661e6` 上配对重跑 8 个任务，严格还原初始状态；N3 未重跑，保留 U。另有导入安装日志的补充轨迹（不配对），以及 R-N1/R-N3 和新批次安装预处理的审核说明（都追加在 `RETEST.md` 末尾） |

## 文件

- `README.md`：试用规则、第一批结果和分类、验收修订记录、第六轮后续复核的摘要。
- `sample.py`、`selection.json`、`trial.py`：第一批的抽样、人工排除和逐步记录器。
- `RETEST.md`、`sample_retest.py`：新批次复测的规则，事先登记。
- `acceptance.py`：验收用例。有效用例是 A2、B2、C、D1、D2b、E、F、G；A、B、D2 作为记录保留。
- `probes/`：真实 uv 输出的采集脚本 `capture_wheel_messages.py`，以及两个复核用的探针 `test_wheel_messages.py`、`test_orphans.py`。探针走生产代码 `collect()` 和 `advise()`，并复用被测版本自带的测试夹具。
- `results/` 下：
  - `N1…C3.jsonl`：第一批的逐步日志；
  - `repos.txt`、`sample.json`：抽样时各仓库的 commit 和全部候选；
  - `baseline*-0eb87e5.json`：修复前的基线；
  - `round6-9db099d/`、`round6-b344455/`、`round6-d8b1c0a/`、`round6-365aa84/`：各阶段提交的自动验收、`manual.json`（先跑试验、再严格照做）和探针；
  - `round6-5d661e6/`：对最终匹配的核对；
  - `retest-5d661e6/`：新批次复测，包括 `draw.json`（全部候选和抽样顺序）、`selection.json`（人工排除和最终 9 个任务）、`repos.txt`、`R-*.jsonl` 和 `summary.json`；
  - `round7-acceptance/`：第七轮验收的基线与 `9b74c2a` 结果、C1 严格照做日志、探针记录；脚本是上一级目录的 `acceptance_r7.py`；
  - `regress-5d661e6/`：第一批配对回归，包括逐步日志、`initial-state.json`（初始状态怎样还原，以及确切版本）、`summary.json`（逐项前后对照和指标）；补充轨迹放在 `supplementary/`，不计入配对指标。

## 自动验收

REVIEW 不计为 PASS。

| 构建 | A2 | B2 | C | D1 | D2b | E | F | G |
|---|---|---|---|---|---|---|---|---|
| `0eb87e5`（修复前） | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL |
| `9db099d` | REVIEW | PASS | REVIEW | PASS | REVIEW | PASS | PASS | PASS |
| `b344455` | REVIEW | PASS | REVIEW | PASS | REVIEW | PASS | PASS | PASS |
| `d8b1c0a` | REVIEW | PASS | REVIEW | PASS | REVIEW | PASS | PASS | PASS |
| `365aa84` | REVIEW | — | REVIEW | — | REVIEW | — | — | — |

- `0eb87e5` 这一行来自几个基线文件：`baseline2`（C、E、F、G）、`baseline3`（A2，以及用修正后判定重跑的 D1）、`baseline4`（D2b）和 `baseline5`（B2）。
- `9db099d` 的 B2 来自 `acceptance-b2.json`；同一构建上原来的 B 判为 FAIL，那是 B 判定本身的错误。
- `365aa84` 的改动只影响依赖试验，所以只重跑了 A2、C 和 D2b。
- `5d661e6` 只改了一处文字匹配，没有重跑验收，只在 14 个真实输出上做了核对（见下文）。

## 人工照做（先跑试验，再严格照做）

| 构建 | A2 | D2b | C |
|---|---|---|---|
| `9db099d` | 操作者自己决定新的固定版本后才跑通：部分需解释 | 同 A2：部分需解释 | 只照步骤无法继续 |
| `b344455` | 试验给出准确的修改和安装命令。照做后 pip check 为 0，测试通过；两步都完全可执行，操作者没有做任何选择 | 同 A2 | 只照步骤无法继续；标题把原因说成解释器或迁移问题 |
| `d8b1c0a` | 同上，没有回退 | 同上，没有回退 | 标题改为试验停在只有源码包的 `django-cors-middleware==1.3.1`；仍无法继续 |
| `365aa84` | 同上，没有回退；解出的依赖集合现在保留已安装的 python-editor 和 python-dateutil | 同上，没有回退 | 与 `d8b1c0a` 相同 |

## 复核探针

**真实 uv 输出**：共 14 个。这些依赖组合是手工挑选的，用来覆盖不同的 uv 报错格式，不是抽样，所以不代表任何比率。

| 构建 | 包名正确 | 只剩版本号 | 没有识别出来 |
|---|---|---|---|
| `d8b1c0a` | 8 | 4 | 2（"has no usable wheels" 中间折行） |
| `27afb06`、`365aa84` | 10 | 4 | 0 |
| `5d661e6` | 14 | 0 | 0 |

- "只剩版本号"的 4 个都是 uv 把阻塞包写成版本范围的情况，例如 `docopt>=0.6.0`，标题就成了 "stopped at 0.6.0"。
- 在 `5d661e6` 上，coveralls 那条的标题只写了 uv 列出的两段 coverage 范围中的第二段。这个说法属实，但不完整。

**旧包探针**（离线 wheel 加真实 uv）：

| 情形 | `27afb06` | `365aa84` |
|---|---|---|
| Codex 的反例：旧包要求 helper<2，升级后需要 helper>=2 | resolved（误判） | not_resolved（正确） |
| 无害的旧包：不依赖任何包，且有 wheel | resolved | resolved，但会把这个已不再需要的旧包一起升级到最新版 |
| 无害的旧包：只有源码包 | resolved | 试验停在这个旧包（措辞如实，但覆盖面变小了） |

## 已知限制（只作记录，不改变判定）

- 已安装、但不在依赖图里的包仍然固定为原版本。升级后如果新版本需要它的更高版本，试验就会失败，不会给出错误的通过。
- 从 `365aa84` 开始，升级后不再被需要的旧包，如果只有源码包，会让只用 wheel 的试验停下；如果有 wheel，会被一起升级到最新版。

## 脱敏与排除

- 本机路径都已替换为 `<scratch>`、`<home>`、`<tmp>`。
- 不包含任何虚拟环境、项目克隆、N3 下载的 84 MB 数据集，也不包含私有数据。
- N3 截止后补跑的附录只作为记录，不计入任何比率。

## 复现

需要 uv，以及能访问 PyPI 和 GitHub 的网络。

自动验收：

```bash
python experiments/field_trial/acceptance.py --out /new/folder --fixfirst <build venv>/bin/fixfirst --tag <tag> --only A2 C D2b
```

REVIEW 用例的人工照做：先运行 `fixfirst run SESSION ACTION`，再照它返回的修改和命令执行（见各 `manual.json` 的 `rule`）。

探针要用被测构建的测试夹具：

```bash
cd experiments/field_trial && FF_TESTS=<checkout>/tests FF_REAL=results/round6-365aa84/probe-wheel-messages.json FF_OUT=out.jsonl <build venv>/bin/python -m pytest -q -p no:cacheprovider probes/test_wheel_messages.py
```

```bash
cd experiments/field_trial && FF_TESTS=<checkout>/tests FF_OUT=out.jsonl <build venv>/bin/python -m pytest -q -p no:cacheprovider probes/test_orphans.py
```
