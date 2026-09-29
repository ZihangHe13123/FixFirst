# C5 安装和使用指南（报告附录）

| | |
|---|---|
| 负责 | C（A 在 Mac 上试一遍） |
| 截止 | 初稿 10/19（一）；10/22（四）定稿，在 C6 合并之后，路径改成 `SystemCode/` |
| 预计用时 | 6–8 小时 |
| 交付 | 报告附录 "Installation and User Guide"（英文，带截图，放进报告），同一份内容放进主仓库 `docs/USER_GUIDE.md` |
| 对应计划 | 后续计划 §7；评分项 "System Implementation（功能、易用性、使用指南）" |

## 为什么要做

课程要求报告附录里有安装和使用指南，评分项也写明要看"使用指南"。老师会照着它装一遍，所以必须让一个**没见过 FixFirst 的人**照着做就能跑起来。

## 写哪些内容（英文，4–8 页）

1. **What you need**：Windows 10/11、macOS 或 Linux；Python 3.10 以上；Git（可选，也可以下载 ZIP）；首次安装要联网。
2. **Install**：
   - Windows：下载或克隆，运行 `setup.ps1`，双击 `start-fixfirst.bat`；
   - macOS / Linux：运行 `scripts/setup.sh`，启动 `fixfirst serve`。

   每一步配截图，命令写成可以直接复制的样子。C6 之后的路径都在 `SystemCode/` 下面。
3. **First run with the sample project**：从 Open a sample project 开始，一直到 All tests pass，每一步截图：Must fix 列表、Details 里的规则和来源、Check again 之后的 Fixed and verified。
4. **Using it on your own project**：
   - 选项目文件夹和 Python（项目自己的 `.venv`）；
   - 选目标（Make my tests pass 等）；
   - 看懂 Must fix、Optional、Other；
   - 复制安装命令；
   - 什么时候用 Find it（要联网，只在临时环境里试装）。
5. **Understanding the results**：
   - 根因的五类是什么意思；
   - "likely" 和确定的结论有什么区别；
   - 为什么要点 Check again 才算修好；
   - Technical details 里有什么。
6. **Command line**：常用的几条命令，从 README 的 Command line 一节挑，并说明各自做什么。
7. **For coding agents (MCP)**：一段话加配置示例，照 README 的 Coding agents 一节写。
8. **Troubleshooting**：至少写这几条——
   - 找不到 Python；
   - PowerShell 不允许运行脚本（ExecutionPolicy）；
   - 端口被占用；
   - 杀毒软件让检查变慢；
   - 项目环境里没有 pytest；
   - Find it 没有网络；
   - 中文路径；
   - 怎么把会话导出给别人看。

   多数可以从 [WINDOWS_TEAM_TEST.md](../WINDOWS_TEAM_TEST.md) 和 [WINDOWS_ADAPTATION.md](../WINDOWS_ADAPTATION.md) 里找到。
9. **Uninstall**：删掉文件夹即可；会话记录在哪里（`.fixfirst/`；MCP 的会话在 `~/.fixfirst/sessions`）。

## 步骤

1. 10/19 前：在 Windows 上边装边写、边截图，写成 `docs/USER_GUIDE.md` 开 PR。截图放 `docs/user-guide-images/`，用 PNG，每张不超过 500 KB。
2. 请 A 在 Mac 上照着从头装一遍，记下卡住的地方，改进指南。
3. C6 合并以后，把所有路径改成 `SystemCode/...`，重新截安装部分的图。
4. 10/22 前定稿，复制进报告附录。C4 最终版验收时再照着装一次。

## 完成标准

- [ ] 九个部分都有，命令可以直接复制，关键步骤有截图
- [ ] 至少一个没参与写作的人照着装成功过（Mac 和 Windows 各一次）
- [ ] 路径与最终目录结构一致
- [ ] 已放进报告附录，并通过 PR 合并到 `docs/USER_GUIDE.md`
