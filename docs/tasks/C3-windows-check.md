# C3 Windows 验收：用户研究的任务终端、冻结版和最终版

| | |
|---|---|
| 负责 | C，在 Windows 电脑上做 |
| 时间 | 用户研究的任务终端：**尽量在 10/9 冻结前**（最迟 10/11，和冻结版一起）；冻结版 v0.7.0：10/10–10/11；最终提交版：10/23 |
| 预计用时 | 每次 2–3 小时 |
| 要先完成 | 任务终端的验收只要 PR #32 已合并（已完成）；冻结版要等 B5；最终版要等 B15 合并、B 宣布最终版本 |
| 交付 | 在 C3 的 Issue 里按反馈格式回复结果 |

## 为什么要做

FixFirst 同时支持 Windows，组里只有 C 的电脑能真正验证它。冻结版要用于用户研究（C2 在 Windows 上做），最终版是提交给老师运行的版本，两次都必须在 Windows 上完整跑通。

## 第一部分：用户研究的任务终端（尽量 10/9 前，**待 C 执行**）

用户研究的判分脚本 `grade.py` 和任务终端 `open_task.py` 只在 macOS 上验证过。Mac 上通过**不等于** Windows 上通过，所以要在你的电脑上按下面的步骤验收一次。每一步都在 PowerShell 里执行，主仓库在 `C:\dev\FixFirst`，任务副本放在 `C:\study`。

1. **准备**：更新主仓库（`git switch main; git pull`），然后运行自检，再重建一次任务：

   ```powershell
   cd C:\dev\FixFirst
   .venv\Scripts\python experiments\user_study\prepare.py C:\study --self-test
   .venv\Scripts\python experiments\user_study\prepare.py C:\study
   ```

   自检应该显示 4 行 `as expected`，最后是 `Self-test passed`。
2. **原始故障判 FAIL**：4 个任务刚建好时都应该判 FAIL：

   ```powershell
   foreach ($t in "T1","T2","T3","T4") { .venv\Scripts\python experiments\user_study\grade.py C:\study $t }
   ```

3. **任务终端用的是任务自己的解释器，临时变量不会带进去**。先在当前终端设两个临时变量，再打开 T3 的任务终端：

   ```powershell
   $env:PYTHONPATH = "src"; $env:PYTEST_ADDOPTS = "-o pythonpath=src"
   .venv\Scripts\python experiments\user_study\open_task.py C:\study T3
   ```

   在打开的任务终端里依次运行：

   ```powershell
   python -c "import sys, os; print(sys.executable); print(os.environ.get('PYTHONPATH'), os.environ.get('PYTEST_ADDOPTS'))"
   python -m pytest -q
   exit
   ```

   第一行应该是 `C:\study\T3-versions\.venv\Scripts\python.exe`，第二行应该是 `None None`；pytest 应该报 `No module named 'distutils'`。
4. **判分终端里的临时变量也不算**：还在刚才那个设了临时变量的终端里，给没修好的 T2 判分，应该是 FAIL。然后清掉临时变量：

   ```powershell
   .venv\Scripts\python experiments\user_study\grade.py C:\study T2
   Remove-Item Env:PYTHONPATH, Env:PYTEST_ADDOPTS
   ```

5. **持久的修复判 PASS**：打开 T2 的任务终端，安装项目，退出后判分，应该是 PASS：

   ```powershell
   .venv\Scripts\python experiments\user_study\open_task.py C:\study T2
   ```

   在任务终端里运行 `python -m pip install -e .`，完成后输入 `exit`，再在主仓库终端运行 `.venv\Scripts\python experiments\user_study\grade.py C:\study T2`。
6. **改测试、跳过测试判 FAIL**：

   ```powershell
   Add-Content C:\study\T1-report\tests\test_render.py "# changed"
   .venv\Scripts\python experiments\user_study\grade.py C:\study T1
   .venv\Scripts\python experiments\user_study\prepare.py C:\study --only T1
   Set-Content C:\study\T4-booking\conftest.py "import pytest`ndef pytest_collection_modifyitems(items):`n    for item in items:`n        item.add_marker(pytest.mark.skip)"
   .venv\Scripts\python experiments\user_study\grade.py C:\study T4
   .venv\Scripts\python experiments\user_study\prepare.py C:\study
   ```

   第一次判分应该是 `FAIL T1: files under tests/ were changed ...`，第二次应该是 `FAIL T4: ... skipped ...`。最后一行把任务恢复成全新状态。

把每一步的结果（✓ 或 ✗，✗ 附完整输出）回复在 C3 的 Issue 里。有任何一步不符合预期，就先不要开始用户研究的试用，等 B 修好。

## 第二部分：冻结版和最终版


1. 取指定版本，重建环境：

   ```powershell
   cd C:\dev\FixFirst
   git fetch --tags
   git switch --detach v0.7.0              # 最终版换成 B 宣布的标签
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Recreate
   ```

   B15 整理目录以后，代码在 `SystemCode\` 下面，上面的命令要在 `C:\dev\FixFirst\SystemCode` 里运行。
2. 自动检查：

   ```powershell
   .venv\Scripts\python -m pytest -q
   .venv\Scripts\ruff check src tests scripts experiments
   ```

   应该全部通过。计时类测试偶尔失败时先重跑一次，见 [Windows 测试说明](../WINDOWS_TEAM_TEST.md)。
3. 手动检查：
   - 双击 `start-fixfirst.bat`，用样例项目完整走一遍（Check → 照 FIXES.md 改 → Check again → All tests pass）；
   - 选一个自己的小项目，放在带中文和空格的路径下，检查一次；
   - 复制界面给出的安装命令，在 PowerShell 里执行，确认能正常运行；
   - 点页面底部的 **Download a shareable report** 导出报告，打开看看中文正不正常，用户名有没有被替换成 `<home>`；
   - 关掉再打开，之前的会话还在。
   - 冻结版这次，顺手截几张 Windows 上安装和使用的图（setup.ps1 运行完、首页、检查结果页），发给 B，用在使用指南（B14）里。
4. 最终版额外检查：
   - 从 GitHub 上下载 ZIP（Code → Download ZIP）；
   - 解压到一个新文件夹，完全按 [B14](B14-user-guide.md) 的使用指南从头安装，看会不会卡住。这也是在验收使用指南。

## 反馈格式

在 C3 的 Issue 里回复：

```text
版本：v0.7.0（git describe --tags 的输出）
Windows 版本：
Python 版本和路径：
pytest 最后一行：
ruff：
手动检查：样例项目 ✓/✗；中文空格路径 ✓/✗；复制安装命令 ✓/✗；导出 ✓/✗；重开后会话 ✓/✗
问题（每个问题写：步骤、预期、实际、完整报错或截图）：
```

发现问题，每个问题单独开一个 Issue，标题以 "Windows:" 开头，由 B 修复。冻结后只修 bug，不改规则。

## 完成标准

- [ ] 第一部分：任务终端的 6 步都符合预期，结果已回复（尽量 10/9 前）
- [ ] 冻结版：测试和 ruff 通过，手动检查都做了，结果已回复
- [ ] 最终版：用 ZIP 按使用指南从头安装成功，结果已回复
