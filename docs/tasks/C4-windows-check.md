# C4 Windows 验收：冻结版和最终版

| | |
|---|---|
| 负责 | C，在 Windows 电脑上做 |
| 时间 | 冻结版 v0.7.0：10/10–10/11；最终提交版：10/23 |
| 预计用时 | 每次 2–3 小时 |
| 要先完成 | B5（冻结）；最终版要等 C6 合并、B 宣布最终版本 |
| 交付 | 在 C4 的 Issue 里按反馈格式回复结果 |

## 为什么要做

FixFirst 同时支持 Windows，组里只有 C 的电脑能真正验证它。冻结版要用于用户研究（C3 在 Windows 上做），最终版是提交给老师运行的版本，两次都必须在 Windows 上完整跑通。

## 步骤

1. 取指定版本，重建环境：

   ```powershell
   cd C:\dev\FixFirst
   git fetch --tags
   git switch --detach v0.7.0              # 最终版换成 B 宣布的标签
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Recreate
   ```

   C6 整理目录以后，代码在 `SystemCode\` 下面，上面的命令要在 `C:\dev\FixFirst\SystemCode` 里运行。
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
4. 最终版额外检查：
   - 从 GitHub 上下载 ZIP（Code → Download ZIP）；
   - 解压到一个新文件夹，完全按 [C5](C5-user-guide.md) 的使用指南从头安装，看会不会卡住。这也是在验收使用指南。

## 反馈格式

在 C4 的 Issue 里回复：

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

- [ ] 冻结版：测试和 ruff 通过，手动检查都做了，结果已回复
- [ ] 最终版：用 ZIP 按使用指南从头安装成功，结果已回复
