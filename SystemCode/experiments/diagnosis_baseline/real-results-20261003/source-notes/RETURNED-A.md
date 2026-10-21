# A 侧 B3 评分交回（2026-10-03）

> 整理说明：本文件来自已定稿的评分回收提交，仅修正文档状态、计数笔误和相对路径。
> 原始评分及共识 CSV 逐字节保留；其中的历史“草案”等措辞不覆盖双方已确认的最终状态。
> 来源提交、原文件摘要及本次修改记录见 `../PROVENANCE.json`。

A、C 的匿名评分表均已交齐，两处分歧已确认，共识表已定稿。
A 的原表保存在 `../scores/model-{1,2,3}-A.csv`，**独立原表不覆盖**。回帖见 FixFirst Issue #4 comment 5964240671。

- 31 条有实际回答按 `correct`/`partial`/`generic`/`wrong` 评分；5 条 `service_no_answer`
  留空分、填 `scored_by`、`notes` 确认，与 `../../real-scoring-20261003/scoring/unavailable-answers.csv` 逐条一致。
- 只改 `score`/`scored_by`/`notes`，其余列与列顺序未动。
- 分布（31 条有答）：correct 12 / partial 9 / generic 0 / wrong 10。

**署名与披露**：A 侧评分由 AI（Claude Code）按事先固定的 [`scoring-rubric.md`](../reference/scoring-rubric.md) 逐行起草，
A 逐行复核后署名 `yongjun`；C 在未见 A 分数的情况下独立完成。报告方法部分须披露该用途与
人工核实方式。AI 未参与标签制定、未接触模型身份映射、未改动任何冻结标签或 FixFirst 结果。
