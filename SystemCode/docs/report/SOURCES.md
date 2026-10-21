# 报告中图、表和数字的来源

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
