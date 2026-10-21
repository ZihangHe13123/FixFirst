# A2 报告素材（第 6 步写 README / 报告时用）

按记录时间倒序。每条都标了**范围**——样本只有 12 个项目，不要写成普遍结论。

## 1. F01（无规则命中的统计猜测）与具名规则的结果落差

来源：`scores-A.csv` 的 `fixfirst_rules` 列 × `score` 列。

| 规则 | 项目数 | correct | partial | generic | wrong |
|---|---|---|---|---|---|
| F01（没有规则命中，决策树猜测） | 4 | 0 | 0 | 3 | 1 |
| 具名规则（D13×2、D20、D21、D40） | 5 | 3 | 1 | 1 | 0 |
| 无规则、也无 cause 输出 | 2 | 0 | 0 | 2 | 0 |
| healthy（不需要规则） | 1 | 1 | 0 | 0 | 0 |

**在这个 12 个项目的留出集里**，4 个 correct 全部来自具名规则或 healthy；4 个 F01 全部落在
generic/wrong，一个 correct 也没有。F01 的定义见 `src/fixfirst/knowledge/rules.toml:626`：
"No diagnosis rule matched; the decision tree trained on labelled cases suggests a likely cause."

**范围**：F01 只有 4 个样本。只能写"在这批 12 个项目里"，**不能**写成"F01 普遍比规则差"，
也不能据此说决策树没用——它到底是 0/4，还是 1/4，这批数据分不出来。

## 2. FixFirst 的 `--only-binary=:all:` 安装策略会让"需要源码构建"的依赖必然装不上

来源：`twins/dateparser.a2-first-step.txt`（twin 实测）。

- FixFirst 给出的第一步命令是 `pip install --only-binary=:all: fasttext`，在本机直接失败：
  `No matching distribution found`，pip 日志里 sdist 被 `Skipping link: No sources permitted
  for fasttext: .../fasttext-0.9.3.tar.gz` 丢弃（fasttext 只有 macOS cp27 的 wheel）。
- 这个 flag 不是环境逼的，是 **FixFirst 自己的策略**：硬编码在
  `dependency_advice.py:107,176`、`dependency_resolution.py:181,277,285`、`versions.py:146`。
- 去掉 flag 后 pip 会去构建 sdist，说明这个 flag 就是成败的分界。

**范围**：实测只有 dateparser 一例。但 flag 是全局策略，所以凡是"目标是缺失依赖、且该依赖
没有 wheel 只有 sdist"的项目都会这样——写的时候说清是"由代码位置推出的适用范围 + 一例实测"。

日期相关的措辞可以用：

> FixFirst identified fasttext as the missing dependency, but the first step it offered was not
> executable in the evaluated environment: its remediation command sets `--only-binary=:all:`,
> which discards the only distributable artifact fasttext publishes for this platform (a source
> distribution; no Windows/cp312 wheel exists). The command fails with "No matching distribution
> found" and the collection errors are unchanged, so the step was scored partial rather than
> correct.

## 3. labels.csv 的 dateparser 行：结论对，理由要更正

`checked_by_trying` 写的是 "uv pip install fasttext fails with 'error: Microsoft Visual C++
14.0 or greater is required' … the intervention itself cannot be executed here"。

2026-10-02 的 twin 实测：本机**装有** VS 2022 Build Tools（14.44.35207），pip 能调用其中的
cl.exe；失败的真正原因是 fasttext 0.9.2/0.9.3 自带的 pybind11 与这个编译器不兼容
（C2672: no matching overload for pybind11::init），不是"没有编译器"。BuildTools 目录创建于
2026-09-30 20:37–20:38，而 `twins/dateparser.txt` 写于 20:47，且那次用的是 `uv pip install`
（uv 的构建前端报的是另一条错）。

**结论不变**（fasttext 这一层在本环境确实无法闭合），只是理由要更正。
按卡片第 21 行：**不改 `labels.csv`**，写进报告 corrections 一节（写法见
`examples/real-world/LABELS.md`）。`first_step` 里的 "or another compatible installation
path" 仍然覆盖实际情况，文本本身不必动。
