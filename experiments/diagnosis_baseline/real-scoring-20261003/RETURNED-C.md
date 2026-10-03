# C 侧 B3 评分交回（2026-10-03）

C 的三张匿名评分表已填好，交回 B 保存；与 A 的逐匿名模型对齐底稿另附
（`alignment/alignment-20261003.md` + 共识表草案 `alignment/scores-consensus-model-{1,2,3}.csv`），
**独立原表不覆盖**（本目录 `model-{1,2,3}-C.csv`，空表备份在 `empty-originals/`）。

- 31 条有实际回答按 `correct`/`partial`/`generic`/`wrong` 评分；5 条 `service_no_answer`
  留空分、填 `scored_by`、`notes` 确认，与 `unavailable-answers.csv` 逐条一致。
- 只改 `score`/`scored_by`/`notes`，其余列与列顺序未动（`fill_scores_C.py` 可复查）。
- 分布（31 条有答）：correct 11 / partial 8 / generic 1 / wrong 10。
- 与 A 的一致率：29/31 = 93.5%（Cohen's kappa 0.90，仅 31 条有回答行）；5 条技术缺答
  双方均确认，单独核对、不计入一致率。2 条分歧（model-2/python-slugify、model-3/pytest）
  的双方立场与取法见对齐文档，待 A/C 会定稿。

**署名与披露**：C 侧评分按事先固定的 `scoring-rubric.md` 逐行起草，
C 逐行复核后署名；C 在未见 A 分数的情况下独立完成。
报告方法部分须披露该用途与人工核实方式。AI 未参与标签制定、未接触模型身份映射、
未改动任何冻结标签或 FixFirst 结果。
