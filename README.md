# FixFirst

帮助 Python 开发者把一堆报错整理成问题清单，判断下一步先检查什么，修改后再验证是否解决。

首版已具备实际检查、日志导入、问题归并、行动排序、状态更新和 HTML 报告。交互入口是终端菜单，报告可在浏览器离线打开。支持 macOS / Linux 的 Python 3.10+；已在 macOS Apple Silicon、Python 3.12 上验收，Windows 原生运行尚未支持。

## 在这台电脑上开始

双击项目根目录的 **`启动FixFirst.command`**，选择：

1. **体验完整演示**：自动创建一个小项目，实际运行“正常 → 缺少模块并出现格式问题 → 只修格式 → 恢复模块”四个阶段，最后打开报告。
2. **开始排查自己的项目**：输入项目目录与该项目使用的 Python 解释器路径。
3. **继续已有排查**：重跑检查、导入日志、查看报告、切换目标或导出结果。

本机 `.venv` 已安装好。也可以在本目录运行：

```bash
.venv/bin/fixfirst interactive
```

不运行程序也能查看随源码附带的 [故障阶段报告](examples/demo/01-failure.html)、[部分检查报告](examples/demo/02-partial-check.html) 和 [恢复后报告](examples/demo/03-restored.html)。这些是实际运行后保存的只读记录。

## 小王会怎样使用它

小王接手一个 Python 项目，测试和代码检查都在报错。他选择“恢复测试收集”，运行一次检查。FixFirst 把多个测试文件里重复出现的同一模块导入失败合并展示，同时保留风格问题，优先提示与当前目标有关的检查和处理。

小王先改了格式，只重跑代码检查。报告会确认风格问题已经解决，但导入问题仍保留。修复导入路径或依赖后，他重跑测试收集；只有对应检查真的完成并通过，系统才标记已验证解决。

| Pain Point | Feature | 当前实现 |
|---|---|---|
| 报错太多、同一问题反复出现 | 归并相似问题，保留每条原始证据 | 结构约束 + TF-IDF；可选 SBERT |
| 不知道下一步从哪里查起 | 围绕当前目标排序行动，并解释依据 | 前向推理 + 前置条件 + 稳定优先级排序 |
| 相同异常可能有不同原因 | 区分观察事实、推导结论与候选类别 | 规则分类；可选 Gini 决策树预测 |
| 改完不确定是否真正解决 | 对相同环境、范围的完整检查进行前后对比 | 已解决、仍存在、待验证、本次未检查等状态 |
| 队友难以了解排查过程 | 展示历史、原始证据和行动清单 | HTML / JSON 报告与脱敏导出 |

## 支持的输入和目标

| 输入 | 自动运行 | 历史日志导入 |
|---|---|---|
| Python 解释器、安装包及版本快照 | 支持 | 不支持 |
| `pip check` 依赖一致性检查 | 支持 | 支持文本 |
| `pip install` 安装失败 | 不自动安装 | 支持部分常见冲突、缺包、网络错误文本 |
| pytest 测试收集 | 支持，附带结构化采集插件 | 支持常见 traceback；信息不足时保留未知 |
| Ruff 代码检查 | 支持 JSON 输出 | 支持 Ruff JSON 数组 |

两个目标分别是 **恢复测试收集**、**通过代码检查**。测试收集成功表示能发现测试，不表示测试执行全部通过。代码检查采用目标项目的 Ruff 配置，不代表所有潜在代码缺陷都消失。

外部库纳入环境与依赖检查，但不会把任意 `ImportError` 都认定为“需要安装包”。项目本地模块、导入名与发行包名差异，都可能需要进一步核查。未知报错仍保留原文。

## 给队友安装

解压源码，在项目目录执行以下命令，把 `python3.12` 换成已有的 Python 3.10+ 路径：

```bash
bash scripts/setup.sh python3.12
.venv/bin/fixfirst interactive
```

首次安装需要网络；默认规则、TF-IDF、检查和报告不调用云端模型。源码包不包含本机虚拟环境或模型权重。`docs/environment.json` 与 `docs/environment-freeze.txt` 记录了本次实际验收环境，并非所有系统都必须安装全部可选依赖。

**FixFirst 自己的环境与被检查项目的环境是分开的。** 排查自己的项目时，要选该项目实际使用的解释器。需要运行的 pytest、Ruff、pip 应在目标环境中可用；缺少工具会作为问题展示。程序不会自动安装目标项目依赖。测试收集会执行项目导入和 `conftest.py`，应对自己信任的项目使用。

## 命令行用法

先激活 FixFirst 环境。以下 `SESSION_ID`、`ISSUE_ID` 和项目路径需要替换成自己的值：

```bash
source .venv/bin/activate

# 创建记录时不会运行项目
fixfirst init /path/to/project --python /path/to/project/.venv/bin/python

# 运行全部检查，或只验证测试收集
fixfirst scan SESSION_ID
fixfirst scan SESSION_ID --checks pytest
fixfirst show SESSION_ID
fixfirst report SESSION_ID --open

# 导入日志；没有可靠退出码时不必填写 --exit-code
fixfirst import SESSION_ID --tool pip_install --file /path/to/install.log

# 自己修改后声明待验证，再运行相关检查
fixfirst mark-fixed SESSION_ID ISSUE_ID
fixfirst scan SESSION_ID --checks pytest

# 切换目标，分享，暂停与继续
fixfirst configure SESSION_ID --goal check_style
fixfirst export SESSION_ID --output workbench/shared.html
fixfirst stop SESSION_ID
fixfirst resume SESSION_ID
```

默认记录保存在当前工作目录的 `.fixfirst/`。从不同目录调用时，用全局参数 `fixfirst --store /absolute/path/to/.fixfirst ...` 指向同一记录目录。报告内可复制的检查命令已经包含完整路径。分享版会隐藏可执行命令、替换常见个人路径及凭据；自定义日志内容仍需自行预览。

`run SESSION_ID ACTION_ID` 只执行清单中的预定义检查。手动修复行动是说明，不会被当作 shell 命令运行。

## 数据从创建到使用

数据集由程序生成一个健康小项目，真实运行基线检查，然后注入已知故障、再次检查、保存输入与独立标签、恢复故障并验证恢复。标签来自预设故障类型，不取自模型预测。

```bash
# 目录必须是新的，避免覆盖已有实验
.venv/bin/fixfirst dataset --output workbench/my-dataset
.venv/bin/fixfirst evaluate workbench/my-dataset --output workbench/my-evaluation
```

每个案例目录的 `baseline.json` 是正常记录，`input.json` 是故障输入，`truth.json` 是预设标签，`restored.json` 是恢复后的记录。`manifest.json` 记录来源、哈希和成功状态；`labeled_issues.json` 用于训练与分类评测。依赖故障通过专用临时虚拟环境内的自建包元数据制造，不改用户环境。

随源码附带的 `examples/dataset/` 有 **30 个受控案例、35 条问题级标签、360 次检查记录**。已移除本机临时虚拟环境并替换常见个人路径，原始本地记录在 `workbench/dataset-v2/`。附带数据可以直接重新评价；要重新执行故障，请使用上面的 `dataset` 命令在自己的机器上重建。

这里的 5 个“项目”来自相近模板，不能当作 5 个独立真实项目。训练使用模板项目 1–3，验证使用 4，测试使用 5。当前测试集只有 7 条问题，规则与决策树 Macro F1 均为 1.0；精确匹配、TF-IDF、SBERT 的归并结果也相同。**目前没有证据说明复杂模型优于简单基线。** 详见 [实验记录](examples/evaluation/REPORT.md)。

## 启用课程中的模型方法

三条技术路线均有可运行代码：文本向量与相似度归并、Gini 决策树、前向推理。默认产品走 TF-IDF + 规则 + 前向推理，训练后的决策树可以作为候选输出接入，SBERT 可以替换归并向量。

```bash
.venv/bin/python -m pip install -e '.[semantic]'
.venv/bin/python scripts/download_model.py --output workbench/models/minilm
.venv/bin/fixfirst evaluate examples/dataset --output workbench/my-semantic-evaluation --sbert-model workbench/models/minilm

.venv/bin/fixfirst init /path/to/project --python /path/to/project/.venv/bin/python --grouping sbert --sbert-model workbench/models/minilm --model workbench/my-semantic-evaluation/decision_tree.json
```

下载脚本使用公开模型 `sentence-transformers/all-MiniLM-L6-v2`，记录下载时的仓库提交号。分组运行只加载指定的本地目录。当前下载的版本记录见 `examples/evaluation/sbert-model-source.json`。

## 实现与分工

| 建议负责人 | 可独立接手的文件 | 交付与验收 |
|---|---|---|
| A：数据与检查 | `runner.py`、`probe.py`、`parsers.py`、`cases.py` | 扩充真实项目与错误格式；保留来源、基线、故障、恢复证据 |
| B：算法与实验 | `grouping.py`、`classification.py`、`reasoning.py`、`evaluation.py` | 增加困难样本；比较误归并、分类与行动排序效果；检验模型增益 |
| C：产品与整合 | `cli.py`、`interactive.py`、`service.py`、`report.py`、模板 | 组织用户试用；改进流程与文案；验证重跑状态和分享报告 |

共享接口在 `models.py`，存储在 `storage.py`。完整实现流程见 [模块与数据流](docs/FLOW.md)，当前交付证据与限制见 [验收说明](docs/DELIVERY.md)。

```bash
.venv/bin/ruff check src tests scripts
.venv/bin/pytest -q
.venv/bin/python -m build
```

当前还需小组补充不同结构的自然故障、真实用户操作对比和课程最终报告。受控案例已证明流程能运行，尚不能证明真实用户节省多少调试时间。
