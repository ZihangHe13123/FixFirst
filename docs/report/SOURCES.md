# 报告中图、表和数字的来源

## Version 0.2 source register checked 9 October 2026

The original skeleton register below is historical. This table identifies the populated version 0.2. Aggregate values and source SHA256 values are retained in `docs/report-assets/B11-results-20261009.json`. Workbench artifacts are local records, not files assumed to be present in public main.

| Section or figure | Evidence | Interpretation |
|---|---|---|
| Business case and literature | Mukherjee et al. ISSTA 2021 author PDF; Horton and Parnin arXiv:1905.11127; Widyasari et al. FSE 2020 author preprint; primary tool documentation in the bibliography | Original titles, authors and findings opened and checked; historical study percentages are not general market estimates |
| Frozen product and Figure 1 | Tag `b7-freeze-20261007`, commit `5c224cf`; `src/fixfirst/knowledge/domain.toml`, `rules.toml`; `docs/validation/2026-10-04-tree-integration.md` | 132 rules, 737 removal entries, 12 deprecation entries, 190 sources, default 81 feature model; entry counts are not complete semantic verification |
| Historical component evaluation | `examples/diagnosis-evaluation/REPORT.md` and `metrics.json` | Historical 44 feature results, separate from the final 81 feature release; development protocols |
| A2 first step scores | `examples/heldout-2026-10/scores-summary.md`, `scores-review.md`, `report-notes.md`, original independent CSVs | 4 correct, 1 partial, 6 generic, 1 wrong out of 12; agreement 9/12 and kappa 0.66 |
| B3 real-project comparison | [Fixed result report at ebe2a709](https://github.com/ZihangHe13123/FixFirst/blob/ebe2a709abbf82bbf2988c6fdd6fdd2ba693469b/experiments/diagnosis_baseline/real-results-20261003/REPORT.md), PR #66 | 36 requests, missing answers retained; advice scored but not executed |
| B3 generated comparison | [Fixed result report at 0f66baaa](https://github.com/ZihangHe13123/FixFirst/blob/0f66baaae518bc5ceb758c389df073fac66ad306/experiments/diagnosis_baseline/generated-results-20261004/REPORT.md), PR #69; local `workbench/codex-b3-generated-results-20261004/COMPARISON.json` | 750 model requests over 220 ordinary and 30 difficult cases; related to training and rule development |
| B7 tables and Figure 2 | Local `workbench/codex-b7-formal-20261007/analysis-20261009/UPLIFT-ANALYSIS.json`; independent `FORMAL-RESULTS-CHECK-20261009.md` | 660 runs; primary analysis is 18 constructed scope tasks and 90 runs per model per arm; strict result and registered sensitivity together |
| Grouping | `examples/grouping-evaluation/collection/metrics.json` and `execution/metrics.json` | Exact and TF IDF have identical scores on the recorded controlled pair sets |
| B12 and user study status | `examples/bugsinpy-verification/README.md`; `docs/user-study/DATA.md` and `fixtures/README.md` | Reproduction and demonstration fixtures are not completed product or participant evaluations |
| Appendix C and guide Figures 1 to 3 | `docs/USER_GUIDE.md`; actual frozen product screenshots in `docs/user-guide-images`; `docs/report-assets/B14-verification-20261009.json` | Fresh macOS setup, four source fixes and four passing tests, CLI and MCP checks; independent Windows/macOS installation remains pending |

Standalone figures retain SVG source files in `docs/report-assets/`. The Word documents use bundled Liberation Serif and Liberation Mono for reliable PDF text extraction; the original skeleton is unchanged. The guide's Word pictures use native cropping of unchanged screenshots.

## Historical skeleton register

每张图、表和每个数字在这里登记：它在报告里的位置、来自仓库里的哪个文件或哪次运行、由哪个任务产出、现在的状态。

报告里不写中文文件名：导出 PDF 的机器没有中文字体时，中文会显示成空白。骨架里的 **technical guide §n** 指 `docs/技术原理详解.md` 的第 n 节。

| 报告中的位置 | 内容 | 来源文件 | 任务 | 状态 |
|---|---|---|---|---|
| Business case：问题 | PyDFix 71.1%；试调研 12/13；PEP 602 | `docs/DATA_SOURCES.md`，`docs/GENERALISATION.md` | B11 | 已有 |
| System design：总览图 | 检查 → 分组 → 证据 → 知识 → 规则 → 排序 → 验证 | `README.md`（How it works），`docs/ARCHITECTURE.md` | B11 | 待画，放 `docs/report-assets/` |
| System design：技术对照表 | 三类课程技术和对应组件；"Where to read more" 指向英文的 `docs/ARCHITECTURE.md` 各节 | `docs/COURSE_ALIGNMENT.md`，`docs/ARCHITECTURE.md`，`docs/技术原理详解.md` | B11 | 规则数冻结后填 |
| Interfaces：界面截图 | 必须修、Details、Fixed and verified | 冻结版 v0.7.0 实际截图 | B11 / B14 | 待截 |
| Experiments：数据表 | 各数据来源和用途。**难例（30 个）是开发数据**：H07、H08 是看过它们以后写的；它们没用来训练决策树，但冻结后重跑也不能算独立的留出证据。多故障案例（5 个）是我们冻结前自己构造的，也不算留出。只有新的真实项目是留出测试，单列 | `docs/DATA_SOURCES.md`，`docs/B4_SCENARIOS.md`，`README.md`（Hard cases 一段），`docs/技术原理详解.md` 10.5 节 | B11 | 冻结后更新数量 |
| Experiments：根因诊断 | 各方法按场景留出、按模板留出的准确率和 Macro-F1 | `examples/diagnosis-evaluation/metrics.json`（冻结时重新生成） | B6 | 待冻结 |
| Experiments：一次性诊断基线 | 各本地模型的准确率和 Macro-F1 | `experiments/diagnosis_baseline/`（正式全量） | B3 | 只有开发试跑，不能引用 |
| Experiments：下一步排序 | 第一步是否合理、无效尝试次数、消融 | B17 的输出（基于 `fixfirst dataset --suite multi`） | B17 | 待做 |
| Experiments：分组 | precision、recall、F1 | `examples/grouping-evaluation/`（B9 更新） | B9 | 待做 |
| Experiments：真实缺陷验证 | BugsInPy 第二阶段 + 4 个上游回归 | `examples/bugsinpy-verification/`，`examples/historical-regressions/` | B12 | 第一阶段完成（只复现） |
| Experiments：留出真实项目 | 打分结果、按根因分列、错误分析 | `examples/heldout-2026-10/` | A2 | 待 10/10 运行 |
| Experiments：agent 修复对比 | 修复率、回合、耗时、token | `experiments/agent_baseline/` | B7 | 待做 |
| Experiments：用户研究 | 完成率、成功任务的中位用时、SUS | `docs/user-study/RESULTS.md` | B13 / C2 | 待做 |
| Discussion：局限 | | `docs/技术原理详解.md` §11 | B11 | 待写 |
