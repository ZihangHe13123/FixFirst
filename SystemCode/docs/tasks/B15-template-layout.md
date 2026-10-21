# B15 按课程示例整理仓库目录

| | |
|---|---|
| 负责 | B（AI 协助）。A、C 各写一句自己的贡献，放进 README 的分工表 |
| 时间 | 代码定稿之后（约 10/20）开始，10/22（四）前合并 |
| 预计用时 | 3–4 小时 |
| 要先完成 | 其他改代码的 PR 都已合并（否则移动目录以后会有大量冲突） |
| 交付 | 一个 PR：新的目录结构，以及按 7 个部分写的根目录 README |
| 对应计划 | 后续计划 §4 P0 第 10a 项 |

## 为什么要做

课程要求提交的 GitHub 仓库参照示例 [IRS-PM/Workshop-Project-Submission-Template](https://github.com/IRS-PM/Workshop-Project-Submission-Template)：

- 根目录 README 按 7 个部分写；
- 代码放在 `SystemCode/`；
- 报告放在 `ProjectReport/`；
- 视频放在 `Video/`；
- 其他材料放在 `Miscellaneous/`。

它只是示例，不是 GitHub 模板仓库，所以要我们自己整理。之所以放到最后做，是因为移动代码以后所有路径和本地环境都要跟着改。

## 思路

把现在的**整个项目原样搬进 `SystemCode/`**，包括代码、测试、脚本、示例、实验、文档、`pyproject.toml` 和启动脚本。项目内部的相对路径全都不变，所以测试和脚本不用改。现在的 README 变成 `SystemCode/README.md`（技术说明），根目录另写一个按课程格式的新 README。

## 第 1 步：移动

```bash
cd ~/FixFirst
git switch main && git pull
git switch -c b15-template-layout
mkdir SystemCode
git mv src tests scripts examples experiments docs pyproject.toml start-fixfirst.bat start-fixfirst.command SystemCode/
git mv README.md SystemCode/README.md
mkdir ProjectReport Video Miscellaneous
```

PowerShell 里的命令相同（`mkdir` 在 PowerShell 里也能用）。

## 第 2 步：改两个配置文件

`.gitignore`、`.gitattributes` 和 `.github/` 留在根目录。这两个文件里，**中间带 `/` 的规则**只对它们所在的目录生效，所以要在前面加上 `SystemCode/`：

- `.gitignore`：
  - `examples/real-world/results-latest.json` 改成 `SystemCode/examples/real-world/results-latest.json`；
  - `docs/WINDOWS_AUDIT_20260924.md` 改成 `SystemCode/docs/WINDOWS_AUDIT_20260924.md`。

  其他规则（`.venv/`、`__pycache__/`、`workbench/` 这类）在任何一层目录都生效，不用改。
- `.gitattributes`：四条 `examples/.../*.html -whitespace` 的规则都加上 `SystemCode/` 前缀。`*.bat`、`*.ps1` 两条不用改。

检查：

```bash
git check-ignore -v SystemCode/examples/real-world/results-latest.json   # 应该显示是哪一条规则忽略了它
git check-attr whitespace SystemCode/examples/demo/00-healthy.html        # 应该显示 whitespace: unset
```

## 第 3 步：三个新文件夹各放一个 README

Git 不记录空文件夹，所以每个文件夹先放一个 README：

- `ProjectReport/README.md`：写一句"最终报告 PDF 放在这里"。B 会在 10/24 放入 `…-Group-Report.pdf`。
- `Video/README.md`：两个视频的链接（YouTube 不公开链接，或 OneDrive / Google Drive 分享链接），以及对应的文件名。视频文件本身**不放进仓库**，太大，GitHub 单个文件不能超过 100 MB；视频文件放在提交的 zip 里（见 [X4](X-team.md)）。
- `Miscellaneous/README.md`：列出其他材料，并附上链接：
  - 用户研究材料（`SystemCode/docs/user-study/`）；
  - proposal PDF；
  - pre 用的幻灯片 PDF。

  proposal 和幻灯片的 PDF 向 B 要，放进这个文件夹。

## 第 4 步：写根目录 README（7 个部分）

照课程示例的格式，用英文写。内容从报告和 `SystemCode/README.md` 里取：

```markdown
## SECTION 1 : PROJECT TITLE
## FixFirst: find the root cause of Python test failures, then verify every fix

<img src="SystemCode/docs/user-guide-images/<一张主界面截图>.png" width="720" />

---

## SECTION 2 : EXECUTIVE SUMMARY / PAPER ABSTRACT

（150–300 词，和报告的 Executive Summary 一致）

---

## SECTION 3 : CREDITS / PROJECT CONTRIBUTION

| Official Full Name | Student ID (MTech Applicable) | Work Items (Who Did What) | Email (Optional) |
| :--- | :---: | :--- | :--- |
| HE ZIHANG | | Reasoning and model: …; integration | |
| WEI YI | | … | |
| CHI YONGJUN | | … | |

---

## SECTION 4 : VIDEO OF SYSTEM MODELLING & USE CASE DEMO

- Promotion video: <链接>
- System design video: <链接>

---

## SECTION 5 : USER GUIDE

`Refer to appendix <Installation & User Guide> in project report at Github Folder: ProjectReport`
(also in SystemCode/docs/USER_GUIDE.md)

Quick start（从 SystemCode/README.md 的 Quick start 复制，命令前加 cd SystemCode）

---

## SECTION 6 : PROJECT REPORT / PAPER

`Refer to project report at Github Folder: ProjectReport`

（列出报告的章节）

---

## SECTION 7 : MISCELLANEOUS

`Refer to Github Folder: Miscellaneous`

（列出 Miscellaneous 里的材料，每项一句话）
```

**学号要不要写进去**：仓库是公开的。课程示例里有学号一栏；另一方面，学号在提交 zip 里的 `member-github.txt` 中一定会写。在 10/19 的周会上决定。没有决定的话，这一栏写 "see member-github.txt in the submission"。

另外改几处路径：

- `SystemCode/README.md` 开头加一句："This is the technical README; the course submission overview is in the root README.md"。
- `SystemCode/README.md` 里 MCP 配置的示例路径，改成 `/path/to/FixFirst/SystemCode/.venv/bin/python`。
- `SystemCode/docs/tasks/README.md` 的"卡片里的约定"加一句："B15 以后，命令都在 `SystemCode/` 里运行"。

## 第 5 步：验证

1. 旧的 `.venv` 留在根目录，已经不能用了（它指向搬家前的路径），删掉。然后在 `SystemCode/` 里重建并跑测试：

   ```bash
   rm -rf .venv
   cd SystemCode
   bash scripts/setup.sh python3.12
   .venv/bin/python -m pytest -q
   .venv/bin/ruff check src tests scripts experiments
   ```

   Windows 上用 `Remove-Item -Recurse -Force .venv` 删除，然后在 `SystemCode` 里运行 `setup.ps1` 和 `.venv\Scripts\python -m pytest -q`。测试要全部通过，数量和搬家前一样。
2. 双击 `SystemCode/start-fixfirst.bat`（或 `.command`），确认界面能打开，样例项目能走完。
3. 检查有没有遗漏：

   ```bash
   git status                     # 不应该有意料之外的未跟踪文件
   grep -rn "/Users/" README.md SystemCode/README.md || echo "no local paths"
   ```

4. push 分支，在 GitHub 上打开这个分支，把根目录 README 和 `SystemCode/README.md` 里的每个链接都点一遍，确认都能打开。

## 第 6 步：提交，通知大家

开 PR，标题写 "B15: course submission layout"，合并以后在群里通知所有人：

```text
仓库目录已整理：代码都在 SystemCode/ 里。请 git pull，删掉根目录的旧 .venv，
在 SystemCode/ 里重新运行 setup（setup.sh 或 setup.ps1）。
```

## 完成标准

- [ ] 根目录只有 `README.md`、`.gitignore`、`.gitattributes`、`.github/`（PR 模板，GitHub 要求放在根目录）和 `SystemCode/`、`ProjectReport/`、`Video/`、`Miscellaneous/` 四个文件夹
- [ ] 根目录 README 有 7 个部分，所有链接都能打开
- [ ] 在 `SystemCode/` 里新建环境后，测试和 ruff 全部通过
- [ ] `.gitignore`、`.gitattributes` 里带路径的规则已更新，并用 `git check-ignore`、`git check-attr` 验证过
- [ ] 学号是否公开已经在周会上决定
