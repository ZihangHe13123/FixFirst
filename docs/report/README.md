# 小组报告（任务 B10、B11）

报告用 **Word 或 WPS** 编辑，最终导出 PDF 提交。

## Current review version

`FixFirst_Report_v0.3_20261009.docx` is the current populated review draft. It adds the independently recomputed DeepSeek result as a separate cloud comparison. Its PDF contains the full B14 guide in Appendix C. The separate `FixFirst_User_Guide_v0.1_20261009.docx` and PDF contain the same guide; `docs/USER_GUIDE.md` is its repository copy.

The v0.3 Markdown file records the content used to edit this draft. After manual Word edits, the Word file remains authoritative; do not regenerate it without reconciling those edits. Versions 0.2 and 0.3 use a static Contents list. The earlier reports and standalone guide are preserved unchanged. Remaining evidence and human contributions are listed in [COMPLETION-CHECKLIST.md](COMPLETION-CHECKLIST.md).

The report has 23 pages and the standalone guide has eight. Every final report page was visually reviewed or confirmed byte-identical to an already reviewed page, and PDF text extraction was checked. Artifact identities and source checks are recorded in [DOCUMENT-QA-v0.3-20261009.json](../report-assets/DOCUMENT-QA-v0.3-20261009.json). The previous [QA record](../report-assets/DOCUMENT-QA-20261009.json) covers the unchanged guide and v0.2 report.

| 文件 | 内容 |
|---|---|
| `FixFirst_Report_v0.1_20260929.docx` | 报告骨架：按课程要求排好的章节、证据表和占位 |
| `report-skeleton.md` | 生成 v0.1 骨架的源文件（`pandoc report-skeleton.md -o <文件名>.docx --toc --toc-depth=2 --metadata toc-title="Contents"`） |
| `VERSIONS.md` | 版本记录 |
| `SOURCES.md` | 每张图、每张表、每个数字来自仓库里的哪个文件 |

**从 v0.1 起以 docx 为准**，直接在 Word 或 WPS 里改。`report-skeleton.md` 只用来生成第一版，之后不再同步。

- **目录**：v0.2 起使用静态目录，改章节标题时一并核对。v0.1 的空目录域可在 Word/WPS 里更新。
- **占位**：`[PLACEHOLDER: …]` 是待写的正文；`[PENDING: 任务, 来源]` 是还没跑出来的数字，由对应任务交结果后填。定稿前全文搜索这两个词，确认一个不剩。
- **版本**：每到一个节点（初稿 10/19、定稿 10/23、提交版 10/24），另存为新文件 `FixFirst_Report_v0.<n>_<日期>.docx`，并在 `VERSIONS.md` 里加一行。旧版本不删。
- **只用英文**：正文和文件名都用英文。导出 PDF 的机器没有中文字体时，中文会显示成空白（v0.1 第一次生成时第 3、6 页的 `docs/技术原理详解.md` 就是这样）。要引用中文文档，写 "technical guide §n"，对照见 `SOURCES.md`。每次导出 PDF 后逐页看一遍。
- **图表**：图片的源文件和导出的 PNG 放在 `docs/report-assets/`，文件名以任务编号开头；每张图、表在 `SOURCES.md` 里登记来源。报告里的数字都要能在那里找到出处。
- **必须有的部分**：AI 使用声明（附录 E）、局限、与 proposal 的偏离（第 5 部分的表）。个人反思（附录 D）由每人自己写，不用 AI。
- **提交**：定稿后导出 PDF，按课程命名规则命名，放进 `ProjectReport/`（任务 B15 建这个文件夹）。
