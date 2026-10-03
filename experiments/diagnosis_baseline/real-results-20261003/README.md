# B3 真实项目：最终结果

先看 [结果报告](REPORT.md)。A/C 评分及共识已定稿，模型身份已揭示。该包完成真实项目部分；生成数据和难例正式全量仍未完成。

- `scores/`：六张独立原表，逐字节保留。
- `consensus/`：三张最终共识表，逐字节保留。notes 中的“草案”是历史文字，当前状态以最终对齐记录为准。
- `source-notes/`：纠正笔误、路径和状态后的交付说明；原提交及原稿摘要见 `PROVENANCE.json`。
- `MODEL_MAPPING.json`、`MODEL_IDENTITY.json`、`RUN_RECEIPT.json`：揭盲映射、制品摘要及允许公开的运行统计。原始响应、完整输入与本机设置未复制进此包。
- `reference/`：已公开 A2 标签与 FixFirst 评分的固定字节副本。
- `summary.json`：从以上公开材料计算的指标。

`MODEL_MAPPING.json` 的 `sheets` 字段保留原空表摘要；填写后的表由本目录 `SHA256SUMS.txt` 核验。

原发出包保留在 [real-scoring-20261003](../real-scoring-20261003/)，其空表、ZIP、封存摘要和当时说明都未修改。该目录写的“等待评分”描述当时交付状态。

## 复算

在此目录执行（标准库即可，无模型、无网络）：

```sh
python summarize.py --check
shasum -a 256 -c SHA256SUMS.txt
```

不带 `--check` 时将重新计算的 JSON 输出到终端，不修改输入文件。目录摘要只覆盖本结果包；原发出包的摘要继续核对原空表，不能用于验证填写后的原表。
