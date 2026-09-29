# 小组报告（任务 B10、B11）

报告用 **Word 或 WPS** 编辑，最终导出 PDF 提交。

| 文件 | 内容 |
|---|---|
| `FixFirst_Report_v0.1_20260929.docx` | 报告骨架：按课程要求排好的章节、证据表和占位 |
| `report-skeleton.md` | 生成 v0.1 骨架的源文件（`pandoc report-skeleton.md -o <文件名>.docx --toc --toc-depth=2`） |
| `VERSIONS.md` | 版本记录 |
| `SOURCES.md` | 每张图、每张表、每个数字来自仓库里的哪个文件 |

**从 v0.1 起以 docx 为准**，直接在 Word 或 WPS 里改。`report-skeleton.md` 只用来生成第一版，之后不再同步。

- **目录**：打开文件后在目录上右键，选"更新域"（WPS 里叫"更新目录"），目录就会填上。
- **占位**：`[PLACEHOLDER: …]` 是待写的正文；`[PENDING: 任务, 来源]` 是还没跑出来的数字，由对应任务交结果后填。定稿前全文搜索这两个词，确认一个不剩。
- **版本**：每到一个节点（初稿 10/19、定稿 10/23、提交版 10/24），另存为新文件 `FixFirst_Report_v0.<n>_<日期>.docx`，并在 `VERSIONS.md` 里加一行。旧版本不删。
- **图表**：图片的源文件和导出的 PNG 放在 `docs/report-assets/`，文件名以任务编号开头；每张图、表在 `SOURCES.md` 里登记来源。报告里的数字都要能在那里找到出处。
- **必须有的部分**：AI 使用声明（附录 E）、局限、与 proposal 的偏离（第 5 部分的表）。个人反思（附录 D）由每人自己写，不用 AI。
- **提交**：定稿后导出 PDF，按课程命名规则命名，放进 `ProjectReport/`（任务 B15 建这个文件夹）。
