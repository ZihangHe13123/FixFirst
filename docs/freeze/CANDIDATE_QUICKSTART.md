# FixFirst 候选版快速开始（草稿）

状态：2026-10-01。本指南对应生产候选 **99c8086**；本地候选应用版本为 **0.7.0**。用户已确认 B5 计划版本为 **v0.7.0**，保留基于 **44 特征、43 场景、215 条记录**的已验内置模型，冻结时不重训；正式版本绑定和发布尚未完成。实际本地构建/安装状态以随包收据为准；尚未发布正式冻结包。

这是源码 ZIP 路线的简明操作说明。命令和按钮名称已按现有源码核对；macOS干净安装、CLI与Web HTTP入口已实际验证，见[本地交付记录](LOCAL_DELIVERY_20261001.md)。浏览器截图、Windows实测及独立新手按指南安装仍待完成。它不替代 [B14 正式指南](../tasks/B14-user-guide.md)：正式交付是英文 4–8 页图文指南及报告附录，10/19 初稿、10/22 定稿；最终 `SystemCode/` 路径调整仍待 B15。

## 1. 从源码 ZIP 安装和启动

准备 Python 3.10 或以上，将源码 ZIP 完整解压，在包含 `README.md`、`pyproject.toml` 和 `scripts/` 的目录打开终端。下面的路径是示例，请替换为实际位置。首次安装通常需要联网下载依赖。

**macOS / Linux：**

```bash
cd "/path/to/FixFirst"
bash scripts/setup.sh python3.12
.venv/bin/fixfirst serve
```

`python3.12` 可换成已安装且符合版本要求的 Python 命令或完整路径。安装脚本建立 FixFirst 自己的 `.venv`，并安装应用和开发工具。macOS 安装后也可使用 `start-fixfirst.command` 启动。

**Windows PowerShell：**

```powershell
Set-Location "C:\Path\To\FixFirst"
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
.venv\Scripts\fixfirst serve
```

安装后也可双击 `start-fixfirst.bat`。需明确选择用于安装 FixFirst 的 Python 时：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Python "C:\Path\To\Python\python.exe"
```

Windows 脚本会复用兼容的 `.venv`。要更换已有环境的 Python，可在上述命令后加 `-Recreate`；旧环境会先移到 `.venv-backup-*`。此时应选择旧 `.venv` 之外的 Python。

`serve` 启动本机 Web 界面并打开浏览器，默认使用 `127.0.0.1` 上的空闲端口。浏览器未自动打开时，使用终端显示的本机地址。使用过程中保留运行服务的终端；结束时可在终端按 Ctrl+C。

## 2. 选择待检查项目及其 Python

1. 在 **Project folder** 输入项目目录，或用 **Browse… → Use this folder** 选择。
2. 在 **Python interpreter** 核对项目自己的解释器；可用 **Auto-detect**，也可输入 venv 或 Conda 中 Python 的完整路径。例如 macOS/Linux 的 `/path/to/project/.venv/bin/python`，或 Windows 的 `C:\Path\To\Project\.venv\Scripts\python.exe`。
3. 保留 **Choose for this project** 以使用入口建议，或手动选择目标和入口。核对后点 **Check my project**。

FixFirst 的安装环境负责运行工具；这里选择的项目环境负责运行你的程序或测试。项目依赖应在后者中可用。自动发现只是静态建议，实际入口需要与你平时运行项目的方式一致。

| 项目情况 | 选择和填写 |
|---|---|
| 已有 pytest 测试 | 使用测试目标；目标环境需要 pytest 和项目依赖。只收集测试时可在 CLI 显式选 `collect_tests`。 |
| 纯 unittest 项目 | 选择 **Unittest discovery**，填写测试目录，如 `tests`；默认文件模式为 `test*.py`，使用标准库运行，不要求 pytest。 |
| 无测试，运行脚本 | 选择 **Python script**，填写项目内脚本，如 `main.py`。 |
| 无测试，运行模块 | 选择 **Python module (-m)**，填写模块名，如 `package.main`，不填 `.py` 路径。 |
| Notebook | 选择 **Notebook**，填写项目内文件，如 `assignment.ipynb`；先安装下述可选支持。 |

脚本和模块的 **Arguments** 每行一个参数。例如 `--data` 与 `data/input.csv` 分两行；不要填整条 `python ...` 命令。**Standard input** 填程序通过 `input()` 等读取的文本。运行工作目录是选中的项目目录。

Notebook 需将驱动安装到 FixFirst 环境，将 `ipykernel` 安装到所选项目环境。在源码目录中运行适合自己系统的命令：

```bash
# macOS / Linux；第二行路径替换为所选项目 Python
.venv/bin/python -m pip install -e '.[notebooks]'
"/path/to/project/.venv/bin/python" -m pip install ipykernel
```

```powershell
# Windows PowerShell；第二行路径替换为所选项目 Python
.venv\Scripts\python.exe -m pip install -e ".[notebooks]"
& "C:\Path\To\Project\.venv\Scripts\python.exe" -m pip install ipykernel
```

Notebook 使用新的内核按顺序执行单元格，保留原 notebook 文件。当前流程不适合交互式 notebook 输入、GUI 操作或持续运行的服务。

## 3. 阅读首步、执行修改、再次检查

先看 **Start here** 标记的第一步，再按 **Must fix / What to do** 的顺序处理。核对文件位置、解释和 **Details → How to confirm**。`Likely` 或 `Possible cause · not confirmed` 表示尚未证实的判断；若建议只有检查方向，应结合原始错误人工判断，不能当作已提供完整修法。

FixFirst 提供建议和可复制命令，由你修改代码或在项目环境执行安装命令。Windows 页面提供的是 PowerShell 命令。**Find it** 等按钮只在相应建议出现时使用：它需要联网，在临时环境尝试发行版本；之后仍需执行所给建议并重新检查。

修改后点 **Check again**。只有相同解释器、相应范围的一次完整真实检查通过，问题才会显示为 **Fixed and verified**。**Optional** 和 **Other findings that do not block this goal** 分开呈现，不代表当前目标被阻塞。

无测试项目不要求安装 pytest。**Program completed successfully** 只确认这次入口在保存的参数和输入下以退出码 0 完成；它不证明所有输入或业务答案正确。超时、取消或未完成不能算通过。

要改解释器、入口、参数或输入，展开 **Python and run settings**，点 **Save settings**，再点 **Check again**。已有结果仍对应原运行配置。

## 4. 测试基准变化时怎么处理

首次检查前，FixFirst 记录测试及影响测试选择、判定的设置。若之后显示 **The tests changed** 或 **The tests could not be verified**，即使最新运行通过，也不能据此确认原问题已修复。

- 如果变化并非本次有意修改，恢复原测试或相关设置，再检查。
- 如果你确实决定采用新测试或设置，检查变化内容后点 **Accept the changes as the new baseline**，确认后再次检查。此后的验证以新基准为准。

接受新基准是用户决定，不是修复代码的快捷步骤。脚本、模块和 notebook 的 `run_project` 目标没有测试基准；其验证范围由入口、参数、输入和解释器共同确定。

## 5. 保存、导出及重开会话

Web 在创建、检查和更改设置后自动保存会话；主页 **Recent projects** 可重开，工作页 **All projects** 返回列表。默认记录位于启动命令当前目录的 `.fixfirst/`，每个会话有自己的 `session.json`。以后从同一源码目录启动即可继续访问该目录里的记录；项目和目标解释器仍需可用。

需要固定记录位置时，在 `serve` 前指定全局 `--store`。例如在 macOS/Linux：

```bash
.venv/bin/fixfirst --store "/path/to/saved-sessions" serve
```

Windows PowerShell 使用：

```powershell
.venv\Scripts\fixfirst --store "C:\Path\To\SavedSessions" serve
```

之后重开也要使用同一 `--store`。环境变量 `FIXFIRST_STORE` 也可指定默认存储位置。

在工作页点 **Download a shareable report** 下载脱敏 HTML；分享前预览内容。它是可阅读的结果副本，继续原会话仍依赖本机保存记录及项目。**Technical details** 可查看证据图、规则和原始输出。

CLI 的常用子命令如下。将表中的 `fixfirst` 换成 macOS/Linux 的 `.venv/bin/fixfirst` 或 Windows 的 `.venv\Scripts\fixfirst`，并将 `SESSION_ID` 替换为实际会话 ID；使用自定义存储时同样在子命令前带上 `--store`。

| 命令 | 用途 |
|---|---|
| `fixfirst list` | 列出已有会话及 ID。 |
| `fixfirst show SESSION_ID` | 查看该会话当前结果和下一步。 |
| `fixfirst scan SESSION_ID` | 按保存的目标和入口重新检查。 |
| `fixfirst report SESSION_ID --open` | 生成本机会话 HTML/JSON 报告并打开 HTML。 |
| `fixfirst export SESSION_ID --output shared.html` | 导出脱敏 HTML，同时在旁边生成 JSON；先预览再分享。 |

CLI 也可创建会话。例如 macOS/Linux 中，创建脚本入口后需再执行输出提示中的 `scan` 命令；`init` 本身不运行项目：

```bash
.venv/bin/fixfirst init "/path/to/project" --python "/path/to/project/.venv/bin/python" --script main.py
```

其他入口参数为 `--module package.main`、`--notebook assignment.ipynb`、`--unittest-dir tests`；pytest 目标可用 `--goal pass_tests`。程序参数可重复写 `--arg`，以 `--` 开头的值写成 `--arg=--data`；`--stdin-file answers.txt` 读取 UTF-8 标准输入文件。

## 6. 候选版边界与待补交付

检查会执行所选项目的代码，使用你信任的项目。诊断的准确性取决于当前证据、已有规则和知识；决策树给出的推测需要核对。某些参数契约可支持精确建议，缺失业务值、成员语义或用途时仍可能只给检查方向；不能由一次通过推断普遍修复能力。

本候选没有宣称完成新的独立任务验收、真实用户研究或当前候选的 Windows 真人安装验收。B5 已确认沿用上述已验内置模型，冻结不重训；计划版本为 v0.7.0，最终源码、模型与版本的绑定及发布仍待完成。B6 计划在冻结后对 44 个场景进行按场景留出评估；此评估尚未在本次指南更新中执行。

正式 B14 还需补齐安装、首步、Details、复查、基准变化、导出和重开的截图；由未参与编写的人分别在 macOS/Windows 按指南安装并记录结果；在 B15 后统一最终目录路径，再形成英文图文指南和报告附录。本草稿不提前勾选这些完成项。

静态核对来源：[README](../../README.md)、[macOS/Linux 安装脚本](../../scripts/setup.sh)、[Windows 安装脚本](../../scripts/setup.ps1)、[CLI](../../src/fixfirst/cli.py)、[Web](../../src/fixfirst/web.py)、[会话页面](../../src/fixfirst/templates/workspace.html)、[测试基准逻辑](../../src/fixfirst/integrity.py)。
