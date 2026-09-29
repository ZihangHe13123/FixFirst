# A3（可选）PyDFix 22 个案例的标注

| | |
|---|---|
| 负责 | A 标注，C 复核（可选） |
| 截止 | 10/12（一） |
| 预计用时 | 2–3 小时 |
| 优先级 | P2，时间不够时第三个砍。先把 A1、A2 做完 |
| 交付 | `examples/public-data/pydfix/labels.csv` 填好，通过 PR 提交 |
| 对应计划 | 后续计划 §4 P2 第 3 项 |

## 为什么要做

proposal 把 PyDFix（ISSTA 2021）列为数据来源。检查后发现，它能用的部分只有 22 个不同的导入错误，而且只有报错那一行，没有完整日志（详见 `examples/public-data/README.md`）。这 22 个案例可以当一个小的外部检查：只给 FixFirst 看报错文本，看它指出的原因和包，和人工标签是否一致。标签必须在运行之前写好。

## 怎么做

1. 打开 `examples/public-data/pydfix/cases.csv`。每行是一个案例，主要看这几列：
   - `repository`、`missing_name`；
   - `error_excerpt`：报错原文；
   - `candidate_packages`：PyDFix 猜的包，含噪声，只作参考；
   - `pydfix_fixed_patch_example`：PyDFix 修好时锁定的版本，只作参考，**不是答案**。
2. 对每个案例，**只根据 `error_excerpt`** 判断根因，用 A1 里的五类（这里没有 healthy）。可以查这个仓库当年的代码和依赖声明（GitHub 上看对应年份的 `setup.py`、`requirements.txt`），判断缺的名字属于谁：
   - 没装的第三方包：`missing_dependency`；
   - 包装了，但版本太新或太旧，缺了这个名字：`version_incompatibility`；
   - 项目自己的模块：`local_module`。
3. 填进 `examples/public-data/pydfix/labels.csv`：
   - `root_cause`；
   - `labelled_by`：你的名字；
   - `notes`：判断依据，一句话，最好带链接。

   `reviewed_by` 留给 C。
4. C 有时间的话，独立看一遍，分歧写进 `notes`，定稿后填上 `reviewed_by`。
5. 开 PR，标题写 "A3: PyDFix labels"。B 之后运行纯文本检查，把结果写进报告。

## 完成标准

- [ ] 22 个案例都有 `root_cause` 和依据
- [ ] 标签在 FixFirst 运行这些案例之前提交（PR 的时间可以证明）
- [ ] PR 已提交
