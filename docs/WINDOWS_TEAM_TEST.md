# Windows 组员测试说明

本包是 FixFirst v0.6.0 的 Windows 修复测试版，已追加 Mac 复核修订
`windows-review-fixes-20260925-r4`。请解压后运行，不要直接在压缩包中启动。
需要 Windows 10/11 和 Python 3.10 以上；首次安装需要联网下载依赖。

## 安装和启动

1. 解压到普通长度的目录，例如 `C:\dev\FixFirst`，也可用中文或带空格的目录。
2. 在解压目录打开 PowerShell，执行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
   ```

   如果需要指定 Python：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Python 'C:\Path\to\python.exe'
   ```

3. 双击 `start-fixfirst.bat`，等待浏览器打开。命令行窗口需要保持开启。
4. 若浏览器没有自动打开，把窗口中显示的 `http://127.0.0.1:端口/` 地址复制到浏览器。
5. 结束时在启动窗口按 Ctrl+C。界面提供的安装命令应复制到 **PowerShell**。

安装只操作本目录的 `.venv`。如需要更换 Python 大版本，给安装命令加
`-Recreate`；旧环境会保留为 `.venv-backup-*`。解压包不包含现成 `.venv`。

## 建议测试顺序

- **示例流程**：点击 Open a sample project，完成检查，按生成目录内的 `FIXES.md`
  修改示例，再点 Check again，确认问题转为已修复。
- **自己的项目**：选择一个可信的 Python 项目及其 Python/虚拟环境，确认路径和
  Python 选择正确。缺少 pytest 时，按提示在目标环境安装。FixFirst 不会自动修改项目。
- **路径和命令**：使用中文、空格目录；复制带版本约束的安装命令，确认 PowerShell
  正确执行。安装会改变所选项目的依赖，建议使用项目副本或测试虚拟环境。
- **持久化与导出**：关闭后重新启动，确认会话仍存在；导出报告，检查内容、中文和脱敏。
- **本次修订复核**：按第二个行动的 ID 提问，中文与 ID 之间不加空格，确认解释的是
  指定行动。自动化回归包括 `为什么inspect-beta？` 和 `inspect-beta为什么排在这里？`。
  导出 `Home 'C:\Users\Alice' is not inside /tmp/project` 应得到
  `Home '<home>' is not inside /tmp/project`，不能丢失中间诊断文字；带单引号、
  空格的用户名及嵌套 JSON 也有回归覆盖。重新跑全套测试，包括真正 GBK 环境。
- **r3 新增复核**：当项目在 `D:\project` 时，导出另一位置的
  `'C:\Users\O' Brien\OtherProject\data.csv'` 应得到 `'<home>\OtherProject\data.csv'`，
  不应留下 `Brien`。新性能回归在独立子进程中处理接近 1 MB 的未闭合路径日志，
  校验完整脱敏输出，并设置 4 秒处理期限及 10 秒子进程超时，防止测试挂起。
- **r4 新增复核**：`Cannot open 'C:\Users\Alice': mode='r'` 应得到
  `Cannot open '<home>': mode='r'`；`error='permission denied'` 等字段也应完整保留。
  这些检查同时覆盖普通日志和嵌套 JSON、单引号加空格用户名及字段中的另一条路径。
  性能测试把本包 `src` 放在子进程 `PYTHONPATH` 最前，并保留原有的依赖路径。
- **计时测试**：如果只有计时相关的测试偶尔失败（`test_orphan_cannot_hold_check_pipes_open`、
  `test_sandbox_timeout_does_not_wait_for_descendants`），先重跑一次；电脑较慢或杀毒软件
  正在扫描时可能超时，重跑仍失败再反馈。
- **退出清理**：在自己的测试副本运行耗时检查时按 Ctrl+C，确认测试进程随服务退出。

## 反馈格式

请把以下内容发给项目组，日志和报告分享前检查是否含私密信息：

```text
测试包版本/基础提交/本地修订号：（见包内 RELEASE_INFO.txt）
Windows 版本：
Python 版本和路径：
项目目录是否含中文或空格：
使用 PowerShell / cmd / 其他终端：
操作步骤：
预期结果：
实际结果及完整错误信息：
截图/相关日志：
```

## 已知验证边界

原 Windows 包的历史记录是 Windows 11 上 149 项通过、Linux 上 148 项通过及
1 项跳过；GBK 环境为 147 项通过、2 项旧测试因默认编码读取 UTF-8 HTML 而失败。

用户转发的 Windows 复核报告称首次修订版 `windows-review-fixes-20260924` 在 Windows
和真正 GBK 环境均 **159 项通过**，Ruff 和包内校验值也通过；原先两个 GBK 失败已消除。
该结果适用于首次修订版，原始记录在 Windows 开发机，本包不含该记录。

用户随后提供的 `r2` 复核记录报告 Windows 和真正 GBK 环境均 **178 项通过**，
Ruff 及 842 个文件校验通过；另发现了上述用户名和性能边界问题。

用户提供的 `r3` 复核记录报告 Windows 和真正 GBK 环境均 **196 项通过**，Ruff、
文件校验通过；近 1 MB 的原性能复现约 0.27 秒完成。该轮另发现诊断字段丢失的问题。

本次 `r4` 增加 21 个用例，当前共 217 个用例；Mac 上 **216 项通过、1 项 PowerShell
专项跳过**，Ruff 通过。近 1 MB 的原性能复现约 0.136 秒；同等大小的字段日志约
0.099 秒，输出均逐字匹配。用户随后提供的复核记录确认 `r4` 在 Windows 和真正 GBK
环境均 **217 项通过**。Windows 10、真实 Conda 环境仍待验收。详见 `docs/WINDOWS_ADAPTATION.md`。
上述回归结果不代表每个真实项目都能准确诊断。
