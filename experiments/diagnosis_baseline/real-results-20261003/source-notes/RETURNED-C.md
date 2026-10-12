# C 侧 B3 评分交回（2026-10-03）

> 整理说明：本文件来自已定稿的评分回收提交，仅修正文档状态、计数笔误和相对路径。
> 原始评分及共识 CSV 逐字节保留；其中的历史“草案”等措辞不覆盖双方已确认的最终状态。
> 来源提交、原文件摘要及本次修改记录见 `../PROVENANCE.json`。

C 的三张匿名评分表已交回，两处分歧已经 A、C 确认，共识表已定稿。
对齐记录见 `alignment-20261003.md`，共识表在 `../consensus/scores-consensus-model-{1,2,3}.csv`。
**独立原表不覆盖**：C 的原表在 `../scores/model-{1,2,3}-C.csv`；发出时的空表保留在
`../../real-scoring-20261003/scoring/`。

- 31 条有实际回答按 `correct`/`partial`/`generic`/`wrong` 评分；5 条 `service_no_answer`
  留空分、填 `scored_by`、`notes` 确认，与 `../../real-scoring-20261003/scoring/unavailable-answers.csv` 逐条一致。
- 只改 `score`/`scored_by`/`notes`，其余列与列顺序未动（原始列与发出版本的核对由回收校验完成）。
- 分布（31 条有答）：correct 11 / partial 8 / generic 1 / wrong 11。
- 与 A 的一致率：29/31 = 93.5%（Cohen's kappa 0.90，仅 31 条有回答行）；5 条技术缺答
  双方均确认，单独核对、不计入一致率。2 条分歧（model-2/python-slugify、model-3/pytest）
  的双方立场与最终取法见 `alignment-20261003.md`。

**署名与披露**：C 侧评分按事先固定的 [`scoring-rubric.md`](../reference/scoring-rubric.md) 逐行起草，
C 逐行复核后署名；C 在未见 A 分数的情况下独立完成。
报告方法部分须披露该用途与人工核实方式。AI 未参与标签制定、未接触模型身份映射、
未改动任何冻结标签或 FixFirst 结果。
