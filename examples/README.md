# 随源码附带的运行记录

v0.2 新增 `execution-demo/`、`execution-dataset/` 和 `execution-evaluation/`。它们分别展示测试执行故事、30 个新增执行故障与实验；下文 `demo/` / `dataset/` / `evaluation/` 仍是 v0.1 原始记录。

执行故事的顺序为：`00-healthy` → `01-two-failures` → `02-selected-pass` → `03-skipped-is-not-fixed` → `04-restored`。每个阶段都有 HTML、session JSON 和 `.graph.json`。可以直接打开 `execution-demo/01-two-failures.html` 查看新功能。

执行套件同样使用相近模板，新增 35 条问题标签、180 次独立检查记录；`truth.json` 的 `event_groups` 明确区分同一工具的独立故障。新评测不再包含无法反映实际修复的固定检查次数模拟。

这些文件来自 2026-09-08 在 macOS / Python 3.12 上的真实执行。为便于分享，已替换常见个人路径并移除临时环境和缓存。HTML 是静态结果，不会在页面内运行检查。

## 按故事看演示

| 文件 | 当时发生了什么 | 应看到什么 |
|---|---|---|
| `demo/00-healthy.html` | 健康项目完成环境、依赖、测试收集、Ruff 检查 | 当前目标已达成 |
| `demo/01-failure.html` | 删除自建 helper 模块，并加入长行 | 多个测试文件的导入失败归并展示；风格问题独立保留 |
| `demo/02-partial-check.html` | 只修改长行并重跑 Ruff | 风格问题已验证解决；导入问题不能被关闭 |
| `demo/03-restored.html` | 恢复 helper 并重跑测试收集 | 导入问题已验证解决；恢复测试收集目标达成 |

每份 HTML 旁边的 JSON 是该阶段的数据。需要自己执行一遍，运行 `fixfirst demo --output workbench/new-demo --open`。

## 数据表与标签

`dataset/manifest.json` 列出 30 个案例；每种故障有 5 个模板变体：缺少本地模块、缺少明确配置、风格问题、代码检查问题、依赖冲突、导入与风格混合问题。

每个案例含 `baseline.json`、`input.json`、`truth.json`、`restored.json` 和恢复后的示例源码。`labeled_issues.json` 共 35 条问题级训练/评价记录；代码检查类别在当前粗粒度分类任务中标为 `other_unknown`，原始 Event / Issue 仍保留 `code_check`。

生成器共记录 360 次不同的工具运行。`input.json` 的故障运行也保留在对应 `restored.json` 历史中，因此不能把所有 JSON 的 runs 数量直接相加当成额外样本。

随包数据可以直接用于 `fixfirst evaluate examples/dataset --output workbench/new-evaluation`。源码目录是恢复后的快照；依赖案例的临时解释器已移除。复现执行应重新运行生成器，不应尝试执行数据里脱敏后的历史命令。

`evaluation/` 保存本轮真实的分类、归并指标、决策树 JSON/文本及 SBERT 下载版本。自然故障、多根因同工具案例、困难语义相似案例和真人试用尚未纳入本轮实验。

自建 fixture 代码声明 CC0-1.0；不应把这些受控样本写成来自开源社区的真实故障数据。模型权重不在源码包内，请通过下载脚本取得，并遵守模型仓库的许可。
