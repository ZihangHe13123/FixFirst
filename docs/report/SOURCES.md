# 报告中图、表和数字的来源

## Version 0.7 literature correction on 12 October 2026

The literature correction follows `LITERATURE-CHECK-20261012.md` and
`REFERENCES-ADDITIONS-20261012.md`. The latter's seven English entries are included verbatim,
with matching in-text numbers. Their complete hashes are in `LITERATURE-v0.7-20261012.json`.

- Corrected Rubio-González, the published ICSE DockerizeMe entry, two original title colons,
  and the pipdeptree organisation. The paper's 493 BugsInPy defects remain separate from the
  repository snapshot's 501; all eight additional indexed defects are in black.
- MCP cites implemented revision 2025-11-25. scikit-learn is cited for fitting the tree and
  computing TF IDF similarity. SUS cites the chapter DOI and its electronic-edition pages,
  207–212; participant results remain pending.
- Model cards identify the official Qwen models and evaluated quantised conversions. The
  stored Qwen revisions agree with those entries. Gemma has no recorded revision; its local
  chat template differs from the online copy, and the archived hashes identify what was run.
  DeepSeek remains a provider-controlled API alias rather than a frozen weight snapshot.
- Crossref metadata for DockerizeMe and SUS and the implementation sources were checked.
  The bibliography update does not change the experiment or participant data. Version 0.6's
  numerical receipt remains the source of the measured results.

The background review still covers three papers. Added implementation references do not make
it a comprehensive survey; the group should decide whether further background work is needed.

## Version 0.6 merged draft on 12 October 2026

The additions were supplied in `REPORT-ADDITIONS-DRAFT-20261012.md` and checked against main
commit `ae6c4ec35d2614cfcd561eb0869e2cc27cf19119`. The recorded A2/B3 and agent scores are unchanged.
New numerical evidence was recounted from the published CSV/JSON files, without a model or a
new defect execution. Full file hashes are in `B11-results-v0.6-20261012.json`.

| Report section | Published evidence | Scope |
| --- | --- | --- |
| 3.3 and 4.3 | The four evaluated tags and their knowledge files | rc2 has 190 source records; rc5 has 191. The 132 rules and 81-feature tree retain their evaluated identities |
| 4.3 later output checks | Independently accepted candidate and follow-check reports | Initial-output compatibility only; no rc5 agent effect estimate |
| 5.2 | `examples/diagnosis-evaluation/frozen-0.8.0rc5/REPORT.md`, `per-case.csv`, `product-replay.json` | Development data, including scenarios that informed rules and features |
| 5.3 and 5.4 | `examples/heldout-2026-10/`; the real and generated B3 packages under `experiments/diagnosis_baseline/` | Older v0.7.0 and `ff92446`; hedged causes and public scorer timing disclosed |
| 5.5 and 5.6 | `experiments/agent_baseline/formal-20261007/analysis.txt`, `cloud-analysis.txt` | Frozen product and runner `5c224cf`; local and cloud conditions kept separate |
| 5.5 early history | `experiments/agent_baseline/a2-development-20261004/RESULTS.md` | 78 + 6, with exact product/runner commits; nine smoke runs excluded |
| 5.7 | `examples/bugsinpy-verification/README.md`, `results.csv`, `heldout/` | Reference-patch verification; new defects in familiar projects in set 3; not an automatic repair rate |
| 5.8 | `examples/ordering-evaluation/REPORT.md`, `ordering.json`, `advice.json` | Five non-discriminating development cases and one advice rater; evidence-display arm not run |
| 5.9 | `examples/grouping-evaluation/REPORT.md`; `experiments/grouping_hard/` | Natural stream comparison and constructed isolated text pairs |
| Appendix C | `docs/USER_GUIDE.md`, `B14-verification-20261012.json` | rc5 trial tag and selected-scope CLI/MCP check; old sample images explicitly labelled |

In the second held-out set, a Sanic target node is recorded but the intended defect does not
reproduce offline. Valid failure-observation counts require reproduction; it stays in the
28-case denominator as a failure. The 75 development defects include the separately marked
PySnooper 2 case, whereas the earlier unseen phase-two result excludes it.

Section 2 and its reference entries were preserved, not rechecked against the publications in
this revision. Real participant data, Windows acceptance and a final version decision remain
pending. The histories below describe their own earlier drafts.

## Version 0.5 follow-check and BugsInPy update

Sections 5.7 and 5.8 incorporate the evidence below. `docs/report-assets/B11-results-v0.5-20261009.json` retains prior numerical results and adds these outcomes. Independent recount of 28 raw records and saved sessions agrees with the registered BugsInPy counts: 27 unseen defects reproduced, 27 runs without mandatory command advice, 2 exact-name target matches and 0 closure successes. Supplementary parameter matching confirms 3 actual observed target failures; it does not replace the registered count. The remaining 24 target failures were not executed by the product. This is not evidence of 27 correct diagnoses or a completed closure-verification claim.

- Peer report: local `workbench/claude-h5-acceptance-20261005/B12-PHASE2-CHECK-20261009.md`, SHA256 `9f4f4be0e0e9d4b67c82107728caa7870213f2bd3809f52bbfca4a33e0b7a27b`.
- Independent receipt: `docs/report-assets/B12-recount-20261009.json`, including per-case record/session identities and the supplementary outcome details.
- Product identity and scope: clean peer checkout at `5c224cf`; frozen CLI and runner confirm that `--nodes` permits reruns of previously observed nodes, not initial selection of arbitrary unseen tests. Unittest/program goals were not tested in this B12 batch.

## Version 0.4 draft status

Version 0.4 keeps the v0.3 numerical evidence unchanged and adds draft notices and the team review agenda. Its coverage limitation follows protocol v1.16 sections 4 and 5: A to D use supported mechanisms, E has two uncovered environment faults, and F has two code defect controls. Proposed additional tests have not been run.

## Product follow-check evidence incorporated in v0.5

The frozen product's scripted follow check, reported on 9 October 2026, repaired 17/18 A to D tasks, 0/2 E tasks and 0/2 F tasks, with no protected edits. Counts were checked against the 22 per-task records. The script executes printed commands or preregistered interpretations of named source changes, for at most six rounds. This is a product follow check on constructed instances, not a human usability study or a measurement of real environment-fault coverage.

- Report: local `workbench/claude-h5-acceptance-20261005/EVAL-FOLLOW-CHECK-20261009.md`, SHA256 `eb09e549aa075ab1bde6741d7f16f0f7144de62fe8e28af95e41a49e4c278916`.
- Per-task record: local `workbench/claude-h5-acceptance-20261005/results/eval-follow-wt-fixedC4-h5.json`, SHA256 `d258600cd587b5a5d0a6eaa8a62282062297a631e7625c74a04109d66c5f17a7`.
- Caveats to discuss: eb1 lacks an executable replacement; ec3 succeeds using the alternative editable install; ee1's passing headline can mislead; ee2 falls back to unconfirmed generic advice.
- BugsInPy phase two is now recorded above, excluding the separately marked PySnooper-2 development case. New real environment failures still need independent selection.

## Version 0.3 cloud addition checked 9 October 2026

Version 0.3 carries forward the version 0.2 evidence below and adds section 5.6. Aggregate values and source identities are in `docs/report-assets/B11-results-v0.3-20261009.json`. The local and cloud results are separate: local cells have five repetitions and cloud cells have three.

| Evidence | Source and interpretation |
|---|---|
| Cloud primary result | Local `workbench/codex-deepseek-comparison-20261009/analysis-20261009/UPLIFT-MAIN.json`: 132 runs, 54/54 scope repairs in each arm; ratios 0.82 turns, 0.71 time and 0.72 tokens over 18 tasks. First-attempt analysis is byte-identical because no retries occurred |
| Independent recomputation and record check | Local `workbench/claude-h5-acceptance-20261005/DEEPSEEK-RESULTS-CHECK-20261009.md`; matches the registered analysis and independently checks 14,321 archived files and 1,320 requests/replies. This is independent AI review, not human replication |
| Exploratory descriptions and cost | The same review and its retained per-task tables: five-task savings partition is post hoc; F totals use a different aggregation. CNY 4.73 formal / 5.05 with probes are peak-price usage accounting, not the actual off-peak bill |
| Conditions | Registration `7dca2f77...` bound protocol v1.15 at launch. Protocol v1.16 subsequently records results only. Frozen product `5c224cf`, H5 and task pack remain unchanged; provider sampling, reasoning amount, cache and model alias are not frozen |

Source SHA256 values:

- Primary analysis: `c35b345f48ae2813f4fc35826271affc4711fefff7325d9d0c13bb6eb455b1e0`.
- Completion audit: `81a8076e95a748fa4c6b50febf61f39df33aa5396ad22e33adfab4e91155858f`.
- Independent review: `959cdc6556ee6f109827a88e898172f7beb5294a4be98c11f95951ba2269aec3`.
- Launch registration: `7dca2f775447bcb5c572c3606c15b99894a27ac175e5510eda2430617c55dc17`.
- Launch protocol v1.15: `ca950b0d50ed62a1da4712449b6a63729420fb25010c222d9a7c4774b62cee48`.
- Results-only protocol v1.16: `50110399fb763b96a68c6c7f95ba17ff33745f3e9f2d9b208928e441c1291461`.

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
