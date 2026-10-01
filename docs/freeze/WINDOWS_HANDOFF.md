# 候选版 Windows 交接：99c8086

**状态：操作说明已准备；以下 Windows 执行、截图与签收全部待 C 完成。**
诊断实现基准为 `99c8086a2fb5445d05e3e7a9fb6e1ace8b2e9681`；实际完整源码SHA见随ZIP的`.receipt.json`，包内候选版本为0.7.0。
这是本地候选交接，不表示B5正式冻结、发布或用户研究已获准开始。
B5政策已确认：冻结时保留当前44特征、43场景/215条训练记录的默认模型，不重训。
默认模型SHA-256为`4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3`。
计划版本为v0.7.0，本地候选元数据已为0.7.0。固定d7ca505源码ZIP和Mac干净安装已完成，见[本地交付记录](LOCAL_DELIVERY_20261001.md)；正式源码采用、发布及真实Windows验收待办。
B6在冻结后另做44场景的按场景留出评估，不替换出厂模型。本交接不改版本、模型或B5任务卡。

已确认的历史记录只有该候选的 **macOS主套776 passed / 1 skipped**、
**Mac实际进程harness 58 passed**，见[第十一轮记录](../../experiments/core_diagnosis/ROUND11.md)。
Windows必须填写自己的实际结果，不能照抄这些数量。

## 1. 接收源码ZIP与准备记录

使用交付方附有实际源码SHA及模型摘要收据的候选源码ZIP，记录ZIP名称、SHA-256及交付方提供的
源码清单/收据；不要以目录名或0.6.1版本字符串代替候选身份。此路径不需要wheel、
sdist或离线镜像。首次安装及B8任务准备需要联网获取依赖。

将ZIP解压到新的中文及空格路径，例如 `C:\FixFirst 验收\候选99c8086`。
以下命令在**包含 `pyproject.toml`、`scripts` 和 `start-fixfirst.bat` 的目录**执行。
本候选尚未做B15目录搬迁。

在PowerShell中记录机器、解释器及ZIP摘要，路径按本机实际填写：

```powershell
Get-FileHash -LiteralPath 'C:\Downloads\候选源码.zip' -Algorithm SHA256
$PSVersionTable.PSVersion
$CandidateRoot = 'C:\FixFirst 验收\候选99c8086'
$HostPython = 'C:\Path\to\Python312\python.exe'
Set-Location -LiteralPath $CandidateRoot
& $HostPython -c "import sys, platform; print(sys.version); print(sys.executable); print(platform.platform())"
```

建议本次选择现有Python 3.12。FixFirst安装最低要求3.10，**B8任务准备要求3.12或更新**。
将[空白收据](ACCEPTANCE_RECEIPT_TEMPLATE.md)另存到本机记录目录；日志与截图名称按收据填写。

## 2. 安装与自动检查

使用仓库现有[setup.ps1](../../scripts/setup.ps1)：

```powershell
powershell -NoProfile -File .\scripts\setup.ps1 -Python $HostPython
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable); print(sys.version)"
.\.venv\Scripts\python.exe -m fixfirst --help
```

脚本在源码目录创建`.venv`并安装`.[dev]`，可复用兼容的现有环境。
若需要更换环境，应指定`.venv`以外的Python并加`-Recreate`；脚本会保留旧环境为
`.venv-backup-*`。本交接不设置ExecutionPolicy、不提权、不更改系统编码或权限；
若现有策略阻止脚本，记录原报错与阻断状态，由负责人另行处理。

保存安装与help完整输出及退出码。收到具备tests及全部公开开发fixture的同提交开发工作区时，另执行下列回归并保存完整结果；当前安装白名单包没有全量开发fixture时，W03/W04记NOT COVERED，不运行空测试集或宣称通过：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts experiments
```

Windows跳过项、失败项及数量按实际记录。
若按[既有计时测试说明](../WINDOWS_TEAM_TEST.md)重跑个别计时用例，同时保留首次结果和重跑结果。
macOS/Linux的源码安装入口仍为`bash scripts/setup.sh python3.12`；本交接不要求重新执行该平台验收。

## 3. 界面、路径、复制命令与持久化

1. 双击`start-fixfirst.bat`。若浏览器未自动打开，使用启动窗口显示的本地地址。
   截图保存安装完成、首页和候选所用解释器。
2. 打开样例项目：Check → 按生成目录的`FIXES.md`修改 → Check again。
   保存修改前后截图；只有实际检查达到目标时才记录“All tests pass”。
3. 在验收用项目副本中检查中文及空格路径，确认界面选用的是**项目自己的Python**。
   记录项目目录、目标解释器与实际检查结果。
4. 如界面给出安装命令，将它**原样复制到PowerShell**，只在验收项目副本/目标环境运行。
   记录完整命令、目标解释器、退出码，并再次检查。没有出现该类建议就记“未覆盖”，不能记通过。
5. 使用页面的 **Download a shareable report** 导出，打开后核对中文、诊断文字、项目路径及用户名脱敏。
   保存导出文件与截图；记录是否出现应替换为`<home>`的用户名残留。
6. 正常退出并从同一源码目录重开。核对原会话、检查记录和目标Python仍在；
   持久化成功不能代替再次运行后的问题验证。

## 4. 结束进程与检查清理

在可信验收项目副本中启动一次足够观察的耗时检查。通过任务管理器“详细信息”及命令行路径，
记录**本次服务和其检查子进程的PID**。

- 第一遍在启动窗口按Ctrl+C；记录服务退出后检查子进程是否结束、有无旧检查继续运行。
- 重新启动后再做一遍，直接关闭启动控制台窗口；记录相同项目。
- 如有残留，记失败并保留PID、路径和时间。不要使用“结束全部python进程”等批量命令。

可在另一个PowerShell窗口只查询已经记录的PID；将示例号码替换为本次实际号码：

```powershell
Get-Process -Id 12345,12346 -ErrorAction SilentlyContinue
```

没有查到这些进程且观察不到本次检查继续执行，才填写相应步骤通过；截图和实际结果待C提供。

## 5. B8任务终端与判分预检

本节依据[C3第一部分](../tasks/C3-windows-check.md)和[B8说明](../../experiments/user_study/README.md)。
这是工程验收，不招募参与者、不产生用户研究成绩。参考答案自检的通过不能计为产品修复收益。
只在本次新建的任务副本执行以下操作。

```powershell
$StudyRoot = 'C:\FixFirst 验收\研究任务'
.\.venv\Scripts\python.exe experiments\user_study\prepare.py $StudyRoot --self-test
.\.venv\Scripts\python.exe experiments\user_study\prepare.py $StudyRoot
foreach ($task in 'T1','T2','T3','T4') {
    .\.venv\Scripts\python.exe experiments\user_study\grade.py $StudyRoot $task
}
```

预期自检显示4行`as expected`及`Self-test passed`；自检后必须重建。
新建任务的四次原始判分都应为FAIL，这是故障任务的预期结果。

在一个**仅用于本次验收的新PowerShell窗口**里设置临时探针变量，再打开T3子终端：

```powershell
$env:PYTHONPATH = 'src'
$env:PYTEST_ADDOPTS = '-o pythonpath=src'
.\.venv\Scripts\python.exe experiments\user_study\open_task.py $StudyRoot T3
```

在子终端中执行：

```powershell
python -c "import sys, os; print(sys.executable); print(os.environ.get('PYTHONPATH'), os.environ.get('PYTEST_ADDOPTS'))"
python -m pytest -q
exit
```

预期解释器在`研究任务\T3-versions\.venv\Scripts\python.exe`，变量显示`None None`，
原始pytest报告缺少`distutils`。`open_task.py`实际使用不加载用户配置的子PowerShell，
绑定任务解释器且无需执行激活脚本。

回到仍有探针变量的父窗口，给未修复T2判分，仍应为FAIL；随后清除本窗口的探针变量：

```powershell
.\.venv\Scripts\python.exe experiments\user_study\grade.py $StudyRoot T2
Remove-Item Env:PYTHONPATH,Env:PYTEST_ADDOPTS
.\.venv\Scripts\python.exe experiments\user_study\open_task.py $StudyRoot T2
```

在T2子终端执行`python -m pip install -e .`，然后`exit`。
在父终端再次给T2判分，预期为PASS且5项测试通过。

最后按C3验证测试完整性：只修改这些可重建的验收副本，完成后恢复全部任务。

```powershell
Add-Content -LiteralPath (Join-Path $StudyRoot 'T1-report\tests\test_render.py') -Value '# changed'
.\.venv\Scripts\python.exe experiments\user_study\grade.py $StudyRoot T1
.\.venv\Scripts\python.exe experiments\user_study\prepare.py $StudyRoot --only T1
Set-Content -LiteralPath (Join-Path $StudyRoot 'T4-booking\conftest.py') -Value "import pytest`ndef pytest_collection_modifyitems(items):`n    for item in items:`n        item.add_marker(pytest.mark.skip)"
.\.venv\Scripts\python.exe experiments\user_study\grade.py $StudyRoot T4
.\.venv\Scripts\python.exe experiments\user_study\prepare.py $StudyRoot
```

预期第一次因测试文件变化判FAIL，第二次因跳过测试判FAIL。
实际判分还要求测试数量完整：T1/T3/T4各4项、T2为5项，失败、跳过或数量变化均不能PASS。

## 6. 收据、正式前置与后续指南

### 位置专用参数机制的Windows待验项W13

**待C真实执行，当前未签收。**第十一轮positional-only精确建议机制默认开启；它只经过5个公开机制任务验证，没有该机制的独立保留任务验证。本项是Windows上的公开机制检查，不计作新增独立修复率或正式A2/B7结果。

1. 从本包的`experiments/field_trial/round11/public/positional-only/`复制整个样例到新的验收目录，保留包内原件。为副本选择Python 3.12和独立项目环境，按样例`requirements.txt`准备依赖；记录完整解释器路径和版本。使用默认模型和普通配置，不开实验开关。
2. 记录副本`test_app.py`的原始SHA-256（PowerShell：`Get-FileHash -LiteralPath '实际副本路径\test_app.py' -Algorithm SHA256`）。首次检查应失败；保存实际TypeError、指向当前`app.py:4`的非空`python_binding`观测及执行引用，可从会话JSON和Details核对。
3. 核对实际第一步是否明确建议把`return adapt(value=value)`改为`return adapt(value)`，保持原表达式`value`。只有确实出现这条建议才照做；不要修改`test_app.py`、`core.py`或自行补全未给出的修法。若没有精确建议或观测不关联当前异常，记录失败并保留输出。
4. 再次检查，预期完整原测试为**1 passed**、目标达到，且原测试SHA-256不变。记录实际结果、修改差异和前后截图/导出。未执行或未满足预期时保持NOT RUN/FAIL，不能引用Mac通过记录填PASS。

本说明随本次文档收尾提供，不改已经验证的ZIP；收到旧包内清单时仍以本项补充及空白收据W13记录实际Windows结果。

### 收据与后续门槛

C真实执行后填收据，逐项关联日志/截图并签收；未做的项目保持“未执行/未覆盖”。
本文件当前没有验收结果，也没有代C签字或向C发送材料。

正式用户研究仍等待真实Windows任务终端验收、指定B8版本，以及B13方案/同意书/问卷就绪。
本候选工程预检不会替代B5版本冻结或用户研究版本确认。

本文件是候选交接清单。完整4–8页图文指南仍按B14安排：**10/19初稿、10/22定稿**；
B15目录搬迁约**10/20**开始，再统一`SystemCode/`路径。这些后续文档/目录工作不新增为本轮冻结前硬门槛。
