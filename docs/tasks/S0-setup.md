# S0 开工准备

| | |
|---|---|
| 负责 | A、C 各做一遍（B 已经做过） |
| 截止 | 10/1（四） |
| 预计用时 | 1–2 小时 |
| 交付 | 在 S0 的 Issue 里回复：姓名、系统、测试结果的最后一行 |

## 1. 装好工具

| 工具 | 用来做什么 | macOS | Windows |
|---|---|---|---|
| Git | 取代码、提交 | 终端运行 `xcode-select --install`，或 `brew install git` | https://git-scm.com/download/win ，安装选项全部用默认 |
| Python 3.12 | 运行 FixFirst（3.10 以上都可以） | https://www.python.org/downloads/ ，或 `brew install python@3.12` | https://www.python.org/downloads/ ，安装时勾选 "Add python.exe to PATH" |
| uv | 一条命令装好不同版本的 Python 和包。A 必须装，C 复核标签时也要用 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| VS Code（建议） | 看代码，编辑 Markdown 和 CSV | https://code.visualstudio.com | 同左 |

装完以后**新开一个终端**，检查三样工具都能用：

```bash
git --version
python3 --version
uv --version
```

Windows 上把 `python3` 换成 `py --version`。

## 2. 加入仓库

邀请已经在 9/29 发给 creazydiamond 和 StupidGuy1122（可以推分支、提 PR、认领 Issue），7 天内有效。到邮箱里接受邀请，或者直接打开 https://github.com/ZihangHe13123/FixFirst/invitations 点 Accept。过期了就在群里说一声，B 重新发。

## 3. 克隆仓库，设置提交身份

仓库是公开的，提交记录里的邮箱谁都能看到，所以提交时用 GitHub 提供的 noreply 邮箱。获取方法：GitHub 右上角头像 → Settings → Emails，勾选 "Keep my email addresses private"，下面会显示一个形如 `12345678+用户名@users.noreply.github.com` 的地址。

macOS / Linux：

```bash
cd ~
git clone https://github.com/ZihangHe13123/FixFirst.git
cd FixFirst
git config user.name "Your Name"
git config user.email "12345678+yourname@users.noreply.github.com"
```

Windows（PowerShell）：

```powershell
mkdir C:\dev -Force; cd C:\dev
git clone https://github.com/ZihangHe13123/FixFirst.git
cd FixFirst
git config user.name "Your Name"
git config user.email "12345678+yourname@users.noreply.github.com"
```

`user.name` 填你想在提交记录里显示的名字，例如 `WEI YI`。

不要在以前的 zip 包或旧文件夹里继续改，比如 r4 测试包，或者 Windows 上以 ec87d05 为基础的仓库。旧文件夹里如果有 r4 之后自己改过、还没交给 B 的内容，在 S0 的 Issue 里说明，由 B 手动合并。

## 4. 装环境，跑测试

macOS / Linux：

```bash
bash scripts/setup.sh python3.12
.venv/bin/python -m pytest -q
```

Windows：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.venv\Scripts\python -m pytest -q
```

测试应该全部通过，大约需要 1–3 分钟。写这份说明时（9/29）的结果是：

- macOS / Linux：`231 passed, 1 skipped`（跳过的那个是只在 Windows 上跑的 PowerShell 测试）；
- Windows：`232 passed`。

以后测试会越来越多，数字会变。如果只有计时相关的测试偶尔失败，先重跑一次，见 [Windows 测试说明](../WINDOWS_TEAM_TEST.md)。

## 5. 亲手用一遍 FixFirst

启动：macOS 运行 `.venv/bin/fixfirst serve`；Windows 双击 `start-fixfirst.bat`，或运行 `.venv\Scripts\fixfirst serve`。浏览器打开以后：

1. 点 **Open a sample project**，再点 **Check my project**。
2. 看 **Must fix** 下面的步骤。每一步都写明改哪个文件的第几行、为什么、改完怎么确认；展开 **Details**，可以看到判断用的规则和官方文档来源。
3. 照着样例项目里 `FIXES.md` 的说明改代码，然后点 **Check again**，一直改到页面显示 **All tests pass**。
4. 点页面底部的 **Technical details**，看一下证据图谱和推理轨迹。

用完在终端里按 Ctrl+C 退出。

## 6. 读懂系统

考试时每个人都要能把系统讲清楚。按顺序读：

1. `README.md` 的 **How it works** 一节，约 15 分钟。
2. [《FixFirst 技术原理详解》](../技术原理详解.md)（中文）：先读第 0 节的全景，再读和自己任务相关的章节。每节最后的“老师可能问”可以当自测题。
3. [docs/ARCHITECTURE.md](../ARCHITECTURE.md)：需要时再查。
4. 自己要用的脚本，读一下开头的说明。每个脚本的第一段都写了用法，运行时加 `-h` 可以看到全部参数。

## 7. 每天怎么提交

每个任务开一个分支，分支名用"任务编号-简短英文"，例如 `c2-study-data`。改完推到 GitHub，再开一个 Pull Request（PR），由 B 合并。

```bash
git switch main && git pull                 # 每次开工前，先拿到最新代码
git switch -c c2-study-data                 # 新建分支（已有分支用 git switch c2-study-data）
# ……改文件……
git status                                  # 看一下改了哪些文件
git add docs/user-study/sessions.csv        # 只加这次要提交的文件
git commit -m "Add the user study session data"
git push -u origin c2-study-data
```

推送成功后打开仓库页面，会出现一条黄色提示 **Compare & pull request**，点它：

- 标题写"任务编号：做了什么"，例如 `A2: held-out results on v0.7.0`；
- 正文按模板填，把卡片里的完成标准复制进去打勾；
- 任务全部完成时，在正文里写 `Closes #Issue编号`，PR 合并后 Issue 会自动关闭。

B 看过以后会合并；需要修改的话，B 会在 PR 里留言，你在同一个分支上改完再 push 一次就行。合并以后回到 main 继续：

```bash
git switch main && git pull
```

注意事项：

- 提交说明用英文短句，说清楚改了什么。
- 不要提交 `.venv`、大于 10 MB 的文件、视频、参与者的个人信息。冻结前也不要提交新项目的任何东西（见任务总表的规矩 1）。
- 不熟悉命令行的话，可以用 GitHub Desktop（https://desktop.github.com）完成同样的步骤：Branch → New branch，然后 Commit、Push、Create Pull Request。

## 8. 卡住了怎么问

在任务对应的 Issue 里留言，照下面的格式写：

```text
任务：A1 第 4 步（heldout.py pytest）
系统：Windows 11 / macOS 15；Python 3.12.x
命令：（完整复制）
结果：（完整复制报错，或者截图）
我已经试过：……
```

A1、C1 的问题不要写出具体的项目名。只写"第 3 个项目"这样的编号，需要细节时私下找对方（A 或 C）。

## 完成标准

- [ ] 已接受仓库邀请，能看到 Issues 页面
- [ ] 本地仓库设置了 `user.name`，`git config user.email` 显示的是 noreply 地址
- [ ] 测试全部通过（贴出最后一行）
- [ ] 用样例项目完整走了一遍，看到 All tests pass
- [ ] 读完 README 的 How it works
- [ ] 在 S0 的 Issue 里回复：姓名、系统、测试结果的最后一行
